import logging
import json
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node
from scripts.utils.template_engine import replace_templates
from scripts.utils.http_client import make_single_http_request

logger = logging.getLogger(__name__)

async def execute_request_iterator(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполнение Request Iterator ноды в соответствии с "Принципом Единого Результата".
    Использует явный шаблон для получения входных данных.
    """
    start_time = datetime.now()
    logger.info(f"Executing Request Iterator node: {node.id}")
    config = node.data.get('config', {})

    json_input_template = config.get('jsonInput', '')
    if not json_input_template:
        raise Exception("Request Iterator: 'jsonInput' template is not configured in the node settings.")

    logger.info(f"📄 Input template for Request Iterator: {json_input_template}")
    requests_to_make_json_str = replace_templates(json_input_template, input_data, label_to_id_map, all_results)

    if not requests_to_make_json_str or requests_to_make_json_str == json_input_template:
        logger.warning(f"Template '{json_input_template}' could not be resolved or resulted in an empty string. Assuming empty list of requests.")
        requests_to_make_json_str = "[]"

    try:
        requests_list = json.loads(requests_to_make_json_str)
        if not isinstance(requests_list, list):
            if isinstance(requests_list, dict):
                requests_list = [requests_list]
            else:
                raise ValueError("Parsed JSON is not a list or a single request object.")
    except (json.JSONDecodeError, ValueError) as e:
        raise Exception(f"Request Iterator: Invalid JSON input after template replacement. Error: {str(e)}")

    if not requests_list:
        logger.info("Request Iterator: No requests to process from input.")
        node_result = {
            "text": "[]",
            "json": [],
            "meta": { "executed_requests_count": 0, "successful_requests_count": 0, "failed_requests_count": 0 },
            "inputs": { "jsonInput_template": json_input_template }
        }
        return node_result

    base_url = config.get('baseUrl', '').rstrip('/')
    execution_mode = config.get('executionMode', 'sequential')
    common_headers_str = config.get('commonHeaders', '{}')
    try:
        parsed_common_headers = json.loads(common_headers_str) if common_headers_str else {}
    except json.JSONDecodeError:
        parsed_common_headers = {}

    all_responses = []
    tasks = []
    async with aiohttp.ClientSession() as session:
        for req_info in requests_list:
            if not isinstance(req_info, dict):
                logger.warning(f"Skipping invalid request item (not a dict): {req_info}")
                all_responses.append({
                    "error": "Invalid request item format",
                    "item_data": req_info,
                    "success": False
                })
                continue

            endpoint = req_info.get('endpoint', '')
            if not endpoint:
                logger.warning(f"Request Iterator: Skipping request with no endpoint: {req_info}")
                all_responses.append({
                    "error": "Missing endpoint",
                    "item_data": req_info,
                    "success": False
                })
                continue
            
            if base_url and not endpoint.startswith('/') and not endpoint.lower().startswith(('http://', 'https://')):
                final_url = f"{base_url}/{endpoint.lstrip('/')}"
            elif not base_url and not endpoint.lower().startswith(('http://', 'https://')):
                logger.warning(f"Request Iterator: Endpoint '{endpoint}' is relative but no baseUrl is configured. Skipping.")
                all_responses.append({
                    "error": "Relative endpoint with no baseUrl",
                    "item_data": req_info,
                    "success": False
                })
                continue
            elif endpoint.lower().startswith(('http://', 'https://')):
                final_url = endpoint
            else:
                final_url = f"{base_url}{endpoint}"

            method = req_info.get('method', 'GET').upper()
            get_params = req_info.get('params') if method == 'GET' else None
            json_body = req_info.get('body') if method in ['POST', 'PUT', 'PATCH'] else None
            specific_headers = req_info.get('headers', {})
            final_headers = {**parsed_common_headers, **specific_headers}

            task = make_single_http_request(
                session,
                method,
                final_url,
                params=get_params,
                json_body=json_body,
                headers=final_headers
            )
            tasks.append(task)

        if execution_mode == 'parallel' and tasks:
            all_responses = await asyncio.gather(*tasks, return_exceptions=True)
        elif tasks:
            for task_coro in tasks:
                all_responses.append(await task_coro)

    final_responses_list = [r for r in all_responses if not isinstance(r, Exception)]
    logger.info(f"Request Iterator: Processed {len(final_responses_list)} requests.")

    execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    successful_count = sum(1 for r in final_responses_list if r.get('success'))
    failed_count = len(final_responses_list) - successful_count

    node_result = {
        "text": json.dumps(final_responses_list, ensure_ascii=False, indent=2),
        "json": final_responses_list,
        "meta": {
            "node_type": node.type,
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": execution_time_ms,
            "executed_requests_count": len(final_responses_list),
            "successful_requests_count": successful_count,
            "failed_requests_count": failed_count,
        },
        "inputs": {
            "baseUrl": base_url,
            "executionMode": execution_mode,
            "jsonInput_template": json_input_template,
        }
    }

    return node_result
