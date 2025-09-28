import logging
import json
import aiohttp
import ast
from typing import Dict, Any

from scripts.models.schemas import Node
from scripts.utils.template_engine import replace_templates

logger = logging.getLogger(__name__)

import uuid

async def execute_mcp_connector(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], 
    all_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполняет вызов функции на удаленном MCP-сервере, используя протокол JSON-RPC 2.0.
    """
    config = node.data.get('config', {})
    logger.info(f"🔌 Executing JSON-RPC MCP Connector node: {node.id}")

    server_url_template = config.get('mcp_server_url', '')
    session_id_template = config.get('session_id', '')
    method_template = config.get('json_rpc_method', '')
    params_template = config.get('json_rpc_params', '{}')

    server_url = replace_templates(server_url_template, input_data, label_to_id_map, all_results)
    session_id = replace_templates(session_id_template, input_data, label_to_id_map, all_results)
    method = replace_templates(method_template, input_data, label_to_id_map, all_results)
    
    params_obj = replace_templates(params_template, input_data, label_to_id_map, all_results)

    if not server_url or not method:
        raise Exception("MCP Connector: 'Server URL' and 'JSON-RPC Method' are required.")

    # --- НОВЫЙ, НАДЕЖНЫЙ ПАРСИНГ ---
    final_params = {}
    if isinstance(params_obj, dict):
        final_params = params_obj
    elif isinstance(params_obj, str):
        try:
            # Сначала пытаемся стандартным способом
            final_params = json.loads(params_obj)
        except json.JSONDecodeError:
            logger.warning("json.loads() failed. Falling back to ast.literal_eval().")
            try:
                # Если не вышло, используем более гибкий и безопасный ast.literal_eval
                final_params = ast.literal_eval(params_obj)
                if not isinstance(final_params, dict):
                    raise TypeError("ast.literal_eval() did not produce a dictionary.")
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as e:
                raise Exception(f"MCP Connector: Failed to parse params string with both json and ast. Result: '{params_obj}'. Error: {e}")
    else:
        raise TypeError(f"MCP Connector: Unsupported type for params: {type(params_obj)}")

    if session_id:
        final_params['sessionId'] = session_id

    request_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": final_params
    }

    logger.info(f"🚀 Calling JSON-RPC method '{method}' on {server_url} with payload: {json.dumps(payload)}")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(server_url, json=payload, ssl=False) as response:
            response_status = response.status
            if not response.ok:
                error_text = await response.text()
                raise Exception(f"MCP Server Error (status {response_status}): {error_text}")

            response_body = await response.json()

            if 'error' in response_body:
                error_data = response_body['error']
                raise Exception(f"JSON-RPC Error {error_data.get('code')}: {error_data.get('message')}")

            logger.info(f"✅ MCP server responded successfully for request id {response_body.get('id')}")
            
            return response_body.get('result', {})
