import logging
import asyncio
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node
from scripts.utils.template_engine import replace_templates

logger = logging.getLogger(__name__)

async def execute_database(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """Выполнение Database ноды"""
    config = node.data.get('config', {})
    query_template = config.get('query', '')
    connection = config.get('connection', 'postgres')

    query = replace_templates(query_template, input_data, label_to_id_map, all_results)

    if not query:
        raise Exception("Database node: query is not specified")

    logger.info(f"🗄️ Выполнение SQL запроса")
    logger.info(f"🔗 Подключение: {connection}")
    logger.info(f"📝 Запрос: {query}")

    await asyncio.sleep(1)

    db_result = {
        "success": True,
        "rows": [
            {
                "id": 1,
                "text": "Sample Data",
                "created_at": datetime.now().isoformat()
            }
        ],
        "rowCount": 1,
        "query": query,
        "connection": connection
    }

    return db_result
