import logging
import json
import aiohttp
import ast
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node
from scripts.utils.template_engine import replace_templates

logger = logging.getLogger(__name__)

async def execute_webhook(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполнение Webhook ноды с новой структурой вывода и явным шаблоном для тела запроса.
    """
    start_time = datetime.now()
    logger.info(f"Executing Webhook node: {node.id}")
    config = node.data.get('config', {})
    node_result = {}
    
    try:
        url_template = config.get('url', '')
        method = config.get('method', 'POST').upper()
        headers_str = config.get('headers', 'Content-Type: application/json')
        body_template = config.get('bodyTemplate', '{}') 

        url = replace_templates(url_template, input_data, label_to_id_map, all_results)
        if not url:
            raise Exception("Webhook: URL is required in the node settings.")

        headers = {}
        if headers_str:
            for line in headers_str.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip()] = value.strip()
        
        payload = None
        if method in ['POST', 'PUT', 'PATCH']:
            resolved_body_obj = replace_templates(body_template, input_data, label_to_id_map, all_results)
            
            if isinstance(resolved_body_obj, dict):
                payload = resolved_body_obj
            elif isinstance(resolved_body_obj, str) and resolved_body_obj.strip():
                try:
                    payload = json.loads(resolved_body_obj)
                except json.JSONDecodeError:
                    logger.warning(f"Webhook node {node.id}: json.loads() failed for body. Falling back to ast.literal_eval().")
                    try:
                        payload = ast.literal_eval(resolved_body_obj)
                        if not isinstance(payload, dict):
                            raise TypeError("ast.literal_eval() did not produce a dictionary.")
                    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as e:
                        raise Exception(f"Webhook node {node.id}: Failed to parse bodyTemplate with both json and ast. Result: '{resolved_body_obj}'. Error: {e}")

        logger.info(f"🌐 Sending {method} to {url}")
        if payload:
            logger.info(f"📦 Payload: {json.dumps(payload, ensure_ascii=False, default=str)[:200]}...")

        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.request(method, url, json=payload, ssl=False) as response:
                response_text = await response.text()
                response_json = None
                try:
                    response_json = json.loads(response_text)
                except json.JSONDecodeError:
                    pass
                
                logger.info(f"✅ Webhook response: {response.status}")

                execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                node_result = {
                    "text": response_text,
                    "json": response_json,
                    "meta": {
                        "node_type": node.type, "timestamp": datetime.now().isoformat(),
                        "execution_time_ms": execution_time_ms, "success": 200 <= response.status < 300,
                        "status_code": response.status, "response_headers": dict(response.headers),
                    },
                    "inputs": {
                        "url_template": url_template, "final_url": url, "method": method,
                        "headers": headers, "body_template": body_template, "final_payload": payload
                    }
                }

    except aiohttp.ClientError as e:
        logger.error(f"❌ Connection Error in Webhook node {node.id}: {str(e)}")
        node_result = _create_error_result(node, config, f"Connection Error: {str(e)}", "connection_error", input_data)
    except Exception as e:
        logger.error(f"❌ Unexpected Error in Webhook node {node.id}: {str(e)}")
        node_result = _create_error_result(node, config, str(e), "unexpected_error", input_data)

    return node_result

def _create_error_result(node: Node, config: Dict, error_message: str, error_type: str, input_data: Dict) -> Dict:
    return {
        "text": error_message,
        "json": None,
        "meta": {
            "node_type": node.type, "timestamp": datetime.now().isoformat(),
            "success": False, "error_message": error_message, "error_type": error_type
        },
        "inputs": {
            "url_template": config.get('url', ''), "method": config.get('method', 'POST'),
            "headers": config.get('headers', ''), "body_template": config.get('bodyTemplate', ''),
            "input_data_snapshot": input_data
        }
    }
