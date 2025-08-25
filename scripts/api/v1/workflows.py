from fastapi import APIRouter, HTTPException, status
import re
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
    workflows = get_all_workflows()
    return {
        "workflows": [
            {"id": wf_id, "name": wf_data.get("name", wf_id)}
            for wf_id, wf_data in workflows.items()
        ]
    }

@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Получить данные конкретного workflow по его ID."""
    workflow = get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow

@router.post("/workflows", status_code=status.HTTP_201_CREATED)
async def create_workflow(request: WorkflowSaveRequest):
    """Создает новый workflow."""
    workflow_id = re.sub(r'[^a-z0-9_]+', '', request.name.lower().replace(" ", "_"))
    if not workflow_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow name, results in empty ID.")
    
    if get_workflow_by_id(workflow_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Workflow with ID '{workflow_id}' already exists.")
    
    workflow_data = {
        "name": request.name,
        "nodes": [node.dict() for node in request.nodes],
        "connections": [conn.dict() for conn in request.connections],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    add_workflow(workflow_id, workflow_data)
    return {"success": True, "workflow_id": workflow_id, "name": request.name}

@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, request: WorkflowUpdateRequest):
    """Обновляет существующий workflow."""
    workflow = get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    workflow["nodes"] = [node.dict() for node in request.nodes]
    workflow["connections"] = [conn.dict() for conn in request.connections]
    workflow["updated_at"] = datetime.now().isoformat()
    add_workflow(workflow_id, workflow)
    return {"success": True, "message": f"Workflow '{workflow_id}' updated successfully."}

@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str):
    """Удаляет workflow."""
    if not get_workflow_by_id(workflow_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    delete_workflow_by_id(workflow_id)
