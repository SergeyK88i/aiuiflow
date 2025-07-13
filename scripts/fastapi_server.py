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
import time

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

class SetupTimerRequest(BaseModel):
    node: Node
    workflow_id: str
# GigaChat API класс
class GigaChatAPI:
    def __init__(self):
        self.access_token = None
        self.conversation_history = []
        
    async def get_token(self, auth_token: str, scope: str = 'GIGACHAT_API_PERS') -> bool:
        """Получение токена доступа"""
        rq_uid = str(uuid.uuid4())
        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

         # --- НОВЫЙ БЛОК ДЛЯ НАДЕЖНОСТИ ---
        # На случай, если пользователь случайно скопировал "Basic " вместе с токеном
        if auth_token and auth_token.lower().startswith('basic '):
            logger.warning("⚠️ Обнаружен префикс 'Basic ' в токене. Удаляю его автоматически.")
            auth_token = auth_token[6:]
        # --- КОНЕЦ НОВОГО БЛОКА ---

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': rq_uid,
            'Authorization': f'Basic {auth_token}'
        }
        payload = {'scope': scope}

        try:
            # --- НОВОЕ ЛОГИРОВАНИЕ ДЛЯ ОТЛАДКИ ---
            logger.info(f"🔑 Попытка получить токен. URL: {url}")
            logger.info(f"📋 Отправляемые заголовки: {headers}")
            # --- КОНЕЦ НОВОГО ЛОГИРОВАНИЯ ---
            # В реальном приложении используйте aiohttp для асинхронных запросов
            response = requests.post(url, headers=headers, data=payload, verify=False)
            if response.status_code == 200:
                self.access_token = response.json()['access_token']
                logger.info("✅ GigaChat токен получен успешно")
                return True
            else:
                logger.error(f"❌ Ошибка получения токена: {response.status_code}")
                # --- САМОЕ ВАЖНОЕ: ЛОГИРУЕМ ТЕЛО ОТВЕТА ---
                try:
                    error_details = response.json()
                    logger.error(f"🔍 Детали ошибки от GigaChat: {error_details}")
                except json.JSONDecodeError:
                    logger.error(f"🔍 Ответ от GigaChat (не JSON): {response.text}")
                # --- КОНЕЦ ВАЖНОГО БЛОКА ---
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
            "model": "GigaChat-Pro",
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
    """Создает и запускает новый таймер (логика почти не изменилась)"""
    if timer_id in active_timers and active_timers[timer_id]["task"] is not None:
        active_timers[timer_id]["task"].cancel()
        logger.info(f"🛑 Отменен существующий таймер {timer_id} для пересоздания")

    task = asyncio.create_task(timer_task(timer_id, node_id, interval, workflow_info))

    active_timers[timer_id] = {
        "node_id": node_id,
        "interval": interval,
        "next_execution": datetime.now() + timedelta(minutes=interval),
        "task": task,
        "status": "active",
        "workflow": workflow_info  # Сохраняем workflow_id и start_node_id
    }
    logger.info(f"🕒 Создан/пересоздан таймер {timer_id} для workflow '{workflow_info.get('workflow_id')}'")
    return active_timers[timer_id]

async def update_timer(timer_id: str, interval: int, workflow_info: Dict[str, Any]):
    """
    Обновляет существующий таймер. Теперь принимает workflow_info.
    """
    if timer_id not in active_timers:
        raise Exception(f"Timer {timer_id} not found")

    timer_info = active_timers[timer_id]
    
    # Просто пересоздаем таймер с новыми данными
    await create_timer(
        timer_id,
        timer_info["node_id"],
        interval,
        workflow_info # Используем новую информацию
    )
    logger.info(f"🔄 Обновлен таймер {timer_id} с новым интервалом {interval} минут")
    return active_timers[timer_id]

async def timer_task(timer_id: str, node_id: str, interval: int, workflow_info: Dict[str, Any]):
    """
    Задача таймера, которая выполняется асинхронно.
    Теперь она работает с workflow_id, а не с его копией.
    """
    try:
        while True:
            logger.info(f"⏰ Запущена задача таймера {timer_id} для ноды {node_id} с интервалом {interval} минут")
            logger.info(f"⏰ Таймер {timer_id} ожидает {interval} минут до следующего запуска")
            await asyncio.sleep(interval * 60) # Переводим минуты в секунды

            active_timers[timer_id]["next_execution"] = datetime.now() + timedelta(minutes=interval)
            # 🔴 ДОБАВИТЬ: Отмечаем начало выполнения workflow
            active_timers[timer_id]["is_executing_workflow"] = True

            try:
                # 1. Получаем ID workflow из информации, сохраненной при настройке
                workflow_id = workflow_info.get("workflow_id")
                if not workflow_id or workflow_id not in saved_workflows:
                    logger.error(f"❌ Workflow с ID '{workflow_id}' не найден. Таймер {timer_id} не может запустить выполнение.")
                    continue # Пропускаем этот цикл

                logger.info(f"🚀 Таймер {timer_id} запускает workflow '{workflow_id}'")

                # 2. Берем самую свежую версию workflow из глобального хранилища
                workflow_data = saved_workflows[workflow_id]

                # 3. Создаем запрос на выполнение
                workflow_request = WorkflowExecuteRequest(
                    nodes=workflow_data["nodes"],
                    connections=workflow_data["connections"],
                    startNodeId=node_id
                )

                # 4. Выполняем workflow
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



# Замени свою старую функцию replace_templates на эту
def replace_templates(text: str, data: Dict[str, Any], label_to_id_map: Dict[str, str]) -> str:
    """Универсальная замена шаблонов вида {{Node Label.path.to.value}} или {{node-id.path.to.value}}"""
    
    # ИМПОРТИРУЕМ МОДУЛЬ ДЛЯ РЕГУЛЯРНЫХ ВЫРАЖЕНИЙ
    import re

    def get_nested_value(obj: Dict[str, Any], path: str) -> Any:
        """Получает значение по пути типа 'node-id.output.text' или 'node-id.json.result[0].text'"""
        
        # Новый, более умный разборщик пути.
        # Он разделяет по точкам и по квадратным скобкам, отбрасывая пустые элементы.
        # Например, 'a.b[0]' превратится в ['a', 'b', '0']
        keys = [key for key in re.split(r'[.\[\]]', path) if key]
        
        current = obj
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            # Теперь он правильно обработает индекс массива
            elif isinstance(current, list) and key.isdigit():
                index = int(key)
                if 0 <= index < len(current):
                    current = current[index]
                else:
                    # Индекс за пределами массива
                    return None
            else:
                # Ключ или индекс не найден
                return None
        return current

    # Паттерн для поиска {{ ... }} с пробелами
    pattern = r"\{\{\s*(.+?)\s*\}\}"

    def replacer(match):
        path = match.group(1).strip()

        # Убираем 'input.', если он есть (для обратной совместимости)
        if path.startswith('input.'):
            path = path[6:]

        # Разделяем путь на первую часть (лейбл или ID) и остальное
        parts = path.split('.', 1)
        node_identifier = parts[0]
        remaining_path = parts[1] if len(parts) > 1 else ''

        # Определяем ID ноды
        node_id = None
        # 1. Сначала ищем по лейблу
        if node_identifier in label_to_id_map:
            node_id = label_to_id_map[node_identifier]
        # 2. Если не нашли, ищем по ID (обратная совместимость)
        elif node_identifier in data:
            node_id = node_identifier
        else:
            logger.warning(f"⚠️ Шаблон: нода с лейблом или ID '{node_identifier}' не найдена.")
            return f"{{{{ERROR: Node '{node_identifier}' not found}}}}"

        # Собираем полный путь для поиска: 'node-id.remaining.path'
        full_path = f"{node_id}.{remaining_path}" if remaining_path else node_id

        value = get_nested_value(data, full_path)

        # УЛУЧШЕНИЕ: Более надежная обработка разных типов данных
        if value is None:
            logger.warning(f"⚠️ Шаблон: путь '{path}' не найден в данных ноды '{node_identifier}'. Замена на пустую строку.")
            return ""
        
        # Если результат - словарь или список, возвращаем его как JSON
        if isinstance(value, (dict, list)):
            final_str = json.dumps(value, ensure_ascii=False)
        else:
            # Для всего остального (строки, числа, булевы) мы делаем трюк:
            # 1. Превращаем значение в строку (на случай если это число).
            # 2. Кодируем эту строку в JSON. Это автоматически экранирует все спецсимволы: \n, ", \ и т.д.
            #    'a\nb' станет '"a\\nb"'
            # 3. Убираем крайние кавычки, которые добавляет json.dumps.
            #    '"a\\nb"' станет 'a\\nb'
            # Это гарантирует, что вставленный текст будет безопасным для JSON.
            final_str = json.dumps(str(value), ensure_ascii=False)
            if final_str.startswith('"') and final_str.endswith('"'):
                final_str = final_str[1:-1]

        logger.info(f"🔄 Замена шаблона: {{{{{match.group(1)}}}}} -> {final_str[:200]}...")
        return final_str

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

        # ДОБАВИТЬ эти строки:
        self.dispatcher_sessions = {}  # Хранилище сессий для всех диспетчеров
        logger.info("🏗️ NodeExecutors инициализирован с поддержкой сессий диспетчеров")
    
    
    async def execute_request_iterator(self, node: Node, label_to_id_map: Dict[str, str],input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнение Request Iterator ноды в соответствии с "Принципом Единого Результата".
        Использует явный шаблон для получения входных данных.
        """
        start_time = datetime.now()
        logger.info(f"Executing Request Iterator node: {node.id}")
        config = node.data.get('config', {})

        # --- 1. Получение входных данных через явный шаблон ---
        # В UI для этой ноды нужно будет добавить поле "JSON Input"
        json_input_template = config.get('jsonInput', '')
        if not json_input_template:
            raise Exception("Request Iterator: 'jsonInput' template is not configured in the node settings.")

        logger.info(f"📄 Input template for Request Iterator: {json_input_template}")
        requests_to_make_json_str = replace_templates(json_input_template, input_data,label_to_id_map)

        # Проверка, что шаблон сработал и вернул непустую строку
        if not requests_to_make_json_str or requests_to_make_json_str == json_input_template:
            logger.warning(f"Template '{json_input_template}' could not be resolved or resulted in an empty string. Assuming empty list of requests.")
            requests_to_make_json_str = "[]"

        # --- 2. Парсинг JSON (остается как было, но с более чистым входом) ---
        try:
            requests_list = json.loads(requests_to_make_json_str)
            if not isinstance(requests_list, list):
                if isinstance(requests_list, dict):
                    requests_list = [requests_list]
                else:
                    raise ValueError("Parsed JSON is not a list or a single request object.")
        except (json.JSONDecodeError, ValueError) as e:
            raise Exception(f"Request Iterator: Invalid JSON input after template replacement. Error: {str(e)}")

        if not requests_list:
            logger.info("Request Iterator: No requests to process from input.")
            # Даже если запросов нет, возвращаем стандартный результат
            node_result = {
                "text": "[]",
                "json": [],
                "meta": { "executed_requests_count": 0, "successful_requests_count": 0, "failed_requests_count": 0 },
                "inputs": { "jsonInput_template": json_input_template }
            }
            return node_result

        # --- 3. Основная логика выполнения запросов (остается почти без изменений) ---
        base_url = config.get('baseUrl', '').rstrip('/')
        execution_mode = config.get('executionMode', 'sequential')
        common_headers_str = config.get('commonHeaders', '{}')
        try:
            parsed_common_headers = json.loads(common_headers_str) if common_headers_str else {}
        except json.JSONDecodeError:
            parsed_common_headers = {}

        all_responses = []
        tasks = []
        async with aiohttp.ClientSession() as session:
            # --- НАЧАЛО ВСТАВЛЕННОГО БЛОКА ---
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
                    final_url = endpoint
                else:
                    final_url = f"{base_url}{endpoint}"

                method = req_info.get('method', 'GET').upper()
                get_params = req_info.get('params') if method == 'GET' else None
                json_body = req_info.get('body') if method in ['POST', 'PUT', 'PATCH'] else None
                specific_headers = req_info.get('headers', {})
                final_headers = {**parsed_common_headers, **specific_headers}

                task = _make_single_http_request(
                    session,
                    method,
                    final_url,
                    params=get_params,
                    json_body=json_body,
                    headers=final_headers
                )
                tasks.append(task)
            # --- КОНЕЦ ВСТАВЛЕННОГО БЛОКА ---

            if execution_mode == 'parallel' and tasks:
                all_responses = await asyncio.gather(*tasks, return_exceptions=True)
            elif tasks:
                for task_coro in tasks:
                    all_responses.append(await task_coro)

        final_responses_list = [r for r in all_responses if not isinstance(r, Exception)]
        logger.info(f"Request Iterator: Processed {len(final_responses_list)} requests.")

        # --- 4. Формирование стандартного объекта результата ---
        execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        successful_count = sum(1 for r in final_responses_list if r.get('success'))
        failed_count = len(final_responses_list) - successful_count

        node_result = {
            "text": json.dumps(final_responses_list, ensure_ascii=False, indent=2),
            "json": final_responses_list,
            "meta": {
                "node_type": node.type,
                "timestamp": datetime.now().isoformat(),
                "execution_time_ms": execution_time_ms,
                "executed_requests_count": len(final_responses_list),
                "successful_requests_count": successful_count,
                "failed_requests_count": failed_count,
            },
            "inputs": {
                "baseUrl": base_url,
                "executionMode": execution_mode,
                "jsonInput_template": json_input_template,
            }
        }

        # --- 5. Финальный return по "Золотому Правилу" ---
        return node_result

    async def execute_gigachat(self, node: Node, label_to_id_map: Dict[str, str],input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение GigaChat ноды"""
        start_time = datetime.now()
        logger.info(f"Executing GigaChat node: {node.id}")
        config = node.data.get('config', {})
        auth_token = config.get('authToken')
        # system_message_template = config.get('systemMessage', 'Ты полезный ассистент')
        # user_message_template = config.get('userMessage', '')
        clear_history = config.get('clearHistory', False)

        # 1. Всегда инициализируем переменные из шаблонов в конфиге.
        #    Теперь они гарантированно существуют.
        system_message = config.get('systemMessage', 'Ты полезный ассистент')
        user_message = config.get('userMessage', '')

        # Сохраняем оригинальные значения для логирования
        original_system_message = system_message
        original_user_message = user_message
        # ДОБАВЛЯЕМ ЛОГИРОВАНИЕ ВХОДНЫХ ДАННЫХ
        # УНИВЕРСАЛЬНАЯ ЗАМЕНА ШАБЛОНОВ
        if input_data:
            logger.info(f"📥 Входные данные от предыдущей ноды: {json.dumps(input_data, ensure_ascii=False, indent=2)[:500]}...")
            
            user_message = replace_templates(original_user_message, input_data,label_to_id_map)
            # Также заменяем шаблоны в system_message если есть
            system_message = replace_templates(original_system_message, input_data,label_to_id_map)
            
            if original_user_message != user_message:
                logger.info(f"📝 Сообщение до замены: {original_user_message}")
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

        # --- НОВЫЙ БЛОК ОЧИСТКИ ---
        import re
        raw_response_text = result.get('response', '')
        cleaned_response_text = raw_response_text
        match = re.search(r'```(json)?\s*([\s\S]*?)\s*```', raw_response_text)
        if match:
            logger.info("🧹 GigaChat вернул Markdown, извлекаем чистый JSON.")
            cleaned_response_text = match.group(2)
        # --- КОНЕЦ БЛОКА ОЧИСТКИ ---
        # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ---
        # Пытаемся распарсить ответ как JSON, но не ломаемся, если это не он.
        parsed_json = None
        try:
            # Попытка парсинга
            parsed_json = json.loads(cleaned_response_text)
            logger.info("✅ Ответ от GigaChat успешно распознан как JSON.")
        except json.JSONDecodeError:
            # Если это не JSON, ничего страшного. Просто логируем это.
            logger.info("ℹ️ Ответ от GigaChat не является валидным JSON. Будет обработан как обычный текст.")
            pass # parsed_json останется None

        # Формируем выходные данные для следующих нод
        # Формируем собственный, уникальный результат этой ноды
        # --- 4. Формирование стандартного объекта результата ---
        execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        node_result = {
            "text": cleaned_response_text,
            "json": parsed_json,
            "meta": {
                "node_type": node.type,
                "timestamp": datetime.now().isoformat(),
                "execution_time_ms": execution_time_ms,
                "conversation_length": result.get("conversation_length", 0),
                "length": len(raw_response_text),
                "words": len(raw_response_text.split()),
                "id_node": node.id
            },
            "inputs": {
                "system_message_template": original_system_message,
                "user_message_template": original_user_message,
                "final_system_message": system_message,
                "final_user_message": user_message,
                "clear_history": clear_history
            }
        }
        return node_result


    async def execute_email(self, node: Node, label_to_id_map: Dict[str, str],input_data: Dict[str, Any]) -> Dict[str, Any]:
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

        email_result = {
            "sent": True,
            "to": to,
            "subject": subject,
            "messageId": f"msg_{int(datetime.now().timestamp())}"
        }
        return email_result

    async def execute_database(self, node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any]) -> Dict[str, Any]:
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

        db_result = {
            "success": True,
            "rows": [
                {
                    "id": 1,
                    "text": "Sample Data",
                    "created_at": datetime.now().isoformat()
                }
            ],
            "rowCount": 1,
            "query": query,
            "connection": connection
        }

        return db_result

    async def execute_webhook(self, node: Node, label_to_id_map: Dict[str, str],input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнение Webhook ноды с новой структурой вывода и явным шаблоном для тела запроса.
        """
        start_time = datetime.now()
        logger.info(f"Executing Webhook node: {node.id}")
        config = node.data.get('config', {})
        node_result = {}
        
        try:
            # --- 1. Получение и обработка входных параметров ---
            url_template = config.get('url', '')
            method = config.get('method', 'POST').upper()
            headers_str = config.get('headers', 'Content-Type: application/json')
            # НОВОЕ: Получаем шаблон тела запроса
            body_template = config.get('bodyTemplate', '{}') 

            url = replace_templates(url_template, input_data,label_to_id_map)
            if not url:
                raise Exception("Webhook: URL is required in the node settings.")

            headers = {}
            if headers_str:
                for line in headers_str.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip()] = value.strip()
            
            # --- НОВАЯ ЛОГИКА: Формирование payload из шаблона ---
            payload = None
            if method in ['POST', 'PUT', 'PATCH']:
                # Заполняем шаблон данными от предыдущих нод
                resolved_body_str = replace_templates(body_template, input_data,label_to_id_map)
                try:
                    # Превращаем строку в Python объект (dict/list)
                    payload = json.loads(resolved_body_str)
                except json.JSONDecodeError:
                    raise Exception(f"Invalid JSON in Request Body after template replacement. Result: {resolved_body_str}")

            logger.info(f"🌐 Sending {method} to {url}")
            if payload:
                logger.info(f"📦 Payload: {json.dumps(payload, ensure_ascii=False, default=str)[:200]}...")

            # --- 2. Выполнение HTTP запроса ---
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.request(method, url, json=payload, ssl=False) as response:
                    response_text = await response.text()
                    response_json = None
                    try:
                        response_json = json.loads(response_text)
                    except json.JSONDecodeError:
                        pass
                    
                    logger.info(f"✅ Webhook response: {response.status}")

                    # --- 3. Формирование стандартного объекта результата ---
                    execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    node_result = {
                        "text": response_text,
                        "json": response_json,
                        "meta": {
                            "node_type": node.type, "timestamp": datetime.now().isoformat(),
                            "execution_time_ms": execution_time_ms, "success": 200 <= response.status < 300,
                            "status_code": response.status, "response_headers": dict(response.headers),
                        },
                        "inputs": {
                            "url_template": url_template, "final_url": url, "method": method,
                            "headers": headers, "body_template": body_template, "final_payload": payload
                        }
                    }

        except aiohttp.ClientError as e:
            logger.error(f"❌ Connection Error in Webhook node {node.id}: {str(e)}")
            node_result = self._create_error_result(node, config, f"Connection Error: {str(e)}", "connection_error", input_data)
        except Exception as e:
            logger.error(f"❌ Unexpected Error in Webhook node {node.id}: {str(e)}")
            node_result = self._create_error_result(node, config, str(e), "unexpected_error", input_data)

        # --- 4. Финальный return по "Золотому Правилу" ---
        return node_result

    # Вспомогательная функция для создания стандартизированных ошибок
    def _create_error_result(self, node: Node, config: Dict, error_message: str, error_type: str, input_data: Dict) -> Dict:
        return {
            "text": error_message,
            "json": None,
            "meta": {
                "node_type": node.type, "timestamp": datetime.now().isoformat(),
                "success": False, "error_message": error_message, "error_type": error_type
            },
            "inputs": {
                "url_template": config.get('url', ''), "method": config.get('method', 'POST'),
                "headers": config.get('headers', ''), "body_template": config.get('bodyTemplate', ''),
                "input_data_snapshot": input_data # Снимок входных данных на момент ошибки
            }
        }


    async def execute_timer(self, node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнение Timer ноды как ПЕРВОГО ШАГА в workflow.
        Ее единственная задача - сгенерировать стартовые данные.
        Она больше не управляет расписанием.
        """
        try:
            logger.info(f"⏰ Нода 'Таймер' {node.id} запускается как часть workflow.")
            current_time = datetime.now()
            config = node.data.get('config', {})
            interval = int(config.get('interval', 5))
            timezone = config.get('timezone', 'UTC')

            # Просто создаем выходные данные и передаем их дальше
            return {
                "success": True,
                "message": f"Workflow triggered by schedule at {current_time.isoformat()}",
                "output": {
                    "text": f"Workflow triggered by schedule at {current_time.isoformat()}",
                    "timestamp": current_time.isoformat(),
                    "interval": interval,
                    "timezone": timezone,
                    "node_id": node.id
                }
            }
        except Exception as e:
            logger.error(f"❌ Ошибка в ноде 'Таймер' {node.id}: {str(e)}")
            return {
                "success": False,
                "error": f"Timer node execution failed: {str(e)}",
                "output": {"text": f"Timer node execution failed: {str(e)}"}
            }

    # Вспомогательная функция, которую можно разместить внутри класса NodeExecutors или перед ним
    def _extract_text_from_data(self, data: Any) -> str:
        """Рекурсивно ищет наиболее подходящий текст в данных."""
        if isinstance(data, str):
            return data
        if not isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False, indent=2)

        # Приоритетный поиск
        if 'text' in data and isinstance(data['text'], str):
            return data['text']
        if 'output' in data and isinstance(data['output'], dict) and 'text' in data['output'] and isinstance(data['output']['text'], str):
            return data['output']['text']
        
        # Если не нашли, ищем в любом значении
        for value in data.values():
            if isinstance(value, dict):
                found_text = self._extract_text_from_data(value)
                if found_text:
                    return found_text
            elif isinstance(value, str):
                return value # Возвращаем первое попавшееся строковое значение

        # Если ничего не найдено, возвращаем строковое представление всего объекта
        return json.dumps(data, ensure_ascii=False, indent=2)


    async def execute_join(self, node: Node,label_to_id_map: Dict[str, str], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнение интеллектуальной Join/Merge ноды, которая находит общие данные,
        изолирует уникальные и формирует чистый результат.
        """
        config = node.data.get('config', {})
        merge_strategy = config.get('mergeStrategy', 'combine_text')
        separator = config.get('separator', '\n\n---\n\n').replace('\\n', '\n')
        
        logger.info(f"🔀 Выполнение интеллектуальной Join/Merge ноды: {node.id}")
        
        inputs = input_data.get('inputs', {})
        if not inputs:
            return {**input_data, "join_result": {"error": "No inputs to join"}, "success": False}
        
        # Если вход только один, просто пробрасываем его дальше
        if len(inputs) == 1:
            return list(inputs.values())[0]

        # --- Магия начинается здесь ---

        # Шаг 1: Находим общие данные
        all_input_dicts = list(inputs.values())
        first_input = all_input_dicts[0]
        other_inputs = all_input_dicts[1:]
        
        common_data = {}
        for key, value in first_input.items():
            # Для простоты сравниваем значения напрямую. Для сложных объектов может потребоваться deep comparison.
            # Проверяем, что ключ и значение идентичны во всех остальных входах
            if all(key in other and other[key] == value for other in other_inputs):
                common_data[key] = value
        
        logger.info(f"🔍 Найдены общие данные: {list(common_data.keys())}")

        # Шаг 2: Изолируем уникальные данные для каждой ветки
        unique_data_per_source = {}
        for source_id, source_dict in inputs.items():
            unique_data = {k: v for k, v in source_dict.items() if k not in common_data}
            unique_data_per_source[source_id] = unique_data

        # Шаг 3: Формируем результат в зависимости от стратегии
        join_result = {}
        output_data = {}

        if merge_strategy == 'combine_text':
            texts = []
            for source_id, unique_data in unique_data_per_source.items():
                # Используем вспомогательную функцию для извлечения текста
                text = self._extract_text_from_data(unique_data)
                texts.append(f"=== Источник {source_id} ===\n{text}")
            
            combined_text = separator.join(texts)
            output_data = {
                'text': combined_text,
                'source_count': len(inputs)
            }
            logger.info(f"✅ Объединено {len(texts)} текстов")

        elif merge_strategy == 'merge_json':
            # В этой стратегии мы просто показываем уникальные данные
            output_data = {
                'json': unique_data_per_source,
                'text': json.dumps(unique_data_per_source, ensure_ascii=False, indent=2),
                'source_count': len(inputs)
            }
            logger.info(f"✅ Объединены данные в JSON от {len(inputs)} источников")

        else:
            raise Exception(f"Unknown merge strategy: {merge_strategy}")

        # Шаг 4: Собираем финальный, идеальный return
        final_result = {
            **common_data,  # 1. Выносим общие данные на верхний уровень
            "join_result": { # 2. Создаем уникальный результат для самой Join ноды
                "sources": unique_data_per_source,
                "metadata": {
                    "source_count": len(inputs),
                    "source_ids": list(inputs.keys()),
                    "merge_strategy": merge_strategy,
                    "merge_time": datetime.now().isoformat()
                }
            },
            "output": output_data, # 3. Добавляем удобный output
            "success": True
        }
        
        return final_result

    async def execute_if_else(self, node: Node,label_to_id_map: Dict[str, str], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение If/Else ноды"""
        start_time = time.time()
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
                'node_id': node.id
            }
        }

    # НОВОЕ: Логика для ноды-диспетчера
    async def execute_dispatcher(self, node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any]):
        """Выполняет диспетчер в режиме router или orchestrator"""
        config = node.data.get('config', {})
        dispatcher_type = config.get('dispatcher_type', 'router')
        
        logger.info(f"🎯 Executing dispatcher {node.id} in {dispatcher_type} mode")
        
        if dispatcher_type == 'router':
            # Существующая логика - простой роутинг
            return await self.execute_router_dispatcher(node, label_to_id_map, input_data)
        
        elif dispatcher_type == 'orchestrator':
            # НОВАЯ логика - планирование и координация
            return await self.execute_orchestrator_dispatcher(node, label_to_id_map, input_data)
        
        else:
            raise Exception(f"Неизвестный тип диспетчера: {dispatcher_type}")
    async def execute_router_dispatcher(self, node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Агент-диспетчер, который анализирует запрос и выбирает нужный workflow (старая логика)"""
        logger.info(f"DEBUG: input_data for dispatcher: {json.dumps(input_data, ensure_ascii=False, indent=2)}")

        logger.info(f"🔀 Executing Router Dispatcher node: {node.id}")
        config = node.data.get('config', {})
        
        # Новый блок: получаем шаблон из конфига или используем дефолтный
        query_template = config.get('userQueryTemplate') or '{{ input.output.text }}'

        # Для replace_templates нужен label_to_id_map, как в execute_workflow_internal
        # Если label_to_id_map пустой, можно попытаться построить его из input_data:
        if not label_to_id_map:
            # Попробуем собрать из input_data (если это контейнер)
            label_to_id_map = {}
            for k, v in input_data.items():
                if isinstance(v, dict) and 'label' in v:
                    label_to_id_map[v['label']] = k

        # Подставляем шаблон
        user_query = replace_templates(query_template, input_data, label_to_id_map).strip()


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

            # classification_prompt = f"""Определи категорию запроса пользователя и выбери подходящий обработчик.
            # Доступные категории: {json.dumps(list(workflow_routes.keys()), ensure_ascii=False)}
            # Запрос пользователя: {user_query}
            # Ответь ТОЛЬКО одним словом - названием категории."""
            # Новый блок: используем кастомный промпт, если он есть
            dispatcher_prompt = config.get('dispatcherPrompt')
            DEFAULT_PROMPT = (
                "Определи категорию запроса пользователя и выбери подходящий обработчик.\n"
                "Доступные категории: {категории}\n"
                "Запрос пользователя: {запрос пользователя}\n"
                "Ответь ТОЛЬКО одним словом - названием категории."
            )
            categories_str = ", ".join(workflow_routes.keys())
            prompt_template = dispatcher_prompt or DEFAULT_PROMPT
            classification_prompt = prompt_template.replace("{категории}", categories_str).replace("{запрос пользователя}", user_query)
            
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
    async def execute_orchestrator_dispatcher(self, node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any]):
        """Планирующий диспетчер - создает план и координирует выполнение"""
        config = node.data.get('config', {})
        session_id = input_data.get('session_id')
        dispatcher_id = node.id
        
        logger.info(f"🎼 Orchestrator dispatcher {dispatcher_id} processing request")
        
        # Инициализируем хранилище сессий для этого диспетчера
        if dispatcher_id not in self.dispatcher_sessions:
            self.dispatcher_sessions[dispatcher_id] = {}
        
        sessions = self.dispatcher_sessions[dispatcher_id]
        
        # 1. Если это возврат от workflow
        if input_data.get('return_to_dispatcher'):
            logger.info(f"📥 Handling workflow return for session {session_id}")
            return await self.handle_workflow_return(dispatcher_id, sessions, input_data)
        
        # 2. Если продолжение существующей сессии
        elif session_id and session_id in sessions:
            logger.info(f"🔄 Continuing session {session_id}")
            return await self.handle_session_continuation(dispatcher_id, sessions, input_data)
        
        # 3. Если новый запрос - создаем план
        else:
            logger.info(f"🆕 Creating new session for new request")
            return await self.create_new_orchestrator_session(dispatcher_id, sessions, config, input_data)
    async def create_new_orchestrator_session(self, dispatcher_id: str, sessions: Dict, config: Dict, input_data: Dict[str, Any]):
        """Создает новую сессию и план выполнения"""
        import uuid
        from datetime import datetime
        
        session_id = str(uuid.uuid4())
        user_query = input_data.get('user_query', input_data.get('message', ''))
        
        logger.info(f"📋 Creating execution plan for: {user_query}")
        
        # Создаем план через GigaChat
        plan = await self.create_execution_plan(config, user_query)
        
        # Сохраняем сессию
        sessions[session_id] = {
            "plan": plan,
            "current_step": 0,
            "user_query": user_query,
            "accumulated_data": {},
            "created_at": datetime.now(),
            "dispatcher_id": dispatcher_id
        }
        
        logger.info(f"💾 Session {session_id} created with {len(plan)} steps")
        
        # Запускаем первый workflow
        if plan:
            first_step = plan[0]
            workflow_id = first_step.get('workflow_id')
            
            if workflow_id:
                workflow_input = {
                    **input_data,
                    "session_id": session_id,
                    "dispatcher_context": {
                        "plan": plan,
                        "step": 0,
                        "dispatcher_id": dispatcher_id
                    }
                }
                
                logger.info(f"🚀 Launching first workflow: {workflow_id}")
                return await self.launch_workflow_by_id(workflow_id, workflow_input)
            else:
                raise Exception("Первый шаг плана не содержит workflow_id")
        else:
            raise Exception("Не удалось создать план выполнения")
    async def create_execution_plan(self, config: Dict, user_query: str):
        """Создает план выполнения через GigaChat"""
        import json
        
        available_workflows = config.get('available_workflows', {})
        auth_token = config.get('dispatcherAuthToken', '')
        
        if not auth_token:
            raise Exception("Токен авторизации для планирующего диспетчера не указан")
        
        if not available_workflows:
            raise Exception("Доступные workflow для планирования не указаны")
        
        # Формируем описание доступных workflow
        workflows_description = "\n".join([
            f"- {wf_id}: {wf_config.get('description', 'Описание отсутствует')}"
            for wf_id, wf_config in available_workflows.items()
        ])
        
        planning_prompt = f"""
        Пользователь просит: "{user_query}"
        
        Доступные workflow для выполнения:
        {workflows_description}
        
        Создай пошаговый план выполнения в формате JSON массива:
        [
            {{"workflow_id": "workflow1", "description": "что делает этот шаг"}},
            {{"workflow_id": "workflow2", "description": "что делает этот шаг"}}
        ]
        
        Правила:
        1. Используй только workflow_id из списка выше
        2. Создавай логичную последовательность шагов
        3. Отвечай ТОЛЬКО JSON массивом, без дополнительного текста
        4. Если задача простая, можно использовать один workflow
        """
        
        if await self.gigachat_api.get_token(auth_token):
            result = await self.gigachat_api.get_chat_completion(
                "Ты планировщик задач. Анализируй запрос пользователя и создавай оптимальный план выполнения из доступных workflow.",
                planning_prompt
            )
            
            try:
                # Пытаемся распарсить JSON
                plan = json.loads(result['response'])
                
                # Валидируем план
                if not isinstance(plan, list):
                    raise ValueError("План должен быть массивом")
                
                for step in plan:
                    if not isinstance(step, dict) or 'workflow_id' not in step:
                        raise ValueError("Каждый шаг должен содержать workflow_id")
                    
                    if step['workflow_id'] not in available_workflows:
                        raise ValueError(f"Workflow {step['workflow_id']} не найден в доступных")
                
                logger.info(f"📋 Создан план из {len(plan)} шагов: {[s['workflow_id'] for s in plan]}")
                return plan
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"❌ Ошибка парсинга плана: {result['response']}")
                logger.error(f"❌ Детали ошибки: {str(e)}")
                
                # Fallback к простому плану
                fallback_workflows = list(available_workflows.keys())
                if fallback_workflows:
                    fallback_plan = [{"workflow_id": fallback_workflows[0], "description": "Fallback workflow"}]
                    logger.info(f"🔄 Используем fallback план: {fallback_plan}")
                    return fallback_plan
                else:
                    raise Exception("Не удалось создать план и нет доступных workflow для fallback")
        
        else:
            raise Exception("Не удалось авторизоваться в GigaChat API для создания плана")
    async def handle_workflow_return(self, dispatcher_id: str, sessions: Dict, input_data: Dict[str, Any]):
        """Обрабатывает возврат от workflow"""
        session_id = input_data.get('session_id')
        
        if not session_id or session_id not in sessions:
            raise Exception(f"Сессия {session_id} не найдена в диспетчере {dispatcher_id}")
        
        session = sessions[session_id]
        
        # Сохраняем результат
        workflow_result = input_data.get('workflow_result', {})
        completed_workflow = input_data.get('completed_workflow', 'unknown')
        
        logger.info(f"📥 Workflow {completed_workflow} завершен для сессии {session_id}")
        
        # Добавляем результат к накопленным данным
        session['accumulated_data'][f"step_{session['current_step']}_result"] = workflow_result
        session['accumulated_data'][f"step_{session['current_step']}_workflow"] = completed_workflow
        
        # Переходим к следующему шагу
        session['current_step'] += 1
        
        # Проверяем, есть ли еще шаги в плане
        if session['current_step'] < len(session['plan']):
            # Запускаем следующий workflow
            next_step = session['plan'][session['current_step']]
            next_workflow_id = next_step.get('workflow_id')
            
            logger.info(f"➡️ Переход к шагу {session['current_step']}: {next_workflow_id}")
            
            workflow_input = {
                "session_id": session_id,
                "user_query": session['user_query'],
                "previous_results": session['accumulated_data'],
                "dispatcher_context": {
                    "plan": session['plan'],
                    "step": session['current_step'],
                    "dispatcher_id": dispatcher_id
                }
            }
            
            return await self.launch_workflow_by_id(next_workflow_id, workflow_input)
        
        else:
            # План выполнен полностью
            logger.info(f"✅ План для сессии {session_id} выполнен полностью")
            
            final_result = {
                "success": True,
                "message": "План выполнен успешно",
                "session_id": session_id,
                "completed_steps": len(session['plan']),
                "results": session['accumulated_data'],
                "session_completed": True,
                "output": {
                    "text": f"Выполнен план из {len(session['plan'])} шагов",
                    "json": session['accumulated_data']
                }
            }
            
            # Удаляем завершенную сессию
            del sessions[session_id]
            logger.info(f"🗑️ Сессия {session_id} удалена")
            
            return final_result
    async def handle_session_continuation(self, dispatcher_id: str, sessions: Dict, input_data: Dict[str, Any]):
        """Обрабатывает продолжение существующей сессии (новый запрос пользователя)"""
        session_id = input_data.get('session_id')
        session = sessions[session_id]
        
        user_query = input_data.get('user_query', input_data.get('message', ''))
        
        logger.info(f"🔄 Продолжение сессии {session_id}: {user_query}")
        
        # Добавляем новый запрос к сессии
        if 'additional_requests' not in session:
            session['additional_requests'] = []
        
        session['additional_requests'].append({
            "query": user_query,
            "timestamp": datetime.now().isoformat()
        })
        
        # Пока что просто возвращаем информацию о текущем состоянии
        # В будущем можно добавить логику для модификации плана
        current_step = session['current_step']
        total_steps = len(session['plan'])
        
        return {
            "success": True,
            "message": f"Запрос добавлен к существующей сессии. Выполняется шаг {current_step + 1} из {total_steps}",
            "session_id": session_id,
            "current_step": current_step,
            "total_steps": total_steps,
            "additional_request_added": True,
            "output": {
                "text": f"Ваш запрос принят. Сейчас выполняется шаг {current_step + 1} из {total_steps}",
                "json": {
                    "session_status": "active",
                    "progress": f"{current_step}/{total_steps}"
                }
            }
        }
    async def launch_workflow_by_id(self, workflow_id: str, input_data: Dict[str, Any]):
        """Запускает workflow по ID"""
        if workflow_id not in saved_workflows:
            raise Exception(f"Workflow {workflow_id} не найден в сохраненных workflow")
        
        workflow_data = saved_workflows[workflow_id]
        
        logger.info(f"🚀 Запуск workflow {workflow_id}")
        
        workflow_request = WorkflowExecuteRequest(
            nodes=workflow_data["nodes"],
            connections=workflow_data["connections"]
        )
        
        # Запускаем workflow с переданными данными
        result = await execute_workflow_internal(workflow_request, initial_input_data=input_data)
        
        return {
            "success": result.success,
            "workflow_id": workflow_id,
            "result": result.result,
            "error": result.error,
            "logs": result.logs,
            "output": {
                "text": f"Workflow {workflow_id} {'выполнен успешно' if result.success else 'завершился с ошибкой'}",
                "json": result.result
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
        result = await executor(node, {},input_data or {})
        
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
    global goto_execution_counter
    goto_execution_counter.clear()

    try:
        # ======================= НАЧАЛО НОВОГО БЛОКА =======================
        # Проверка на уникальность лейблов и создание карты 'label' -> 'id'
        # Мы используем request.nodes, так как ноды приходят внутри объекта WorkflowExecuteRequest
        labels = [node.data.get('label', node.id) for node in request.nodes] # Используем .get для безопасности
        if len(labels) != len(set(labels)):
            # Находим дубликат для более информативного сообщения
            seen = set()
            duplicates = {x for x in labels if x in seen or seen.add(x)}
            raise ValueError(f"Ошибка: Обнаружены дублирующиеся лейблы нод: {', '.join(duplicates)}. Каждая нода должна иметь уникальное имя (label).")

        # Создаем карту 'label' -> 'id'
        label_to_id_map = {node.data.get('label', node.id): node.id for node in request.nodes}
        # ======================== КОНЕЦ НОВОГО БЛОКА ========================

        logger.info(f"🚀 Запуск workflow с {len(request.nodes)} нодами")
        if initial_input_data:
            logger.info(f"💡 Workflow запущен с начальными данными: {json.dumps(initial_input_data, default=str, indent=2)[:300]}...")

        for node in request.nodes:
            logger.info(f"📋 Нода {node.id} типа {node.type}: {node.data.get('label', 'Без метки')}")
        logger.info(f"🔗 Соединения: {len(request.connections)}")
        for conn in request.connections:
            logger.info(f"🔗 Соединение: {conn.source} -> {conn.target}")

        join_node_data = {}

        start_node = None
        if request.startNodeId:
            start_node = next((n for n in request.nodes if n.id == request.startNodeId), None)
            logger.info(f"🎯 Используем указанную стартовую ноду: {request.startNodeId}")
        else:
            node_ids_with_inputs = {conn.target for conn in request.connections}
            startable_types = ['gigachat', 'webhook', 'timer', 'webhook_trigger']
            start_candidates = [
                n for n in request.nodes
                if n.type in startable_types and n.id not in node_ids_with_inputs
            ]
            if start_candidates:
                start_node = start_candidates[0]
                logger.info(f"🔍 Найдена стартовая нода без входящих соединений: {start_node.id}")
            else:
                start_node = next((n for n in request.nodes if n.type in startable_types), None)
                logger.info(f"⚠️ Все ноды имеют входящие соединения, берем первую доступную: {start_node.id if start_node else 'None'}")

        if not start_node:
            raise Exception("No startable node found")

        if start_node.type == "timer":
            timer_id = f"timer_{start_node.id}"
            if timer_id in active_timers:
                active_timers[timer_id]["workflow"] = {
                    "nodes": request.nodes,
                    "connections": request.connections,
                    "startNodeId": start_node.id
                }

        # ИЗМЕНЕНО: Это теперь главный контейнер для ВСЕХ результатов
        workflow_results = {}

        async def execute_node_recursive(node_id: str,label_to_id_map: Dict[str, str], source_node_id: str = None):
            node = next((n for n in request.nodes if n.id == node_id), None)
            if not node:
                return

            # ИЗМЕНЕНО: Определяем входные данные для текущей ноды
            current_input_data = {}
            if source_node_id:
                # Для обычных нод входные данные - это ВЕСЬ контейнер результатов
                current_input_data = workflow_results
            elif initial_input_data:
                 # Для самой первой ноды - это начальные данные
                current_input_data = initial_input_data

            # Специальная обработка для webhook ноды
            if node.type == 'webhook_trigger' and not source_node_id:
                logger.info(f"🔔 Webhook нода {node_id} активирована")
                # Webhook нода просто формирует свой первый результат
                node_result = {
                    "success": True,
                    "output": current_input_data,
                    "message": "Webhook data received"
                }
                workflow_results[node_id] = node_result # Сохраняем результат

                # Передаем управление следующим нодам
                next_connections = [c for c in request.connections if c.source == node_id]
                for connection in next_connections:
                    await execute_node_recursive(connection.target, label_to_id_map, node_id)
                return

            # Проверка на join ноду
            incoming_connections = [c for c in request.connections if c.target == node_id]
            if node.type == 'join' and len(incoming_connections) > 1:
                if node_id not in join_node_data:
                    join_node_data[node_id] = {
                        'expected_sources': set(c.source for c in incoming_connections),
                        'received_data': {}
                    }
                if source_node_id:
                    # ИЗМЕНЕНО: Сохраняем результат конкретной предыдущей ноды
                    join_node_data[node_id]['received_data'][source_node_id] = workflow_results.get(source_node_id)
                    logger.info(f"🔀 Join нода {node_id} получила данные от {source_node_id}")
                    logger.info(f"📊 Ожидается: {join_node_data[node_id]['expected_sources']}")
                    logger.info(f"📊 Получено от: {set(join_node_data[node_id]['received_data'].keys())}")

                received_sources = set(join_node_data[node_id]['received_data'].keys())
                expected_sources = join_node_data[node_id]['expected_sources']

                if node.data.get('config', {}).get('waitForAll', True):
                    if received_sources != expected_sources:
                        logger.info(f"⏳ Join нода {node_id} ждет данные от {expected_sources - received_sources}")
                        return # Выходим и ждем, пока другие ветки дойдут до этой ноды

                # Все данные получены, формируем вход для join ноды
                current_input_data = {'inputs': join_node_data[node_id]['received_data']}
                del join_node_data[node_id]

            # Логируем выполнение
            logs.append({
                "message": f"Executing {node.data.get('label', node.type)}...",
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "nodeId": node_id
            })

            # Выбираем и выполняем ноду
            executor_map = {
                'gigachat': executors.execute_gigachat,
                'email': executors.execute_email,
                'database': executors.execute_database,
                'webhook': executors.execute_webhook,
                'timer': executors.execute_timer,
                'join': executors.execute_join,
                'request_iterator': executors.execute_request_iterator,
                'if_else': executors.execute_if_else,
                'dispatcher': executors.execute_dispatcher
            }

            executor = executor_map.get(node.type)
            if executor:
                # ИЗМЕНЕНО: Вызываем executor с подготовленными данными
                node_result = await executor(node, label_to_id_map,current_input_data)

                # ИЗМЕНЕНО: Сохраняем ИЗОЛИРОВАННЫЙ результат ноды в общий контейнер
                workflow_results[node_id] = node_result

                logs.append({
                    "message": f"{node.data.get('label', node.type)} completed successfully",
                    "timestamp": datetime.now().isoformat(),
                    "level": "success",
                    "nodeId": node_id
                })

                # Находим следующие ноды для перехода
                next_connections = [c for c in request.connections if c.source == node_id]

                # Специальная обработка для If/Else ноды
                if node.type == 'if_else' and 'branch' in node_result:
                    branch = node_result['branch']
                    logger.info(f"🔍 If/Else нода {node_id} вернула branch: {branch}")

                    filtered_connections = []
                    goto_connections = []

                    for conn in next_connections:
                        conn_label = conn.data.get('label', '').lower() if conn.data else ''
                        if conn_label == f"{branch}:goto":
                            goto_connections.append(conn)
                        elif conn_label == branch:
                            filtered_connections.append(conn)

                    if goto_connections:
                        for goto_conn in goto_connections:
                            goto_key = f"{node_id}_to_{goto_conn.target}"
                            goto_execution_counter.setdefault(goto_key, 0)
                            goto_execution_counter[goto_key] += 1
                            max_iterations = node.data.get('config', {}).get('maxGotoIterations', 10)

                            if goto_execution_counter[goto_key] > max_iterations:
                                logger.error(f"🔄 Превышен лимит goto переходов ({max_iterations}) для {goto_key}")
                                continue

                            logger.info(f"🔄 Активирован goto переход к {goto_conn.target} (итерация {goto_execution_counter[goto_key]})")
                            # ИЗМЕНЕНО: Рекурсивный вызов без прямой передачи данных
                            await execute_node_recursive(goto_conn.target, label_to_id_map,node_id,)
                        return # После goto не выполняем обычные соединения

                    for connection in filtered_connections:
                        # ИЗМЕНЕНО: Рекурсивный вызов без прямой передачи данных
                        await execute_node_recursive(connection.target,label_to_id_map, node_id)
                else:
                    # Для всех остальных типов нод
                    for connection in next_connections:
                        # ИЗМЕНЕНО: Рекурсивный вызов без прямой передачи данных
                        await execute_node_recursive(connection.target, label_to_id_map,node_id)
            else:
                raise Exception(f"Unknown node type: {node.type}")

        # Запускаем выполнение с самой первой ноды
        await execute_node_recursive(start_node.id,label_to_id_map)

        # ИЗМЕНЕНО: Возвращаем ВЕСЬ контейнер с результатами, а не последний результат
        return ExecutionResult(
            success=True,
            result=workflow_results,
            logs=logs
        )

    except Exception as e:
        logger.error(f"❌ Ошибка выполнения workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc()) # Добавим трассировку для лучшей отладки
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

# @app.post("/timers/{timer_id}/update")
# async def update_timer_endpoint(timer_id: str, interval: int):
#     """Обновление интервала таймера"""
#     if timer_id not in active_timers:
#         raise HTTPException(status_code=404, detail=f"Timer {timer_id} not found")
    
#     result = await update_timer(timer_id, interval)
    
#     logger.info(f"🔄 Таймер {timer_id} обновлен с новым интервалом {interval} минут")
    
#     return result
# ДОБАВЛЯЕМ: Новый эндпоинт для настройки таймера из UI
@app.post("/setup-timer", status_code=status.HTTP_200_OK)
async def setup_timer(request: SetupTimerRequest):
    """
    Создает или обновляет фоновую задачу таймера.
    Этот эндпоинт должен вызываться из UI при сохранении workflow с нодой таймера.
    """
    try:
        node = request.node
        workflow_id = request.workflow_id
        
        if node.type != 'timer':
            raise HTTPException(status_code=400, detail="Node must be of type 'timer'")

        if workflow_id not in saved_workflows:
             raise HTTPException(status_code=404, detail=f"Workflow with ID '{workflow_id}' not found.")

        config = node.data.get('config', {})
        interval = int(config.get('interval', 5))
        timer_id = f"timer_{node.id}"

        # Информация, которую будет использовать фоновая задача
        workflow_info_for_task = {
            "workflow_id": workflow_id,
        }

        if timer_id not in active_timers:
            await create_timer(timer_id, node.id, interval, workflow_info_for_task)
            message = f"Таймер {timer_id} для workflow '{workflow_id}' создан."
        else:
            await update_timer(timer_id, interval, workflow_info_for_task)
            message = f"Таймер {timer_id} для workflow '{workflow_id}' обновлен."
        
        logger.info(f"✅ {message}")
        return {"success": True, "message": message, "timer_id": timer_id}
    except Exception as e:
        logger.error(f"❌ Ошибка настройки таймера: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/dispatcher/{dispatcher_id}/sessions")
async def get_dispatcher_sessions(dispatcher_id: str):
    """Получить активные сессии конкретного диспетчера"""
    if dispatcher_id not in executors.dispatcher_sessions:
        return {"sessions": []}
    
    sessions = executors.dispatcher_sessions[dispatcher_id]
    
    sessions_info = []
    for session_id, session_data in sessions.items():
        sessions_info.append({
            "session_id": session_id,
            "current_step": session_data.get('current_step', 0),
            "total_steps": len(session_data.get('plan', [])),
            "user_query": session_data.get('user_query', ''),
            "created_at": session_data.get('created_at', '').isoformat() if session_data.get('created_at') else '',
            "plan": session_data.get('plan', [])
        })
    
    return {"sessions": sessions_info}

@app.delete("/dispatcher/{dispatcher_id}/sessions/{session_id}")
async def delete_dispatcher_session(dispatcher_id: str, session_id: str):
    """Удалить конкретную сессию диспетчера"""
    if dispatcher_id not in executors.dispatcher_sessions:
        raise HTTPException(status_code=404, detail="Диспетчер не найден")
    
    sessions = executors.dispatcher_sessions[dispatcher_id]
    
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    
    del sessions[session_id]
    logger.info(f"🗑️ Сессия {session_id} диспетчера {dispatcher_id} удалена")
    
    return {"message": f"Сессия {session_id} удалена"}


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
