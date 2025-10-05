# Содержит логику для скачивания и парсинга веб-сайтов
import aiohttp
from bs4 import BeautifulSoup

async def crawl_website(start_url: str, **kwargs) -> str:
    # ВАЖНО: Это базовая реализация, которая скачивает только одну страницу.
    # Для полноценного рекурсивного обхода ее нужно будет усложнить.
    async with aiohttp.ClientSession() as session:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            async with session.get(start_url, ssl=False, timeout=30, headers=headers) as response:
                response.raise_for_status()
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Удаляем ненужные теги (скрипты, стили)
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                
                # Извлекаем текст. В идеале, здесь нужно находить основной <main> или <article> тег
                return soup.get_text(separator='\n', strip=True)
        except aiohttp.ClientError as e:
            raise ConnectionError(f"Ошибка при скачивании сайта по URL {start_url}: {e}")
