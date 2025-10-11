import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any

from scripts.models.schemas import WorkflowExecuteRequest
from scripts.services.storage import get_workflow_by_id

logger = logging.getLogger(__name__)

active_timers: Dict[str, Dict[str, Any]] = {}

async def create_timer(timer_id: str, node_id: str, interval: int, workflow_info: Dict[str, Any]):
    """Создает и запускает новый таймер"""
    if timer_id in active_timers and active_timers[timer_id]["task"] is not None:
        active_timers[timer_id]["task"].cancel()
        logger.info(f"🛑 Отменен существующий таймер {timer_id} для пересоздания")

    task = asyncio.create_task(timer_task(timer_id, node_id, interval, workflow_info))

    active_timers[timer_id] = {
        "node_id": node_id,
        "interval": interval,
        "next_execution": datetime.now() + timedelta(minutes=int(interval)),
        "task": task,
        "status": "active",
        "workflow": workflow_info
    }
    logger.info(f"🕒 Создан/пересоздан таймер {timer_id} для workflow '{workflow_info.get('workflow_id')}'")
    return active_timers[timer_id]

async def update_timer(timer_id: str, interval: int, workflow_info: Dict[str, Any]):
    """
    Обновляет существующий таймер.
    """
    if timer_id not in active_timers:
        raise Exception(f"Timer {timer_id} not found")

    timer_info = active_timers[timer_id]
    
    await create_timer(
        timer_id,
        timer_info["node_id"],
        interval,
        workflow_info
    )
    logger.info(f"🔄 Обновлен таймер {timer_id} с новым интервалом {interval} минут")
    return active_timers[timer_id]

async def timer_task(timer_id: str, node_id: str, interval: int, workflow_info: Dict[str, Any]):
    """
    Задача таймера, которая выполняется асинхронно.
    """
    try:
        while True:
            logger.info(f"⏰ Запущена задача таймера {timer_id} для ноды {node_id} с интервалом {interval} минут")
            logger.info(f"⏰ Таймер {timer_id} ожидает {interval} минут до следующего запуска")
            await asyncio.sleep(int(interval) * 60)

            active_timers[timer_id]["next_execution"] = datetime.now() + timedelta(minutes=int(interval))
            active_timers[timer_id]["is_executing_workflow"] = True

            try:
                workflow_id = workflow_info.get("workflow_id")
                workflow_exists = await get_workflow_by_id(workflow_id)
                if not workflow_id or not workflow_exists:
                    logger.error(f"❌ Workflow с ID '{workflow_id}' не найден. Таймер {timer_id} не может запустить выполнение.")
                    continue

                logger.info(f"🚀 Таймер {timer_id} запускает workflow '{workflow_id}'")

                workflow_data_raw = await get_workflow_by_id(workflow_id)
                workflow_data = dict(workflow_data_raw)
                nodes = json.loads(workflow_data.get('nodes', '[]'))
                connections = json.loads(workflow_data.get('connections', '[]'))

                from scripts.core.workflow_engine import execute_workflow_internal
                workflow_request = WorkflowExecuteRequest(
                    nodes=nodes,
                    connections=connections,
                    startNodeId=node_id
                )

                start_time = datetime.now()
                result = await execute_workflow_internal(workflow_request)
                execution_time = (datetime.now() - start_time).total_seconds()

                if result.success:
                    logger.info(f"✅ Workflow '{workflow_id}' выполнен за {execution_time:.2f} секунд")
                else:
                    logger.error(f"❌ Ошибка выполнения workflow '{workflow_id}' таймером {timer_id}: {result.error}")

            except Exception as e:
                logger.error(f"❌ Критическая ошибка при выполнении workflow таймером {timer_id}: {str(e)}")
                import traceback
                logger.error(f"🔍 Трассировка: {traceback.format_exc()}")
            finally:
                if timer_id in active_timers:
                    active_timers[timer_id]["is_executing_workflow"] = False
                    logger.info(f"🔓 Флаг выполнения снят для таймера {timer_id}")

    except asyncio.CancelledError:
        logger.info(f"🛑 Таймер {timer_id} остановлен")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в задаче таймера {timer_id}: {str(e)}")
        if timer_id in active_timers:
            active_timers[timer_id]["status"] = "error"

def get_timer_by_id(timer_id: str):
    return active_timers.get(timer_id)

def delete_timer_by_id(timer_id: str):
    if timer_id in active_timers:
        active_timers[timer_id]["task"].cancel()
        del active_timers[timer_id]

async def execute_timer_now_by_id(timer_id: str):
    timer = get_timer_by_id(timer_id)
    if not timer:
        raise Exception(f"Timer {timer_id} not found")

    workflow_id = timer['workflow']['workflow_id']
    node_id = timer['node_id']
    workflow_data_raw = await get_workflow_by_id(workflow_id)

    if not workflow_data_raw:
        raise Exception(f"Workflow {workflow_id} not found")

    workflow_data = dict(workflow_data_raw)
    nodes = json.loads(workflow_data.get('nodes', '[]'))
    connections = json.loads(workflow_data.get('connections', '[]'))

    from scripts.core.workflow_engine import execute_workflow_internal
    workflow_request = WorkflowExecuteRequest(
        nodes=nodes,
        connections=connections,
        startNodeId=node_id
    )
    return await execute_workflow_internal(workflow_request)