"""
Этот файл делает папку 'loaders' Python-модулем 
и предоставляет единую функцию-диспетчер для вызова нужного загрузчика.
"""
from .website_loader import crawl_website
from .pdf_loader import download_and_parse_pdf
from .local_file_loader import read_local_file

async def load_data_from_source(source_type: str, url: str, **kwargs) -> str:
    """
    Главная функция-диспетчер.
    Выбирает и вызывает нужный загрузчик в зависимости от типа источника.
    """
    if source_type == 'website':
        # kwargs могут содержать, например, 'depth' для рекурсивного обхода
        return await crawl_website(url, **kwargs)
    elif source_type == 'pdf':
        return await download_and_parse_pdf(url, **kwargs)
    elif source_type == 'local_file':
        return await read_local_file(url, **kwargs)
    # Когда вы захотите добавить YouTube, вы просто добавите здесь elif source_type == 'youtube'
    else:
        raise ValueError(f"Неподдерживаемый тип источника: {source_type}")
