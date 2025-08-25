import json
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

WORKFLOWS_FILE = "saved_workflows.json"

# Это будет наше хранилище в памяти
saved_workflows: Dict[str, Any] = {}

def save_workflows_to_disk():
    """Сохраняет текущие workflows в JSON файл."""
    try:
        with open(WORKFLOWS_FILE, "w", encoding="utf-8") as f:
            json.dump(saved_workflows, f, ensure_ascii=False, indent=4)
        logger.info(f"💾 Workflows сохранены в {WORKFLOWS_FILE}")
    except IOError as e:
        logger.error(f"❌ Не удалось записать workflows в файл {WORKFLOWS_FILE}: {e}")

def load_workflows_from_disk():
    """Загружает workflows из JSON файла при старте."""
    if os.path.exists(WORKFLOWS_FILE):
        try:
            with open(WORKFLOWS_FILE, "r", encoding="utf-8") as f:
                global saved_workflows
                saved_workflows = json.load(f)
                logger.info(f"✅ Workflows загружены из {WORKFLOWS_FILE}")
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"❌ Не удалось загрузить workflows из файла {WORKFLOWS_FILE}: {e}")
            saved_workflows = {}
    else:
        logger.warning(f"Файл {WORKFLOWS_FILE} не найден. Будет создан новый при первом сохранении.")
        saved_workflows = {}

# Функции для доступа к данным (вместо прямого доступа к глобальной переменной)
def get_all_workflows() -> Dict[str, Any]:
    return saved_workflows

def get_workflow_by_id(workflow_id: str) -> Dict[str, Any] | None:
    return saved_workflows.get(workflow_id)

def add_workflow(workflow_id: str, workflow_data: Dict[str, Any]):
    saved_workflows[workflow_id] = workflow_data
    save_workflows_to_disk()

def delete_workflow_by_id(workflow_id: str):
    if workflow_id in saved_workflows:
        del saved_workflows[workflow_id]
        save_workflows_to_disk()
