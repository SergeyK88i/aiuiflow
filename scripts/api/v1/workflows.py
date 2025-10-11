from fastapi import APIRouter, HTTPException, status
import re
import json
from datetime import datetime

from scripts.models.schemas import WorkflowSaveRequest, WorkflowUpdateRequest
from scripts.services.storage import (
    get_all_workflows,
    get_workflow_by_id,
    add_workflow,
    delete_workflow_by_id,
)

router = APIRouter()

@router.get("/workflows")
async def list_workflows():
    """Получить список всех сохраненных workflows."""
    # Теперь get_all_workflows асинхронная и возвращает список словарей
    workflows_list = await get_all_workflows()
    return {"workflows": workflows_list}

@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Получить данные конкретного workflow по его ID."""
    workflow = await get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    # Данные из JSONB колонок нужно десериализовать
    workflow_dict = dict(workflow)
    if workflow_dict.get('nodes'):
        workflow_dict['nodes'] = json.loads(workflow_dict['nodes'])
    if workflow_dict.get('connections'):
        workflow_dict['connections'] = json.loads(workflow_dict['connections'])
        
    return workflow_dict

@router.post("/workflows", status_code=status.HTTP_201_CREATED)
async def create_workflow(request: WorkflowSaveRequest):
    """Создает новый workflow."""
    workflow_id = re.sub(r'[^a-z0-9_]+', '', request.name.lower().replace(" ", "_"))
    if not workflow_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow name, results in empty ID.")
    
    if await get_workflow_by_id(workflow_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Workflow with ID '{workflow_id}' already exists.")
    
    workflow_data = {
        "name": request.name,
        "nodes": [node.dict() for node in request.nodes],
        "connections": [conn.dict() for conn in request.connections],
        "status": "draft"
    }
    await add_workflow(workflow_id, workflow_data)
    return {"success": True, "workflow_id": workflow_id, "name": request.name}


@router.post("/workflows/{workflow_id}/publish", status_code=status.HTTP_200_OK)
async def publish_workflow(workflow_id: str):
    """Публикует workflow, делая его триггеры активными."""
    workflow = await get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    # Преобразуем в изменяемый словарь
    workflow_data = dict(workflow)
    workflow_data["status"] = "published"
    
    # Десериализуем JSONB поля перед отправкой на сохранение
    if workflow_data.get('nodes'):
        workflow_data['nodes'] = json.loads(workflow_data['nodes'])
    if workflow_data.get('connections'):
        workflow_data['connections'] = json.loads(workflow_data['connections'])

    await add_workflow(workflow_id, workflow_data)
    
    return {"success": True, "message": f"Workflow '{workflow_id}' has been published."}


@router.post("/workflows/{workflow_id}/unpublish", status_code=status.HTTP_200_OK)
async def unpublish_workflow(workflow_id: str):
    """Снимает workflow с публикации, делая его триггеры неактивными."""
    workflow = await get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    workflow_data = dict(workflow)
    workflow_data["status"] = "draft"

    if workflow_data.get('nodes'):
        workflow_data['nodes'] = json.loads(workflow_data['nodes'])
    if workflow_data.get('connections'):
        workflow_data['connections'] = json.loads(workflow_data['connections'])

    await add_workflow(workflow_id, workflow_data)
    
    return {"success": True, "message": f"Workflow '{workflow_id}' has been unpublished and is now a draft."}


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, request: WorkflowUpdateRequest):
    """Обновляет существующий workflow."""
    workflow = await get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    # Создаем новый словарь для сохранения, чтобы не мутировать исходные данные
    workflow_data = {
        "name": workflow['name'], # Имя не меняем при этом вызове
        "status": workflow['status'],
        "nodes": [node.dict() for node in request.nodes],
        "connections": [conn.dict() for conn in request.connections]
    }

    await add_workflow(workflow_id, workflow_data)
    return {"success": True, "message": f"Workflow '{workflow_id}' updated successfully."}

@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str):
    """Удаляет workflow."""
    if not await get_workflow_by_id(workflow_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    await delete_workflow_by_id(workflow_id)