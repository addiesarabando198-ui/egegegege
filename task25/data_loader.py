"""Загрузчик данных для задания 25."""

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def load_data_sync() -> Optional[Dict[str, Any]]:
    """Синхронная загрузка данных из JSON файла."""
    data_file = os.path.join(os.path.dirname(__file__), "task25_topics.json")

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        topics = []
        if isinstance(data, list):
            # Если это список тем
            topics = data
        elif isinstance(data, dict) and "topics" in data:
            topics = data["topics"]
        else:
            logger.error("Unexpected data format in task25_topics.json")
            return {"topics": [], "topics_by_block": {}}

        # Создаем структуру topics_by_block для группировки по блокам
        topics_by_block = {}
        for topic in topics:
            block_name = topic.get("block", "Без блока")
            if block_name not in topics_by_block:
                topics_by_block[block_name] = []
            topics_by_block[block_name].append(topic)

        logger.info(f"Loaded {len(topics)} topics in {len(topics_by_block)} blocks")

        return {
            "topics": topics,
            "topics_by_block": topics_by_block
        }
    except FileNotFoundError:
        logger.error(f"Data file not found: {data_file}")
        return {"topics": [], "topics_by_block": {}}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return {"topics": [], "topics_by_block": {}}
    except Exception as e:
        logger.error(f"Failed to load topics data: {e}")
        return {"topics": [], "topics_by_block": {}}


def get_data() -> Dict[str, Any]:
    """Получить данные для задания 25.

    Returns:
        Словарь с ключом 'topics', содержащий список тем.
    """
    return load_data_sync()
