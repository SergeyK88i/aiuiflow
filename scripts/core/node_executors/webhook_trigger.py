import logging
from typing import Dict, Any

from scripts.models.schemas import Node

logger = logging.getLogger(__name__)

async def execute_webhook_trigger(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполнение Webhook Trigger ноды.
    Ее задача - просто вернуть данные, с которыми был запущен воркфлоу.
    """
    logger.info(f"🔔 Webhook Trigger node {node.id} executed.")
    return {
        "success": True,
        "output": input_data
    }
