# Этот файл будет содержать логику для нарезки текста и получения эмбеддингов
import uuid
import os
from typing import List, Dict, Any
import logging

# Предполагаем, что эти функции и классы доступны в окружении
# В реальном проекте их нужно импортировать из правильных модулей
from scripts.services.giga_chat_copy import GigaChatAPI
from nltk.tokenize import sent_tokenize

logger = logging.getLogger(__name__)

# --- Конфигурация (должна быть согласована с другими частями системы) ---
CHUNK_TARGET_SIZE = 500

# Инициализируем GigaChat API клиент один раз
# В реальном приложении токен должен управляться централизованно
gigachat_client = GigaChatAPI()


def split_text_into_chunks(text: str, target_size: int) -> List[Dict[str, Any]]:
    """Делит текст на чанки, извлекая заголовки и сохраняя целостность предложений."""
    lines = text.split('\n')
    chunks = []
    current_chunk_text = ""
    current_h1 = None
    current_h2 = None

    def finalize_chunk_if_needed():
        nonlocal current_chunk_text
        if current_chunk_text:
            chunks.append({
                "text": current_chunk_text.strip(),
                "header_1": current_h1,
                "header_2": current_h2
            })
            current_chunk_text = ""

    for line in lines:
        stripped_line = line.strip()

        if stripped_line.startswith('# '):
            finalize_chunk_if_needed()
            current_h1 = stripped_line[2:].strip()
            current_h2 = None
            continue
        
        if stripped_line.startswith('## '):
            finalize_chunk_if_needed()
            current_h2 = stripped_line[3:].strip()
            continue

        if not stripped_line:
            continue
        
        sentences = sent_tokenize(stripped_line, language='russian')
        for sentence in sentences:
            if not current_chunk_text:
                current_chunk_text = sentence
                continue

            if len(current_chunk_text) + len(sentence) + 1 > target_size:
                finalize_chunk_if_needed()
                current_chunk_text = sentence
            else:
                current_chunk_text += " " + sentence
    
    finalize_chunk_if_needed()
        
    return chunks

async def process_text_to_chunks(raw_text: str, doc_name: str) -> List[Dict[str, Any]]:
    """Полный пайплайн обработки текста: нарезка, метаданные, эмбеддинги."""
    
    if not gigachat_client.access_token:
        auth_token = os.getenv("GIGACHAT_AUTH_TOKEN")
        if not auth_token:
            raise ValueError("Переменная окружения GIGACHAT_AUTH_TOKEN не установлена!")
        await gigachat_client.get_token(auth_token)

    structured_chunks = split_text_into_chunks(raw_text, CHUNK_TARGET_SIZE)
    
    processed_chunks = []
    for i, chunk_data in enumerate(structured_chunks):
        chunk_id = f"{doc_name}_{i}"
        chunk_text = chunk_data["text"]

        if not chunk_text:
            continue

        embedding = await gigachat_client.get_embedding(chunk_text)
        if not embedding:
            print(f"Warning: Could not get embedding for chunk {chunk_id}. Skipping.")
            continue

        processed_chunks.append({
            "id": chunk_id,
            "doc_name": doc_name,
            "chunk_sequence_num": i,
            "header_1": chunk_data["header_1"],
            "header_2": chunk_data["header_2"],
            "chunk_text": chunk_text,
            "embedding": embedding
        })
        
    return processed_chunks
