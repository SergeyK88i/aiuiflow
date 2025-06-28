import asyncio
import aiohttp
import json

TELEGRAM_TOKEN = "7768666638:AAH-bOhEwfunRXFrIcE3TVT0xipdycXx7dM"
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
# LOCAL_WORKFLOW_URL = "http://localhost:8000/execute-workflow/sales_consultation"
LOCAL_WORKFLOW_URL = "http://localhost:8000/execute-workflow/fitness_sales_bot"


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
    """Обрабатывает сообщение через ваш workflow"""
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    user_name = message["from"].get("first_name", "User")
    print(f"📨 Получено сообщение: '{text}' от {user_name}")

    # --- НОВАЯ ЛОГИКА ---
    # Список ID нод, которые генерируют финальный ответ для пользователя.
    # Возьмите эти ID из вашего UI-редактора.
    HANDLER_NODE_IDS = [
        "handler_interest",
        "handler_question",
        "handler_objection",
        "handler_purchase"
    ]
    # --- КОНЕЦ НОВОЙ ЛОГИКИ ---

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        try:
            async with session.post(LOCAL_WORKFLOW_URL, json={
                "user_id": f"tg_{message['from']['id']}",
                "message": text,
                "chat_id": chat_id,
                "user_name": user_name
            }) as response:
                print(f"📡 Статус ответа от сервера: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    print(f"📦 Получен результат: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")

                    if result and "result" in result and result["result"]:
                        all_node_results = result["result"]
                        final_answer = None

                        # 1. Сначала ищем ответ в приоритетных нодах-обработчиках
                        for node_id in HANDLER_NODE_IDS:
                            if node_id in all_node_results:
                                node_result = all_node_results[node_id]
                                # Ищем текст ответа в output.text или в response
                                answer_text = node_result.get("output", {}).get("text") or node_result.get("response")
                                if answer_text and isinstance(answer_text, str):
                                    # Проверяем, что это не JSON
                                    if not answer_text.strip().startswith('{'):
                                        final_answer = answer_text
                                        print(f"✅ Найден финальный ответ в ноде '{node_id}': {final_answer[:100]}")
                                        break # Нашли ответ, выходим из цикла

                        if final_answer:
                            await send_message(chat_id, final_answer)
                        else:
                            print("⚠️ Не найден подходящий текстовый ответ в нодах-обработчиках.")
                            await send_message(chat_id, "Извините, не могу обработать ваш запрос.")
                    else:
                        print("❌ Результат пустой или неверной структуры")
                        await send_message(chat_id, "Произошла ошибка при обработке запроса")
                else:
                    error_text = await response.text()
                    print(f"❌ Ошибка от сервера: {error_text}")
                    await send_message(chat_id, "Сервис временно недоступен")
        except Exception as e:
            print(f"💥 Ошибка при обращении к workflow: {str(e)}")
            await send_message(chat_id, "Произошла техническая ошибка")


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
