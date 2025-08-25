import logging
import time
from typing import Dict, Any

from scripts.models.schemas import Node

logger = logging.getLogger(__name__)

async def execute_if_else(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """Выполнение If/Else ноды"""
    start_time = time.time()
    config = node.data.get('config', {})
    condition_type = config.get('conditionType', 'equals')
    field_path = config.get('fieldPath', 'output.text')
    compare_value = config.get('compareValue', '')
    case_sensitive = config.get('caseSensitive', False)
    
    logger.info(f"🔀 Выполнение If/Else ноды: {node.id}")
    logger.info(f"📋 Условие: {field_path} {condition_type} {compare_value}")
    
    def get_value_by_path(data: Dict[str, Any], path: str) -> Any:
        keys = path.split('.')
        current = data
        
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
    
    # Сначала ищем идентификатор ноды в глобальных результатах
    node_id = label_to_id_map.get(field_path.split('.')[0])
    if node_id and node_id in all_results:
        data_source = all_results
        path_to_value = f"{node_id}.{'.'.join(field_path.split('.')[1:])}"
    else:
        data_source = input_data
        path_to_value = field_path

    actual_value = get_value_by_path(data_source, path_to_value)
    
    if actual_value is None and condition_type not in ['exists', 'is_empty']:
        logger.warning(f"⚠️ Поле {field_path} не найдено в данных")
        actual_value = ""
    
    if condition_type not in ['greater', 'greater_equal', 'less', 'less_equal']:
        actual_value_str = str(actual_value) if actual_value is not None else ""
        compare_value_str = str(compare_value)
        
        if not case_sensitive:
            actual_value_str = actual_value_str.lower()
            compare_value_str = compare_value_str.lower()
    else:
        try:
            actual_value_str = float(actual_value)
            compare_value_str = float(compare_value)
        except (ValueError, TypeError):
            actual_value_str = 0
            compare_value_str = 0
    
    result = False
    
    if condition_type == 'equals':
        result = actual_value_str == compare_value_str
    elif condition_type == 'not_equals':
        result = actual_value_str != compare_value_str
    elif condition_type == 'contains':
        result = compare_value_str in actual_value_str
    elif condition_type == 'not_contains':
        result = compare_value_str not in actual_value_str
    elif condition_type == 'greater':
        result = actual_value_str > compare_value_str
    elif condition_type == 'greater_equal':
        result = actual_value_str >= compare_value_str
    elif condition_type == 'less':
        result = actual_value_str < compare_value_str
    elif condition_type == 'less_equal':
        result = actual_value_str <= compare_value_str
    elif condition_type == 'regex':
        import re
        try:
            result = bool(re.search(compare_value, str(actual_value)))
        except re.error:
            result = False
    elif condition_type == 'exists':
        result = actual_value is not None
    elif condition_type == 'is_empty':
        result = actual_value is None or str(actual_value).strip() == ""
    elif condition_type == 'is_not_empty':
        result = actual_value is not None and str(actual_value).strip() != ""
    
    branch = 'true' if result else 'false'
    
    logger.info(f"📊 Результат проверки: {result} (ветка: {branch})")
    logger.info(f"📍 Фактическое значение: {actual_value}")
    logger.info(f"📍 Ожидаемое значение: {compare_value}")
    
    return {
        **input_data,
        'success': True,
        'branch': branch,
        'if_else_result': {
            'condition_met': result,
            'checked_value': str(actual_value),
            'condition': f"{field_path} {condition_type} {compare_value}",
            'node_id': node.id
        }
    }
