import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import os
import re
import json
from typing import List, Dict, Any
import sys

# Попытка импортировать numpy. Если его нет, это вызовет ошибку при запуске.
# Пользователю нужно будет его установить в свое виртуальное окружение.
try:
    import numpy as np
except ImportError:
    print("NumPy не найден. Пожалуйста, установите его в ваше окружение: pip install numpy")
    sys.exit(1)

# Добавляем корень проекта в путь для импортов
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Решение проблемы с SSL для NLTK
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
    sys.exit(1)

from scripts.services.giga_chat import GigaChatAPI

# --- Конфигурация ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GIGACHAT_AUTH_TOKEN = "ZmU1MTI4YWYtMzc0My00ZmU1LThhNzEtMmUyZGI0ZjQzMDlhOmQ1OWQzZmI1LTcwOWItNDEyNS04MGU1LTUwNzFlOTQ3ODk5Zg=="
MAX_DEPTH = 2
TOP_LEVEL_CHUNK_TARGET_SIZE = 20000
LOWER_LEVEL_CHUNK_TARGET_SIZE = 5000

CACHE_HIT_THRESHOLD = 0.99
CACHE_SHORTCUT_THRESHOLD = 0.92

KNOWLEDGE_BASE_FILE = "knowledge_base.json"

app = FastAPI(title="Advanced RAG MCP Server", version="1.0.0")

# --- Глобальные переменные ---
DOCUMENT_STORE: Dict[str, str] = {}
KNOWLEDGE_BASE: List[Dict[str, Any]] = []
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

# --- Вспомогательные функции ---
def cosine_similarity(v1, v2):
    vec1 = np.array(v1)
    vec2 = np.array(v2)
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

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

# --- Основная логика RAG ---

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
    """Генерирует финальный ответ на основе контекста."""
    logger.info(f"Синтез ответа на основе {len(context)} символов контекста.")
    system_message = "Ты — полезный ассистент-консультант. Ответь на вопрос пользователя, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном ниже контексте из документации. Не придумывай ничего от себя. Если ответ нельзя найти в контексте, так и скажи."
    user_message = f"КОНТЕКСТ:\n{context}\n\nВОПРОС: {question}"
    final_response = await gigachat_client.get_chat_completion(system_message, user_message)
    return final_response.get('response', "Не удалось сгенерировать ответ.")

async def execute_full_rag(question: str) -> Dict[str, Any]:
    logger.info(f"Запуск полного RAG-цикла для вопроса: '{question}'")
    scratchpad = ""
    top_level_chunks = []
    for doc_name, text in DOCUMENT_STORE.items():
        for i, chunk_text in enumerate(split_text_into_chunks(text, TOP_LEVEL_CHUNK_TARGET_SIZE)):
            top_level_chunks.append({"id": f"{doc_name}_{i}", "text": chunk_text})
    
    current_chunks = top_level_chunks
    for depth in range(MAX_DEPTH + 1):
        result = await route_chunks(question, current_chunks, scratchpad, depth)
        scratchpad, selected_ids = result["scratchpad"], result["selected_ids"]
        selected_chunks = [c for c in current_chunks if c['id'] in selected_ids]
        if not selected_chunks:
            logger.warning("Навигация завершена: на одном из уровней не было выбрано ни одного чанка.")
            current_chunks = [] # Явно обнуляем, чтобы вернуть пустой ответ
            break
        current_chunks = selected_chunks
        if depth == MAX_DEPTH:
            break
        next_level_chunks = []
        for chunk in current_chunks:
            for i, sub_chunk_text in enumerate(split_text_into_chunks(chunk['text'], LOWER_LEVEL_CHUNK_TARGET_SIZE)):
                next_level_chunks.append({"id": f"{chunk['id']}_{i}", "text": sub_chunk_text})
        current_chunks = next_level_chunks

    if not current_chunks:
        return {"answer": "К сожалению, я не смог найти релевантную информацию в документации по вашему вопросу.", "source_chunk_ids": []}

    final_context = "\n\n---\n\n".join([c['text'] for c in current_chunks])
    final_answer = await synthesize_answer(question, final_context)
    final_chunk_ids = [c['id'] for c in current_chunks]
    return {"answer": final_answer, "source_chunk_ids": final_chunk_ids}

async def execute_shortcut_rag(question: str, source_chunk_ids: List[str]) -> str:
    logger.info(f"Запуск ускоренного RAG с использованием {len(source_chunk_ids)} готовых чанков.")
    # Эта функция должна будет находить текст чанков по их ID. В нашей простой модели это сложно.
    # Поэтому мы симулируем, просто генерируя новый ответ на основе всего документа.
    # В реальной системе с БД здесь был бы поиск по ID.
    context = "\n\n---\n\n".join(DOCUMENT_STORE.values())
    return await synthesize_answer(question, context)

# --- Обработчики HTTP и JSON-RPC ---

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Сервер запускается...")
    # 1. Загрузка документов
    docs_path = os.path.join(project_root, 'docs')
    if os.path.exists(docs_path):
        for filename in os.listdir(docs_path):
            if filename.endswith(".md"):
                file_path = os.path.join(docs_path, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    DOCUMENT_STORE[filename] = f.read()
                    logger.info(f"✅ Документ '{filename}' успешно загружен.")
    # 2. Загрузка базы знаний
    if os.path.exists(KNOWLEDGE_BASE_FILE):
        with open(KNOWLEDGE_BASE_FILE, 'r', encoding='utf-8') as f:
            global KNOWLEDGE_BASE
            KNOWLEDGE_BASE = json.load(f)
            logger.info(f"✅ База знаний '{KNOWLEDGE_BASE_FILE}' успешно загружена ({len(KNOWLEDGE_BASE)} записей).")
    # 3. Проверка токена GigaChat
    if not await gigachat_client.get_token(GIGACHAT_AUTH_TOKEN):
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить токен GigaChat при запуске. Сервер может работать некорректно.")

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
        else: raise HTTPException(status_code=404, detail=f"Method '{method}' not found")
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
             raise Exception("Токен GigaChat не был получен при запуске, не могу обработать запрос.")

        query_vector = await gigachat_client.get_embedding(query)
        if not query_vector: raise Exception("Не удалось получить эмбеддинг для запроса.")

        # Ищем в кэше
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
                logger.info(f"CACHE HIT: Сходство ({highest_similarity:.2f}) очень высокое с вопросом '{best_match['question']}'. Отдаем готовый ответ.")
                final_answer = best_match['answer']
            else:
                logger.info(f"SHORTCUT: Сходство ({highest_similarity:.2f}) среднее с вопросом '{best_match['question']}'. Используем готовые чанки.")
                final_answer = await execute_shortcut_rag(query, best_match['source_chunk_ids'])
        else:
            logger.info("CACHE MISS: Похожих вопросов не найдено, запускаем полный RAG-цикл.")
            rag_result = await execute_full_rag(query)
            final_answer = rag_result['answer']

            # ПРОВЕРКА: Не кэшируем отрицательные ответы
            not_found_message = "К сожалению, я не смог найти релевантную информацию"
            if not_found_message in final_answer:
                logger.warning("Ответ не найден. Результат не будет добавлен в кэш.")
            else:
                KNOWLEDGE_BASE.append({
                    "question": query,
                    "vector": query_vector,
                    "answer": final_answer,
                    "source_chunk_ids": rag_result['source_chunk_ids']
                })
                save_knowledge_base()
                logger.info("Новый успешный ответ добавлен в базу знаний.")
        
        # Возвращаем JSON-экранированную строку для совместимости
        return {"content": [{"type": "text", "text": json.dumps(final_answer)}], "isError": False}
    else:
        raise ValueError(f"Неизвестное имя инструмента: {tool_name}")

if __name__ == "__main__":
    print("🚀 Запуск Advanced RAG MCP Server на http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)("CACHE MISS: Похожих вопросов не найдено, запускаем полный RAG-цикл.")
            rag_result = await execute_full_rag(query)
            final_answer = rag_result['answer']

            # ПРОВЕРКА: Не кэшируем отрицательные ответы
            not_found_message = "К сожалению, я не смог найти релевантную информацию"
            if not_found_message in final_answer:
                logger.warning("Ответ не найден. Результат не будет добавлен в кэш.")
            else:
                KNOWLEDGE_BASE.append({
                    "question": query,
                    "vector": query_vector,
                    "answer": final_answer,
                    "source_chunk_ids": rag_result['source_chunk_ids']
                })
                save_knowledge_base()
                logger.info("Новый успешный ответ добавлен в базу знаний.")
        
        # Возвращаем JSON-экранированную строку для совместимости
        return {"content": [{"type": "text", "text": json.dumps(final_answer)}], "isError": False}
    else:
        raise ValueError(f"Неизвестное имя инструмента: {tool_name}")

if __name__ == "__main__":
    print("🚀 Запуск Advanced RAG MCP Server на http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)