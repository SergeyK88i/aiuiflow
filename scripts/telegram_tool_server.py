
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import uuid
import aiohttp

# --- Конфигурация ---
# ВАЖНО: Замените на ваш реальный токен
TELEGRAM_TOKEN = "7768666638:AAH-bOhEwfunRXFrIcE3TVT0xipdycXx7dM"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram Tool MCP Server", version="1.0.0")

# --- Хранилище сессий (оставлено для совместимости и будущих улучшений) ---
SESSIONS = {}

# --- Описание "умений" нашего Telegram-сервера ---
TOOLS_LIST = [
    {
        "name": "send_message",
        "description": "Отправляет текстовое сообщение в указанный чат Telegram.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "number",
                    "description": "ID чата, куда нужно отправить сообщение"
                },
                "text": {
                    "type": "string",
                    "description": "Текст сообщения"
                }
            },
            "required": ["chat_id", "text"]
        }
    }
    # Сюда можно будет добавлять другие инструменты: edit_message, send_photo и т.д.
]

# --- Вспомогательная функция для отправки сообщения в Telegram ---
async def _send_telegram_message(chat_id: int, text: str) -> dict:
    """Отправляет сообщение и возвращает ответ от API Telegram."""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            if response.ok:
                logger.info(f"✅ Сообщение в чат {chat_id} успешно отправлено.")
                return await response.json()
            else:
                error_text = await response.text()
                logger.error(f"❌ Ошибка Telegram API: {error_text}")
                raise Exception(f"Telegram API Error: {error_text}")

# --- Главный обработчик JSON-RPC запросов ---
@app.post("/")
async def json_rpc_handler(request: Request):
    body = await request.json()

    if "jsonrpc" not in body or body["jsonrpc"] != "2.0" or "method" not in body or "id" not in body:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request"}}
        )

    request_id = body["id"]
    method = body["method"]
    params = body.get("params", {})

    logger.info(f"⚡️ Получен запрос: method='{method}', id={request_id}")

    try:
        if method == "tools/list":
            result = handle_tools_list(params)
        elif method == "tools/call":
            result = await handle_tools_call(params) # Обратите внимание на await
        else:
            # Для простоты пока не реализуем initialize, т.к. сессии не используются
            raise HTTPException(status_code=404, detail=f"Method '{method}' not found")

        return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": result})

    except Exception as e:
        logger.error(f"❌ Ошибка при выполнении метода '{method}': {e}")
        return JSONResponse(
            status_code=500,
            content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal Error", "data": str(e)}}
        )

# --- Обработчики методов ---
def handle_tools_list(params: dict):
    """Возвращает список инструментов."""
    logger.info(f"📚 Отправлен список инструментов")
    return {"tools": TOOLS_LIST}

async def handle_tools_call(params: dict):
    """Выполняет один из инструментов."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    logger.info(f"🛠 Вызов инструмента '{tool_name}'")

    if tool_name == "send_message":
        chat_id = arguments.get("chat_id")
        text = arguments.get("text")
        if not isinstance(chat_id, int) or not isinstance(text, str):
            raise ValueError("chat_id (integer) and text (string) are required for send_message")
        
        api_result = await _send_telegram_message(chat_id, text)
        return {"content": [{"type": "json", "json": api_result}], "isError": False}

    else:
        raise ValueError(f"Unknown tool name: {tool_name}")

# --- Запуск сервера ---
if __name__ == "__main__":
    print("🚀 Запуск Telegram Tool Server на http://localhost:8001")
    print("   - Доступные инструменты: send_message")
    uvicorn.run(app, host="0.0.0.0", port=8001)
