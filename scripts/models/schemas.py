from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime

class NodeConfig(BaseModel):
    authToken: Optional[str] = None
    systemMessage: Optional[str] = None
    userMessage: Optional[str] = None
    clearHistory: Optional[bool] = False
    to: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    query: Optional[str] = None
    connection: Optional[str] = None
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[str] = None
    interval: Optional[int] = None
    timezone: Optional[str] = None
    waitForAll: Optional[bool] = True 
    mergeStrategy: Optional[str] = "combine_text"
    separator: Optional[str] = "\n\n---\n\n"
    # Для Request Iterator ноды
    baseUrl: Optional[str] = None
    executionMode: Optional[str] = "sequential" # New: 'sequential' or 'parallel'
    commonHeaders: Optional[str] = None # New: JSON string for common headers
    # Для If/Else ноды
    conditionType: Optional[str] = "equals"
    fieldPath: Optional[str] = "output.text"
    compareValue: Optional[str] = ""
    caseSensitive: Optional[bool] = False
    maxGotoIterations: Optional[int] = 3  # Защита от бесконечных циклов
    # НОВОЕ: Для Dispatcher ноды
    routes: Optional[Dict[str, Any]] = None
    useAI: Optional[bool] = True
    dispatcherAuthToken: Optional[str] = None # Токен для GigaChat внутри диспетчера
    dispatcher_type: Optional[str] = "router"  # "router" или "orchestrator"
    enable_planning: Optional[bool] = False
    available_workflows: Optional[Dict[str, Any]] = {}
    session_storage: Optional[str] = "memory"

class Node(BaseModel):
    id: str
    type: str
    position: Dict[str, float]
    data: Dict[str, Any]

class Connection(BaseModel):
    id: str
    source: str
    target: str
    data: Optional[Dict[str, Any]] = {}  # Добавляем поддержку data для меток

class WorkflowExecuteRequest(BaseModel):
    nodes: List[Node]
    connections: List[Connection]
    startNodeId: Optional[str] = None

class ExecutionResult(BaseModel):
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    logs: List[Dict[str, Any]] = []

class WorkflowSaveRequest(BaseModel):
    name: str
    nodes: List[Node]
    connections: List[Connection]

class WorkflowUpdateRequest(BaseModel):
    nodes: List[Node]
    connections: List[Connection]

class WebhookCreateRequest(BaseModel):
    workflow_id: str
    name: str
    description: Optional[str] = None
    auth_required: Optional[bool] = False
    allowed_ips: Optional[List[str]] = None

class WebhookInfo(BaseModel):
    webhook_id: str
    workflow_id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    url: str
    auth_required: bool = False
    allowed_ips: Optional[List[str]] = None
    call_count: int = 0
    last_called: Optional[str] = None

class SetupTimerRequest(BaseModel):
    node: Node
    workflow_id: str

# --- НОВАЯ МОДЕЛЬ ДЛЯ КОЛЛБЭКА ДИСПЕТЧЕРА ---
class DispatcherCallbackRequest(BaseModel):
    session_id: str
    step_result: Dict[str, Any]
