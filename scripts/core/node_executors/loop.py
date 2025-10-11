import logging
import json
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node, WorkflowExecuteRequest
from scripts.services.storage import get_workflow_by_id

logger = logging.getLogger(__name__)

async def execute_loop(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    start_time = datetime.now()
    
    config = node.data.get('config', {})
    array_path = config.get('inputArrayPath', 'items')
    sub_workflow_id = config.get('subWorkflowId')
    execution_mode = config.get('executionMode', 'sequential')
    max_concurrent = config.get('maxConcurrent', 5)
    timeout = config.get('timeout', 300)
    skip_errors = config.get('skipErrors', True)
    batch_size = config.get('batchSize', 0)
    
    logger.info(f"🔍 Loop node input data: {json.dumps(input_data, ensure_ascii=False)}")
    logger.info(f"🔍 Looking for array at path: {array_path}")
    logger.info(f"🔍 Label to ID map: {label_to_id_map}")
    
    path_parts = array_path.split('.')
    first_part = path_parts[0]
    if first_part in label_to_id_map:
        node_id = label_to_id_map[first_part]
        logger.info(f"🔄 Replacing label '{first_part}' with node ID '{node_id}'")
        path_parts[0] = node_id
        array_path = '.'.join(path_parts)
        logger.info(f"🔄 New path: {array_path}")
    
    def get_by_path(data, path):
        for part in path.split('.'):
            if isinstance(data, dict):
                data = data.get(part)
            else:
                return None
        return data
    
    # Сначала ищем идентификатор ноды в глобальных результатах
    node_id = label_to_id_map.get(array_path.split('.')[0])
    if node_id and node_id in all_results:
        data_source = all_results
        path_to_value = f"{node_id}.{'.'.join(array_path.split('.')[1:])}"
    else:
        data_source = input_data
        path_to_value = array_path

    array = get_by_path(data_source, path_to_value)
    if array is None and isinstance(input_data, dict) and 'json' in input_data and isinstance(input_data['json'], list):
        logger.info(f"⚠️ Data not found at '{array_path}', but found a list in the 'json' field of the input. Using that instead.")
        array = input_data['json']
    
    if array is not None:
        logger.info(f"✅ Found data at path '{array_path}': {json.dumps(array, ensure_ascii=False)}")
    else:
        logger.error(f"❌ No data found at path '{array_path}'")
        raise Exception(f"Loop node: no data found at path '{array_path}'")
    
    if not isinstance(array, list):
        raise Exception(f"Loop node: input at path '{array_path}' is not a list")
    
    if not sub_workflow_id:
        raise Exception("Loop node: subWorkflowId is required")
    
    sub_workflow_data_raw = await get_workflow_by_id(sub_workflow_id)
    if not sub_workflow_data_raw:
        raise Exception(f"Loop node: subWorkflow with ID '{sub_workflow_id}' not found")

    # Десериализуем поля nodes и connections из JSONB
    sub_workflow_data = dict(sub_workflow_data_raw)
    if sub_workflow_data.get('nodes'):
        sub_workflow_data['nodes'] = json.loads(sub_workflow_data['nodes'])
    if sub_workflow_data.get('connections'):
        sub_workflow_data['connections'] = json.loads(sub_workflow_data['connections'])
    
    from scripts.core.workflow_engine import execute_workflow_internal
    async def run_subworkflow(item, idx):
        sub_input = {"item": item, "loop_index": idx}
        try:
            result = await execute_workflow_internal(
                WorkflowExecuteRequest(
                    nodes=sub_workflow_data["nodes"],
                    connections=sub_workflow_data["connections"]
                ),
                initial_input_data=sub_input
            )
            return {
                "success": result.success,
                "result": result.result,
                "item": item,
                "index": idx,
                "error": result.error if not result.success else None
            }
        except Exception as e:
            logger.error(f"❌ Error in subworkflow for item {idx}: {str(e)}")
            if not skip_errors:
                raise
            return {
                "success": False,
                "result": None,
                "item": item,
                "index": idx,
                "error": str(e)
            }
    
    results = []
    
    if batch_size > 0 and len(array) > batch_size:
        batches = [array[i:i+batch_size] for i in range(0, len(array), batch_size)]
        logger.info(f"🔢 Processing array in {len(batches)} batches of size {batch_size}")
        
        all_results = []
        for batch_idx, batch in enumerate(batches):
            logger.info(f"📦 Processing batch {batch_idx+1}/{len(batches)}")
            batch_results = []
            
            if execution_mode == "parallel":
                import asyncio
                semaphore = asyncio.Semaphore(max_concurrent)
                
                async def limited_run(item, global_idx):
                    async with semaphore:
                        return await run_subworkflow(item, global_idx)
                
                start_idx = batch_idx * batch_size
                tasks = [limited_run(item, start_idx + idx) for idx, item in enumerate(batch)]
                batch_results = await asyncio.gather(*tasks, return_exceptions=skip_errors)
            else:
                start_idx = batch_idx * batch_size
                for idx, item in enumerate(batch):
                    global_idx = start_idx + idx
                    batch_results.append(await run_subworkflow(item, global_idx))
            
            all_results.extend(batch_results)
        
        results = all_results
    else:
        if execution_mode == "parallel":
            import asyncio
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def limited_run(item, idx):
                async with semaphore:
                    return await run_subworkflow(item, idx)
            
            tasks = [limited_run(item, idx) for idx, item in enumerate(array)]
            results = await asyncio.gather(*tasks, return_exceptions=skip_errors)
            
            if not skip_errors:
                for result in results:
                    if isinstance(result, Exception):
                        raise result
        else:
            for idx, item in enumerate(array):
                results.append(await run_subworkflow(item, idx))
    
    execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    success_count = sum(1 for r in results if r.get('success', True))
    error_count = len(results) - success_count
    
    return {
        "results": results,
        "summary": {
            "total": len(array),
            "executed": len(results),
            "success_count": success_count,
            "error_count": error_count,
            "execution_mode": execution_mode,
            "execution_time_ms": execution_time_ms
        },
        "output": {
            "text": f"Processed {len(array)} items with {success_count} successes and {error_count} errors",
            "json": results
        }
    }
