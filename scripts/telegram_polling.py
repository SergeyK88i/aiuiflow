import asyncio
import aiohttp
import json

import os
import sys

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения TELEGRAM_TOKEN не установлена!")
    sys.exit(1)

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
# START_NODE_ID = "node-1750962779368"
# LOCAL_WORKFLOW_URL = f"http://localhost:8000/execute-workflow/sales_consultation?startNodeId={START_NODE_ID}"
# LOCAL_WORKFLOW_URL = "http://localhost:8000/execute-workflow/sales_consultation"
# LOCAL_WORKFLOW_URL = "http://localhost:8000/execute-workflow/fitness_sales_bot"


# LOCAL_WORKFLOW_URL = "http://localhost:8000/api/v1/webhooks/6341d166-703a-4d7d-8c5e-05136e5c6556"
LOCAL_WORKFLOW_URL = "http://localhost:8000/api/v1/webhooks/a1b2c3d4-e5f6-7890-1234-567890abcdef"

async def get_updates(offset=0):
    """Получает новые сообщения от Telegram"""
    url = f"{API_URL}/getUpdates?offset={offset}&timeout=30"
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.get(url) as response:
            return await response.json()

async def send_message(chat_id, text):
    """Отправляет сообщение в Telegram"""
    url = f"{API_URL}/sendMessage"
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        await session.post(url, json={
            "chat_id": chat_id,
            "text": text
        })

async def process_message(message):
    """Обрабатывает сообщение, просто запуская workflow."""
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    user_name = message["from"].get("first_name", "User")
    print(f"📨 Получено сообщение: '{text}' от {user_name}. Запускаю воркфлоу...")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        try:
            # Просто запускаем воркфлоу и не ждем ответа для обработки.
            # Устанавливаем короткий таймаут, чтобы не блокировать поллер надолго.
            timeout = aiohttp.ClientTimeout(total=5)
            async with session.post(LOCAL_WORKFLOW_URL, json={
                "user_id": f"tg_{message['from']['id']}",
                "message": text,
                "chat_id": chat_id,
                "user_name": user_name
            }, timeout=timeout) as response:
                # Просто логируем статус, но ничего не отправляем в ответ.
                if response.status >= 200 and response.status < 300:
                    print(f"✅ Воркфлоу успешно запущен (статус {response.status}).")
                else:
                    error_text = await response.text()
                    print(f"⚠️ Воркфлоу вернул неожиданный статус {response.status}: {error_text}")
        except Exception as e:
            # Логируем ошибку, но не отправляем сообщение пользователю.
            print(f"💥 Ошибка при запуске воркфлоу: {str(e)}")


async def main():
    print("🤖 Бот запущен в режиме polling")
    offset = 0
    
    while True:
        try:
            # Получаем обновления
            updates = await get_updates(offset)
            
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                
                # Обрабатываем только текстовые сообщения
                if "message" in update and "text" in update["message"]:
                    await process_message(update["message"])
                    
        except Exception as e:
            print(f"Ошибка: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
