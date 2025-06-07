import requests
import uuid
import json
import os
import sys

class GigaChatAPI:
    def __init__(self):
        self.access_token = None
        self.conversation_history = []
        
    def get_token(self, auth_token, scope='GIGACHAT_API_PERS'):
        rq_uid = str(uuid.uuid4())
        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': rq_uid,
            'Authorization': f'Basic {auth_token}'
        }
        payload = {
            'scope': scope
        }

        try:
            response = requests.post(url, headers=headers, data=payload, verify=False)
            if response.status_code == 200:
                self.access_token = response.json()['access_token']
                print(f"✅ Токен получен успешно")
                return True
            else:
                print(f"❌ Ошибка получения токена: {response.status_code}")
                return False
        except requests.RequestException as e:
            print(f"❌ Ошибка: {str(e)}")
            return False

    def get_chat_completion(self, system_message, user_message):
        if not self.access_token:
            print("❌ Ошибка: Токен доступа не получен. Сначала вызовите метод get_token().")
            return None

        # Формируем сообщения с учетом истории
        messages = [
            {"role": "system", "content": system_message}
        ]
        
        # Добавляем историю предыдущих сообщений
        messages.extend(self.conversation_history)

        # Добавляем текущий вопрос
        messages.append({"role": "user", "content": user_message})

        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        payload = json.dumps({
            "model": "GigaChat",
            "messages": messages,
            "temperature": 1,
            "top_p": 0.1,
            "n": 1,
            "stream": False,
            "max_tokens": 512,
            "repetition_penalty": 1,
            "update_interval": 0
        })
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=payload, verify=False)
            if response.status_code == 200:
                # Сохраняем вопрос и ответ в историю
                self.conversation_history.append({"role": "user", "content": user_message})
                assistant_response = response.json()['choices'][0]['message']['content']
                self.conversation_history.append({"role": "assistant", "content": assistant_response})
                
                print(f"✅ Ответ получен от GigaChat")
                print(f"📝 Вопрос: {user_message}")
                print(f"🤖 Ответ: {assistant_response}")
                
                return {
                    "success": True,
                    "response": assistant_response,
                    "user_message": user_message,
                    "system_message": system_message,
                    "conversation_length": len(self.conversation_history)
                }
            else:
                print(f"❌ Ошибка API: {response.status_code}")
                return {
                    "success": False,
                    "error": f"API Error: {response.status_code}",
                    "response": None
                }
        except requests.RequestException as e:
            print(f"❌ Произошла ошибка: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": None
            }
    
    def clear_history(self):
        """Очистка истории диалога"""
        self.conversation_history = []
        print("🗑️ История диалога очищена")

# Функция для выполнения из workflow
def execute_gigachat_node(auth_token, system_message, user_message, clear_history=False):
    """
    Выполняет запрос к GigaChat API
    """
    print(f"🚀 Запуск GigaChat ноды...")
    print(f"📋 System: {system_message}")
    print(f"💬 User: {user_message}")
    
    # Создаем экземпляр API
    api = GigaChatAPI()
    
    # Очищаем историю если нужно
    if clear_history:
        api.clear_history()
    
    # Получаем токен
    if not api.get_token(auth_token):
        return {
            "success": False,
            "error": "Не удалось получить токен доступа",
            "response": None
        }
    
    # Выполняем запрос
    result = api.get_chat_completion(system_message, user_message)
    return result

# Пример использования
if __name__ == "__main__":
    # Тестовые данные
    test_token = 'ZmU1MTI4YWYtMzc0My00ZmU1LThhNzEtMmUyZGI0ZjQzMDlhOmJjZDE1MzAzLTdmNzUtNGY4MC04MWYzLTZiODU4NmRhYmQwMg=='
    test_system = "Ты полезный ассистент, который отвечает кратко и по делу."
    test_user = "Привет! Как дела?"
    
    result = execute_gigachat_node(test_token, test_system, test_user)
    print(f"\n🎯 Результат: {json.dumps(result, ensure_ascii=False, indent=2)}")
