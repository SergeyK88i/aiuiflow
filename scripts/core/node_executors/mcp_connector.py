import logging
import json
import aiohttp
from typing import Dict, Any
     
from scripts.models.schemas import Node
from scripts.utils.template_engine import replace_templates
    
logger = logging.getLogger(__name__)
    
async def execute_mcp_connector(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], 
    all_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполняет вызов функции на удаленном MCP-сервере.
    """
    config = node.data.get('config', {})
    logger.info(f"🔌 Executing MCP Connector node: {node.id}")

    # 1. Получаем настройки из ноды
    server_url = config.get('mcp_server_url', '').rstrip('/')
    function_name = config.get('mcp_function_name')
    parameters_template = config.get('mcp_parameters', '{}')

    if not server_url or not function_name:
        raise Exception("MCP Connector: 'Server URL' and 'Function Name' are required.")

    # 2. Заполняем шаблоны в параметрах
    resolved_params_str = replace_templates(parameters_template, input_data, label_to_id_map, all_results)
    try:
        final_parameters = json.loads(resolved_params_str)
    except json.JSONDecodeError:
        raise Exception(f"MCP Connector: Invalid JSON in parameters after template replacement. Result: {resolved_params_str}")
    
    # 3. Формируем и отправляем запрос
    execute_url = f"{server_url}/execute"
    payload = {
        "function": function_name,
        "parameters": final_parameters
    }

    logger.info(f"🚀 Calling MCP function '{function_name}' on {execute_url}")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(execute_url, json=payload, ssl=False) as response:
            response_status = response.status
            response_body = await response.json()

            logger.info(f"✅ MCP server responded with status {response_status}")

            if 200 <= response_status < 300:
                return response_body # Возвращаем результат как есть
            else:
                error_message = response_body.get('error', 'Unknown error from MCP server')
                raise Exception(f"MCP Server Error (status {response_status}): {error_message}")