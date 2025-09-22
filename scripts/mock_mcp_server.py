
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import uuid

# --- Настройка --- 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mock JSON-RPC MCP Server", version="1.0.0")

# --- Хранилище сессий в памяти --- 
# В реальном приложении здесь могла бы быть Redis или другая БД
SESSIONS = {}

# --- Описание "умений" сервера --- 
TOOLS_LIST = [
    {
      "name": "create_report",
      "description": "Создает отчет на основе входного текста и сохраняет его в сессии.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "title": {"type": "string", "description": "Заголовок отчета"},
          "text": {"type": "string", "description": "Основной текст отчета"}
        },
        "required": ["title", "text"]
      }
    },
    {
      "name": "get_report_summary",
      "description": "Возвращает краткое содержание отчета из текущей сессии.",
      "inputSchema": { "type": "object", "properties": {} }
    },
    {
      "name": "echo",
      "description": "Просто возвращает обратно любые переданные аргументы.",
      "inputSchema": {
        "type": "object",
        "properties": {
            "data": { "type": "object" }
        },
        "required": ["data"]
      }
    }
]

# --- Главный и единственный эндпоинт для всех JSON-RPC запросов --- 
@app.post("/")
async def json_rpc_handler(request: Request):
    body = await request.json()

    # Базовая валидация JSON-RPC запроса
    if "jsonrpc" not in body or body["jsonrpc"] != "2.0" or "method" not in body or "id" not in body:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request"}}
        )

    request_id = body["id"]
    method = body["method"]
    params = body.get("params", {})

    logger.info(f"⚡️ Получен запрос: method='{method}', id={request_id}")

    # --- Маршрутизация методов --- 
    try:
        if method == "initialize":
            result = handle_initialize(params)
        elif method == "tools/list":
            result = handle_tools_list(params)
        elif method == "tools/call":
            result = handle_tools_call(params)
        else:
            raise HTTPException(status_code=404, detail=f"Method '{method}' not found")

        return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": result})

    except Exception as e:
        logger.error(f"❌ Ошибка при выполнении метода '{method}': {e}")
        return JSONResponse(
            status_code=500,
            content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal Error", "data": str(e)}}
        )

# --- Обработчики методов --- 

def handle_initialize(params: dict):
    """Обрабатывает рукопожатие и создает сессию."""
    session_id = str(uuid.uuid4()) # В реальном мире ID мог бы приходить от клиента
    SESSIONS[session_id] = {
        "report_title": None,
        "report_text": None,
        "initialized_at": str(uuid.uuid4()) # Просто для примера
    }
    logger.info(f"🤝 Сессия создана: {session_id}")
    # Возвращаем возможности сервера и ID сессии
    return {
        "protocolVersion": "2025-03-26",
        "serverInfo": {
            "name": "Mock MCP Server",
            "version": "1.0.0"
        },
        "sessionId": session_id # Отдаем клиенту его ID сессии
    }

def handle_tools_list(params: dict):
    """Возвращает список инструментов."""
    logger.info(f"📚 Отправлен список инструментов")
    return {"tools": TOOLS_LIST}

def handle_tools_call(params: dict):
    """Выполняет один из инструментов."""
    session_id = params.get("sessionId")
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if not session_id:
        raise ValueError("Session ID is missing in params")

    # Для удобства тестирования: если сессия с таким ID еще не существует, создаем ее на лету
    if session_id not in SESSIONS:
        logger.warning(f"⚠️ Сессия {session_id} не была инициализирована. Создаю ее на лету.")
        SESSIONS[session_id] = {
            "report_title": None,
            "report_text": None,
            "initialized_at": str(uuid.uuid4())
        }

    logger.info(f"🛠 Вызов инструмента '{tool_name}' в сессии {session_id}")

    # --- Логика инструментов ---
    if tool_name == "create_report":
        title = arguments.get("title")
        text = arguments.get("text")
        if not title or not text:
            raise ValueError("Missing title or text for create_report")
        SESSIONS[session_id]["report_title"] = title
        SESSIONS[session_id]["report_text"] = text
        return {"content": [{"type": "text", "text": f"Отчет '{title}' успешно создан в сессии."}], "isError": False}

    elif tool_name == "get_report_summary":
        report_text = SESSIONS[session_id].get("report_text")
        if not report_text:
            return {"content": [{"type": "text", "text": "Ошибка: отчет не найден в сессии. Сначала создайте его."}], "isError": True}
        
        summary = f"В отчете '{SESSIONS[session_id]['report_title']}' содержится {len(report_text)} символов."
        return {"content": [{"type": "text", "text": summary}], "isError": False}

    elif tool_name == "echo":
        return {"content": [{"type": "json", "json": arguments.get("data")}], "isError": False}

    else:
        raise ValueError(f"Unknown tool name: {tool_name}")

# --- Запуск сервера --- 
if __name__ == "__main__":
    print("🚀 Запуск Mock MCP Server на http://localhost:8001")
    print("   - Манифест инструментов будет доступен через метод 'tools/list'")
    print("   - Выполнение инструментов через метод 'tools/call'")
    uvicorn.run(app, host="0.0.0.0", port=8001)
