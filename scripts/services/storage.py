import asyncpg
import json
import logging
import os
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Глобальный пул соединений
db_pool = None

async def init_db_pool():
    """Инициализирует пул соединений с PostgreSQL."""
    global db_pool
    if db_pool:
        return

    try:
        db_url = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/dbname")
        db_pool = await asyncpg.create_pool(db_url)
        logger.info("✅ Пул соединений с PostgreSQL для сервиса workflows инициализирован.")
    except Exception as e:
        logger.error(f"❌ Не удалось инициализировать пул соединений с PostgreSQL: {e}")
        db_pool = None

async def close_db_pool():
    """Закрывает пул соединений."""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("🛑 Пул соединений с PostgreSQL для сервиса workflows закрыт.")

async def get_all_workflows() -> List[Dict[str, Any]]:
    """Получает список всех workflows (только id и name)."""
    if not db_pool:
        raise Exception("Пул соединений с БД не инициализирован.")
    
    async with db_pool.acquire() as conn:
        records = await conn.fetch("SELECT id, name, status, updated_at FROM workflow_service.workflows ORDER BY updated_at DESC")
        return [dict(record) for record in records]

async def get_workflow_by_id(workflow_id: str) -> Dict[str, Any] | None:
    """Получает данные конкретного workflow по его ID."""
    if not db_pool:
        raise Exception("Пул соединений с БД не инициализирован.")

    async with db_pool.acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM workflow_service.workflows WHERE id = $1", workflow_id)
        return dict(record) if record else None

async def add_workflow(workflow_id: str, workflow_data: Dict[str, Any]):
    """Добавляет или обновляет workflow в базе данных."""
    if not db_pool:
        raise Exception("Пул соединений с БД не инициализирован.")

    name = workflow_data.get('name')
    # Преобразуем словари в JSON-строки для записи в тип JSONB
    nodes = json.dumps(workflow_data.get('nodes'))
    connections = json.dumps(workflow_data.get('connections'))
    status = workflow_data.get('status', 'draft')

    async with db_pool.acquire() as conn:
        # Используем INSERT ... ON CONFLICT для создания или обновления записи (UPSERT)
        await conn.execute("""
            INSERT INTO workflow_service.workflows (id, name, nodes, connections, status, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                nodes = EXCLUDED.nodes,
                connections = EXCLUDED.connections,
                status = EXCLUDED.status,
                updated_at = NOW();
        """, workflow_id, name, nodes, connections, status)
    logger.info(f"💾 Workflow '{workflow_id}' сохранен в базу данных.")


async def delete_workflow_by_id(workflow_id: str):
    """Удаляет workflow из базы данных."""
    if not db_pool:
        raise Exception("Пул соединений с БД не инициализирован.")

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM workflow_service.workflows WHERE id = $1", workflow_id)
    logger.info(f"🗑️ Workflow '{workflow_id}' удален из базы данных.")