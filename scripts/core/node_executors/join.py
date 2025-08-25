import logging
import json
from datetime import datetime
from typing import Dict, Any

from scripts.models.schemas import Node

logger = logging.getLogger(__name__)

def _extract_text_from_data(data: Any) -> str:
    """Рекурсивно ищет наиболее подходящий текст в данных."""
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False, indent=2)

    if 'text' in data and isinstance(data['text'], str):
        return data['text']
    if 'output' in data and isinstance(data['output'], dict) and 'text' in data['output'] and isinstance(data['output']['text'], str):
        return data['output']['text']
    
    for value in data.values():
        if isinstance(value, dict):
            found_text = _extract_text_from_data(value)
            if found_text:
                return found_text
        elif isinstance(value, str):
            return value

    return json.dumps(data, ensure_ascii=False, indent=2)

async def execute_join(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], all_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполнение интеллектуальной Join/Merge ноды, которая находит общие данные,
    изолирует уникальные и формирует чистый результат.
    """
    config = node.data.get('config', {})
    merge_strategy = config.get('mergeStrategy', 'combine_text')
    separator = config.get('separator', '\n\n---\n\n').replace('\\n', '\n')
    
    logger.info(f"🔀 Выполнение интеллектуальной Join/Merge ноды: {node.id}")
    
    inputs = input_data.get('inputs', {})
    if not inputs:
        return {**input_data, "join_result": {"error": "No inputs to join"}, "success": False}
    
    if len(inputs) == 1:
        return list(inputs.values())[0]

    all_input_dicts = list(inputs.values())
    first_input = all_input_dicts[0]
    other_inputs = all_input_dicts[1:]
    
    common_data = {}
    for key, value in first_input.items():
        if all(key in other and other[key] == value for other in other_inputs):
            common_data[key] = value
    
    logger.info(f"🔍 Найдены общие данные: {list(common_data.keys())}")

    unique_data_per_source = {}
    for source_id, source_dict in inputs.items():
        unique_data = {k: v for k, v in source_dict.items() if k not in common_data}
        unique_data_per_source[source_id] = unique_data

    join_result = {}
    output_data = {}

    if merge_strategy == 'combine_text':
        texts = []
        for source_id, unique_data in unique_data_per_source.items():
            text = _extract_text_from_data(unique_data)
            texts.append(f"=== Источник {source_id} ===\n{text}")
        
        combined_text = separator.join(texts)
        output_data = {
            'text': combined_text,
            'source_count': len(inputs)
        }
        logger.info(f"✅ Объединено {len(texts)} текстов")

    elif merge_strategy == 'merge_json':
        output_data = {
            'json': unique_data_per_source,
            'text': json.dumps(unique_data_per_source, ensure_ascii=False, indent=2),
            'source_count': len(inputs)
        }
        logger.info(f"✅ Объединены данные в JSON от {len(inputs)} источников")

    else:
        raise Exception(f"Unknown merge strategy: {merge_strategy}")

    final_result = {
        **common_data,
        "join_result": {
            "sources": unique_data_per_source,
            "metadata": {
                "source_count": len(inputs),
                "source_ids": list(inputs.keys()),
                "merge_strategy": merge_strategy,
                "merge_time": datetime.now().isoformat()
            }
        },
        "output": output_data,
        "success": True
    }
    
    return final_result
