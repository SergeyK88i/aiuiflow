import aiohttp
from fastapi import FastAPI, HTTPException,Request, Body, Header, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional, Tuple
import requests
import uuid
import json
import asyncio
import logging
from datetime import datetime, timedelta
import re
import hashlib
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# НОВОЕ: Путь к файлу для хранения workflows и функции для работы с ним
WORKFLOWS_FILE = "saved_workflows.json"

def _save_workflows_to_disk():
    """Сохраняет текущие workflows в JSON файл."""
    with open(WORKFLOWS_FILE, "w", encoding="utf-8") as f:
        json.dump(saved_workflows, f, ensure_ascii=False, indent=4)
    logger.info(f"💾 Workflows сохранены в {WORKFLOWS_FILE}")

def _load_workflows_from_disk():
    """Загружает workflows из JSON файла при старте."""
    if os.path.exists(WORKFLOWS_FILE):
        with open(WORKFLOWS_FILE, "r", encoding="utf-8") as f:
            global saved_workflows
            saved_workflows = json.load(f)
            logger.info(f"✅ Workflows загружены из {WORKFLOWS_FILE}")

app = FastAPI(title="N8N Clone API", version="1.0.0")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище для активных таймеров
active_timers = {}
# Добавьте глобальную переменную для хранения workflow после других глобальных переменных (примерно строка 30)
saved_workflows = {}
# Добавьте эту глобальную переменную для хранения последних результатов выполнения нод
node_execution_results = {}

goto_execution_counter = {} 

# Расширьте глобальное хранилище webhook_triggers (около строки 40)
webhook_triggers: Dict[str, Dict[str, Any]] = {}
# Добавьте статистику вебхуков
webhook_stats: Dict[str, Dict[str, Any]] = {}

# Модели данных
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

# Добавьте эту модель данных после существующих моделей (примерно строка 50-60)
class WorkflowSaveRequest(BaseModel):
    name: str
    nodes: List[Node]
    connections: List[Connection]

# НОВОЕ: Модель для обновления workflow
class WorkflowUpdateRequest(BaseModel):
    nodes: List[Node]
    connections: List[Connection]

# Добавьте новые модели данных после существующих (около строки 80)
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
    created_at: str
    url: str
    auth_required: bool = False
    allowed_ips: Optional[List[str]] = None
    call_count: int = 0
    last_called: Optional[str] = None

# GigaChat API класс
class GigaChatAPI:
    def __init__(self):
        self.access_token = None
        self.conversation_history = []
        
    async def get_token(self, auth_token: str, scope: str = 'GIGACHAT_API_PERS') -> bool:
        """Получение токена доступа"""
        rq_uid = str(uuid.uuid4())
        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': rq_uid,
            'Authorization': f'Basic {auth_token}'
        }
        payload = {'scope': scope}

        try:
            # В реальном приложении используйте aiohttp для асинхронных запросов
            response = requests.post(url, headers=headers, data=payload, verify=False)
            if response.status_code == 200:
                self.access_token = response.json()['access_token']
                logger.info("✅ GigaChat токен получен успешно")
                return True
            else:
                logger.error(f"❌ Ошибка получения токена: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка при получении токена: {str(e)}")
            return False

    async def get_chat_completion(self, system_message: str, user_message: str) -> Dict[str, Any]:
        """Получение ответа от GigaChat"""
        if not self.access_token:
            raise Exception("Токен доступа не получен")

        # Формируем сообщения
        messages = [{"role": "system", "content": system_message}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_message})

        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 1,
            "top_p": 0.1,
            "n": 1,
            "stream": False,
            "max_tokens": 512,
            "repetition_penalty": 1,
            "update_interval": 0
        }
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False)
            if response.status_code == 200:
                # Сохраняем в историю
                self.conversation_history.append({"role": "user", "content": user_message})
                assistant_response = response.json()['choices'][0]['message']['content']
                self.conversation_history.append({"role": "assistant", "content": assistant_response})
                
                logger.info(f"✅ Получен ответ от GigaChat")
                logger.info(f"🤖 ОТВЕТ: {assistant_response}")
                return {
                    "success": True,
                    "response": assistant_response,
                    "user_message": user_message,
                    "system_message": system_message,
                    "conversation_length": len(self.conversation_history)
                }
            else:
                logger.error(f"❌ Ошибка API GigaChat: {response.status_code}")
                return {
                    "success": False,
                    "error": f"API Error: {response.status_code}",
                    "response": None
                }
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе к GigaChat: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": None
            }

    def clear_history(self):
        """Очистка истории диалога"""
        self.conversation_history = []
        logger.info("🗑️ История диалога очищена")

# Функция для создания и запуска таймера
async def create_timer(timer_id: str, node_id: str, interval: int, workflow_info: Dict[str, Any]):
    """Создает и запускает новый таймер"""
    # Отменяем существующий таймер, если он есть
    if timer_id in active_timers and active_timers[timer_id]["task"] is not None:
        active_timers[timer_id]["task"].cancel()
        logger.info(f"🛑 Отменен существующий таймер {timer_id}")
    
    # Создаем новый таймер
    next_execution = datetime.now() + timedelta(minutes=interval)
    
    # Создаем и запускаем задачу таймера
    task = asyncio.create_task(timer_task(timer_id, node_id, interval, workflow_info))
    
    # Сохраняем информацию о таймере
    active_timers[timer_id] = {
        "node_id": node_id,
        "interval": interval,
        "next_execution": next_execution,
        "task": task,
        "status": "active",
        "workflow": workflow_info
    }
    
    return {
        "id": timer_id,
        "node_id": node_id,
        "interval": interval,
        "next_execution": next_execution.isoformat(),
        "status": "active"
    }

async def update_timer(timer_id: str, interval: int):
    """Обновляет существующий таймер"""
    if timer_id not in active_timers:
        raise Exception(f"Timer {timer_id} not found")
    
    # Получаем информацию о существующем таймере
    timer_info = active_timers[timer_id]
    
    # Создаем новый таймер с обновленным интервалом
    await create_timer(
        timer_id, 
        timer_info["node_id"], 
        interval, 
        timer_info["workflow"]
    )
    
    return {
        "id": timer_id,
        "node_id": timer_info["node_id"],
        "interval": interval,
        "next_execution": active_timers[timer_id]["next_execution"].isoformat(),
        "status": "active"
    }

async def timer_task(timer_id: str, node_id: str, interval: int, workflow_info: Dict[str, Any]):
    """Задача таймера, которая выполняется асинхронно"""
    try:
        while True:
            # Ждем указанный интервал
            logger.info(f"⏰ Запущена задача таймера {timer_id} для ноды {node_id} с интервалом {interval} минут")
            logger.info(f"⏰ Таймер {timer_id} ожидает {interval} минут до следующего запуска")
            await asyncio.sleep(interval * 60)  # Переводим минуты в секунды
            
            # Обновляем время следующего выполнения
            active_timers[timer_id]["next_execution"] = datetime.now() + timedelta(minutes=interval)

            # Перед началом выполнения workflow
            if timer_id in active_timers and active_timers[timer_id].get("is_executing_workflow", False):
                logger.warning(f"⚠️ Таймер {timer_id} уже выполняет workflow, пропускаем этот цикл")
                continue

            # 🔴 ДОБАВИТЬ: Отмечаем начало выполнения workflow
            active_timers[timer_id]["is_executing_workflow"] = True
            
            try:
                # Выполняем workflow
                logger.info(f"🚀 Таймер {timer_id} запускает workflow")
                # Используем ту же логику, что и execute_workflow
                workflow_request = WorkflowExecuteRequest(
                    nodes=workflow_info["nodes"],
                    connections=workflow_info["connections"],
                    startNodeId=node_id  # Начинаем с ноды таймера
                )
                
                # Выполняем workflow правильно
                start_time = datetime.now()
                result = await execute_workflow_internal(workflow_request)
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.info(f"⏱️ Workflow выполнен за {execution_time:.2f} секунд")
                
                if result.success:
                    logger.info(f"✅ Таймер {timer_id} успешно выполнил workflow")
                    
                    # Сохраняем результаты для отображения в UI
                    if result.result:
                        for node_id_result, node_result in result.result.items():
                            node_execution_results[node_id_result] = {
                                "result": node_result,
                                "timestamp": datetime.now().isoformat(),
                                "status": "success"
                            }
                else:
                    logger.error(f"❌ Ошибка выполнения workflow таймером {timer_id}: {result.error}")
            
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при выполнении workflow таймером {timer_id}: {str(e)}")
                import traceback
                logger.error(f"🔍 Трассировка: {traceback.format_exc()}")
            finally:
                # 🔴 ДОБАВИТЬ: Снимаем флаг выполнения
                if timer_id in active_timers:
                    active_timers[timer_id]["is_executing_workflow"] = False
                    logger.info(f"🔓 Флаг выполнения снят для таймера {timer_id}")
                else:
                    logger.warning(f"⚠️ Таймер {timer_id} был удален во время выполнения workflow")
                
    except asyncio.CancelledError:
        logger.info(f"🛑 Таймер {timer_id} остановлен")
    except Exception as e:
        logger.error(f"❌ Ошибка в задаче таймера {timer_id}: {str(e)}")
        # Обновляем статус таймера
        if timer_id in active_timers:
            active_timers[timer_id]["status"] = "error"



def replace_templates(text: str, data: Dict[str, Any]) -> str:
        """Универсальная замена шаблонов вида {{path.to.value}}"""
        
        def get_nested_value(obj: Dict[str, Any], path: str) -> Any:
            """Получает значение по пути типа 'input.output.text'"""
            keys = path.split('.')
            current = obj
            
            for key in keys:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return f"{{{{ {path} }}}}"  # Возвращаем исходный шаблон если путь не найден
            
            return str(current)
        
        # Находим все шаблоны вида {{что-то}}
        pattern = r'\{\{([^}]+)\}\}'
        
        def replacer(match):
            path = match.group(1).strip()
            
            # Если путь начинается с 'input.', убираем это
            if path.startswith('input.'):
                path = path[6:]  # Убираем 'input.'
            
            value = get_nested_value(data, path)
            logger.info(f"🔄 Замена шаблона: {{{{{match.group(1)}}}}} -> {value}")
            return value
        
        return re.sub(pattern, replacer, text)

# Add this helper function within the NodeExecutors class or globally if preferred
# For simplicity, let's add it before the NodeExecutors class or as a static method

async def _make_single_http_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Makes a single HTTP request and returns a structured response or mock on error.
    """
    request_details = {
        "request_url": url,
        "request_method": method,
        "request_params": params if method == "GET" else None,
        "request_body": json_body if method in ["POST", "PUT", "PATCH"] else None,
        "request_headers": headers,
    }
    try:
        logger.info(f"🌍 Making {method} request to {url} with params={params}, body={json_body}, headers={headers}")
        async with session.request(
            method,
            url,
            params=params if method == "GET" else None, # Query params for GET
            json=json_body if method in ["POST", "PUT", "PATCH"] else None, # JSON body for POST/PUT etc.
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10), # 10-second timeout
            ssl=False
        ) as response:
            response_data = None
            try:
                # Try to parse as JSON, but handle cases where it might not be
                if response.content_type == 'application/json':
                    response_data = await response.json()
                else:
                    response_data = await response.text()
            except (aiohttp.ContentTypeError, json.JSONDecodeError) as json_err:
                logger.warning(f"⚠️ Could not parse JSON response from {url}: {json_err}. Reading as text.")
                response_data = await response.text() # Fallback to text
            except Exception as e:
                logger.error(f"🚨 Error reading response content from {url}: {e}")
                response_data = f"Error reading response: {e}"


            logger.info(f"✅ Response from {url}: {response.status}")
            return {
                **request_details,
                "status_code": response.status,
                "response_headers": dict(response.headers),
                "response_data": response_data,
                "success": 200 <= response.status < 300,
            }
    except aiohttp.ClientConnectorError as e:
        logger.error(f"❌ Connection error for {url}: {e}")
        return {
            **request_details,
            "status_code": 503, # Service Unavailable
            "response_data": {"error": "Connection Error", "details": str(e)},
            "success": False,
            "mock_reason": "Connection Error",
        }
    except asyncio.TimeoutError:
        logger.error(f"⏰ Timeout error for {url}")
        return {
            **request_details,
            "status_code": 504, # Gateway Timeout
            "response_data": {"error": "Timeout Error", "details": "Request timed out after 10 seconds"},
            "success": False,
            "mock_reason": "Timeout Error",
        }
    except Exception as e:
        logger.error(f"💥 Unexpected error for {url}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            **request_details,
            "status_code": 500, # Internal Server Error
            "response_data": {"error": "Unexpected Error", "details": str(e)},
            "success": False,
            "mock_reason": "Unexpected Error",
        }
    
# Исполнители нод
class NodeExecutors:
    def __init__(self):
        self.gigachat_api = GigaChatAPI()
    
    
    async def execute_request_iterator(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Executing Request Iterator node: {node.id}")
        config = node.data.get('config', {})
        base_url = config.get('baseUrl', '').rstrip('/') # Ensure no trailing slash
        execution_mode = config.get('executionMode', 'sequential')
        common_headers_str = config.get('commonHeaders', '{}')

        parsed_common_headers = {}
        try:
            parsed_common_headers = json.loads(common_headers_str) if common_headers_str else {}
            if not isinstance(parsed_common_headers, dict):
                logger.warning("Common headers is not a valid JSON object, ignoring.")
                parsed_common_headers = {}
        except json.JSONDecodeError:
            logger.warning("Failed to parse common headers JSON, ignoring.")
            parsed_common_headers = {}

        requests_to_make_json_str = ""
        if input_data and 'output' in input_data and 'text' in input_data['output']:
            requests_to_make_json_str = input_data['output']['text']
        elif input_data and isinstance(input_data.get('requests_array'), list):
            requests_to_make_json_str = json.dumps(input_data.get('requests_array'))
        elif isinstance(input_data, list): # If the direct input_data is a list
             requests_to_make_json_str = json.dumps(input_data)
        elif isinstance(input_data, str): # If the direct input_data is a JSON string
             requests_to_make_json_str = input_data
        else:
            logger.error("Request Iterator: Input data must contain a JSON string or array of requests.")
            raise Exception("Request Iterator: Input data must contain a JSON string or array of requests.")

        try:
            requests_list = json.loads(requests_to_make_json_str)
            if not isinstance(requests_list, list):
                # If it's a single object, wrap it in a list
                if isinstance(requests_list, dict):
                    logger.info("Request Iterator: Received a single JSON object, wrapping it into a list.")
                    requests_list = [requests_list]
                else:
                    raise ValueError("Parsed JSON is not a list or a single request object.")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Request Iterator: Failed to parse JSON input: {str(e)}")
            raise Exception(f"Request Iterator: Invalid JSON input for requests: {str(e)}")

        if not requests_list:
            logger.info("Request Iterator: No requests to process from input.")
            return {
                "success": True,
                "executed_requests_count": 0,
                "responses": [],
                "output": {"text": "[]"}
            }

        all_responses = []
        tasks = []

        # It's better to create one session for all requests from this node execution
        async with aiohttp.ClientSession() as session:
            for req_info in requests_list:
                if not isinstance(req_info, dict):
                    logger.warning(f"Skipping invalid request item (not a dict): {req_info}")
                    all_responses.append({
                        "error": "Invalid request item format",
                        "item_data": req_info,
                        "success": False
                    })
                    continue

                endpoint = req_info.get('endpoint', '')
                if not endpoint:
                    logger.warning(f"Request Iterator: Skipping request with no endpoint: {req_info}")
                    all_responses.append({
                        "error": "Missing endpoint",
                        "item_data": req_info,
                        "success": False
                    })
                    continue
                
                # Ensure endpoint starts with a slash if base_url is present, or is a full URL
                if base_url and not endpoint.startswith('/') and not endpoint.lower().startswith(('http://', 'https://')):
                    final_url = f"{base_url}/{endpoint.lstrip('/')}"
                elif not base_url and not endpoint.lower().startswith(('http://', 'https://')):
                    logger.warning(f"Request Iterator: Endpoint '{endpoint}' is relative but no baseUrl is configured. Skipping.")
                    all_responses.append({
                        "error": "Relative endpoint with no baseUrl",
                        "item_data": req_info,
                        "success": False
                    })
                    continue
                elif endpoint.lower().startswith(('http://', 'https://')):
                    final_url = endpoint # Endpoint is already a full URL
                else: # base_url is present and endpoint starts with /
                    final_url = f"{base_url}{endpoint}"


                method = req_info.get('method', 'GET').upper()
                
                # Prepare params for GET and body for POST/PUT etc.
                get_params = req_info.get('params') if method == 'GET' else None
                json_body = req_info.get('body') if method in ['POST', 'PUT', 'PATCH'] else None
                
                # Merge headers: common_headers < specific_request_headers
                specific_headers = req_info.get('headers', {})
                if not isinstance(specific_headers, dict):
                    logger.warning(f"Specific headers for {final_url} is not a dict, ignoring.")
                    specific_headers = {}

                final_headers = {**parsed_common_headers, **specific_headers}

                # Create a coroutine for the request
                task = _make_single_http_request(
                    session,
                    method,
                    final_url,
                    params=get_params,
                    json_body=json_body,
                    headers=final_headers
                )
                tasks.append(task)

            if execution_mode == 'parallel' and tasks:
                logger.info(f"Request Iterator: Executing {len(tasks)} requests in PARALLEL mode.")
                # asyncio.gather executes tasks concurrently
                # return_exceptions=True ensures that if one task fails, others continue and we get the exception
                gathered_results = await asyncio.gather(*tasks, return_exceptions=True)
                for result_or_exc in gathered_results:
                    if isinstance(result_or_exc, Exception):
                        # This case should ideally be handled within _make_single_http_request itself
                        # by returning a structured error. If it still gets here, log it.
                        logger.error(f"Request Iterator: Unhandled exception from parallel task: {result_or_exc}")
                        all_responses.append({
                            "error": "Unhandled parallel execution error",
                            "details": str(result_or_exc),
                            "success": False,
                        })
                    else:
                        all_responses.append(result_or_exc)
            elif tasks: # Sequential mode (default)
                logger.info(f"Request Iterator: Executing {len(tasks)} requests in SEQUENTIAL mode.")
                for task_coro in tasks:
                    result = await task_coro # Await each task one by one
                    all_responses.append(result)
            
        # Filter out any initial error placeholders if they were added before task creation
        final_responses_list = [r for r in all_responses if r.get("request_url") or r.get("error")]


        logger.info(f"Request Iterator: Processed {len(final_responses_list)} requests.")
        return {
            "success": True, # The iterator node itself succeeded in processing
            "executed_requests_count": len(final_responses_list),
            "responses": final_responses_list,
            "output": { # Provide the responses as text for downstream nodes
                "text": json.dumps(final_responses_list, ensure_ascii=False, indent=2),
                "json_array": final_responses_list # Also provide as a direct array
            }
        }

    async def execute_gigachat(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение GigaChat ноды"""
        logger.info(f"Executing GigaChat node: {node.id}")
        config = node.data.get('config', {})
        auth_token = config.get('authToken')
        system_message = config.get('systemMessage', 'Ты полезный ассистент')
        user_message = config.get('userMessage', '')
        clear_history = config.get('clearHistory', False)

        # ДОБАВЛЯЕМ ЛОГИРОВАНИЕ ВХОДНЫХ ДАННЫХ
        logger.info(f"📥 Входные данные от предыдущей ноды: {json.dumps(input_data, ensure_ascii=False, indent=2)[:500]}...")
        # УНИВЕРСАЛЬНАЯ ЗАМЕНА ШАБЛОНОВ
        if input_data:
            original_message = user_message
            user_message = replace_templates(user_message, input_data)
            # Также заменяем шаблоны в system_message если есть
            system_message = replace_templates(system_message, input_data)
            
            if original_message != user_message:
                logger.info(f"📝 Сообщение до замены: {original_message}")
                logger.info(f"📝 Сообщение после замены: {user_message}")

        if not auth_token or not user_message:
            raise Exception("GigaChat: Auth token and user message are required")

        logger.info(f"🤖 Выполнение GigaChat ноды: {node.id}")
        logger.info(f"📝 Вопрос: {user_message}")
        # Очищаем историю если нужно
        if clear_history:
            self.gigachat_api.clear_history()

        # Получаем токен
        if not await self.gigachat_api.get_token(auth_token):
            raise Exception("Не удалось получить токен доступа")

        # Выполняем запрос
        result = await self.gigachat_api.get_chat_completion(system_message, user_message)
        
        if not result.get('success'):
            raise Exception(result.get('error', 'Unknown error'))

        # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ---
        # Пытаемся распарсить ответ как JSON, но не ломаемся, если это не он.
        raw_response_text = result.get('response', '')
        parsed_json = None
        try:
            # Попытка парсинга
            parsed_json = json.loads(raw_response_text)
            logger.info("✅ Ответ от GigaChat успешно распознан как JSON.")
        except json.JSONDecodeError:
            # Если это не JSON, ничего страшного. Просто логируем это.
            logger.info("ℹ️ Ответ от GigaChat не является валидным JSON. Будет обработан как обычный текст.")
            pass # parsed_json останется None

        # Формируем выходные данные для следующих нод
        # Теперь output содержит и text, и json
        return {
            **result, # Включаем все исходные поля из result (success, response и т.д.)
            "output": {
                "text": raw_response_text, # Всегда содержит сырой текстовый ответ
                "json": parsed_json,      # Содержит распарсенный объект или null
                "question": user_message,
                "length": len(raw_response_text),
                "words": len(raw_response_text.split()),
                "timestamp": datetime.now().isoformat()
            }
        }


    async def execute_email(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение Email ноды"""
        config = node.data.get('config', {})
        to = config.get('to', '')
        subject = config.get('subject', '')
        body = config.get('body', '')

        # Используем данные из предыдущих нод если поля пустые
        if not body and input_data and 'output' in input_data:
            body = input_data['output'].get('text', 'No content from previous node')
        
        if not subject and input_data and 'output' in input_data:
            subject = f"Response: {input_data['output'].get('question', 'Workflow Result')}"

        logger.info(f"📧 Отправка email на {to}")
        logger.info(f"📋 Тема: {subject}")
        logger.info(f"📄 Тело: {body[:100]}...")

        # Здесь будет реальная отправка email (например, через SendGrid, SMTP)
        # Пока симулируем
        await asyncio.sleep(1)

        return {
            "success": True,
            "sent": True,
            "to": to,
            "subject": subject,
            "body": body,
            "messageId": f"msg_{int(datetime.now().timestamp())}",
            "inputData": input_data
        }

    async def execute_database(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение Database ноды"""
        config = node.data.get('config', {})
        query = config.get('query', '')
        connection = config.get('connection', 'postgres')

        # Автогенерация запроса если пустой
        if not query and input_data and 'output' in input_data:
            text_data = input_data['output'].get('text', 'No data')[:100]
            query = f"INSERT INTO responses (text, timestamp) VALUES ('{text_data}', NOW())"

        logger.info(f"🗄️ Выполнение SQL запроса")
        logger.info(f"🔗 Подключение: {connection}")
        logger.info(f"📝 Запрос: {query}")

        # Здесь будет реальное выполнение SQL запроса
        # Пока симулируем
        await asyncio.sleep(1)

        return {
            "success": True,
            "rows": [
                {
                    "id": 1,
                    "text": input_data.get('output', {}).get('text', 'Sample Data')[:100],
                    "created_at": datetime.now().isoformat()
                }
            ],
            "rowCount": 1,
            "query": query,
            "connection": connection,
            "inputData": input_data
        }

    async def execute_webhook(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение Webhook ноды - отправляет HTTP запрос"""
        config = node.data.get('config', {})
        url = config.get('url', '')
        method = config.get('method', 'POST').upper()
        headers_str = config.get('headers', 'Content-Type: application/json')
        
        # Заменяем шаблоны в URL (например, https://api.com/user/{{input.output.user_id}})
        if input_data:
            url = replace_templates(url, input_data)

        if not url:
            raise Exception("Webhook URL is required")
        
        # Парсим заголовки
        headers = {}
        if headers_str:
            for line in headers_str.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip()] = value.strip()
        
        # Подготавливаем данные для отправки
        # Если есть output.text от предыдущей ноды, используем его
        payload = input_data
        if input_data and 'output' in input_data:
            # Можно отправить либо весь output, либо только text
            payload = input_data['output']
        
        logger.info(f"🌐 Отправка {method} запроса на {url}")
        if method in ['POST', 'PUT', 'PATCH'] and payload:
            logger.info(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)[:200]}...")
        
        try:
            # Реальная отправка запроса
            async with aiohttp.ClientSession() as session:
                # ⬇️ ГЛАВНОЕ ИЗМЕНЕНИЕ: Правильная обработка параметров
                request_params = {
                    'method': method,
                    'url': url,
                    'headers': headers,
                    'timeout': aiohttp.ClientTimeout(total=30),
                    'ssl': False
                }
            
                # Добавляем body только для методов, которые его поддерживают
                if method in ['POST', 'PUT', 'PATCH'] and payload:
                    request_params['json'] = payload
                
                # Для GET запросов НЕ добавляем params из payload
                # (если нужны query параметры, они должны быть в URL)
            
                async with session.request(**request_params) as response:
                    response_text = await response.text()
                    response_json = None
                    
                    try:
                        response_json = await response.json()
                    except:
                        pass  # Не все ответы в JSON
                    
                    logger.info(f"✅ Webhook ответ: {response.status}")
                    
                    # ⬇️ ДОБАВЛЕНО: Логирование полученных данных для отладки
                    if response_json and isinstance(response_json, list):
                        logger.info(f"📊 Получено {len(response_json)} элементов")
                    
                    return {
                        "success": response.status < 400,
                        "status_code": response.status,
                        "response": response_text,
                        "response_json": response_json,
                        "url": url,
                        "method": method,
                        "timestamp": datetime.now().isoformat(),
                        "output": {
                            "text": response_text,
                            "status": response.status,
                            "json": response_json
                        }
                    }

                    
        except aiohttp.ClientError as e:
            logger.error(f"❌ Ошибка webhook: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "connection_error",
                "url": url,
                "method": method,
                "timestamp": datetime.now().isoformat(),
                "output": {
                    "text": f"Error: {str(e)}",
                    "status": 0
                }
            }
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка webhook: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "unexpected_error",
                "url": url,
                "method": method,
                "timestamp": datetime.now().isoformat()
            }


    async def execute_timer(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение Timer ноды"""
        try:
            config = node.data.get('config', {})
            
            # Получаем интервал с обработкой ошибок
            try:
                interval = int(config.get('interval', 5))
            except ValueError:
                logger.warning(f"❌ Неверный формат интервала: {config.get('interval')}. Используем значение по умолчанию: 5")
                interval = 5
                
            timezone = config.get('timezone', 'UTC')

            logger.info(f"⏰ Timer нода выполнена: интервал {interval} минут, часовой пояс {timezone}")
            
            # Проверяем, существует ли уже таймер для этой ноды
            timer_id = f"timer_{node.id}"
            
            # 🔴 ДОБАВИТЬ ЗДЕСЬ ПРОВЕРКУ
            # Проверяем, выполняет ли таймер сейчас workflow
            if timer_id in active_timers:
                current_timer = active_timers[timer_id]
                if current_timer.get("is_executing_workflow", False):
                    logger.info(f"⏳ Timer {timer_id} сейчас выполняет workflow, пропускаем обновление")
                    
                    # Формируем выходные данные без пересоздания таймера
                    current_time = datetime.now()
                    next_execution = current_timer.get("next_execution", current_time + timedelta(minutes=interval))
                    
                    return {
                        "success": True,
                        "message": f"Timer is currently executing workflow",
                        "interval": interval,
                        "timezone": timezone,
                        "timestamp": current_time.isoformat(),
                        "next_execution": next_execution.isoformat() if isinstance(next_execution, datetime) else next_execution,
                        "timer_id": timer_id,
                        "output": {
                            "text": f"Timer triggered at {current_time.isoformat()}. Timer is currently busy.",
                            "timestamp": current_time.isoformat(),
                            "interval": interval,
                            "timezone": timezone
                        }
                    }
            # 🔴 КОНЕЦ ДОБАВЛЕННОГО БЛОКА

            # Получаем ID текущего workflow из имени
            workflow_id = None
            for wf_id, wf_data in saved_workflows.items():
                if any(n['id'] == node.id for n in wf_data["nodes"]):
                    workflow_id = wf_id
                    break
            
            if not workflow_id:
                logger.warning(f"⚠️ Workflow для ноды {node.id} не найден. Таймер может работать некорректно.")
            
            # Если это первое выполнение, создаем новый таймер
            if timer_id not in active_timers:
                # Используем сохраненный workflow или создаем минимальный
                workflow_info = None
                if workflow_id and workflow_id in saved_workflows:
                    workflow_info = {
                        "nodes": saved_workflows[workflow_id]["nodes"],
                        "connections": saved_workflows[workflow_id]["connections"],
                        "startNodeId": node.id
                    }
                else:
                    # Минимальный workflow с текущей нодой
                    workflow_info = {
                        "nodes": [node],
                        "connections": [],
                        "startNodeId": node.id
                    }
                
                # Создаем таймер
                await create_timer(timer_id, node.id, interval, workflow_info)
                
                logger.info(f"🕒 Создан новый таймер {timer_id} с интервалом {interval} минут")
            else:
                # Обновляем существующий таймер
                await update_timer(timer_id, interval)
                logger.info(f"🕒 Обновлен таймер {timer_id} с новым интервалом {interval} минут")
            
            # Формируем выходные данные для следующих нод
            current_time = datetime.now()
            next_execution = current_time + timedelta(minutes=interval)
            
            return {
                "success": True,
                "message": f"Timer triggered at {current_time.isoformat()}",
                "interval": interval,
                "timezone": timezone,
                "timestamp": current_time.isoformat(),
                "next_execution": next_execution.isoformat(),
                "timer_id": timer_id,
                "output": {
                    "text": f"Timer triggered at {current_time.isoformat()}. Next execution at {next_execution.isoformat()}",
                    "timestamp": current_time.isoformat(),
                    "interval": interval,
                    "timezone": timezone
                }
            }
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения Timer ноды: {str(e)}")
            raise Exception(f"Timer execution failed: {str(e)}")
    
    async def execute_join(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение Join/Merge ноды"""
        config = node.data.get('config', {})
        wait_for_all = config.get('waitForAll', True)
        merge_strategy = config.get('mergeStrategy', 'combine_text')
        separator = config.get('separator', '\n\n---\n\n').replace('\\n', '\n')
        
        logger.info(f"🔀 Выполнение Join/Merge ноды: {node.id}")
        logger.info(f"📥 Стратегия: {merge_strategy}")
        
        # input_data должен содержать словарь inputs с данными от всех источников
        inputs = input_data.get('inputs', {})
        
        if not inputs:
            raise Exception("Join node requires input data from at least one source")
        
        logger.info(f"📊 Получены данные от {len(inputs)} источников: {list(inputs.keys())}")
        
        result = {}
        
        if merge_strategy == 'combine_text':
            # Объединяем все тексты
            texts = []
            for i, (source_id, data) in enumerate(inputs.items()):
                # Извлекаем текст из разных возможных мест
                text = ""
                if isinstance(data, dict):
                    if 'output' in data and 'text' in data['output']:
                        text = data['output']['text']
                    elif 'response' in data:
                        text = data['response']
                    elif 'text' in data:
                        text = data['text']
                    else:
                        # Если не нашли текст, конвертируем в строку
                        text = json.dumps(data, ensure_ascii=False, indent=2)
                else:
                    text = str(data)
                
                texts.append(f"=== Источник {i+1} ({source_id}) ===\n{text}")
            
            combined_text = separator.join(texts)
            
            result = {
                'output': {
                    'text': combined_text,
                    'source_count': len(inputs),
                    'sources': list(inputs.keys())
                },
                'success': True
            }
            
            logger.info(f"✅ Объединено {len(texts)} текстов")
            
        elif merge_strategy == 'merge_json':
            # Объединяем все данные в единый JSON
            merged_data = {
                'sources': {},
                'metadata': {
                    'source_count': len(inputs),
                    'merge_time': datetime.now().isoformat(),
                    'source_ids': list(inputs.keys())
                }
            }
            
            # Добавляем данные от каждого источника
            for source_id, data in inputs.items():
                merged_data['sources'][source_id] = data
            
            result = {
                'output': {
                    'text': json.dumps(merged_data, ensure_ascii=False, indent=2),
                    'json': merged_data,
                    'source_count': len(inputs),
                    'sources': list(inputs.keys())
                },
                'success': True
            }
            
            logger.info(f"✅ Объединены данные в JSON от {len(inputs)} источников")
        
        else:
            raise Exception(f"Unknown merge strategy: {merge_strategy}")
        
        return result

    async def execute_if_else(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение If/Else ноды"""
        config = node.data.get('config', {})
        condition_type = config.get('conditionType', 'equals')
        field_path = config.get('fieldPath', 'output.text')
        compare_value = config.get('compareValue', '')
        case_sensitive = config.get('caseSensitive', False)
        
        logger.info(f"🔀 Выполнение If/Else ноды: {node.id}")
        logger.info(f"📋 Условие: {field_path} {condition_type} {compare_value}")
        
        # Получаем значение по пути
        def get_value_by_path(data: Dict[str, Any], path: str) -> Any:
            keys = path.split('.')
            current = data
            
            for key in keys:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                elif isinstance(current, list) and key.isdigit():
                    index = int(key)
                    if 0 <= index < len(current):
                        current = current[index]
                    else:
                        return None
                else:
                    return None
            
            return current
        
        actual_value = get_value_by_path(input_data, field_path)
        
        if actual_value is None and condition_type not in ['exists', 'is_empty']:
            logger.warning(f"⚠️ Поле {field_path} не найдено в данных")
            actual_value = ""
        
        # Приводим к строке для сравнения (если не число)
        if condition_type not in ['greater', 'greater_equal', 'less', 'less_equal']:
            actual_value_str = str(actual_value) if actual_value is not None else ""
            compare_value_str = str(compare_value)
            
            if not case_sensitive:
                actual_value_str = actual_value_str.lower()
                compare_value_str = compare_value_str.lower()
        else:
            # Для числовых сравнений
            try:
                actual_value_str = float(actual_value)
                compare_value_str = float(compare_value)
            except (ValueError, TypeError):
                actual_value_str = 0
                compare_value_str = 0
        
        # Проверяем условие
        result = False
        
        if condition_type == 'equals':
            result = actual_value_str == compare_value_str
        elif condition_type == 'not_equals':
            result = actual_value_str != compare_value_str
        elif condition_type == 'contains':
            result = compare_value_str in actual_value_str
        elif condition_type == 'not_contains':
            result = compare_value_str not in actual_value_str
        elif condition_type == 'greater':
            result = actual_value_str > compare_value_str
        elif condition_type == 'greater_equal':
            result = actual_value_str >= compare_value_str
        elif condition_type == 'less':
            result = actual_value_str < compare_value_str
        elif condition_type == 'less_equal':
            result = actual_value_str <= compare_value_str
        elif condition_type == 'regex':
            import re
            try:
                result = bool(re.search(compare_value, str(actual_value)))
            except re.error:
                result = False
        elif condition_type == 'exists':
            result = actual_value is not None
        elif condition_type == 'is_empty':
            result = actual_value is None or str(actual_value).strip() == ""
        elif condition_type == 'is_not_empty':
            result = actual_value is not None and str(actual_value).strip() != ""
        
        branch = 'true' if result else 'false'
        
        logger.info(f"📊 Результат проверки: {result} (ветка: {branch})")
        logger.info(f"📍 Фактическое значение: {actual_value}")
        logger.info(f"📍 Ожидаемое значение: {compare_value}")
        
        # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ---
        # Мы не создаем новый output, а возвращаем исходные данные,
        # добавляя к ним результат проверки для маршрутизации.
        # Это гарантирует, что данные от предыдущих нод не будут потеряны.
        return {
            **input_data,  # <--- Пропускаем все входные данные дальше
            'success': True,
            'branch': branch, # <--- Это поле используется для выбора следующей ноды
            'if_else_result': { # <--- Добавляем отдельный блок с результатами If/Else для ясности
                'condition_met': result,
                'checked_value': str(actual_value),
                'condition': f"{field_path} {condition_type} {compare_value}",
            }
        }

    # НОВОЕ: Логика для ноды-диспетчера
    async def execute_dispatcher(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Агент-диспетчер, который анализирует запрос и выбирает нужный workflow"""
        logger.info(f"Executing Dispatcher node: {node.id}")
        config = node.data.get('config', {})
        
        # Получаем вопрос пользователя из разных возможных источников
        user_query = ""
        if input_data and 'output' in input_data and 'text' in input_data['output']:
            user_query = input_data['output']['text']
        elif input_data and 'user_query' in input_data:
            user_query = input_data['user_query']
        elif isinstance(input_data, dict): # Пытаемся найти ключ с запросом
            user_query = input_data.get('query', input_data.get('text', ''))

        if not user_query:
            raise Exception("Dispatcher: User query not found in input data.")

        # Конфигурация маршрутов
        workflow_routes = config.get('routes', {})
        if not workflow_routes:
            raise Exception("Dispatcher: Routes are not configured.")

        category = 'default'
        
        # Используем GigaChat для умного анализа
        if config.get('useAI', True):
            auth_token = config.get('dispatcherAuthToken')
            if not auth_token:
                raise Exception("Dispatcher: GigaChat auth token is required for AI mode.")

            classification_prompt = f"""Определи категорию запроса пользователя и выбери подходящий обработчик.
Доступные категории: {json.dumps(list(workflow_routes.keys()), ensure_ascii=False)}
Запрос пользователя: {user_query}
Ответь ТОЛЬКО одним словом - названием категории."""
            
            # Получаем токен и делаем запрос
            if await self.gigachat_api.get_token(auth_token):
                gigachat_result = await self.gigachat_api.get_chat_completion(
                    "Ты - классификатор запросов. Отвечай только одним словом - названием категории.",
                    classification_prompt
                )
                response_text = gigachat_result.get('response', 'default').strip().lower()
                # Проверяем, что GigaChat вернул валидную категорию
                if response_text in workflow_routes:
                    category = response_text
                else:
                    logger.warning(f"GigaChat returned an unknown category '{response_text}', using default.")
            else:
                logger.error("Dispatcher: Failed to get GigaChat token.")

        else:
            # Простая классификация по ключевым словам
            query_lower = user_query.lower()
            for cat_name, cat_info in workflow_routes.items():
                if cat_name != 'default' and 'keywords' in cat_info:
                    if any(keyword.lower() in query_lower for keyword in cat_info['keywords']):
                        category = cat_name
                        break
        
        selected_route = workflow_routes.get(category, workflow_routes.get('default'))
        if not selected_route:
            raise Exception(f"Dispatcher: No route found for category '{category}' and no default route is set.")

        workflow_id = selected_route['workflow_id']
        logger.info(f"🎯 Диспетчер выбрал категорию: {category} -> Запуск workflow: {workflow_id}")

        if workflow_id not in saved_workflows:
            raise Exception(f"Dispatcher: Target workflow '{workflow_id}' not found.")

        # Запускаем выбранный workflow
        workflow_data = saved_workflows[workflow_id]
        workflow_request = WorkflowExecuteRequest(
            nodes=workflow_data["nodes"],
            connections=workflow_data["connections"]
        )
        
        # Передаем исходные данные в выбранный workflow
        sub_workflow_result = await execute_workflow_internal(
            workflow_request, 
            initial_input_data={
                **input_data,
                "dispatcher_info": {
                    "category": category,
                    "original_query": user_query,
                    "selected_workflow": workflow_id
                }
            }
        )

        # Возвращаем результат работы под-процесса
        return {
            **sub_workflow_result.result,
            "success": sub_workflow_result.success,
            "dispatcher_category": category,
            "executed_workflow_id": workflow_id,
            "output": {
                "text": f"Результат от workflow '{workflow_id}': {sub_workflow_result.result}",
                "json": sub_workflow_result.result
            }
        }
    
# Глобальный экземпляр исполнителей
executors = NodeExecutors()

# API эндпоинты
@app.get("/")
async def root():
    return {"message": "N8N Clone API Server", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/execute-node")
async def execute_node(
    node_type: str,
    node_data: Dict[str, Any],
    input_data: Dict[str, Any] = None
):
    """Выполнение отдельной ноды"""
    try:
        logger.info(f"Received request for node_type: {node_type}")
        logger.info(f"node_data: {json.dumps(node_data, indent=2)}")
        # Создаем объект ноды
        node = Node(
            id=node_data.get('id', 'temp'),
            type=node_type,
            position=node_data.get('position', {'x': 0, 'y': 0}),
            data=node_data.get('data', {})
        )
        logger.info(f"Created node: {node}")
        logger.info(f"Node data: {node.data}")
        logger.info(f"Config: {node.data.get('config', {})}")

        # Выбираем исполнитель
        executor_map = {
            'gigachat': executors.execute_gigachat,
            'email': executors.execute_email,
            'database': executors.execute_database,
            'webhook': executors.execute_webhook,
            'timer': executors.execute_timer,
            'join': executors.execute_join,
            'request_iterator': executors.execute_request_iterator,
            'if_else': executors.execute_if_else,  # Добавляем новый исполнитель
            'dispatcher': executors.execute_dispatcher # НОВОЕ
            
        }

        executor = executor_map.get(node_type)
        if not executor:
            raise HTTPException(status_code=400, detail=f"Unknown node type: {node_type}")

        # Выполняем ноду
        result = await executor(node, input_data or {})
        
        return ExecutionResult(
            success=True,
            result=result,
            logs=[{
                "message": f"Node {node_type} executed successfully",
                "timestamp": datetime.now().isoformat(),
                "level": "info"
            }]
        )

    except Exception as e:
        logger.error(f"❌ Ошибка выполнения ноды {node_type}: {str(e)}")
        return ExecutionResult(
            success=False,
            error=str(e),
            logs=[{
                "message": f"Error executing node {node_type}: {str(e)}",
                "timestamp": datetime.now().isoformat(),
                "level": "error"
            }]
        )

# --- НОВОЕ: CRUD Эндпоинты для Workflows ---

@app.get("/workflows")
async def list_workflows():
    """Получить список всех сохраненных workflows."""
    return {
        "workflows": [
            {"id": wf_id, "name": wf_data.get("name", wf_id)}
            for wf_id, wf_data in saved_workflows.items()
        ]
    }

@app.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Получить данные конкретного workflow по его ID."""
    if workflow_id not in saved_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return saved_workflows[workflow_id]

@app.post("/workflows", status_code=status.HTTP_201_CREATED)
async def create_workflow(request: WorkflowSaveRequest):
    """Создает новый workflow."""
    # Генерируем ID из имени, делая его безопасным для URL
    workflow_id = re.sub(r'[^a-z0-9_]+', '', request.name.lower().replace(" ", "_"))
    if not workflow_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow name, results in empty ID.")
    if workflow_id in saved_workflows:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Workflow with ID '{workflow_id}' already exists.")
    
    # Сохраняем workflow в памяти
    saved_workflows[workflow_id] = {
        "name": request.name,
        "nodes": [node.dict() for node in request.nodes],
        "connections": [conn.dict() for conn in request.connections],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    _save_workflows_to_disk() # Сохраняем на диск
    logger.info(f"✅ Workflow '{request.name}' (ID: {workflow_id}) создан.")
    return {"success": True, "workflow_id": workflow_id, "name": request.name}

@app.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, request: WorkflowUpdateRequest):
    """Обновляет существующий workflow."""
    if workflow_id not in saved_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    # Обновляем данные
    saved_workflows[workflow_id]["nodes"] = [node.dict() for node in request.nodes]
    saved_workflows[workflow_id]["connections"] = [conn.dict() for conn in request.connections]
    saved_workflows[workflow_id]["updated_at"] = datetime.now().isoformat()
    _save_workflows_to_disk() # Сохраняем на диск
    logger.info(f"🔄 Workflow '{workflow_id}' обновлен.")
    return {"success": True, "message": f"Workflow '{workflow_id}' updated successfully."}

@app.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str):
    """Удаляет workflow."""
    if workflow_id not in saved_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    del saved_workflows[workflow_id]
    _save_workflows_to_disk() # Сохраняем на диск
    logger.info(f"🗑️ Workflow '{workflow_id}' удален.")
# Добавьте этот эндпоинт после других эндпоинтов (примерно строка 600-650)
# @app.post("/save-workflow")
# async def save_workflow(request: WorkflowSaveRequest):
#     """Сохраняет workflow на сервере"""
#     try:
#         workflow_id = request.name.lower().replace(" ", "_")
        
#         # Сохраняем workflow в памяти
#         saved_workflows[workflow_id] = {
#             "name": request.name,
#             "nodes": request.nodes,
#             "connections": request.connections,
#             "updated_at": datetime.now().isoformat()
#         }
        
#         # Можно также сохранить на диск для персистентности
#         # with open(f"workflows/{workflow_id}.json", "w") as f:
#         #     json.dump(saved_workflows[workflow_id], f)
        
#         logger.info(f"✅ Workflow '{request.name}' сохранен успешно")
        
#         return {
#             "success": True,
#             "workflow_id": workflow_id,
#             "message": f"Workflow '{request.name}' saved successfully"
#         }
#     except Exception as e:
#         logger.error(f"❌ Ошибка сохранения workflow: {str(e)}")
#         return {
#             "success": False,
#             "error": str(e)
#         }

@app.post("/execute-workflow/{workflow_id}")
async def execute_saved_workflow(workflow_id: str, initial_input_data: Optional[Dict[str, Any]] = Body(None)):
    """Запускает сохраненный workflow по его ID."""
    if workflow_id not in saved_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    workflow_data = saved_workflows[workflow_id]
    
    workflow_request = WorkflowExecuteRequest(
        nodes=workflow_data["nodes"],
        connections=workflow_data["connections"]
    )

    return await execute_workflow_internal(workflow_request, initial_input_data=initial_input_data)


# Добавьте новые эндпоинты после существующих

@app.post("/webhooks/create")
async def create_webhook(request: WebhookCreateRequest):
    """Создает новый вебхук для workflow"""
    try:
        # Проверяем, существует ли workflow
        if request.workflow_id not in saved_workflows:
            raise HTTPException(status_code=404, detail=f"Workflow {request.workflow_id} not found")
        
        # Генерируем уникальный ID для вебхука
        webhook_id = str(uuid.uuid4())
        
        # Сохраняем информацию о вебхуке
        webhook_info = {
            "webhook_id": webhook_id,
            "workflow_id": request.workflow_id,
            "name": request.name,
            "description": request.description,
            "created_at": datetime.now().isoformat(),
            "auth_required": request.auth_required,
            "allowed_ips": request.allowed_ips or [],
            "call_count": 0,
            "last_called": None
        }
        
        webhook_triggers[webhook_id] = webhook_info
        
        # Инициализируем статистику
        webhook_stats[webhook_id] = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "last_error": None,
            "call_history": []  # Последние 10 вызовов
        }
        
        # Формируем полный URL
        base_url = "http://localhost:8000"  # В продакшене берите из конфига
        webhook_url = f"{base_url}/webhooks/{webhook_id}"
        
        logger.info(f"✅ Создан вебхук {webhook_id} для workflow {request.workflow_id}")
        
        return WebhookInfo(
            webhook_id=webhook_id,
            workflow_id=request.workflow_id,
            name=request.name,
            description=request.description,
            created_at=webhook_info["created_at"],
            url=webhook_url,
            auth_required=request.auth_required,
            allowed_ips=request.allowed_ips,
            call_count=0,
            last_called=None
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания вебхука: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhooks/{webhook_id}")
async def trigger_webhook(
    webhook_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None)
):
    logger.info(f"🔔 Webhook {webhook_id} triggered")
    logger.info(f"📦 Received data: {json.dumps(body, ensure_ascii=False)[:200]}...")
    """Обработчик вызова вебхука"""
    try:
        # Проверяем существование вебхука
        if webhook_id not in webhook_triggers:
            raise HTTPException(status_code=404, detail="Webhook not found")
        
        webhook_info = webhook_triggers[webhook_id]
        
        # Проверка IP-адреса если настроена
        client_ip = request.client.host
        if webhook_info.get("allowed_ips") and client_ip not in webhook_info["allowed_ips"]:
            logger.warning(f"⚠️ Попытка вызова вебхука {webhook_id} с неразрешенного IP: {client_ip}")
            raise HTTPException(status_code=403, detail="IP not allowed")
        
        # Проверка авторизации если требуется
        if webhook_info.get("auth_required") and not authorization:
            raise HTTPException(status_code=401, detail="Authorization required")
        
        # Обновляем статистику
        webhook_triggers[webhook_id]["call_count"] += 1
        webhook_triggers[webhook_id]["last_called"] = datetime.now().isoformat()
        webhook_stats[webhook_id]["total_calls"] += 1
        
        # Логируем вызов
        logger.info(f"🔔 Вебхук {webhook_id} вызван с данными: {json.dumps(body, ensure_ascii=False)[:200]}...")
        
        # Получаем workflow
        workflow_id = webhook_info["workflow_id"]
        if workflow_id not in saved_workflows:
            raise HTTPException(status_code=404, detail="Associated workflow not found")
        
        workflow_data = saved_workflows[workflow_id]
        
        # Находим ноду webhook_trigger в workflow
        webhook_trigger_node = None
        for node in workflow_data["nodes"]:
            if node.get("type") == "webhook_trigger":
                webhook_trigger_node = node
                break
        
        if not webhook_trigger_node:
            # Если нет специальной ноды webhook_trigger, начинаем с первой доступной
            logger.warning(f"⚠️ В workflow {workflow_id} нет ноды webhook_trigger")
        
        # Создаем запрос на выполнение workflow
        workflow_request = WorkflowExecuteRequest(
            nodes=workflow_data["nodes"],
            connections=workflow_data["connections"],
            startNodeId=webhook_trigger_node.get("id") if webhook_trigger_node else None
        )
        
        # Выполняем workflow с переданными данными
        result = await execute_workflow_internal(workflow_request, initial_input_data=body)
        
        # Обновляем статистику успешных вызовов
        webhook_stats[webhook_id]["successful_calls"] += 1
        
        # Сохраняем в историю (последние 10)
        call_record = {
            "timestamp": datetime.now().isoformat(),
            "success": True,
            "input_data": body,
            "result": result.result if result.success else None,
            "error": result.error if not result.success else None
        }
        
        webhook_stats[webhook_id]["call_history"].insert(0, call_record)
        webhook_stats[webhook_id]["call_history"] = webhook_stats[webhook_id]["call_history"][:10]
        
        if result.success:
            logger.info(f"✅ Вебхук {webhook_id} успешно выполнил workflow")
            return {
                "success": True,
                "webhook_id": webhook_id,
                "workflow_id": workflow_id,
                "result": result.result,
                "execution_time": datetime.now().isoformat()
            }
        else:
            logger.error(f"❌ Ошибка выполнения workflow для вебхука {webhook_id}: {result.error}")
            webhook_stats[webhook_id]["failed_calls"] += 1
            webhook_stats[webhook_id]["last_error"] = result.error
            raise HTTPException(status_code=500, detail=result.error)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука {webhook_id}: {str(e)}")
        webhook_stats[webhook_id]["failed_calls"] += 1
        webhook_stats[webhook_id]["last_error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/webhooks")
async def list_webhooks():
    """Получить список всех вебхуков"""
    webhooks = []
    for webhook_id, info in webhook_triggers.items():
        base_url = "http://localhost:8000"
        webhook_url = f"{base_url}/webhooks/{webhook_id}"
        
        webhooks.append(WebhookInfo(
            webhook_id=webhook_id,
            workflow_id=info["workflow_id"],
            name=info["name"],
            description=info.get("description"),
            created_at=info["created_at"],
            url=webhook_url,
            auth_required=info.get("auth_required", False),
            allowed_ips=info.get("allowed_ips"),
            call_count=info.get("call_count", 0),
            last_called=info.get("last_called")
        ))
    
    return {"webhooks": webhooks}

@app.get("/webhooks/{webhook_id}/info")
async def get_webhook_info(webhook_id: str):
    """Получить информацию о конкретном вебхуке"""
    if webhook_id not in webhook_triggers:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    info = webhook_triggers[webhook_id]
    stats = webhook_stats.get(webhook_id, {})
    
    base_url = "http://localhost:8000"
    webhook_url = f"{base_url}/webhooks/{webhook_id}"
    
    return {
        "webhook": WebhookInfo(
            webhook_id=webhook_id,
            workflow_id=info["workflow_id"],
            name=info["name"],
            description=info.get("description"),
            created_at=info["created_at"],
            url=webhook_url,
            auth_required=info.get("auth_required", False),
            allowed_ips=info.get("allowed_ips"),
            call_count=info.get("call_count", 0),
            last_called=info.get("last_called")
        ),
        "statistics": {
            "total_calls": stats.get("total_calls", 0),
            "successful_calls": stats.get("successful_calls", 0),
            "failed_calls": stats.get("failed_calls", 0),
            "last_error": stats.get("last_error"),
            "recent_calls": stats.get("call_history", [])[:5]
        }
    }

@app.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str):
    """Удалить вебхук"""
    if webhook_id not in webhook_triggers:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    del webhook_triggers[webhook_id]
    if webhook_id in webhook_stats:
        del webhook_stats[webhook_id]
    
    logger.info(f"🗑️ Вебхук {webhook_id} удален")
    
    return {"message": f"Webhook {webhook_id} deleted successfully"}

@app.put("/webhooks/{webhook_id}")
async def update_webhook(webhook_id: str, request: WebhookCreateRequest):
    """Обновить настройки вебхука"""
    if webhook_id not in webhook_triggers:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    # Обновляем информацию
    webhook_triggers[webhook_id].update({
        "name": request.name,
        "description": request.description,
        "auth_required": request.auth_required,
        "allowed_ips": request.allowed_ips or []
    })
    
    logger.info(f"🔄 Вебхук {webhook_id} обновлен")
    
    return {"message": "Webhook updated successfully"}

async def execute_workflow_internal(request: WorkflowExecuteRequest, initial_input_data: Optional[Dict[str, Any]] = None):
    """Внутренняя функция выполнения workflow (без HTTP обертки)"""
    logs = []
    # НОВОЕ: Очищаем счетчики goto при новом выполнении
    global goto_execution_counter
    goto_execution_counter.clear()

    try:
        logger.info(f"🚀 Запуск workflow с {len(request.nodes)} нодами")
        if initial_input_data:
            logger.info(f"💡 Workflow запущен с начальными данными: {json.dumps(initial_input_data, default=str, indent=2)[:300]}...")
        
        # Детальное логирование нод и соединений (из старой версии)
        for node in request.nodes:
            logger.info(f"📋 Нода {node.id} типа {node.type}: {node.data.get('label', 'Без метки')}")
        
        logger.info(f"🔗 Соединения: {len(request.connections)}")
        for conn in request.connections:
            logger.info(f"🔗 Соединение: {conn.source} -> {conn.target}")
        
        # Хранилище для накопления данных для join нод
        join_node_data = {}
        
        # Находим стартовую ноду
        start_node = None
        if request.startNodeId:
            start_node = next((n for n in request.nodes if n.id == request.startNodeId), None)
            logger.info(f"🎯 Используем указанную стартовую ноду: {request.startNodeId}")
        else:
            # Ищем ноду без входящих соединений
            node_ids_with_inputs = {conn.target for conn in request.connections}
            startable_types = ['gigachat', 'webhook', 'timer']
            
            start_candidates = [
                n for n in request.nodes 
                if n.type in startable_types and n.id not in node_ids_with_inputs
            ]
            
            if start_candidates:
                start_node = start_candidates[0]
                logger.info(f"🔍 Найдена стартовая нода без входящих соединений: {start_node.id}")
            else:
                # Если все ноды имеют входящие соединения, берем любую стартовую
                start_node = next((n for n in request.nodes if n.type in startable_types), None)
                logger.info(f"⚠️ Все ноды имеют входящие соединения, берем первую доступную: {start_node.id if start_node else 'None'}")

        if not start_node:
            raise Exception("No startable node found")

        # Если это нода Timer, обновляем информацию о workflow в таймере
        if start_node.type == "timer":
            timer_id = f"timer_{start_node.id}"
            if timer_id in active_timers:
                active_timers[timer_id]["workflow"] = {
                    "nodes": request.nodes,
                    "connections": request.connections,
                    "startNodeId": start_node.id
                }

        # Выполняем workflow
        results = {}
        
        
        async def execute_node_recursive(node_id: str, input_data: Dict[str, Any] = None, source_node_id: str = None, is_first_node: bool = False):
            node = next((n for n in request.nodes if n.id == node_id), None)
            if not node:
                return None

            # Если это первая нода И есть initial_input_data, используем их
            if is_first_node and initial_input_data:
                input_data = initial_input_data
                logger.info(f"💡 Стартовая нода {node_id} получила начальные данные от вебхука")
            
            # Специальная обработка для webhook ноды
            if node.type == 'webhook_trigger' and is_first_node:
                logger.info(f"🔔 Webhook нода {node_id} активирована")
                # Webhook нода просто передает полученные данные дальше
                result = {
                    "success": True,
                    "output": input_data,
                    "message": "Webhook data received"
                }
                results[node_id] = result
                
                # Передаем данные следующим нодам
                next_connections = [c for c in request.connections if c.source == node_id]
                for connection in next_connections:
                    await execute_node_recursive(connection.target, result, node_id, False)
                
                return result
            
            # Проверяем, является ли это join нодой с множественными входами
            incoming_connections = [c for c in request.connections if c.target == node_id]
            
            if node.type == 'join' and len(incoming_connections) > 1:
                # Это join нода - накапливаем данные
                if node_id not in join_node_data:
                    join_node_data[node_id] = {
                        'expected_sources': set(c.source for c in incoming_connections),
                        'received_data': {}
                    }
                
                # Сохраняем данные от текущего источника
                if source_node_id:
                    join_node_data[node_id]['received_data'][source_node_id] = input_data
                    logger.info(f"🔀 Join нода {node_id} получила данные от {source_node_id}")
                    logger.info(f"📊 Ожидается: {join_node_data[node_id]['expected_sources']}")
                    logger.info(f"📊 Получено от: {set(join_node_data[node_id]['received_data'].keys())}")
                
                # Проверяем, получили ли мы данные от всех источников
                received_sources = set(join_node_data[node_id]['received_data'].keys())
                expected_sources = join_node_data[node_id]['expected_sources']
                
                if node.data.get('config', {}).get('waitForAll', True):
                    if received_sources != expected_sources:
                        # Еще не все данные получены
                        logger.info(f"⏳ Join нода {node_id} ждет данные от {expected_sources - received_sources}")
                        return None
                
                # Все данные получены или не ждем всех - выполняем join
                input_data = {'inputs': join_node_data[node_id]['received_data']}
                
                # Очищаем временные данные
                del join_node_data[node_id]
            
            # Логируем выполнение
            logs.append({
                "message": f"Executing {node.data.get('label', node.type)}...",
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "nodeId": node_id
            })

            # Выполняем ноду
            executor_map = {
                'gigachat': executors.execute_gigachat,
                'email': executors.execute_email,
                'database': executors.execute_database,
                'webhook': executors.execute_webhook,
                'timer': executors.execute_timer,
                'join': executors.execute_join,
                'request_iterator': executors.execute_request_iterator,
                'if_else': executors.execute_if_else,
                'dispatcher': executors.execute_dispatcher # НОВОЕ
            }

            executor = executor_map.get(node.type)
            if executor:
                result = await executor(node, input_data or {})
                results[node_id] = result
                
                logs.append({
                    "message": f"{node.data.get('label', node.type)} completed successfully",
                    "timestamp": datetime.now().isoformat(),
                    "level": "success",
                    "nodeId": node_id
                })

                # Находим следующие ноды
                next_connections = [c for c in request.connections if c.source == node_id]

                # НОВОЕ: Специальная обработка для If/Else ноды
                if node.type == 'if_else' and 'branch' in result:
                    branch = result['branch']  # 'true' или 'false'
                    
                    # ДОБАВЬТЕ ЗДЕСЬ (после строки 1097):
                    logger.info(f"🔍 If/Else нода {node_id} вернула branch: {branch}")
                    logger.info(f"🔍 Найдено соединений: {len(next_connections)}")
                    for conn in next_connections:
                        logger.info(f"  - {conn.id}: label='{conn.data.get('label', 'none')}'")

                    # Фильтруем соединения по метке
                    filtered_connections = []
                    goto_connections = []
                    
                    for conn in next_connections:
                        conn_label = conn.data.get('label', '').lower() if conn.data else ''
                        
                        # Проверяем goto соединения
                        if conn_label == f"{branch}:goto":
                            goto_connections.append(conn)
                        elif conn_label == branch:
                            filtered_connections.append(conn)
                    
                    # Сначала проверяем goto соединения
                    if goto_connections:
                        for goto_conn in goto_connections:
                            # Проверяем защиту от циклов
                            goto_key = f"{node_id}_to_{goto_conn.target}"
                            if goto_key not in goto_execution_counter:
                                goto_execution_counter[goto_key] = 0
                            
                            goto_execution_counter[goto_key] += 1
                            max_iterations = node.data.get('config', {}).get('maxGotoIterations', 10)
                            
                            if goto_execution_counter[goto_key] > max_iterations:
                                logger.error(f"🔄 Превышен лимит goto переходов ({max_iterations}) для {goto_key}")
                                return {
                                    'success': False,
                                    'error': f'Exceeded max goto iterations ({max_iterations})',
                                    'branch': branch,
                                    'goto_iterations': goto_execution_counter[goto_key]
                                }
                            
                            logger.info(f"🔄 Активирован goto переход к {goto_conn.target} (итерация {goto_execution_counter[goto_key]})")
                            await execute_node_recursive(goto_conn.target, result, node_id, False)
                        
                        # После goto не выполняем обычные соединения
                        return result
                    
                    # Если нет goto, выполняем обычные соединения
                    for connection in filtered_connections:
                        await execute_node_recursive(connection.target, result, node_id)
                else:
                    # Для остальных типов нод - обычное выполнение
                    for connection in next_connections:
                        await execute_node_recursive(connection.target, result, node_id)

                return result
            else:
                raise Exception(f"Unknown node type: {node.type}")

        # Запускаем выполнение
        await execute_node_recursive(start_node.id, is_first_node=True)

        return ExecutionResult(
            success=True,
            result=results,
            logs=logs
        )

    except Exception as e:
        logger.error(f"❌ Ошибка выполнения workflow: {str(e)}")
        return ExecutionResult(
            success=False,
            error=str(e),
            logs=logs + [{
                "message": f"Workflow execution failed: {str(e)}",
                "timestamp": datetime.now().isoformat(),
                "level": "error"
            }]
        )


@app.post("/execute-workflow")
async def execute_workflow(request: WorkflowExecuteRequest):
    return await execute_workflow_internal(request)

# Добавьте новый эндпоинт для получения статусов нод
@app.post("/node-status")
async def get_node_status(node_ids: List[str]):
    """Получение статуса выполнения нод"""
    results = {}
    
    for node_id in node_ids:
        if node_id in node_execution_results:
            # Получаем результат и проверяем, не устарел ли он (не старше 5 минут)
            result_data = node_execution_results[node_id]
            timestamp = datetime.fromisoformat(result_data["timestamp"])
            
            if datetime.now() - timestamp < timedelta(minutes=5):
                results[node_id] = result_data
                
                # Очищаем результат после отправки, чтобы не отправлять его повторно
                # при следующем запросе (это предотвратит повторное подсвечивание ноды)
                del node_execution_results[node_id]
    
    return {"results": results}

# Новые эндпоинты для управления таймерами

@app.get("/timers")
async def get_timers():
    """Получение списка всех активных таймеров"""
    timers = []
    for timer_id, timer in active_timers.items():
        timers.append({
            "id": timer_id,
            "node_id": timer["node_id"],
            "interval": timer["interval"],
            "next_execution": timer["next_execution"].isoformat(),
            "status": timer["status"]
        })
    return {"timers": timers}

@app.get("/timers/{timer_id}")
async def get_timer(timer_id: str):
    """Получение информации о конкретном таймере"""
    if timer_id not in active_timers:
        raise HTTPException(status_code=404, detail=f"Timer {timer_id} not found")
    
    timer = active_timers[timer_id]
    return {
        "id": timer_id,
        "node_id": timer["node_id"],
        "interval": timer["interval"],
        "next_execution": timer["next_execution"].isoformat(),
        "status": timer["status"]
    }

@app.post("/timers/{timer_id}/pause")
async def pause_timer(timer_id: str):
    """Приостановка таймера"""
    if timer_id not in active_timers:
        raise HTTPException(status_code=404, detail=f"Timer {timer_id} not found")
    
    # Отменяем задачу таймера
    if active_timers[timer_id]["task"] is not None:
        active_timers[timer_id]["task"].cancel()
    
    # Обновляем статус
    active_timers[timer_id]["status"] = "paused"
    
    logger.info(f"⏸️ Таймер {timer_id} приостановлен")
    
    return {
        "id": timer_id,
        "status": "paused",
        "message": "Timer paused successfully"
    }

@app.post("/timers/{timer_id}/resume")
async def resume_timer(timer_id: str):
    """Возобновление таймера"""
    if timer_id not in active_timers:
        raise HTTPException(status_code=404, detail=f"Timer {timer_id} not found")
    
    timer = active_timers[timer_id]
    
    # Создаем новую задачу таймера
    task = asyncio.create_task(timer_task(
        timer_id, 
        timer["node_id"], 
        timer["interval"], 
        timer["workflow"]
    ))
    
    # Обновляем информацию о таймере
    timer["task"] = task
    timer["status"] = "active"
    timer["next_execution"] = datetime.now() + timedelta(minutes=timer["interval"])
    
    logger.info(f"▶️ Таймер {timer_id} возобновлен")
    
    return {
        "id": timer_id,
        "status": "active",
        "next_execution": timer["next_execution"].isoformat(),
        "message": "Timer resumed successfully"
    }

@app.delete("/timers/{timer_id}")
async def delete_timer(timer_id: str):
    """Удаление таймера"""
    if timer_id not in active_timers:
        raise HTTPException(status_code=404, detail=f"Timer {timer_id} not found")
    
    # Отменяем задачу таймера
    if active_timers[timer_id]["task"] is not None:
        active_timers[timer_id]["task"].cancel()
    
    # Удаляем таймер из хранилища
    del active_timers[timer_id]
    
    logger.info(f"🗑️ Таймер {timer_id} удален")
    
    return {
        "message": f"Timer {timer_id} deleted successfully"
    }

@app.post("/timers/{timer_id}/update")
async def update_timer_endpoint(timer_id: str, interval: int):
    """Обновление интервала таймера"""
    if timer_id not in active_timers:
        raise HTTPException(status_code=404, detail=f"Timer {timer_id} not found")
    
    result = await update_timer(timer_id, interval)
    
    logger.info(f"🔄 Таймер {timer_id} обновлен с новым интервалом {interval} минут")
    
    return result

@app.post("/timers/{timer_id}/execute-now")
async def execute_timer_now(timer_id: str):
    """Немедленное выполнение таймера"""
    if timer_id not in active_timers:
        raise HTTPException(status_code=404, detail=f"Timer {timer_id} not found")
    
    timer = active_timers[timer_id]
    
    # Получаем информацию о workflow
    workflow_info = timer["workflow"]
    
    try:
        # Создаем запрос на выполнение workflow
        workflow_request = WorkflowExecuteRequest(
            nodes=workflow_info["nodes"],
            connections=workflow_info["connections"],
            startNodeId=timer["node_id"]
        )
        
        # Выполняем workflow
        result = await execute_workflow_internal(workflow_request)
        
        logger.info(f"✅ Таймер {timer_id} выполнен немедленно")
        
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка при немедленном выполнении таймера {timer_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Обработчик запуска сервера
@app.on_event("startup")
async def startup_event():
    """Выполняется при запуске сервера"""
    _load_workflows_from_disk() # НОВОЕ: Загружаем workflows
    logger.info("🚀 Сервер запущен")

# Обработчик остановки сервера
@app.on_event("shutdown")
async def shutdown_event():
    """Выполняется при остановке сервера"""
    logger.info("🛑 Остановка всех таймеров...")
    
    # Отменяем все активные таймеры
    for timer_id, timer in active_timers.items():
        if timer["task"] is not None:
            timer["task"].cancel()
    
    logger.info("👋 Сервер остановлен")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Запуск FastAPI сервера...")
    print("📡 API будет доступен на: http://localhost:8000")
    print("📚 Документация: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
