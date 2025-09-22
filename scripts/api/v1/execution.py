from fastapi import APIRouter, HTTPException, status, Body
from datetime import datetime
from typing import Dict, Any, List

from scripts.models.schemas import WorkflowExecuteRequest, ExecutionResult, Node
from scripts.core.workflow_engine import execute_workflow_internal, get_executor, get_node_results, clear_node_results
from scripts.services.giga_chat import GigaChatAPI

router = APIRouter()
gigachat_api = GigaChatAPI()
dispatcher_sessions = {}

@router.post("/execute-workflow")
async def execute_workflow(request: WorkflowExecuteRequest) -> ExecutionResult:
    return await execute_workflow_internal(request)

@router.post("/node-status")
async def get_node_status(node_ids: List[str]):
    """Возвращает результаты для указанных нод и очищает их."""
    results = get_node_results(node_ids)
    clear_node_results(list(results.keys())) # Очищаем только те, что нашли
    return {"results": results}

@router.post("/execute-node")
async def execute_node(
    node_type: str,
    node_data: Dict[str, Any],
    input_data: Dict[str, Any] = None
) -> ExecutionResult:
    """Выполнение отдельной ноды"""
    try:
        node = Node(
            id=node_data.get('id', 'temp'),
            type=node_type,
            position=node_data.get('position', {'x': 0, 'y': 0}),
            data=node_data.get('data', {})
        )

        executor = get_executor(node_type)
        if not executor:
            raise HTTPException(status_code=400, detail=f"Unknown node type: {node_type}")

        # Pass dependencies to executors that need them
        if node.type == 'gigachat':
            result = await executor(node, {}, input_data or {}, gigachat_api, {})
        elif node.type == 'dispatcher':
            result = await executor(node, {}, input_data or {}, gigachat_api, dispatcher_sessions)
        else:
            result = await executor(node, {}, input_data or {})
        
        return ExecutionResult(
            success=True,
            result=result,
            logs=[{
                "message": f"Node {node_type} executed successfully",
                "timestamp": datetime.now().isoformat(),
                "level": "info"
            }]
        )

    except Exception as e:
        return ExecutionResult(
            success=False,
            error=str(e),
            logs=[{
                "message": f"Error executing node {node_type}: {str(e)}",
                "timestamp": datetime.now().isoformat(),
                "level": "error"
            }]
        )
