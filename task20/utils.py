"""Утилиты для оптимизации."""

from typing import List, Dict, Set, Optional
import random

class TopicSelector:
    """Оптимизированный выбор тем."""
    
    def __init__(self, topics: List[Dict]):
        self.topics = topics
        self.topics_by_block = self._group_by_block(topics)
        self.topic_ids = {t['id'] for t in topics}
        self.topics_by_id = {t['id']: t for t in topics}
    
    def _group_by_block(self, topics: List[Dict]) -> Dict[str, List[Dict]]:
        """Группировка тем по блокам."""
        result = {}
        for topic in topics:
            block = topic.get('block', 'Другое')
            if block not in result:
                result[block] = []
            result[block].append(topic)
        return result
    
    def get_random_topic(self, exclude_ids: Set[int] = None) -> Optional[Dict]:
        """Получить случайную тему, исключая указанные ID."""
        if exclude_ids:
            available = [t for t in self.topics if t['id'] not in exclude_ids]
        else:
            available = self.topics
        
        return random.choice(available) if available else None
    
    def get_random_from_block(self, block: str, exclude_ids: Set[int] = None) -> Optional[Dict]:
        """Получить случайную тему из блока."""
        if block not in self.topics_by_block:
            return None
        
        topics = self.topics_by_block[block]
        if exclude_ids:
            available = [t for t in topics if t['id'] not in exclude_ids]
        else:
            available = topics
        
        return random.choice(available) if available else None
    
    def get_recommended_topics(self, user_results: List[Dict], limit: int = 3) -> List[Dict]:
        """Получить рекомендованные темы на основе истории."""
        # Анализируем слабые места
        low_score_blocks = {}
        for result in user_results:
            if result['score'] < 2:
                block = result.get('block', 'Другое')
                if block not in low_score_blocks:
                    low_score_blocks[block] = 0
                low_score_blocks[block] += 1
        
        # Сортируем блоки по количеству ошибок
        sorted_blocks = sorted(low_score_blocks.items(), key=lambda x: x[1], reverse=True)
        
        # Выбираем темы из проблемных блоков
        recommendations = []
        done_topics = {r['topic_id'] for r in user_results}
        
        for block, _ in sorted_blocks[:3]:  # Топ-3 проблемных блока
            topics = self.topics_by_block.get(block, [])
            for topic in topics:
                if topic['id'] not in done_topics:
                    recommendations.append(topic)
                    if len(recommendations) >= limit:
                        return recommendations
        
        # Если мало рекомендаций, добавляем случайные
        while len(recommendations) < limit:
            topic = self.get_random_topic(exclude_ids=done_topics)
            if topic:
                recommendations.append(topic)
                done_topics.add(topic['id'])
            else:
                break
        
        return recommendations