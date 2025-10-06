import time
import logging
import os
import requests
import json
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Конфигурация ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Определяем путь к папке /docs относительно текущего скрипта
WATCH_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docs'))
INGESTION_API_URL = "http://localhost:8005/" # URL нашего ingestion_service
# --- Конец Конфигурации ---

def call_ingestion_service(file_path: str):
    """Вызывает API сервиса загрузки для индексации файла."""
    if not os.path.exists(file_path):
        logging.warning(f"Файл {file_path} был удален до того, как мы успели его обработать.")
        return

    logging.info(f"🚀 Обнаружен файл для индексации: {file_path}")
    
    # Преобразуем путь в file:// URL
    file_uri = Path(file_path).as_uri()

    payload = {
        "jsonrpc": "2.0",
        "id": f"watch-{os.path.basename(file_path)}",
        "method": "tools/call",
        "params": {
            "name": "start_ingestion_job",
            "arguments": {
                "source_type": "local_file",
                "source_url": file_uri
            }
        }
    }

    try:
        response = requests.post(INGESTION_API_URL, json=payload, timeout=10)
        if response.status_code == 200:
            logging.info(f"✅ Задача на индексацию файла {os.path.basename(file_path)} успешно создана. Ответ: {response.json()}")
        else:
            logging.error(f"❌ Ошибка при создании задачи на индексацию. Статус: {response.status_code}, Ответ: {response.text}")
    except requests.RequestException as e:
        logging.error(f"💥 Не удалось подключиться к ingestion_service по адресу {INGESTION_API_URL}. Ошибка: {e}")
        logging.error("   Убедитесь, что ingestion_service запущен.")

class MarkdownHandler(FileSystemEventHandler):
    """Обработчик, который реагирует только на изменения в .md файлах."""
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            call_ingestion_service(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            call_ingestion_service(event.src_path)

if __name__ == "__main__":
    if not os.path.exists(WATCH_PATH):
        logging.error(f"❌ Директория для наблюдения не найдена: {WATCH_PATH}")
        exit()
        
    logging.info(f"👀 Запуск наблюдателя за папкой: {WATCH_PATH}")
    event_handler = MarkdownHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_PATH, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    logging.info("🛑 Наблюдатель остановлен.")
