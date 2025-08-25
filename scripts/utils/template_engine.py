import re
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def replace_templates(template_str: str, input_data: Dict[str, Any], label_to_id_map: Dict[str, str], all_results: Dict[str, Any]) -> str:
    """Универсальная замена шаблонов вида {{Node Label.path.to.value}} или {{node-id.path.to.value}}"""
    
    def get_nested_value(obj: Dict[str, Any], path: str) -> Any:
        """Получает значение по пути типа 'output.text' или 'json.result[0].text'"""
        if not path:
            return obj
            
        keys = [key for key in re.split(r'[.\[\]]', path) if key]
        
        current = obj
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            elif isinstance(current, list) and key.isdigit():
                index = int(key)
                if 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                return None
        return current

    pattern = r"\{\{\s*(.+?)\s*\}\}"

    def replacer(match):
        path = match.group(1).strip()

        # 1. Определяем источник данных
        parts = path.split('.', 1)
        node_identifier = parts[0]
        remaining_path = parts[1] if len(parts) > 1 else ''

        data_source = None
        
        # Особый случай для {{input.field}}
        if node_identifier == 'input':
            data_source = input_data
            path_in_source = remaining_path
        else:
            # Ищем по лейблу или ID
            node_id = label_to_id_map.get(node_identifier, node_identifier)
            
            if node_id in all_results:
                data_source = all_results[node_id]
                path_in_source = remaining_path
            else:
                logger.warning(f"⚠️ Шаблон: нода с лейблом или ID '{node_identifier}' (resolved to '{node_id}') не найдена в результатах.")
                return f"{{{{ERROR: Node '{node_identifier}' not found}}}}"

        # 2. Извлекаем значение
        value = get_nested_value(data_source, path_in_source)

        # 3. Преобразуем в строку и возвращаем
        if value is None:
            logger.warning(f"⚠️ Шаблон: путь '{path}' не найден. Замена на пустую строку.")
            return ""
        
        if isinstance(value, (dict, list)):
            final_str = json.dumps(value, ensure_ascii=False)
        else:
            final_str = str(value)

        logger.info(f"🔄 Замена шаблона: {{{{{match.group(1)}}}}} -> {final_str[:200]}...")
        return final_str

    return re.sub(pattern, replacer, template_str)
