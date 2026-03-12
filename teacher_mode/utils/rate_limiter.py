"""
Простой rate limiter для защиты критичных операций от злоупотреблений.

Использует in-memory хранилище (подходит для single-process приложений).
Для multi-process деплоя можно заменить на Redis.
"""

import time
import logging
from typing import Dict, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Простой in-memory rate limiter с sliding window.

    Для каждого ключа (например, user_id) отслеживает количество запросов
    в заданном временном окне.
    """

    def __init__(self):
        # user_key -> [(timestamp1, timestamp2, ...)]
        self._requests: Dict[str, list] = defaultdict(list)
        self._cleanup_interval = 60  # Очистка старых записей каждые 60 секунд
        self._last_cleanup = time.time()

    def check_rate_limit(
        self,
        user_key: str,
        max_requests: int,
        window_seconds: int
    ) -> Tuple[bool, Optional[int]]:
        """
        Проверяет, не превышен ли лимит запросов для пользователя.

        Args:
            user_key: Уникальный ключ пользователя (обычно user_id)
            max_requests: Максимальное количество запросов
            window_seconds: Временное окно в секундах

        Returns:
            Tuple[bool, Optional[int]]: (разрешено, секунд до разблокировки)
            - (True, None): запрос разрешен
            - (False, N): запрос заблокирован, повторить через N секунд

        Examples:
            >>> limiter = RateLimiter()
            >>> allowed, retry_after = limiter.check_rate_limit("user_123", max_requests=5, window_seconds=60)
            >>> if not allowed:
            >>>     print(f"Слишком много запросов. Повторите через {retry_after} секунд")
        """
        current_time = time.time()

        # Периодическая очистка старых записей
        if current_time - self._last_cleanup > self._cleanup_interval:
            self._cleanup_old_entries()
            self._last_cleanup = current_time

        # Получаем историю запросов пользователя
        user_requests = self._requests[user_key]

        # Удаляем запросы вне временного окна
        cutoff_time = current_time - window_seconds
        user_requests[:] = [req_time for req_time in user_requests if req_time > cutoff_time]

        # Проверяем лимит
        if len(user_requests) >= max_requests:
            # Лимит превышен - вычисляем время до разблокировки
            oldest_request = user_requests[0]
            retry_after = int(oldest_request + window_seconds - current_time) + 1

            logger.warning(
                f"Rate limit exceeded for {user_key}: "
                f"{len(user_requests)}/{max_requests} requests in {window_seconds}s"
            )

            return False, retry_after

        # Лимит не превышен - добавляем текущий запрос
        user_requests.append(current_time)
        return True, None

    def _cleanup_old_entries(self):
        """
        Удаляет записи пользователей без активности последние 5 минут.
        Предотвращает неограниченный рост словаря.
        """
        current_time = time.time()
        cutoff = current_time - 300  # 5 минут

        keys_to_delete = []
        for user_key, requests in self._requests.items():
            if not requests or requests[-1] < cutoff:
                keys_to_delete.append(user_key)

        for key in keys_to_delete:
            del self._requests[key]

        if keys_to_delete:
            logger.debug(f"Cleaned up {len(keys_to_delete)} inactive rate limit entries")


# Глобальный экземпляр rate limiter
_global_limiter = RateLimiter()


def check_rate_limit(user_key: str, max_requests: int, window_seconds: int) -> Tuple[bool, Optional[int]]:
    """
    Глобальная функция для проверки rate limit.

    Args:
        user_key: Уникальный ключ пользователя
        max_requests: Максимальное количество запросов
        window_seconds: Временное окно в секундах

    Returns:
        Tuple[bool, Optional[int]]: (разрешено, секунд до разблокировки)

    Examples:
        >>> from teacher_mode.utils.rate_limiter import check_rate_limit
        >>> allowed, retry_after = check_rate_limit(f"add_student_{teacher_id}", max_requests=10, window_seconds=60)
        >>> if not allowed:
        >>>     await update.message.reply_text(f"⏱ Слишком много запросов. Подождите {retry_after} сек.")
        >>>     return
    """
    return _global_limiter.check_rate_limit(user_key, max_requests, window_seconds)


# Предустановленные лимиты для критичных операций
RATE_LIMITS = {
    # Добавление ученика: 10 запросов в минуту
    'add_student': {'max_requests': 10, 'window_seconds': 60},

    # Создание задания: 20 заданий в час
    'create_homework': {'max_requests': 20, 'window_seconds': 3600},

    # Отправка комментария: 30 комментариев в минуту
    'add_comment': {'max_requests': 30, 'window_seconds': 60},

    # Генерация промокода: 5 промокодов в час
    'create_promo': {'max_requests': 5, 'window_seconds': 3600},

    # Активация промокода: 3 попытки в минуту
    'use_promo': {'max_requests': 3, 'window_seconds': 60},

    # Подключение к учителю: 5 попыток в час
    'connect_teacher': {'max_requests': 5, 'window_seconds': 3600},

    # Быстрая проверка: 50 проверок в час (дополнительно к квоте из БД)
    'quick_check': {'max_requests': 50, 'window_seconds': 3600},
}


def check_operation_limit(user_id: int, operation: str) -> Tuple[bool, Optional[int]]:
    """
    Проверяет rate limit для предустановленной операции.

    Args:
        user_id: ID пользователя
        operation: Название операции (из RATE_LIMITS)

    Returns:
        Tuple[bool, Optional[int]]: (разрешено, секунд до разблокировки)

    Raises:
        ValueError: Если операция не найдена в RATE_LIMITS

    Examples:
        >>> allowed, retry_after = check_operation_limit(teacher_id, 'add_student')
        >>> if not allowed:
        >>>     await update.message.reply_text(f"⏱ Подождите {retry_after} сек.")
        >>>     return
    """
    if operation not in RATE_LIMITS:
        raise ValueError(f"Unknown operation: {operation}. Available: {list(RATE_LIMITS.keys())}")

    limits = RATE_LIMITS[operation]
    user_key = f"{operation}_{user_id}"

    return check_rate_limit(user_key, limits['max_requests'], limits['window_seconds'])
