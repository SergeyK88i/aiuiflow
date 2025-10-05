import asyncio
import asyncpg
import logging
import os
import json
from typing import Dict, Any

# Эти модули мы создадим на следующих шагах
from .data_loaders import load_data_from_source
from .processing import process_text_to_chunks

# --- Настройка ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/dbname")
WORKER_SLEEP_INTERVAL = 10  # Секунд

async def process_job(job: Dict[str, Any], db_pool: asyncpg.Pool):
    """Основная логика обработки одной задачи."""
    job_id = job['id']
    logger.info(f"[Job {job_id}] Начинаю обработку задачи...")
    logs = [f"[{job_id}] Worker started processing."]

    try:
        # --- Шаг 1: Извлечение (Extract) ---
        logger.info(f"[Job {job_id}] Шаг 1: Загрузка данных из {job['source_url']}")
        raw_text = await load_data_from_source(job['source_type'], job['source_url'])
        logs.append(f"Successfully extracted {len(raw_text)} characters.")

        # --- Шаг 2: Трансформация (Transform) ---
        logger.info(f"[Job {job_id}] Шаг 2: Нарезка на чанки и получение эмбеддингов.")
        # В этой функции будет вся логика: нарезка, метаданные, эмбеддинги
        chunks_to_insert = await process_text_to_chunks(raw_text, str(job['source_url']))
        logs.append(f"Processed into {len(chunks_to_insert)} chunks.")

        # --- Шаг 3: Загрузка (Load) ---
        logger.info(f"[Job {job_id}] Шаг 3: Сохранение чанков в базу данных.")
        async with db_pool.acquire() as connection:
            # Удаляем старые чанки для этого документа, чтобы избежать дублей
            await connection.execute("DELETE FROM chunks WHERE doc_name = $1", str(job['source_url']))
            
            # Готовим данные для массовой вставки
            data_to_insert = [
                (c['id'], c['doc_name'], c['chunk_sequence_num'], c['header_1'], c['header_2'], c['chunk_text'], c['embedding'])
                for c in chunks_to_insert
            ]
            
            # Выполняем массовую вставку
            await connection.copy_records_to_table(
                'chunks',
                records=data_to_insert,
                columns=['id', 'doc_name', 'chunk_sequence_num', 'header_1', 'header_2', 'chunk_text', 'embedding']
            )
        logs.append(f"Successfully saved {len(chunks_to_insert)} chunks to the database.")
        
        # --- Финализация ---
        final_status = 'completed'
        logger.info(f"[Job {job_id}] ✅ Задача успешно завершена.")

    except Exception as e:
        logger.error(f"[Job {job_id}] ❌ Ошибка при выполнении задачи: {e}", exc_info=True)
        logs.append(f"ERROR: {e}")
        final_status = 'failed'
    
    # Обновляем статус и лог задачи в БД
    async with db_pool.acquire() as connection:
        await connection.execute(
            "UPDATE ingestion_jobs SET status = $1, logs = $2, finished_at = NOW() WHERE id = $3",
            final_status, '\n'.join(logs), job_id
        )

async def main_loop():
    """Бесконечный цикл воркера для поиска и обработки задач."""
    logger.info("🛠️ Воркер запущен. Ищу новые задачи...")
    db_pool = await asyncpg.create_pool(DATABASE_URL)

    while True:
        try:
            async with db_pool.acquire() as connection:
                # Ищем и сразу блокируем одну задачу, чтобы другие воркеры ее не взяли
                job = await connection.fetchrow(
                    """
                    SELECT id, source_url, source_type FROM ingestion_jobs
                    WHERE status = 'pending'
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                if job:
                    await connection.execute("UPDATE ingestion_jobs SET status = 'processing' WHERE id = $1", job['id'])
            
            if job:
                await process_job(job, db_pool)
            else:
                # Если задач нет, ждем
                await asyncio.sleep(WORKER_SLEEP_INTERVAL)

        except Exception as e:
            logger.error(f"Критическая ошибка в основном цикле воркера: {e}", exc_info=True)
            await asyncio.sleep(WORKER_SLEEP_INTERVAL) # Ждем перед повторной попыткой

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Воркер остановлен вручную.")
