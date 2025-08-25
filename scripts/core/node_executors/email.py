import logging
import asyncio
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node
from scripts.utils.template_engine import replace_templates

logger = logging.getLogger(__name__)

async def execute_email(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """Выполнение Email ноды"""
    config = node.data.get('config', {})
    to_template = config.get('to', '')
    subject_template = config.get('subject', '')
    body_template = config.get('body', '')

    to = replace_templates(to_template, input_data, label_to_id_map, all_results)
    subject = replace_templates(subject_template, input_data, label_to_id_map, all_results)
    body = replace_templates(body_template, input_data, label_to_id_map, all_results)

    if not to:
        raise Exception("Email node: recipient (to) is not specified")

    logger.info(f"📧 Отправка email на {to}")
    logger.info(f"📋 Тема: {subject}")
    logger.info(f"📄 Тело: {body[:100]}...")

    await asyncio.sleep(1)

    email_result = {
        "sent": True,
        "to": to,
        "subject": subject,
        "messageId": f"msg_{int(datetime.now().timestamp())}"
    }
    return email_result
