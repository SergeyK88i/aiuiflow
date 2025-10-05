# Этот файл будет содержать логику для нарезки текста и получения эмбеддингов
import uuid
from typing import List, Dict, Any

# Предполагаем, что эти функции и классы доступны в окружении
# В реальном проекте их нужно импортировать из правильных модулей
from scripts.services.giga_chat import GigaChatAPI
from nltk.tokenize import sent_tokenize

# --- Конфигурация (должна быть согласована с другими частями системы) ---
CHUNK_TARGET_SIZE = 20000

# Инициализируем GigaChat API клиент один раз
# В реальном приложении токен должен управляться централизованно
gigachat_client = GigaChatAPI()


def split_text_into_chunks(text: str, target_size: int) -> List[str]:
    """Делит текст на чанки, сохраняя целостность предложений."""
    sentences = sent_tokenize(text, language='russian')
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > target_size and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk += " " + sentence
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

async def process_text_to_chunks(raw_text: str, doc_name: str) -> List[Dict[str, Any]]:
    """Полный пайплайн обработки текста: нарезка, метаданные, эмбеддинги."""
    
    # Убедимся, что у нас есть токен для получения эмбеддингов
    # В реальной системе токен не должен передаваться так, это для примера
    if not gigachat_client.access_token:
        from scripts.rag_server_copy import GIGACHAT_AUTH_TOKEN # Плохая практика, но для примера
        await gigachat_client.get_token(GIGACHAT_AUTH_TOKEN)

    text_chunks = split_text_into_chunks(raw_text, CHUNK_TARGET_SIZE)
    
    processed_chunks = []
    for i, chunk_text in enumerate(text_chunks):
        chunk_id = f"{doc_name}_{i}"
        
        # Получаем эмбеддинг для чанка
        embedding = await gigachat_client.get_embedding(chunk_text)
        if not embedding:
            print(f"Warning: Could not get embedding for chunk {chunk_id}. Skipping.")
            continue

        # Здесь можно добавить логику извлечения метаданных (заголовков)
        processed_chunks.append({
            "id": chunk_id,
            "doc_name": doc_name,
            "chunk_sequence_num": i,
            "header_1": None, # Заглушка
            "header_2": None, # Заглушка
            "chunk_text": chunk_text,
            "embedding": embedding
        })
        
    return processed_chunks
