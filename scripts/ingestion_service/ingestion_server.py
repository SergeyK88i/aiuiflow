import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import os
import json
import asyncpg
from typing import List, Dict, Any
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uuid

# --- Настройка ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Подключение к БД (лучше вынести в переменные окружения)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/dbname")

# --- Глобальные переменные ---
db_pool = None

# --- Модели данных Pydantic ---
class JobCreateRequest(BaseModel):
    source_type: str
    source_url: str
    extra_params: Dict[str, Any] = {}

class JobStatusResponse(BaseModel):
    id: int
    source_url: str
    source_type: str
    status: str
    logs: str | None = None
    created_at: str
    finished_at: str | None = None

# --- Управление жизненным циклом приложения (подключение к БД) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Сервер загрузки запускается...")
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("✅ Соединение с PostgreSQL установлено.")
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось подключиться к PostgreSQL: {e}")
        # В реальном приложении здесь можно было бы завершить работу
        db_pool = None
    
    yield
    
    if db_pool:
        await db_pool.close()
        logger.info("🛑 Соединение с PostgreSQL закрыто.")

app = FastAPI(title="Ingestion MCP Server", version="1.0.0", lifespan=lifespan)

# --- Описание "умений" сервера (для MCP) ---
TOOLS_LIST = [
    {
        "name": "start_ingestion_job",
        "description": "Запускает фоновую задачу по загрузке и индексации документа из источника (URL сайта, PDF и т.д.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_type": {"type": "string", "description": "Тип источника, например 'website' или 'pdf'"},
                "source_url": {"type": "string", "description": "URL источника для загрузки"},
                "extra_params": {"type": "object", "description": "Дополнительные параметры, например {'depth': 2} для сайта"}
            },
            "required": ["source_type", "source_url"]
        }
    },
    {
        "name": "get_job_status",
        "description": "Проверяет статус ранее запущенной задачи по ее ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer"}},
            "required": ["job_id"]
        }
    }
]

# --- Основной обработчик JSON-RPC --- 
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

# --- Логика вызова инструментов ---
async def handle_tools_call(params: dict) -> dict:
    if not db_pool:
        raise Exception("Нет соединения с базой данных. Сервер не готов к работе.")

    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if tool_name == "start_ingestion_job":
        req = JobCreateRequest(**arguments)
        async with db_pool.acquire() as connection:
            job_id = await connection.fetchval(
                "INSERT INTO ingestion_jobs (source_url, source_type, status) VALUES ($1, $2, 'pending') RETURNING id",
                req.source_url, req.source_type
            )
        logger.info(f"✅ Создана новая задача на индексацию с ID: {job_id}")
        return {"content": [{"type": "json", "json": {"job_id": job_id, "status": "pending"}}], "isError": False}
    
    elif tool_name == "get_job_status":
        job_id = arguments.get("job_id")
        if not job_id:
            raise ValueError("job_id is required for get_job_status")
        
        async with db_pool.acquire() as connection:
            job_record = await connection.fetchrow("SELECT * FROM ingestion_jobs WHERE id = $1", job_id)
        
        if not job_record:
            raise HTTPException(status_code=404, detail=f"Job with ID {job_id} not found")

        status_response = JobStatusResponse(
            id=job_record['id'],
            source_url=job_record['source_url'],
            source_type=job_record['source_type'],
            status=job_record['status'],
            logs=job_record['logs'],
            created_at=str(job_record['created_at']),
            finished_at=str(job_record['finished_at']) if job_record['finished_at'] else None
        )
        return {"content": [{"type": "json", "json": status_response.dict()}], "isError": False}

    else:
        raise ValueError(f"Unknown tool name: {tool_name}")

# --- Запуск сервера ---
if __name__ == "__main__":
    print("🚀 Запуск Ingestion MCP Server на http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
