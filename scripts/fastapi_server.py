from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import requests
import uuid
import json
import asyncio
import logging
from datetime import datetime

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

# Исполнители нод
class NodeExecutors:
    def __init__(self):
        self.gigachat_api = GigaChatAPI()

    async def execute_gigachat(self, node: Node, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение GigaChat ноды"""
        config = node.data.get('config', {})
        auth_token = config.get('authToken')
        system_message = config.get('systemMessage', 'Ты полезный ассистент')
        user_message = config.get('userMessage', '')
        clear_history = config.get('clearHistory', False)

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
        config = node.data.get('config', {})
        interval = config.get('interval', 5)
        timezone = config.get('timezone', 'UTC')

        logger.info(f"⏰ Timer выполнен: интервал {interval} минут, часовой пояс {timezone}")

        return {
            "success": True,
            "message": "Timer executed",
            "interval": interval,
            "timezone": timezone,
            "timestamp": datetime.now().isoformat(),
            "inputData": input_data
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
        # Создаем объект ноды
        node = Node(
            id=node_data.get('id', 'temp'),
            type=node_type,
            position=node_data.get('position', {'x': 0, 'y': 0}),
            data=node_data
        )

        # Выбираем исполнитель
        executor_map = {
            'gigachat': executors.execute_gigachat,
            'email': executors.execute_email,
            'database': executors.execute_database,
            'webhook': executors.execute_webhook,
            'timer': executors.execute_timer
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

@app.post("/execute-workflow")
async def execute_workflow(request: WorkflowExecuteRequest):
    """Выполнение полного workflow"""
    try:
        logger.info(f"🚀 Запуск workflow с {len(request.nodes)} нодами")
        
        # Находим стартовую ноду
        start_node = None
        if request.startNodeId:
            start_node = next((n for n in request.nodes if n.id == request.startNodeId), None)
        else:
            # Ищем любую стартовую ноду
            startable_types = ['gigachat', 'webhook', 'timer']
            start_node = next((n for n in request.nodes if n.type in startable_types), None)

        if not start_node:
            raise HTTPException(status_code=400, detail="No startable node found")

        # Выполняем workflow
        results = {}
        logs = []
        
        async def execute_node_recursive(node_id: str, input_data: Dict[str, Any] = None):
            node = next((n for n in request.nodes if n.id == node_id), None)
            if not node:
                return None

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
                'timer': executors.execute_timer
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
                    await execute_node_recursive(connection.target, result)

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

if __name__ == "__main__":
    import uvicorn
    print("🚀 Запуск FastAPI сервера...")
    print("📡 API будет доступен на: http://localhost:8000")
    print("📚 Документация: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
