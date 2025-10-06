# Содержит логику для чтения локальных текстовых файлов
from urllib.parse import urlparse
from pathlib import Path

async def read_local_file(url: str, **kwargs) -> str:
    """Читает текстовый файл с локального диска по пути, указанному в URL."""
    try:
        parsed_url = urlparse(url)
        # Для Windows и Unix-подобных систем, urlparse.path может начинаться с /
        # pathlib.Path корректно обработает это.
        file_path = Path(parsed_url.path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Файл не найден по пути: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise ConnectionError(f"Ошибка при чтении локального файла {url}: {e}")
