import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import os
import re
import json
from typing import List, Dict, Any
import sys
from contextlib import asynccontextmanager

try:
    import nltk
    from nltk.tokenize import sent_tokenize
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
except ImportError:
    print("NLTK не найден. Пожалуйста, установите его в ваше окружение: pip install nltk")
    sys.exit(1)


try:
    import numpy as np
except ImportError:
    print("NumPy не найден. Пожалуйста, установите его в ваше окружение: pip install numpy")
    sys.exit(1)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Импортируем основной, а не 'copy' файл, предполагая, что мы их слили
from scripts.services.giga_chat_copy import GigaChatAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Конфигурация ---
GIGACHAT_AUTH_TOKEN = "ZmU1MTI4YWYtMzc0My00ZmU1LThhNzEtMmUyZGI0ZjQzMDlhOmQ1OWQzZmI1LTcwOWItNDEyNS04MGU1LTUwNzFlOTQ3ODk5Zg=="
MAX_DEPTH = 2
TOP_LEVEL_CHUNK_TARGET_SIZE = 20000
LOWER_LEVEL_CHUNK_TARGET_SIZE = 5000
CACHE_HIT_THRESHOLD = 0.99
CACHE_SHORTCUT_THRESHOLD = 0.92

# Файлы с данными
KNOWLEDGE_BASE_FILE = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
CHUNKS_DATABASE_FILE = os.path.join(os.path.dirname(__file__), "chunks_database.json")

import asyncpg
from pgvector.asyncpg import register_vector

# --- Глобальные переменные ---
db_pool = None
gigachat_client = GigaChatAPI()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 RAG-сервер (PostgreSQL) запускается...")
    global db_pool
    
    # 1. Подключение к базе данных
    try:
        DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/dbname")
        db_pool = await asyncpg.create_pool(DATABASE_URL, init=register_vector)
        # Проверка соединения
        async with db_pool.acquire() as connection:
            await connection.fetchval("SELECT 1")
        logger.info("✅ Соединение с PostgreSQL (pgvector) установлено.")
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось подключиться к PostgreSQL: {e}")
        db_pool = None # Убедимся, что пул не используется, если он невалиден
    
    # 2. Проверка токена GigaChat
    if not await gigachat_client.get_token(GIGACHAT_AUTH_TOKEN):
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить токен GigaChat при запуске.")
    
    logger.info("✨ Startup complete.")
    yield
    
    # 3. Закрытие пула соединений при остановке
    if db_pool:
        await db_pool.close()
        logger.info("🛑 Соединение с PostgreSQL закрыто.")


app = FastAPI(title="Pre-indexed RAG MCP Server", version="2.0.0", lifespan=lifespan)


TOOLS_LIST = [
    {
        "name": "answer_question",
        "description": "Принимает вопрос пользователя, находит релевантную информацию в документации и генерирует осмысленный ответ.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Вопрос пользователя"}
            },
            "required": ["query"]
        }
    }
]

# --- Вспомогательные функции ---
async def synthesize_answer(question: str, context: str) -> str:
    """Генерирует финальный ответ на основе контекста."""
    logger.info(f"Синтез ответа на основе {len(context)} символов контекста.")
    system_message = "Ты — полезный ассистент-консультант. Ответь на вопрос пользователя, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном ниже контексте из документации. Не придумывай ничего от себя. Если ответ нельзя найти в контексте, так и скажи."
    user_message = f"КОНТЕКСТ:\n{context}\n\nВОПРОС: {question}"
    final_response = await gigachat_client.get_chat_completion(system_message, user_message)
    return final_response.get('response', "Не удалось сгенерировать ответ.")

async def find_relevant_chunks(query_vector: List[float], limit: int = 25) -> List[Dict[str, Any]]:
    """Этап 1: Быстрый поиск. Находит N самых похожих чанков в PostgreSQL."""
    if not db_pool:
        raise Exception("Пул соединений с базой данных не инициализирован.")

    logger.info(f"🔍 Выполняю векторный поиск {limit} ближайших чанков в PostgreSQL...")
    async with db_pool.acquire() as connection:
        # Используем оператор <-> из pgvector для поиска по косинусному расстоянию
        records = await connection.fetch(
            """SELECT id, chunk_text, doc_name FROM chunks ORDER BY embedding <-> $1 LIMIT $2""",
            query_vector, limit
        )
    logger.info(f"✅ Найдено {len(records)} чанков-кандидатов.")
    return [dict(record) for record in records]

async def rerank_chunks(question: str, chunks: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Этап 2: Умная фильтрация. Использует LLM для выбора лучших чанков из кандидатов."""
    logger.info(f"🧠 Выполняю re-ranking для {len(chunks)} чанков с помощью LLM...")
    system_message = ("Ты — эксперт-аналитик. Твоя задача — из списка фрагментов текста выбрать несколько самых важных, которые нужны для ответа на вопрос пользователя. "
                      f"Ты должен вернуть JSON-объект с ключом 'best_chunk_ids', содержащим список ID ровно из {limit} лучших фрагментов.")

    context_for_reranking = ""
    for chunk in chunks:
        context_for_reranking += f"--- ЧАНК ID: {chunk['id']} ---\n{chunk['chunk_text']}\n\n"

    user_message = f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}\n\nСПИСОК ФРАГМЕНТОВ:\n{context_for_reranking}"

    response = await gigachat_client.get_chat_completion(system_message, user_message)
    response_text = response.get('response', '')

    try:
        # Извлекаем JSON из ответа LLM
        json_str = re.search(r"\{.*\}", response_text, re.DOTALL).group(0)
        best_ids = json.loads(json_str).get('best_chunk_ids', [])
        logger.info(f"✅ LLM выбрал лучшие чанки: {best_ids}")
        
        # Возвращаем только те чанки, которые выбрал LLM, сохраняя исходный порядок
        selected_chunks = [chunk for chunk in chunks if chunk['id'] in best_ids]
        return selected_chunks[:limit] # Ограничиваем на случай, если LLM вернул больше

    except Exception as e:
        logger.error(f"Ошибка re-ranking: не удалось извлечь ID из ответа LLM: {e}. Возвращаем топ-{limit} изначальных кандидатов.")
        # В случае ошибки просто возвращаем первые N чанков из изначального поиска
        return chunks[:limit]

@app.post("/")
async def json_rpc_handler(request: Request):
    body = await request.json()
    if "jsonrpc" not in body or body["jsonrpc"] != "2.0" or "method" not in body or "id" not in body:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request"}})
    request_id = body["id"]
    method = body["method"]
    params = body.get("params", {})
    try:
        if method == "tools/list": result = {"tools": TOOLS_LIST}
        elif method == "tools/call": result = await handle_tools_call(params)
        else: raise HTTPException(status_code=404, detail=f"Method '{body.get('method')}' not found")
        return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": result})
    except Exception as e:
        logger.error(f"❌ Ошибка при выполнении метода '{method}': {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal Error", "data": str(e)}})

async def handle_tools_call(params: dict):
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    if tool_name == "answer_question":
        query = arguments.get("query")
        if not query: raise ValueError("Для 'answer_question' требуется аргумент 'query'")
        if not gigachat_client.access_token or not db_pool:
             raise Exception("Сервер не готов к работе: токен GigaChat или подключение к БД отсутствуют.")

        # Шаг 1: Получаем вектор для вопроса
        query_vector = await gigachat_client.get_embedding(query)
        if not query_vector: raise Exception("Не удалось получить эмбеддинг для запроса.")

        # Шаг 2: Быстрый поиск (Retrieval)
        candidate_chunks = await find_relevant_chunks(query_vector, limit=25)
        if not candidate_chunks:
            return {"content": [{"type": "text", "text": json.dumps("К сожалению, я не смог найти релевантную информацию в базе знаний.")}], "isError": False}

        # Шаг 3: Умная фильтрация (Re-ranking)
        final_chunks = await rerank_chunks(query, candidate_chunks, limit=5)

        # Шаг 4: Синтез ответа
        context = "\n\n---\n\n".join([c['chunk_text'] for c in final_chunks])
        final_answer = await synthesize_answer(query, context)
        
        # На этом этапе мы не реализуем сохранение в кэш, просто возвращаем ответ
        return {"content": [{"type": "text", "text": json.dumps(final_answer)}], "isError": False}
    else:
        raise ValueError(f"Неизвестное имя инструмента: {tool_name}")

if __name__ == "__main__":
    print("🚀 Запуск Pre-indexed RAG MCP Server на http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)
