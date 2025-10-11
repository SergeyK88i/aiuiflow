
import logging
import json
import os
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node
from scripts.services.giga_chat import GigaChatAPI
from scripts.utils.template_engine import replace_templates

logger = logging.getLogger(__name__)

async def execute_gigachat(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], gigachat_api: GigaChatAPI, all_results: Dict[str, Any]) -> Dict[str, Any]:
    """Выполнение GigaChat ноды"""
    start_time = datetime.now()
    logger.info(f"Executing GigaChat node: {node.id}")
    config = node.data.get('config', {})
    
    # Новая логика получения токена
    auth_token = config.get('authToken')
    if not auth_token:
        auth_token = os.getenv('GIGACHAT_AUTH_TOKEN')

    clear_history = config.get('clearHistory', False)

    system_message = config.get('systemMessage', 'Ты полезный ассистент')
    user_message = config.get('userMessage', '')

    original_system_message = system_message
    original_user_message = user_message

    if input_data:
        logger.info(f"📥 Входные данные от предыдущей ноды: {json.dumps(input_data, ensure_ascii=False, indent=2)[:500]}...")
        
        user_message = replace_templates(original_user_message, input_data, label_to_id_map, all_results)
        system_message = replace_templates(original_system_message, input_data, label_to_id_map, all_results)
        
        if original_user_message != user_message:
            logger.info(f"📝 Сообщение до замены: {original_user_message}")
            logger.info(f"📝 Сообщение после замены: {user_message}")

    if not auth_token or not user_message:
        raise Exception("GigaChat: Auth token is not configured in the node and GIGACHAT_AUTH_TOKEN environment variable is not set.")

    logger.info(f"🤖 Выполнение GigaChat ноды: {node.id}")
    logger.info(f"📝 Вопрос: {user_message}")

    if clear_history:
        gigachat_api.clear_history()

    if not await gigachat_api.get_token(auth_token):
        raise Exception("Не удалось получить токен доступа")

    result = await gigachat_api.get_chat_completion(system_message, user_message)
    
    if not result.get('success'):
        raise Exception(result.get('error', 'Unknown error'))

    import re
    raw_response_text = result.get('response', '')
    cleaned_response_text = raw_response_text
    match = re.search(r'```(json)?\s*([\s\S]*?)\s*```', raw_response_text)
    if match:
        logger.info("🧹 GigaChat вернул Markdown, извлекаем чистый JSON.")
        cleaned_response_text = match.group(2)

    parsed_json = None
    try:
        parsed_json = json.loads(cleaned_response_text)
        logger.info("✅ Ответ от GigaChat успешно распознан как JSON.")
    except json.JSONDecodeError:
        logger.info("ℹ️ Ответ от GigaChat не является валидным JSON. Будет обработан как обычный текст.")
        pass

    execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    
    node_result = {
        "text": cleaned_response_text,
        "json": parsed_json,
        "meta": {
            "node_type": node.type,
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": execution_time_ms,
            "conversation_length": result.get("conversation_length", 0),
            "length": len(raw_response_text),
            "words": len(raw_response_text.split()),
            "id_node": node.id
        },
        "inputs": {
            "system_message_template": original_system_message,
            "user_message_template": original_user_message,
            "final_system_message": system_message,
            "final_user_message": user_message,
            "clear_history": clear_history
        }
    }
    return node_result
