from fastapi import APIRouter, Request, HTTPException, status
from typing import Dict, Any
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
    Не сохраняет вебхук, а просто возвращает сгенерированные данные,
    чтобы фронтенд мог сохранить их в конфигурации ноды.
    """
    webhook_id = str(uuid.uuid4())
    
    base_url = str(http_request.base_url).rstrip('/')
    webhook_url = f"{base_url}api/v1/webhooks/{webhook_id}"

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


@router.post("/webhooks/{webhook_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_webhook(webhook_id: str, request: Request):
    """
    Принимает входящие вебхуки, находит соответствующий воркфлоу и запускает его.
    """
    # 1. Найти воркфлоу и ноду, которые соответствуют этому webhook_id
    target_workflow_id = None
    target_node_id = None
    all_workflows = get_all_workflows()

    for wf_id, wf_data in all_workflows.items():
        for node in wf_data.get('nodes', []):
            # Ищем ноду-триггер с совпадающим ID
            if node.get('type') == 'webhook_trigger':
                if node.get('data', {}).get('config', {}).get('webhookId') == webhook_id:
                    target_workflow_id = wf_id
                    target_node_id = node['id']
                    break
        if target_workflow_id:
            break

    if not target_workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook ID not found")

    # 2. Подготовить входные данные из запроса
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

    # 3. Запустить воркфлоу
    workflow_to_execute = get_workflow_by_id(target_workflow_id)
    if not workflow_to_execute:
         # Эта проверка на всякий случай, но она не должна сработать, если мы нашли ID выше
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow to execute not found")

    execution_request = WorkflowExecuteRequest(
        nodes=workflow_to_execute['nodes'],
        connections=workflow_to_execute['connections'],
        startNodeId=target_node_id
    )

    # Запускаем выполнение в фоновом режиме, чтобы не заставлять внешний сервис ждать
    # Это важно для вебхуков, которые часто имеют короткий таймаут
    background_tasks = request.app.state.background_tasks
    background_tasks.add_task(execute_workflow_internal, execution_request, initial_input_data)

    return {"status": "success", "message": f"Workflow {target_workflow_id} triggered."}