import logging
import json
import aiohttp
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

    # 1. Получаем и разрешаем шаблоны для параметров из UI
    server_url_template = config.get('mcp_server_url', '')
    session_id_template = config.get('session_id', '')
    method_template = config.get('json_rpc_method', '')
    params_template = config.get('json_rpc_params', '{}')

    server_url = replace_templates(server_url_template, input_data, label_to_id_map, all_results)
    session_id = replace_templates(session_id_template, input_data, label_to_id_map, all_results)
    method = replace_templates(method_template, input_data, label_to_id_map, all_results)
    params_str = replace_templates(params_template, input_data, label_to_id_map, all_results)

    if not server_url or not method:
        raise Exception("MCP Connector: 'Server URL' and 'JSON-RPC Method' are required.")

    try:
        final_params = json.loads(params_str)
    except json.JSONDecodeError:
        raise Exception(f"MCP Connector: Invalid JSON in params after template replacement. Result: {params_str}")

    # 2. Добавляем ID сессии в параметры, если он есть
    if session_id:
        final_params['sessionId'] = session_id

    # 3. Формируем тело запроса в формате JSON-RPC 2.0
    request_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": final_params
    }

    logger.info(f"🚀 Calling JSON-RPC method '{method}' on {server_url}")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(server_url, json=payload, ssl=False) as response:
            response_status = response.status
            if not response.ok:
                error_text = await response.text()
                raise Exception(f"MCP Server Error (status {response_status}): {error_text}")

            response_body = await response.json()

            # 4. Проверяем ответ на ошибки JSON-RPC
            if 'error' in response_body:
                error_data = response_body['error']
                raise Exception(f"JSON-RPC Error {error_data.get('code')}: {error_data.get('message')}")

            logger.info(f"✅ MCP server responded successfully for request id {response_body.get('id')}")
            
            # 5. Возвращаем только поле result, как и положено по стандарту
            return response_body.get('result', {})