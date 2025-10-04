import os
import json
import sys
from typing import List

# Попытка импортировать NLTK и скачать необходимые данные
try:
    import nltk
    from nltk.tokenize import sent_tokenize
    nltk.data.find('tokenizers/punkt')
except LookupError:
    print("NLTK 'punkt' модель не найдена. Скачиваем...")
    nltk.download('punkt')
    from nltk.tokenize import sent_tokenize

# Добавляем корень проекта в путь для импортов, если это необходимо
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

# --- Конфигурация ---
# Путь к директории с исходными документами
DOCS_DIR = os.path.join(project_root, 'docs')
# Имя файла, куда будут сохранены чанки
CHUNKS_OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'chunks_database.json')
# Целевой размер чанка в символах (должен совпадать с конфигом сервера)
CHUNK_TARGET_SIZE = 20000


def split_text_into_chunks(text: str, target_size: int) -> List[str]:
    """Делит текст на чанки, сохраняя целостность предложений."""
    sentences = sent_tokenize(text, language='russian') # Указываем язык для лучшей токенизации
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

def main():
    """
    Читает все markdown-документы, нарезает их на чанки и сохраняет
    в JSON-файл в виде словаря {chunk_id: chunk_text}.
    """
    print("🚀 Запуск индексатора...")
    if not os.path.exists(DOCS_DIR):
        print(f"❌ Директория с документами не найдена: {DOCS_DIR}")
        return

    chunks_database = {}
    
    for filename in os.listdir(DOCS_DIR):
        if filename.endswith(".md"):
            file_path = os.path.join(DOCS_DIR, filename)
            print(f"📄 Обработка документа: {filename}")
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                chunks = split_text_into_chunks(text, CHUNK_TARGET_SIZE)
                
                for i, chunk_text in enumerate(chunks):
                    chunk_id = f"{filename}_{i}"
                    chunks_database[chunk_id] = chunk_text
                
                print(f"   -> Создано {len(chunks)} чанков.")

            except Exception as e:
                print(f"   ❌ Ошибка при обработке файла {filename}: {e}")

    try:
        with open(CHUNKS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(chunks_database, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Индексация завершена. База данных чанков сохранена в {CHUNKS_OUTPUT_FILE}")
        print(f"   Всего создано {len(chunks_database)} чанков.")
    except Exception as e:
        print(f"\n❌ Ошибка при сохранении файла с чанками: {e}")


if __name__ == "__main__":
    main()
