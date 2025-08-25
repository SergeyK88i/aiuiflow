import requests
import uuid
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class GigaChatAPI:
    def __init__(self):
        self.access_token = None
        self.conversation_history = []
        
    async def get_token(self, auth_token: str, scope: str = 'GIGACHAT_API_PERS') -> bool:
        """Получение токена доступа"""
        rq_uid = str(uuid.uuid4())
        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

        if auth_token and auth_token.lower().startswith('basic '):
            logger.warning("⚠️ Обнаружен префикс 'Basic ' в токене. Удаляю его автоматически.")
            auth_token = auth_token[6:]

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': rq_uid,
            'Authorization': f'Basic {auth_token}'
        }
        payload = {'scope': scope}

        try:
            logger.info(f"🔑 Попытка получить токен. URL: {url}")
            response = requests.post(url, headers=headers, data=payload, verify=False)
            if response.status_code == 200:
                self.access_token = response.json()['access_token']
                logger.info("✅ GigaChat токен получен успешно")
                return True
            else:
                logger.error(f"❌ Ошибка получения токена: {response.status_code}")
                try:
                    error_details = response.json()
                    logger.error(f"🔍 Детали ошибки от GigaChat: {error_details}")
                except json.JSONDecodeError:
                    logger.error(f"🔍 Ответ от GigaChat (не JSON): {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка при получении токена: {str(e)}")
            return False

    async def get_chat_completion(self, system_message: str, user_message: str) -> Dict[str, Any]:
        """Получение ответа от GigaChat"""
        if not self.access_token:
            raise Exception("Токен доступа не получен")

        messages = [{"role": "system", "content": system_message}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_message})

        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        payload = {
            "model": "GigaChat-Max",
            "messages": messages,
            "temperature": 1,
            "top_p": 0.1,
            "n": 1,
            "stream": False,
            "max_tokens": 512,
            "repetition_penalty": 1,
            "update_interval": 0
        }
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False)
            if response.status_code == 200:
                self.conversation_history.append({"role": "user", "content": user_message})
                assistant_response = response.json()['choices'][0]['message']['content']
                self.conversation_history.append({"role": "assistant", "content": assistant_response})
                
                logger.info(f"✅ Получен ответ от GigaChat")
                return {
                    "success": True,
                    "response": assistant_response,
                    "user_message": user_message,
                    "system_message": system_message,
                    "conversation_length": len(self.conversation_history)
                }
            else:
                logger.error(f"❌ Ошибка API GigaChat: {response.status_code}")
                return {
                    "success": False,
                    "error": f"API Error: {response.status_code}",
                    "response": None
                }
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе к GigaChat: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": None
            }

    def clear_history(self):
        """Очистка истории диалога"""
        self.conversation_history = []
        logger.info("🗑️ История диалога очищена")
