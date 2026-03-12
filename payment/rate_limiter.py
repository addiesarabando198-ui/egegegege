# payment/rate_limiter.py
"""Rate limiting для защиты от спама создания платежей."""
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple
import asyncio

logger = logging.getLogger(__name__)


class PaymentRateLimiter:
    """
    Ограничитель частоты создания платежей для защиты от спама.

    Лимиты:
    - Максимум 5 платежей за 10 минут на одного пользователя
    - Максимум 3 платежа за 1 минуту на одного пользователя (защита от burst)
    """

    def __init__(self):
        # Словарь: user_id -> [(timestamp1, order_id1), (timestamp2, order_id2), ...]
        self._payment_attempts: Dict[int, List[Tuple[datetime, str]]] = defaultdict(list)

        # Лимиты
        self.max_payments_10min = 5
        self.max_payments_1min = 3
        self.window_10min = timedelta(minutes=10)
        self.window_1min = timedelta(minutes=1)

        # Запускаем периодическую очистку старых записей
        self._cleanup_task = None

    def start_cleanup_task(self):
        """Запускает фоновую задачу очистки старых записей."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            logger.info("Rate limiter cleanup task started")

    def stop_cleanup_task(self):
        """Останавливает фоновую задачу очистки."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None
            logger.info("Rate limiter cleanup task stopped")

    async def _periodic_cleanup(self):
        """Периодически очищает старые записи (каждые 5 минут)."""
        while True:
            try:
                await asyncio.sleep(300)  # 5 минут
                self._cleanup_old_attempts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in rate limiter cleanup: {e}")

    def _cleanup_old_attempts(self):
        """Удаляет попытки старше 10 минут."""
        now = datetime.now()
        cutoff = now - self.window_10min

        # Очищаем старые записи
        users_to_clean = []
        for user_id, attempts in self._payment_attempts.items():
            # Оставляем только свежие попытки
            fresh_attempts = [(ts, oid) for ts, oid in attempts if ts > cutoff]

            if fresh_attempts:
                self._payment_attempts[user_id] = fresh_attempts
            else:
                users_to_clean.append(user_id)

        # Удаляем пользователей без активных попыток
        for user_id in users_to_clean:
            del self._payment_attempts[user_id]

        if users_to_clean:
            logger.debug(f"Cleaned up rate limiter data for {len(users_to_clean)} users")

    def check_rate_limit(self, user_id: int) -> Tuple[bool, str]:
        """
        Проверяет, может ли пользователь создать новый платеж.

        Args:
            user_id: ID пользователя

        Returns:
            (allowed, message): allowed=True если можно создать платеж,
                               message содержит причину отказа если allowed=False
        """
        now = datetime.now()

        # Получаем попытки пользователя
        attempts = self._payment_attempts.get(user_id, [])

        # Фильтруем только свежие попытки
        attempts_10min = [(ts, oid) for ts, oid in attempts if now - ts < self.window_10min]
        attempts_1min = [(ts, oid) for ts, oid in attempts if now - ts < self.window_1min]

        # Проверяем лимит за 1 минуту (burst protection)
        if len(attempts_1min) >= self.max_payments_1min:
            wait_seconds = int((self.window_1min - (now - attempts_1min[0][0])).total_seconds())
            return False, f"Слишком частые попытки оплаты. Подождите {wait_seconds} секунд."

        # Проверяем лимит за 10 минут
        if len(attempts_10min) >= self.max_payments_10min:
            wait_minutes = int((self.window_10min - (now - attempts_10min[0][0])).total_seconds() / 60) + 1
            return False, f"Превышен лимит платежей (максимум {self.max_payments_10min} за 10 минут). Подождите {wait_minutes} мин."

        # Все проверки пройдены
        return True, ""

    def record_payment_attempt(self, user_id: int, order_id: str):
        """
        Записывает попытку создания платежа.

        Args:
            user_id: ID пользователя
            order_id: ID заказа
        """
        now = datetime.now()
        self._payment_attempts[user_id].append((now, order_id))

        logger.info(f"Recorded payment attempt for user {user_id}: {order_id}")
        logger.debug(f"User {user_id} has {len(self._payment_attempts[user_id])} recent payment attempts")

    def get_user_stats(self, user_id: int) -> Dict[str, int]:
        """
        Возвращает статистику попыток для пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            Словарь со статистикой
        """
        now = datetime.now()
        attempts = self._payment_attempts.get(user_id, [])

        attempts_10min = [ts for ts, _ in attempts if now - ts < self.window_10min]
        attempts_1min = [ts for ts, _ in attempts if now - ts < self.window_1min]

        return {
            'total_attempts': len(attempts),
            'attempts_last_10min': len(attempts_10min),
            'attempts_last_1min': len(attempts_1min),
            'limit_10min': self.max_payments_10min,
            'limit_1min': self.max_payments_1min,
            'can_create_payment': len(attempts_10min) < self.max_payments_10min and len(attempts_1min) < self.max_payments_1min
        }

    def reset_user_limits(self, user_id: int):
        """
        Сбрасывает лимиты для пользователя (для админов).

        Args:
            user_id: ID пользователя
        """
        if user_id in self._payment_attempts:
            del self._payment_attempts[user_id]
            logger.info(f"Reset rate limits for user {user_id}")


# Глобальный экземпляр
_rate_limiter_instance: PaymentRateLimiter = None


def get_rate_limiter() -> PaymentRateLimiter:
    """Возвращает глобальный экземпляр rate limiter."""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        _rate_limiter_instance = PaymentRateLimiter()
        _rate_limiter_instance.start_cleanup_task()
    return _rate_limiter_instance


def stop_rate_limiter():
    """Останавливает rate limiter."""
    global _rate_limiter_instance
    if _rate_limiter_instance is not None:
        _rate_limiter_instance.stop_cleanup_task()
