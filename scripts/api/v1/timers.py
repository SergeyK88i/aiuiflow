from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any, List
from datetime import datetime

from scripts.models.schemas import SetupTimerRequest
from scripts.core.timer_manager import (
    active_timers,
    create_timer,
    update_timer,
    get_timer_by_id,
    delete_timer_by_id,
    execute_timer_now_by_id,
)
# Добавляем импорт для доступа к данным воркфлоу
from scripts.services.storage import get_workflow_by_id

router = APIRouter()

@router.post("/setup-timer")
async def setup_timer(request: SetupTimerRequest):
    node = request.node
    workflow_id = request.workflow_id
    timer_id = f"workflow_timer_{workflow_id}"

    # Получаем воркфлоу, чтобы проверить его статус
    workflow = await get_workflow_by_id(workflow_id)

    # Если воркфлоу по какой-то причине не найден, удаляем его таймер, если он был
    if not workflow:
        if timer_id in active_timers:
            delete_timer_by_id(timer_id)
        # Не возвращаем ошибку, просто сообщаем, что таймер не настроен
        return {"message": f"Workflow {workflow_id} not found, timer setup cancelled."}

    # ГЛАВНАЯ ПРОВЕРКА - "ОХРАННИК"
    if workflow.get("status") != "published":
        # Если воркфлоу не опубликован, его таймер не должен быть активен.
        # Проверяем, есть ли уже активный таймер (например, от предыдущей опубликованной версии)
        if timer_id in active_timers:
            delete_timer_by_id(timer_id)
            return {"message": f"Timer for workflow {workflow_id} has been deactivated because it is not published."}
        else:
            return {"message": f"Timer for draft workflow {workflow_id} is not active."}

    # Если мы дошли сюда, значит status == "published", и таймер должен работать
    config = node.data.get('config', {})
    interval = config.get('interval', 5)
    workflow_info = {
        "workflow_id": workflow_id,
        "start_node_id": node.id
    }

    if timer_id in active_timers:
        await update_timer(timer_id, interval, workflow_info)
        return {"message": f"Timer for published workflow {workflow_id} updated."}
    else:
        await create_timer(timer_id, node.id, interval, workflow_info)
        return {"message": f"Timer for published workflow {workflow_id} created."}

@router.get("/timers")
async def get_timers():
    timers_list = []
    for timer_id, timer_data in active_timers.items():
        # Создаем копию данных, чтобы не изменять оригинал
        safe_timer_data = timer_data.copy()
        # Удаляем несериализуемый объект задачи
        safe_timer_data.pop("task", None)
        # Добавляем ID в сам объект для удобства
        safe_timer_data["id"] = timer_id
        timers_list.append(safe_timer_data)
    return {"timers": timers_list}

@router.post("/timers/{timer_id}/pause")
async def pause_timer(timer_id: str):
    timer = get_timer_by_id(timer_id)
    if not timer:
        raise HTTPException(status_code=404, detail="Timer not found")
    timer["task"].cancel()
    timer["status"] = "paused"
    return {"message": f"Timer {timer_id} paused."}

@router.post("/timers/{timer_id}/resume")
async def resume_timer(timer_id: str):
    timer = get_timer_by_id(timer_id)
    if not timer:
        raise HTTPException(status_code=404, detail="Timer not found")
    await create_timer(timer_id, timer['node_id'], timer['interval'], timer['workflow'])
    return {"message": f"Timer {timer_id} resumed."}

@router.delete("/timers/{timer_id}")
async def delete_timer(timer_id: str):
    delete_timer_by_id(timer_id)
    return {"message": f"Timer {timer_id} deleted."}

@router.post("/timers/{timer_id}/execute-now")
async def execute_timer_now(timer_id: str):
    result = await execute_timer_now_by_id(timer_id)
    return result