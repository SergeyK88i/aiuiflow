import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import os
import re
import json
from typing import List, Dict, Any
import sys

# --- ИСПРАВЛЕНИЕ 1: Добавляем корень проекта в путь для импортов ---
# Это позволит находить модуль scripts.services.giga_chat
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# --- ИСПРАВЛЕНИЕ 2: Решение проблемы с SSL для NLTK на macOS ---
try:
    import nltk
    import ssl
    try:
        _create_unverified_https_context = ssl._create_unverified_context
    except AttributeError:
        pass
    else:
        ssl._create_default_https_context = _create_unverified_https_context
    nltk.download('punkt_tab', quiet=True)
    from nltk.tokenize import sent_tokenize
except ImportError:
    print("NLTK не найден. Пожалуйста, установите: pip install nltk")
    exit()

# Импортируем GigaChatAPI из вашей структуры проекта
from scripts.services.giga_chat import GigaChatAPI

# --- Конфигурация ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GIGACHAT_AUTH_TOKEN = "ZmU1MTI4YWYtMzc0My00ZmU1LThhNzEtMmUyZGI0ZjQzMDlhOmQ1OWQzZmI1LTcwOWItNDEyNS04MGU1LTUwNzFlOTQ3ODk5Zg=="
MAX_DEPTH = 2
TOP_LEVEL_CHUNK_TARGET_SIZE = 40000
LOWER_LEVEL_CHUNK_TARGET_SIZE = 10000

app = FastAPI(title="RAG MCP Server", version="1.0.0")

# --- Глобальные переменные ---
DOCUMENT_STORE: Dict[str, str] = {}
gigachat_client = GigaChatAPI()

# --- Описание "умений" сервера ---
TOOLS_LIST = [
    {
        "name": "answer_question",
        "description": "Принимает вопрос пользователя, находит релевантную информацию в документации и генерирует осмысленный ответ.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Вопрос пользователя"
                }
            },
            "required": ["query"]
        }
    }
]

# --- Логика RAG ---

def split_text_into_chunks(text: str, target_size: int) -> List[str]:
    """Делит текст на чанки, стараясь не разрывать предложения."""
    sentences = sent_tokenize(text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > target_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

async def route_chunks(question: str, chunks: List[Dict[str, Any]], scratchpad: str, depth: int) -> Dict[str, Any]:
    """Использует LLM для выбора релевантных чанков."""
    logger.info(f"==== РОУТИНГ НА ГЛУБИНЕ {depth} | Оценивается {len(chunks)} чанков ====")

    system_message = ("Ты — эксперт-навигатор по документам. Твоя задача — выбрать чанки, которые с наибольшей вероятностью содержат ответ на вопрос пользователя. "
                      "Будь избирательным, но не пропускай важное. Ты ОБЯЗАН ответить в формате: РАССУЖДЕНИЕ: [твои мысли] ВЫБОР: [JSON-объект с ключом 'chunk_ids']")

    user_message = f"ВОПРОС: {question}\n\n"
    if scratchpad:
        user_message += f"ПРЕДЫДУЩИЕ РАССУЖДЕНИЯ (SCRATCHPAD):\n{scratchpad}\n\n"
    user_message += "ДОСТУПНЫЕ ЧАНКИ:\n\n"
    for chunk in chunks:
        preview = chunk['text'][:500]
        user_message += f"--- ЧАНК ID: {chunk['id']} ---\n{preview}...\n\n"

    if not await gigachat_client.get_token(GIGACHAT_AUTH_TOKEN):
        raise Exception("Не удалось получить токен GigaChat для роутинга.")

    response = await gigachat_client.get_chat_completion(system_message, user_message)
    response_text = response.get('response', '')

    reasoning = ""
    selection = []
    try:
        reasoning_match = re.search(r"РАССУЖДЕНИЕ:(.*?)(ВЫБОР:|$)", response_text, re.DOTALL | re.IGNORECASE)
        if reasoning_match:
            reasoning = reasoning_match.group(1).strip()

        selection_match = re.search(r"ВЫБОР:(.*)", response_text, re.DOTALL | re.IGNORECASE)
        if selection_match:
            json_str = selection_match.group(1).strip()
            json_str = re.sub(r'^```json\n', '', json_str)
            json_str = re.sub(r'\n```$', '', json_str)
            selection_data = json.loads(json_str)
            selection = selection_data.get('chunk_ids', [])
        
        logger.info(f"Рассуждение модели: {reasoning}")
        logger.info(f"Выбранные чанки: {selection}")

    except Exception as e:
        logger.error(f"Ошибка парсинга ответа LLM-роутера: {e}\nОтвет модели: {response_text}")
        return {"selected_ids": [], "scratchpad": scratchpad}

    updated_scratchpad = scratchpad
    if reasoning:
        scratchpad_entry = f"ГЛУБИНА {depth} РАССУЖДЕНИЕ:\n{reasoning}"
        if updated_scratchpad:
            updated_scratchpad += "\n\n" + scratchpad_entry
        else:
            updated_scratchpad = scratchpad_entry

    return {"selected_ids": selection, "scratchpad": updated_scratchpad}

async def navigate_and_answer(question: str) -> str:
    """Основная логика RAG с иерархической навигацией."""
    logger.info(f"Получен вопрос для навигации: '{question}'")
    scratchpad = ""

    top_level_chunks = []
    for doc_name, text in DOCUMENT_STORE.items():
        doc_chunks = split_text_into_chunks(text, TOP_LEVEL_CHUNK_TARGET_SIZE)
        for i, chunk_text in enumerate(doc_chunks):
            top_level_chunks.append({"id": f"{doc_name}_{i}", "text": chunk_text})

    current_chunks = top_level_chunks

    for depth in range(MAX_DEPTH + 1):
        result = await route_chunks(question, current_chunks, scratchpad, depth)
        scratchpad = result["scratchpad"]
        selected_ids = result["selected_ids"]
        
        selected_chunks = [c for c in current_chunks if c['id'] in selected_ids]

        if not selected_chunks:
            logger.warning("Навигация завершена: на одном из уровней не было выбрано ни одного чанка.")
            break

        if depth == MAX_DEPTH:
            current_chunks = selected_chunks
            break

        next_level_chunks = []
        for chunk in selected_chunks:
            sub_chunks = split_text_into_chunks(chunk['text'], LOWER_LEVEL_CHUNK_TARGET_SIZE)
            for i, sub_chunk_text in enumerate(sub_chunks):
                next_level_chunks.append({"id": f"{chunk['id']}_{i}", "text": sub_chunk_text})
        current_chunks = next_level_chunks

    if not current_chunks:
        return "К сожалению, я не смог найти релевантную информацию в документации по вашему вопросу."

    logger.info(f"Синтез ответа на основе {len(current_chunks)} финальных чанков.")
    context = "\n\n---\n\n".join([c['text'] for c in current_chunks])

    system_message = "Ты — полезный ассистент-консультант. Ответь на вопрос пользователя, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном ниже контексте из документации. Не придумывай ничего от себя. Если ответ нельзя найти в контексте, так и скажи."
    user_message = f"КОНТЕКСТ:\n{context}\n\nВОПРОС: {question}"

    if not await gigachat_client.get_token(GIGACHAT_AUTH_TOKEN):
        raise Exception("Не удалось получить токен GigaChat для синтеза ответа.")

    final_response = await gigachat_client.get_chat_completion(system_message, user_message)
    final_answer = final_response.get('response', "Не удалось сгенерировать ответ.")
    # Возвращаем JSON-экранированную строку для безопасной вставки в другие JSON
    return json.dumps(final_answer)

# --- Обработчики HTTP и JSON-RPC ---

@app.on_event("startup")
def on_startup():
    logger.info("🚀 Сервер запускается... Загружаем документы.")
    docs_path = os.path.join(project_root, 'docs')
    for dirpath, _, filenames in os.walk(docs_path):
        for filename in filenames:
            if filename.endswith(".md"):
                file_path = os.path.join(dirpath, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        relative_path = os.path.relpath(file_path, docs_path)
                        DOCUMENT_STORE[relative_path] = f.read()
                        logger.info(f"✅ Документ '{relative_path}' успешно загружен.")
                except Exception as e:
                    logger.error(f"❌ Не удалось загрузить документ '{filename}': {e}")

@app.post("/")
async def json_rpc_handler(request: Request):
    body = await request.json()
    if "jsonrpc" not in body or body["jsonrpc"] != "2.0" or "method" not in body or "id" not in body:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request"}})

    request_id = body["id"]
    method = body["method"]
    params = body.get("params", {})
    logger.info(f"⚡️ Получен запрос: method='{method}', id={request_id}")

    try:
        if method == "tools/list":
            result = {"tools": TOOLS_LIST}
        elif method == "tools/call":
            result = await handle_tools_call(params)
        else:
            raise HTTPException(status_code=404, detail=f"Method '{method}' not found")
        return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": result})

    except Exception as e:
        logger.error(f"❌ Ошибка при выполнении метода '{method}': {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal Error", "data": str(e)}})

async def handle_tools_call(params: dict):
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    logger.info(f"🛠 Вызов инструмента '{tool_name}' с аргументами: {arguments}")

    if tool_name == "answer_question":
        query = arguments.get("query")
        if not query:
            raise ValueError("Для 'answer_question' требуется аргумент 'query'")
        answer_text = await navigate_and_answer(query)
        return {"content": [{"type": "text", "text": answer_text}], "isError": False}
    else:
        raise ValueError(f"Неизвестное имя инструмента: {tool_name}")

if __name__ == "__main__":
    print("🚀 Запуск RAG MCP Server на http://localhost:8002")
    # Используем python из виртуального окружения для запуска
    uvicorn.run(app, host="0.0.0.0", port=8002)