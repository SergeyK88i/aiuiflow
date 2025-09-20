import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Tuple

from scripts.models.schemas import WorkflowExecuteRequest, ExecutionResult, Node
from scripts.services.giga_chat import GigaChatAPI
from scripts.core.node_executors.gigachat import execute_gigachat
from scripts.core.node_executors.webhook import execute_webhook
from scripts.core.node_executors.request_iterator import execute_request_iterator
from scripts.core.node_executors.if_else import execute_if_else
from scripts.core.node_executors.dispatcher import execute_dispatcher
from scripts.core.node_executors.loop import execute_loop
from scripts.core.node_executors.join import execute_join
from scripts.core.node_executors.timer import execute_timer
from scripts.core.node_executors.webhook_trigger import execute_webhook_trigger
from scripts.core.node_executors.email import execute_email
from scripts.core.node_executors.database import execute_database

logger = logging.getLogger(__name__)

node_results: Dict[str, Any] = {}

def get_node_results(node_ids: List[str]) -> Dict[str, Any]:
    """Возвращает результаты для указанных нод."""
    return {node_id: node_results.get(node_id) for node_id in node_ids if node_id in node_results}

def clear_node_results(node_ids: List[str]):
    """Очищает результаты для указанных нод."""
    for node_id in node_ids:
        if node_id in node_results:
            del node_results[node_id]

gigachat_api = GigaChatAPI()

async def execute_workflow_internal(
    request: WorkflowExecuteRequest,
    initial_input_data: Dict[str, Any] = None
) -> ExecutionResult:
    nodes = {node.id: node for node in request.nodes}
    connections = request.connections
    start_node_id = request.startNodeId

    if not start_node_id:
        # Find a start node (a node with no incoming connections)
        target_nodes = {c.target for c in connections}
        start_nodes = [n for n in request.nodes if n.id not in target_nodes]
        if not start_nodes:
            return ExecutionResult(success=False, error="No start node found")
        start_node_id = start_nodes[0].id

    execution_queue: List[Tuple[str, Dict[str, Any]]] = [(start_node_id, initial_input_data or {})]
    executed_nodes = set()
    all_results: Dict[str, Any] = {}
    logs: List[Dict[str, Any]] = []

    label_to_id_map = {node.data.get('label', node.id): node.id for node in request.nodes}
    goto_counts: Dict[str, int] = {}

    while execution_queue:
        node_id, input_data = execution_queue.pop(0)

        if node_id in executed_nodes:
            continue

        node = nodes.get(node_id)
        if not node:
            continue

        # Special handling for Join node
        if node.type == 'join':
            join_inputs = {}
            for conn in connections:
                if conn.target == node.id and conn.source in all_results:
                    join_inputs[conn.source] = all_results[conn.source]
            input_data = {'inputs': join_inputs} # Overwrite input_data for join node

        logger.info(f"Executing node {node.id} ({node.type}) with input: {input_data}")
        logs.append({
            "nodeId": node.id,
            "level": "info",
            "message": f"Executing node {node.data.get('label', node.id)}",
            "timestamp": datetime.now().isoformat()
        })

        try:
            executor = get_executor(node.type)
            if not executor:
                raise Exception(f"No executor for node type {node.type}")

            # Pass dependencies to executors that need them
            if node.type == 'gigachat':
                result = await executor(node, label_to_id_map, input_data, gigachat_api, all_results)
            elif node.type == 'dispatcher':
                result = await executor(node, label_to_id_map, input_data, gigachat_api, all_results)
            else:
                result = await executor(node, label_to_id_map, input_data, all_results)

            # --- NEW: Preserve dispatcher_context across nodes ---
            if 'dispatcher_context' in input_data and 'dispatcher_context' not in result:
                result['dispatcher_context'] = input_data['dispatcher_context']
            # --- END NEW ---

            all_results[node.id] = result
            executed_nodes.add(node.id)

            logs.append({
                "nodeId": node.id,
                "level": "success",
                "message": f"Node {node.data.get('label', node.id)} executed successfully",
                "timestamp": datetime.now().isoformat(),
                "data": result
            })

            # Find next nodes to execute
            next_nodes = []
            if node.type == 'if_else':
                branch = result.get('branch', 'false')
                for conn in connections:
                    if conn.source == node.id:
                        conn_label = conn.data.get('label', 'true')
                        is_goto = ':goto' in conn_label
                        actual_label = conn_label.split(':')[0]

                        if actual_label == branch:
                            # Add to queue if it's a GOTO jump OR if it has not been executed yet
                            if is_goto or conn.target not in executed_nodes:
                                if is_goto:
                                    goto_key = f"{conn.source}->{conn.target}"
                                    goto_counts[goto_key] = goto_counts.get(goto_key, 0) + 1
                                    max_gotos = node.data.get('config', {}).get('maxGotoIterations', 10)
                                    if goto_counts[goto_key] > max_gotos:
                                        raise Exception(f"GOTO limit ({max_gotos}) exceeded for {goto_key}")
                                    logger.info(f"↪️ GOTO: Jumping from {conn.source} to {conn.target} (iteration {goto_counts[goto_key]})")
                                    
                                    # Allow the target node and the If/Else node itself to be re-executed
                                    if conn.target in executed_nodes:
                                        executed_nodes.remove(conn.target)
                                    if conn.source in executed_nodes:
                                        executed_nodes.remove(conn.source)
                                
                                next_nodes.append((conn.target, result))
            else:
                for conn in connections:
                    if conn.source == node.id:
                        if conn.target not in executed_nodes:
                            next_nodes.append((conn.target, result))

            for next_node_id, next_input_data in next_nodes:
                execution_queue.append((next_node_id, next_input_data))

        except Exception as e:
            logger.error(f"Error executing node {node.id}: {e}")
            logs.append({
                "nodeId": node.id,
                "level": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return ExecutionResult(success=False, error=str(e), logs=logs, result=all_results)

    return ExecutionResult(success=True, result=all_results, logs=logs)

def get_executor(node_type: str):
    executor_map = {
        'gigachat': execute_gigachat,
        'webhook': execute_webhook,
        'request_iterator': execute_request_iterator,
        'if_else': execute_if_else,
        'dispatcher': execute_dispatcher,
        'loop': execute_loop,
        'join': execute_join,
        'timer': execute_timer,
        'webhook_trigger': execute_webhook_trigger,
        'email': execute_email,
        'database': execute_database,
    }
    return executor_map.get(node_type)
