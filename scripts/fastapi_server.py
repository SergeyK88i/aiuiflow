from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import requests
import uuid
import json
import asyncio
import logging
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

class Node(BaseModel):
    id: str
    type: str
    position: Dict[str, float]
    data: Dict[str, Any]

class Connection(BaseModel):
    id: str
    source: str
    target: str

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
            
            # Выполняем workflow
            logger.info(f"🚀 Таймер {timer_id} запускает workflow")
            try:
                # Используем ту же логику, что и execute_workflow
                workflow_request = WorkflowExecuteRequest(
                    nodes=workflow_info["nodes"],
                    connections=workflow_info["connections"],
                    startNodeId=node_id  # Начинаем с ноды таймера
                )
                
                # Выполняем workflow правильно
                result = await execute_workflow_internal(workflow_request)
                
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
                
    except asyncio.CancelledError:
        logger.info(f"🛑 Таймер {timer_id} остановлен")
    except Exception as e:
        logger.error(f"❌ Ошибка в задаче таймера {timer_id}: {str(e)}")
        # Обновляем статус таймера
        if timer_id in active_timers:
            active_timers[timer_id]["status"] = "error"




# Исполнители нод
class NodeExecutors:
    def __init__(self):
        self.gigachat_api = GigaChatAPI()

    async def execute_gigachat(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение GigaChat ноды"""
        logger.info(f"Executing GigaChat node: {node}")
        logger.info(f"Node data: {node.data}")
        logger.info(f"Config: {node.data.get('config', {})}")

        config = node.data.get('config', {})
        role = config.get('role', 'custom')  # Добавляем получение роли
        auth_token = config.get('authToken')
        system_message = config.get('systemMessage', 'Ты полезный ассистент')
        user_message = config.get('userMessage', '')
        clear_history = config.get('clearHistory', False)

        # ДОБАВЛЯЕМ ЛОГИРОВАНИЕ ВХОДНЫХ ДАННЫХ
        logger.info(f"📥 Входные данные от предыдущей ноды: {json.dumps(input_data, ensure_ascii=False, indent=2)[:500]}...")

        logger.info(f"Auth token: {auth_token is not None}")
        logger.info(f"Role: {role}")  # Логируем роль
        logger.info(f"User message: {user_message}")

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

        # Формируем выходные данные для следующих нод
        return {
            **result,
            "output": {
                "text": result.get('response', ''),
                "question": user_message,
                "length": len(result.get('response', '')),
                "words": len(result.get('response', '').split()),
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
        """Выполнение Webhook ноды"""
        config = node.data.get('config', {})
        url = config.get('url', 'https://example.com/webhook')
        method = config.get('method', 'POST')
        headers = config.get('headers', 'Content-Type: application/json')

        logger.info(f"🌐 Webhook запрос: {method} {url}")

        # Здесь будет реальный HTTP запрос
        # Пока симулируем
        await asyncio.sleep(1)

        return {
            "success": True,
            "message": "Webhook triggered",
            "url": url,
            "method": method,
            "timestamp": datetime.now().isoformat(),
            "inputData": input_data
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
            
            # Получаем ID текущего workflow из имени
            workflow_id = None
            for wf_id, wf_data in saved_workflows.items():
                if any(n.id == node.id for n in wf_data["nodes"]):
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
            'join': executors.execute_join  # Добавьте эту строку
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
# Добавьте этот эндпоинт после других эндпоинтов (примерно строка 600-650)
@app.post("/save-workflow")
async def save_workflow(request: WorkflowSaveRequest):
    """Сохраняет workflow на сервере"""
    try:
        workflow_id = request.name.lower().replace(" ", "_")
        
        # Сохраняем workflow в памяти
        saved_workflows[workflow_id] = {
            "name": request.name,
            "nodes": request.nodes,
            "connections": request.connections,
            "updated_at": datetime.now().isoformat()
        }
        
        # Можно также сохранить на диск для персистентности
        # with open(f"workflows/{workflow_id}.json", "w") as f:
        #     json.dump(saved_workflows[workflow_id], f)
        
        logger.info(f"✅ Workflow '{request.name}' сохранен успешно")
        
        return {
            "success": True,
            "workflow_id": workflow_id,
            "message": f"Workflow '{request.name}' saved successfully"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения workflow: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

async def execute_workflow_internal(request: WorkflowExecuteRequest):
    """Внутренняя функция выполнения workflow (без HTTP обертки)"""
    logs = []
    try:
        logger.info(f"🚀 Запуск workflow с {len(request.nodes)} нодами")
        
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
        
        
        async def execute_node_recursive(node_id: str, input_data: Dict[str, Any] = None, source_node_id: str = None):
            node = next((n for n in request.nodes if n.id == node_id), None)
            if not node:
                return None

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
                'join': executors.execute_join
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
                for connection in next_connections:
                    await execute_node_recursive(connection.target, result, node_id)

                return result
            else:
                raise Exception(f"Unknown node type: {node.type}")

        # Запускаем выполнение
        await execute_node_recursive(start_node.id)

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
