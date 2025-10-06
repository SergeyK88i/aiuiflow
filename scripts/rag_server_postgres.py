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
    system_message = (f"Из представленных фрагментов текста выбери не более {limit} самых релевантных для ответа на вопрос. "
                      "Верни ТОЛЬКО JSON-объект с ключом 'best_chunk_ids' и списком их ID. Пример: {\"best_chunk_ids\": [\"doc1_chunk2\", \"doc3_chunk5\"]}")

    context_for_reranking = ""
    for chunk in chunks:
        context_for_reranking += f"--- ЧАНК ID: {chunk['id']} ---\n{chunk['chunk_text']}\n\n"

    user_message = f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}\n\nСПИСОК ФРАГМЕНТОВ:\n{context_for_reranking}"

    response = await gigachat_client.get_chat_completion(system_message, user_message)
    response_text = response.get('response', '')
    logger.info(f"LLM Re-ranker RAW response: {response_text}")

    try:
        # Извлекаем JSON из ответа LLM
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not match:
            logger.error("Re-ranker error: No JSON object found in the LLM response.")
            return chunks[:limit]

        json_str = match.group(0)
        logger.info(f"Extracted JSON string for re-ranking: {json_str}")

        best_ids = json.loads(json_str).get('best_chunk_ids', [])
        logger.info(f"✅ LLM выбрал лучшие чанки: {best_ids}")
        
        if not best_ids:
            logger.warning("LLM re-ranker returned an empty list of chunk IDs.")

        # Возвращаем только те чанки, которые выбрал LLM, сохраняя исходный порядок
        selected_chunks = [chunk for chunk in chunks if chunk['id'] in best_ids]
        return selected_chunks[:limit] # Ограничиваем на случай, если LLM вернул больше

    except json.JSONDecodeError as e:
        logger.error(f"Re-ranker JSON parsing error: {e}. Returning top-{limit} initial candidates.")
        return chunks[:limit]
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

async def execute_db_shortcut_rag(question: str, source_chunk_ids: List[str]) -> str:
    """Выполняет RAG с 'расширением контекста' до полных глав."""
    logger.info(f"SHORTCUT: Запуск RAG с расширением контекста для {len(source_chunk_ids)} исходных чанков.")
    if not db_pool:
        raise Exception("Пул соединений с базой данных не инициализирован.")

    async with db_pool.acquire() as connection:
        # Шаг 1: Находим родительские главы для исходных чанков
        chapter_records = await connection.fetch(
            """SELECT DISTINCT header_1 FROM chunks WHERE id = ANY($1::TEXT[]) AND header_1 IS NOT NULL""",
            source_chunk_ids
        )
        parent_chapters = [record['header_1'] for record in chapter_records]

        context_texts = []
        if parent_chapters:
            logger.info(f"Найдены родительские главы: {parent_chapters}. Расширяем контекст...")
            # Шаг 2: Загружаем ВСЕ чанки из этих глав для полного контекста
            full_chapter_records = await connection.fetch(
                """SELECT chunk_text FROM chunks WHERE header_1 = ANY($1::TEXT[]) ORDER BY doc_name, chunk_sequence_num""",
                parent_chapters
            )
            context_texts = [record['chunk_text'] for record in full_chapter_records]
        else:
            # Fallback: если главы не найдены, используем старую логику (только исходные чанки)
            logger.warning("Родительские главы для кэшированных чанков не найдены. Используем только исходные чанки.")
            fallback_records = await connection.fetch(
                """SELECT chunk_text FROM chunks WHERE id = ANY($1::TEXT[])""",
                source_chunk_ids
            )
            context_texts = [record['chunk_text'] for record in fallback_records]

    if not context_texts:
        logger.error("Не удалось восстановить контекст из кэшированных ID. Запускаем полный RAG.")
        # Для execute_full_rag нужен query_vector, получим его снова
        query_vector = await gigachat_client.get_embedding(question)
        rag_result = await execute_full_rag(question, query_vector)
        return rag_result['answer']

    context = "\n\n---\n\n".join(context_texts)
    return await synthesize_answer(question, context)

async def execute_full_rag(question: str, query_vector: List[float]) -> Dict[str, Any]:
    """Выполняет полный гибридный RAG-пайплайн: Поиск -> Ранжирование -> Синтез."""
    # Шаг 1: Быстрый поиск (Retrieval)
    candidate_chunks = await find_relevant_chunks(query_vector, limit=2)
    if not candidate_chunks:
        return {"answer": "К сожалению, я не смог найти релевантную информацию в базе знаний.", "source_chunk_ids": []}

    # Шаг 2: Умная фильтрация (Re-ranking)
    final_chunks = await rerank_chunks(question, candidate_chunks, limit=2)

    # Шаг 3: Синтез ответа
    context = "\n\n---\n\n".join([c['chunk_text'] for c in final_chunks])
    final_answer = await synthesize_answer(question, context)
    final_chunk_ids = [c['id'] for c in final_chunks]
    
    return {"answer": final_answer, "source_chunk_ids": final_chunk_ids}


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

        # Шаг 2: Ищем в кэше вопросов
        async with db_pool.acquire() as connection:
            # Ищем самый похожий вопрос и сразу считаем схожесть
            cached_record = await connection.fetchrow(
                """SELECT final_answer, source_chunk_ids, (1 - (question_vector <=> $1)) AS similarity 
                   FROM question_cache ORDER BY similarity DESC LIMIT 1""",
                query_vector
            )

        # Шаг 3: Принимаем решение на основе кэша
        if cached_record and cached_record['similarity'] >= CACHE_SHORTCUT_THRESHOLD:
            if cached_record['similarity'] >= CACHE_HIT_THRESHOLD:
                logger.info(f"CACHE HIT: Сходство ({cached_record['similarity']:.2f}) очень высокое. Отдаем готовый ответ.")
                final_answer = cached_record['final_answer']
            else:
                logger.info(f"SHORTCUT: Сходство ({cached_record['similarity']:.2f}) среднее. Используем готовые чанки из БД.")
                final_answer = await execute_db_shortcut_rag(query, cached_record['source_chunk_ids'])
        else:
            logger.info("CACHE MISS: Похожих вопросов в кэше не найдено, запускаем полный RAG-цикл.")
            rag_result = await execute_full_rag(query, query_vector)
            final_answer = rag_result['answer']

            # Сохраняем новый результат в кэш, если он не является "отказом"
            not_found_message = "К сожалению, я не смог найти релевантную информацию"
            if not_found_message not in final_answer:
                async with db_pool.acquire() as connection:
                    await connection.execute(
                        """INSERT INTO question_cache (question_text, question_vector, final_answer, source_chunk_ids)
                           VALUES ($1, $2, $3, $4)""",
                        query, query_vector, final_answer, rag_result['source_chunk_ids']
                    )
                logger.info("✅ Новый успешный ответ добавлен в кэш вопросов-ответов.")

        return {"content": [{"type": "text", "text": json.dumps(final_answer)}], "isError": False}
    else:
        raise ValueError(f"Неизвестное имя инструмента: {tool_name}")

if __name__ == "__main__":
    print("🚀 Запуск Pre-indexed RAG MCP Server на http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)
