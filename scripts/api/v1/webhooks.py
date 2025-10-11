from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks
from typing import Dict, Any, List
import uuid
from datetime import datetime

from scripts.services.storage import get_all_workflows, get_workflow_by_id
from scripts.core.workflow_engine import execute_workflow_internal
from scripts.models.schemas import WorkflowExecuteRequest, WebhookCreateRequest, WebhookInfo

router = APIRouter()

@router.post("/webhooks/create", response_model=WebhookInfo, status_code=status.HTTP_201_CREATED)
async def create_webhook(request: WebhookCreateRequest, http_request: Request):
    """
    Создает уникальный ID и URL для нового вебхука.
    """
    webhook_id = str(uuid.uuid4())
    base_url = str(http_request.base_url).rstrip('/')
    webhook_url = f"{base_url}/api/v1/webhooks/{webhook_id}"

    webhook_info = WebhookInfo(
        webhook_id=webhook_id,
        url=webhook_url,
        workflow_id=request.workflow_id,
        name=request.name,
        description=request.description,
        created_at=datetime.now(),
        auth_required=request.auth_required or False,
        allowed_ips=request.allowed_ips or [],
        call_count=0,
        last_called=None
    )
    return webhook_info

import json

@router.post("/webhooks/{webhook_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_webhook(webhook_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Принимает входящие вебхуки, находит соответствующий воркфлоу и запускает его.
    """
    target_workflow_id = None
    target_node_id = None
    
    # Получаем краткий список всех workflow
    all_workflows_summary = await get_all_workflows()

    # Итерируемся по всем workflow, чтобы найти нужный webhook_trigger
    for wf_summary in all_workflows_summary:
        wf_id = wf_summary.get('id')
        # Получаем полные данные workflow для проверки узлов
        wf_data_raw = await get_workflow_by_id(wf_id)
        if not wf_data_raw:
            continue

        # Десериализуем узлы
        nodes_json = wf_data_raw.get('nodes', '[]')
        nodes = json.loads(nodes_json)

        for node in nodes:
            if node.get('type') == 'webhook_trigger':
                if node.get('data', {}).get('config', {}).get('webhookId') == webhook_id:
                    target_workflow_id = wf_id
                    target_node_id = node['id']
                    break
        if target_workflow_id:
            break

    if not target_workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook ID not found")

    workflow_to_execute_raw = await get_workflow_by_id(target_workflow_id)
    if not workflow_to_execute_raw:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow to execute not found")

    workflow_to_execute = dict(workflow_to_execute_raw)
    if workflow_to_execute.get("status") != "published":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workflow is not published.")

    try:
        body = await request.json()
    except Exception:
        body = await request.text()
        
    headers = dict(request.headers)
    query_params = dict(request.query_params)

    initial_input_data = {
        "body": body,
        "headers": headers,
        "query_params": query_params
    }

    # Десериализуем данные перед передачей в движок
    nodes = json.loads(workflow_to_execute.get('nodes', '[]'))
    connections = json.loads(workflow_to_execute.get('connections', '[]'))

    execution_request = WorkflowExecuteRequest(
        nodes=nodes,
        connections=connections,
        startNodeId=target_node_id
    )

    background_tasks.add_task(execute_workflow_internal, execution_request, initial_input_data)

    return {"status": "success", "message": f"Workflow {target_workflow_id} triggered."}
