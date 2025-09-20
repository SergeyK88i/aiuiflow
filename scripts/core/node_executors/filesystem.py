import logging
import json
from typing import Dict, Any

from scripts.models.schemas import Node
from scripts.services.storage import add_workflow # <--- ПЕРЕИСПОЛЬЗУЕМ КОД!
 
logger = logging.getLogger(__name__)
 
async def execute_filesystem(node: Node, input_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    Выполняет операции с файловой системой, в частности, обновление воркфлоу.
    """
    config = node.data.get('config', {})
    operation = config.get('fs_operation', 'update_workflows')
    logger.info(f"💾 Executing File System node in '{operation}' mode.")

    if operation == 'update_workflows':
        # Ожидаем, что предыдущая нода (LLM) вернула результат в поле 'json'
        new_workflows = input_data.get('json', {})
 
        if not isinstance(new_workflows, dict):
            raise Exception("File System node (update_workflows) expects a dictionary of workflows as input.") 
        for workflow_id, workflow_data in new_workflows.items():
            logger.info(f"➕ Adding/updating workflow: {workflow_id}")
            # Вызываем нашу централизованную функцию, которая сама все сохранит
            add_workflow(workflow_id, workflow_data)

        return {
            "success": True,
            "message": f"Successfully processed {len(new_workflows)} workflows.",
            "processed_ids": list(new_workflows.keys())
        }
    else:
        raise Exception(f"File System node: Unsupported operation '{operation}'.")