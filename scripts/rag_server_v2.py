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

# --- Глобальные переменные (загружаются при старте) ---
CHUNKS_DB: Dict[str, str] = {}
KNOWLEDGE_BASE: List[Dict[str, Any]] = []
gigachat_client = GigaChatAPI()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Сервер запускается...")
    global CHUNKS_DB, KNOWLEDGE_BASE
    
    # 1. Загрузка базы данных чанков
    if os.path.exists(CHUNKS_DATABASE_FILE):
        with open(CHUNKS_DATABASE_FILE, 'r', encoding='utf-8') as f:
            CHUNKS_DB = json.load(f)
        logger.info(f"✅ База данных чанков '{CHUNKS_DATABASE_FILE}' успешно загружена ({len(CHUNKS_DB)} чанков).")
    else:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: Файл с базой чанков не найден: {CHUNKS_DATABASE_FILE}")
        logger.error("Пожалуйста, запустите сначала scripts/indexer.py для создания базы чанков.")
    
    # 2. Загрузка базы знаний (кэша вопросов)
    if os.path.exists(KNOWLEDGE_BASE_FILE):
        with open(KNOWLEDGE_BASE_FILE, 'r', encoding='utf-8') as f:
            KNOWLEDGE_BASE = json.load(f)
        logger.info(f"✅ База знаний '{KNOWLEDGE_BASE_FILE}' успешно загружена ({len(KNOWLEDGE_BASE)} записей).")
    
    # 3. Проверка токена GigaChat
    if not await gigachat_client.get_token(GIGACHAT_AUTH_TOKEN):
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить токен GigaChat при запуске.")
    
    logger.info("✨ Startup complete.")
    yield
    # Код для выполнения при остановке сервера (если нужно)
    logger.info("🛑 Сервер останавливается...")


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
def cosine_similarity(v1, v2):
    vec1 = np.array(v1)
    vec2 = np.array(v2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return np.dot(vec1, vec2) / (norm1 * norm2)

def save_knowledge_base():
    with open(KNOWLEDGE_BASE_FILE, 'w', encoding='utf-8') as f:
        json.dump(KNOWLEDGE_BASE, f, ensure_ascii=False, indent=2)

def split_text_into_chunks(text: str, target_size: int) -> List[str]:
    sentences = sent_tokenize(text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > target_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            current_chunk = sentence if not current_chunk else current_chunk + " " + sentence
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

async def route_chunks(question: str, chunks: List[Dict[str, Any]], scratchpad: str, depth: int) -> Dict[str, Any]:
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
    
    response = await gigachat_client.get_chat_completion(system_message, user_message)
    response_text = response.get('response', '')

    reasoning, selection = "", []
    try:
        reasoning_match = re.search(r"РАССУЖДЕНИЕ:(.*?)(ВЫБОР:|$)", response_text, re.DOTALL | re.IGNORECASE)
        if reasoning_match: reasoning = reasoning_match.group(1).strip()
        selection_match = re.search(r"ВЫБОР:(.*)", response_text, re.DOTALL | re.IGNORECASE)
        if selection_match:
            json_str = re.sub(r'^```json\n?|\n?```$', '', selection_match.group(1).strip())
            selection = json.loads(json_str).get('chunk_ids', [])
        logger.info(f"Рассуждение модели: {reasoning}")
        logger.info(f"Выбранные чанки: {selection}")
    except Exception as e:
        logger.error(f"Ошибка парсинга ответа LLM-роутера: {e}\nОтвет модели: {response_text}")
        return {"selected_ids": [], "scratchpad": scratchpad}

    updated_scratchpad = f"{scratchpad}\n\nГЛУБИНА {depth} РАССУЖДЕНИЕ:\n{reasoning}".strip()
    return {"selected_ids": selection, "scratchpad": updated_scratchpad}

async def synthesize_answer(question: str, context: str) -> str:
    logger.info(f"Синтез ответа на основе {len(context)} символов контекста.")
    system_message = "Ты — полезный ассистент-консультант. Ответь на вопрос пользователя, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном ниже контексте из документации. Не придумывай ничего от себя. Если ответ нельзя найти в контексте, так и скажи."
    user_message = f"КОНТЕКСТ:\n{context}\n\nВОПРОС: {question}"
    final_response = await gigachat_client.get_chat_completion(system_message, user_message)
    return final_response.get('response', "Не удалось сгенерировать ответ.")

async def execute_shortcut_rag(question: str, source_chunk_ids: List[str]) -> str:
    logger.info(f"Запуск ускоренного RAG с использованием {len(source_chunk_ids)} кэшированных чанков.")
    context_texts = []
    for chunk_id in source_chunk_ids:
        text = CHUNKS_DB.get(chunk_id)
        if text:
            context_texts.append(text)
        else:
            logger.warning(f"Не удалось найти текст для кэшированного ID чанка: {chunk_id}")

    if not context_texts:
        logger.error("Не удалось восстановить контекст из кэшированных ID. Запускаем полный RAG.")
        rag_result = await execute_full_rag(question)
        return rag_result['answer']

    context = "\n\n---\n\n".join(context_texts)
    return await synthesize_answer(question, context)

async def execute_full_rag(question: str) -> Dict[str, Any]:
    logger.info(f"Запуск полного иерархического RAG-цикла для вопроса: '{question}'")
    scratchpad = ""
    top_level_chunks = [{'id': chunk_id, 'text': chunk_text} for chunk_id, chunk_text in CHUNKS_DB.items()]
    current_chunks = top_level_chunks
    for depth in range(MAX_DEPTH + 1):
        result = await route_chunks(question, current_chunks, scratchpad, depth)
        scratchpad, selected_ids = result["scratchpad"], result["selected_ids"]
        selected_chunks = [c for c in current_chunks if c['id'] in selected_ids]
        if not selected_chunks:
            logger.warning(f"Навигация завершена на глубине {depth}: LLM-роутер не выбрал ни одного чанка.")
            current_chunks = []
            break
        current_chunks = selected_chunks
        if depth == MAX_DEPTH:
            break
        next_level_chunks = []
        for chunk in current_chunks:
            sub_chunks = split_text_into_chunks(chunk['text'], LOWER_LEVEL_CHUNK_TARGET_SIZE)
            for i, sub_chunk_text in enumerate(sub_chunks):
                next_level_chunks.append({"id": f"{chunk['id']}_{i}", "text": sub_chunk_text})
        if not next_level_chunks:
            logger.warning(f"Не удалось создать под-чанки на глубине {depth}. Используем текущие чанки.")
            break
        current_chunks = next_level_chunks
    if not current_chunks:
        return {"answer": "К сожалению, я не смог найти релевантную информацию в документации по вашему вопросу.", "source_chunk_ids": []}
    final_context = "\n\n---\n\n".join([c['text'] for c in current_chunks])
    final_answer = await synthesize_answer(question, final_context)
    final_chunk_ids = [c['id'] for c in current_chunks]
    return {"answer": final_answer, "source_chunk_ids": final_chunk_ids}

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
        if not gigachat_client.access_token:
             raise Exception("Токен GigaChat не был получен. Сервер не готов к работе.")
        query_vector = await gigachat_client.get_embedding(query)
        if not query_vector: raise Exception("Не удалось получить эмбеддинг для запроса.")
        best_match = None
        highest_similarity = -1.0
        for entry in KNOWLEDGE_BASE:
            similarity = cosine_similarity(query_vector, entry['vector'])
            if similarity > highest_similarity:
                highest_similarity = similarity
                best_match = entry
        final_answer = ""
        if best_match and highest_similarity >= CACHE_SHORTCUT_THRESHOLD:
            if highest_similarity >= CACHE_HIT_THRESHOLD:
                logger.info(f"CACHE HIT: Сходство ({highest_similarity:.2f}). Отдаем готовый ответ.")
                final_answer = best_match['answer']
            else:
                logger.info(f"SHORTCUT: Сходство ({highest_similarity:.2f}). Используем готовые чанки.")
                final_answer = await execute_shortcut_rag(query, best_match['source_chunk_ids'])
        else:
            logger.info("CACHE MISS: Похожих вопросов не найдено, запускаем полный RAG-цикл.")
            rag_result = await execute_full_rag(query)
            final_answer = rag_result['answer']
            not_found_message = "К сожалению, я не смог найти релевантную информацию"
            if not_found_message not in final_answer:
                KNOWLEDGE_BASE.append({
                    "question": query,
                    "vector": query_vector,
                    "answer": final_answer,
                    "source_chunk_ids": rag_result['source_chunk_ids']
                })
                save_knowledge_base()
                logger.info("Новый успешный ответ добавлен в базу знаний.")
        return {"content": [{"type": "text", "text": json.dumps(final_answer)}], "isError": False}
    else:
        raise ValueError(f"Неизвестное имя инструмента: {tool_name}")

if __name__ == "__main__":
    print("🚀 Запуск Pre-indexed RAG MCP Server на http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)