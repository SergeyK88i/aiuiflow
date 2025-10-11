from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from starlette.background import BackgroundTasks

from scripts.api.v1 import workflows, execution, timers, webhooks, dispatcher_callback
from scripts.services.storage import init_db_pool, close_db_pool

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

# Подключаем роутеры
app.include_router(workflows.router, prefix="/api/v1", tags=["Workflows"])
app.include_router(execution.router, prefix="/api/v1", tags=["Execution"])
app.include_router(timers.router, prefix="/api/v1", tags=["Timers"])
app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"])
app.include_router(dispatcher_callback.router, prefix="/api/v1", tags=["Dispatcher"])

@app.on_event("startup")
async def on_startup():
    """Действия при старте приложения."""
    logger.info("🚀 Приложение запускается...")
    await init_db_pool()

@app.on_event("shutdown")
async def on_shutdown():
    """Действия при остановке приложения."""
    logger.info("🛑 Приложение останавливается...")
    await close_db_pool()

@app.get("/")
async def root():
    return {"message": "N8N Clone API Server", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
