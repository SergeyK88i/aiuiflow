# Содержит логику для скачивания и парсинга PDF-файлов
import requests
from io import BytesIO
from pypdf import PdfReader

async def download_and_parse_pdf(url: str, **kwargs) -> str:
    # pypdf - синхронная библиотека. В идеале, этот блокирующий код 
    # нужно выполнять в отдельном потоке через asyncio.to_thread,
    # чтобы не "замораживать" асинхронный воркер.
    # Для простоты оставляем как есть, но держим это в уме для продакшена.
    
    try:
        response = requests.get(url, timeout=60) # Добавляем таймаут
        response.raise_for_status()
        
        pdf_bytes = BytesIO(response.content)
        pdf_reader = PdfReader(pdf_bytes)
        
        full_text = ""
        for page in pdf_reader.pages:
            full_text += page.extract_text() + "\n"
        return full_text
    except requests.RequestException as e:
        raise ConnectionError(f"Ошибка при скачивании PDF по URL {url}: {e}")

