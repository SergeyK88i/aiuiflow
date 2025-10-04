import requests
import json
import time

# URL-адрес вашего RAG-сервера
SERVER_URL = "http://localhost:8002"

# Список вопросов для бенчмарка
QUESTIONS = [
    "Как получить токен доступа для GigaChat API?",
    "Какие модели доступны в GigaChat API?",
    "Как я могу загрузить файл с помощью GigaChat API?",
    "Что делает эндпоинт /chat/completions?",
    "Существует ли способ проверить, был ли текст написан искусственным интеллектом?",
    "Как подсчитать количество токенов в тексте?",
    "Как удалить файл из хранилища?",
]

def call_rpc(method: str, params: dict) -> dict:
    """Отправляет JSON-RPC запрос на сервер."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    headers = {'Content-Type': 'application/json'}
    response = requests.post(SERVER_URL, data=json.dumps(payload), headers=headers)
    response.raise_for_status()
    return response.json()

def run_benchmark():
    """Запускает бенчмарк, отправляя вопросы на сервер."""
    print("🚀 Запуск бенчмарка для RAG сервера...")
    print("-" * 50)

    total_time = 0
    questions_to_run = len(QUESTIONS)
    successful_requests = 0

    for i, question in enumerate(QUESTIONS):
        print(f"❓ Вопрос {i+1}/{len(QUESTIONS)}: {question}")
        
        start_time = time.time()
        
        try:
            params = {
                "name": "answer_question",
                "arguments": {
                    "query": question
                }
            }
            response_json = call_rpc("tools/call", params)
            
            end_time = time.time()
            duration = end_time - start_time
            total_time += duration

            if "result" in response_json and response_json["result"].get("content"):
                successful_requests += 1
                # Ответ от сервера приходит как JSON-экранированная строка
                try:
                    answer_str = response_json["result"]["content"][0]["text"]
                    # Убираем экранирование
                    answer = json.loads(answer_str)
                    print(f"✅ Ответ: {answer}")
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    print(f"⚠️ Не удалось разобрать ответ от сервера: {e}")
                    print(f"   Получен ответ: {response_json['result']}")

            elif "error" in response_json:
                print(f"❌ Ошибка: {response_json['error']['message']}")
                if 'data' in response_json['error']:
                    print(f"   Детали: {response_json['error']['data']}")

            print(f"⏱️ Время выполнения: {duration:.2f} сек.")

        except requests.exceptions.RequestException as e:
            print(f"❌ Не удалось подключиться к серверу: {e}")
            print("   Убедитесь, что 'scripts/rag_server.py' запущен.")
            questions_to_run = i
            break # Прерываем бенчмарк, если сервер недоступен
        
        print("-" * 50)

    print("🏁 Бенчмарк завершен.")
    if questions_to_run > 0:
        print(f"⏱️ Общее время выполнения: {total_time:.2f} сек.")
        avg_time = total_time / questions_to_run
        print(f"⏱️ Среднее время на вопрос: {avg_time:.2f} сек.")
        print(f"📈 Успешных запросов: {successful_requests}/{questions_to_run}")


if __name__ == "__main__":
    run_benchmark()
