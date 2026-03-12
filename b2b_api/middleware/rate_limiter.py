"""
Rate Limiter для B2B API.

Реализует:
- Лимит запросов в минуту
- Лимит запросов в день
- Месячная квота
- Sliding window алгоритм для точного подсчёта
"""

import logging
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, List
from collections import defaultdict
from fastapi import HTTPException, Depends, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from b2b_api.middleware.api_key_auth import verify_api_key, get_api_key_auth

logger = logging.getLogger(__name__)


class RateLimitExceeded(HTTPException):
    """Исключение при превышении лимита."""

    def __init__(
        self,
        limit_type: str,
        limit_value: int,
        retry_after: int = 60
    ):
        detail = {
            "error": "rate_limit_exceeded",
            "limit_type": limit_type,
            "limit_value": limit_value,
            "retry_after": retry_after,
            "message": f"Rate limit exceeded: {limit_value} requests per {limit_type}. Retry after {retry_after} seconds."
        }
        super().__init__(status_code=429, detail=detail)
        self.retry_after = retry_after


class SlidingWindowCounter:
    """
    Sliding Window Counter для rate limiting.
    Более точный чем fixed window, но менее затратный чем sliding log.
    """

    def __init__(self, window_size_seconds: int = 60):
        self.window_size = window_size_seconds
        # {client_id: [(timestamp, count), ...]}
        self.windows: Dict[str, List[tuple]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str, limit: int) -> tuple:
        """
        Проверяет, разрешён ли запрос.

        Returns:
            (is_allowed, current_count, remaining)
        """
        async with self._lock:
            now = time.time()
            window_start = now - self.window_size

            # Получаем записи для клиента
            client_windows = self.windows[client_id]

            # Удаляем старые записи
            client_windows = [
                (ts, count) for ts, count in client_windows
                if ts > window_start
            ]

            # Считаем текущее использование
            current_count = sum(count for _, count in client_windows)

            if current_count >= limit:
                # Вычисляем когда освободится слот
                if client_windows:
                    oldest_ts = min(ts for ts, _ in client_windows)
                    retry_after = int(oldest_ts + self.window_size - now) + 1
                else:
                    retry_after = self.window_size

                return False, current_count, 0, retry_after

            # Добавляем текущий запрос
            client_windows.append((now, 1))
            self.windows[client_id] = client_windows

            remaining = limit - current_count - 1

            return True, current_count + 1, remaining, 0

    async def cleanup(self):
        """Очищает старые записи."""
        async with self._lock:
            now = time.time()
            for client_id in list(self.windows.keys()):
                window_start = now - self.window_size
                self.windows[client_id] = [
                    (ts, count) for ts, count in self.windows[client_id]
                    if ts > window_start
                ]
                if not self.windows[client_id]:
                    del self.windows[client_id]


class DailyCounter:
    """Счётчик дневных запросов."""

    def __init__(self):
        # {client_id: {date: count}}
        self.counters: Dict[str, Dict[str, int]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str, limit: int) -> tuple:
        """
        Проверяет дневной лимит.

        Returns:
            (is_allowed, current_count, remaining)
        """
        async with self._lock:
            today = datetime.now(timezone.utc).date().isoformat()

            client_counters = self.counters[client_id]

            # Очищаем старые дни
            old_dates = [d for d in client_counters if d != today]
            for d in old_dates:
                del client_counters[d]

            current_count = client_counters.get(today, 0)

            if current_count >= limit:
                # Вычисляем время до полуночи UTC
                now = datetime.now(timezone.utc)
                midnight = datetime(
                    now.year, now.month, now.day,
                    tzinfo=timezone.utc
                ).replace(hour=0, minute=0, second=0) + \
                    __import__('datetime').timedelta(days=1)
                retry_after = int((midnight - now).total_seconds()) + 1

                return False, current_count, 0, retry_after

            client_counters[today] = current_count + 1
            remaining = limit - current_count - 1

            return True, current_count + 1, remaining, 0


class RateLimiter:
    """
    Главный класс rate limiter.

    Проверяет:
    - Лимит в минуту (sliding window)
    - Лимит в день (fixed window)
    - Месячную квоту (из БД)
    """

    def __init__(self):
        self.minute_limiter = SlidingWindowCounter(window_size_seconds=60)
        self.daily_limiter = DailyCounter()

        # Запускаем периодическую очистку
        self._cleanup_task = None

    async def start_cleanup_task(self):
        """Запускает фоновую задачу очистки."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self):
        """Периодическая очистка старых записей."""
        while True:
            await asyncio.sleep(300)  # Каждые 5 минут
            try:
                await self.minute_limiter.cleanup()
                logger.debug("Rate limiter cleanup completed")
            except Exception as e:
                logger.error(f"Error in rate limiter cleanup: {e}")

    async def check(
        self,
        client_id: str,
        minute_limit: int,
        daily_limit: int,
        monthly_quota: Optional[int],
        current_monthly_usage: int
    ) -> Dict:
        """
        Проверяет все лимиты.

        Returns:
            dict с информацией о лимитах

        Raises:
            RateLimitExceeded если лимит превышен
        """
        result = {
            "minute": {"allowed": True, "current": 0, "limit": minute_limit, "remaining": minute_limit},
            "daily": {"allowed": True, "current": 0, "limit": daily_limit, "remaining": daily_limit},
            "monthly": {"allowed": True, "current": current_monthly_usage, "limit": monthly_quota, "remaining": None}
        }

        # Проверяем месячную квоту (если установлена)
        if monthly_quota is not None:
            if current_monthly_usage >= monthly_quota:
                raise RateLimitExceeded(
                    limit_type="monthly",
                    limit_value=monthly_quota,
                    retry_after=86400  # Попробуйте завтра
                )
            result["monthly"]["remaining"] = monthly_quota - current_monthly_usage

        # Проверяем дневной лимит
        daily_allowed, daily_count, daily_remaining, daily_retry = \
            await self.daily_limiter.is_allowed(client_id, daily_limit)

        result["daily"]["current"] = daily_count
        result["daily"]["remaining"] = daily_remaining

        if not daily_allowed:
            result["daily"]["allowed"] = False
            raise RateLimitExceeded(
                limit_type="daily",
                limit_value=daily_limit,
                retry_after=daily_retry
            )

        # Проверяем минутный лимит
        minute_allowed, minute_count, minute_remaining, minute_retry = \
            await self.minute_limiter.is_allowed(client_id, minute_limit)

        result["minute"]["current"] = minute_count
        result["minute"]["remaining"] = minute_remaining

        if not minute_allowed:
            result["minute"]["allowed"] = False
            raise RateLimitExceeded(
                limit_type="minute",
                limit_value=minute_limit,
                retry_after=minute_retry
            )

        return result


# Глобальный экземпляр
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Возвращает глобальный экземпляр RateLimiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def check_rate_limit(
    client_data: dict = Depends(verify_api_key)
) -> dict:
    """
    FastAPI dependency для проверки rate limit.

    Использование:
    @router.post("/check")
    async def create_check(
        request: CheckRequest,
        rate_info: dict = Depends(check_rate_limit)
    ):
        ...
    """
    limiter = get_rate_limiter()

    try:
        rate_info = await limiter.check(
            client_id=client_data['client_id'],
            minute_limit=client_data['rate_limit_per_minute'],
            daily_limit=client_data['rate_limit_per_day'],
            monthly_quota=client_data['monthly_quota'],
            current_monthly_usage=client_data['checks_this_month']
        )

        # Добавляем client_data для использования в route
        rate_info['client_data'] = client_data

        return rate_info

    except RateLimitExceeded:
        raise


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware для добавления rate limit заголовков в ответы.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Добавляем заголовки если есть информация о rate limit
        if hasattr(request.state, 'rate_limit_info'):
            info = request.state.rate_limit_info
            response.headers["X-RateLimit-Limit-Minute"] = str(info['minute']['limit'])
            response.headers["X-RateLimit-Remaining-Minute"] = str(info['minute']['remaining'])
            response.headers["X-RateLimit-Limit-Daily"] = str(info['daily']['limit'])
            response.headers["X-RateLimit-Remaining-Daily"] = str(info['daily']['remaining'])

            if info['monthly']['limit']:
                response.headers["X-RateLimit-Limit-Monthly"] = str(info['monthly']['limit'])
                response.headers["X-RateLimit-Remaining-Monthly"] = str(info['monthly']['remaining'])

        return response


async def add_rate_limit_headers(request: Request, rate_info: dict):
    """Добавляет информацию о rate limit в request.state для middleware."""
    request.state.rate_limit_info = rate_info
