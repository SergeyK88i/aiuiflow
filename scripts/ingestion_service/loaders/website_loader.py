# Содержит логику для скачивания и парсинга веб-сайтов
import aiohttp
from markdownify import markdownify as md

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
                
                # Конвертируем HTML в Markdown, сохраняя структуру
                # heading_style='ATX' делает заголовки в виде #, ## и т.д.
                markdown_text = md(html, heading_style='ATX')
                return markdown_text
        except aiohttp.ClientError as e:
            raise ConnectionError(f"Ошибка при скачивании сайта по URL {start_url}: {e}")