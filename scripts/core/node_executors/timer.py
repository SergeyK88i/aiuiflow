import logging
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node

logger = logging.getLogger(__name__)

async def execute_timer(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполнение Timer ноды как ПЕРВОГО ШАГА в workflow.
    Ее единственная задача - сгенерировать стартовые данные.
    Она больше не управляет расписанием.
    """
    try:
        logger.info(f"⏰ Нода 'Таймер' {node.id} запускается как часть workflow.")
        current_time = datetime.now()
        config = node.data.get('config', {})
        interval = int(config.get('interval', 5))
        timezone = config.get('timezone', 'UTC')

        return {
            "success": True,
            "message": f"Workflow triggered by schedule at {current_time.isoformat()}",
            "output": {
                "text": f"Workflow triggered by schedule at {current_time.isoformat()}",
                "timestamp": current_time.isoformat(),
                "interval": interval,
                "timezone": timezone,
                "node_id": node.id
            }
        }
    except Exception as e:
        logger.error(f"❌ Ошибка в ноде 'Таймер' {node.id}: {str(e)}")
        return {
            "success": False,
            "error": f"Timer node execution failed: {str(e)}",
            "output": {"text": f"Timer node execution failed: {str(e)}"}
        }
