"""
API Logger для B2B API.

Логирует все запросы для:
- Аналитики использования
- Биллинга
- Мониторинга
- Отладки
"""

import logging
import aiosqlite
import asyncio
from datetime import datetime, timezone
from typing import Optional
from collections import deque
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


class APILogger:
    """
    Асинхронный логгер API запросов.

    Использует batch insert для производительности.
    """

    def __init__(self, database_file: str = DATABASE_FILE, batch_size: int = 50):
        self.database_file = database_file
        self.batch_size = batch_size
        self._queue = deque()
        self._lock = asyncio.Lock()
        self._flush_task = None

    async def start(self):
        """Запускает фоновую задачу сброса логов."""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())
            logger.info("API Logger started")

    async def stop(self):
        """Останавливает логгер и сбрасывает оставшиеся логи."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Сбрасываем оставшиеся логи
        await self._flush()
        logger.info("API Logger stopped")

    async def log(
        self,
        client_id: str,
        key_id: Optional[str],
        endpoint: str,
        method: str,
        response_status: int,
        response_time_ms: int,
        request_size: int = 0,
        response_size: int = 0,
        check_id: Optional[str] = None,
        task_number: Optional[int] = None,
        is_billable: bool = True
    ):
        """
        Добавляет запись в очередь логов.
        """
        log_entry = {
            "client_id": client_id,
            "key_id": key_id,
            "endpoint": endpoint,
            "method": method,
            "response_status": response_status,
            "response_time_ms": response_time_ms,
            "request_size_bytes": request_size,
            "response_size_bytes": response_size,
            "check_id": check_id,
            "task_number": task_number,
            "is_billable": 1 if is_billable else 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        async with self._lock:
            self._queue.append(log_entry)

            # Сбрасываем если накопилось достаточно
            if len(self._queue) >= self.batch_size:
                await self._flush()

    async def _flush(self):
        """Сбрасывает накопленные логи в БД."""
        if not self._queue:
            return

        async with self._lock:
            entries = list(self._queue)
            self._queue.clear()

        if not entries:
            return

        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.executemany("""
                    INSERT INTO b2b_api_logs (
                        client_id, key_id, endpoint, method,
                        request_size_bytes, response_status,
                        response_time_ms, response_size_bytes,
                        check_id, task_number, is_billable, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    (
                        e["client_id"],
                        e["key_id"],
                        e["endpoint"],
                        e["method"],
                        e["request_size_bytes"],
                        e["response_status"],
                        e["response_time_ms"],
                        e["response_size_bytes"],
                        e["check_id"],
                        e["task_number"],
                        e["is_billable"],
                        e["timestamp"]
                    )
                    for e in entries
                ])
                await db.commit()

            logger.debug(f"Flushed {len(entries)} API log entries")

        except Exception as e:
            logger.error(f"Error flushing API logs: {e}")
            # Возвращаем записи в очередь
            async with self._lock:
                for entry in reversed(entries):
                    self._queue.appendleft(entry)

    async def _periodic_flush(self):
        """Периодический сброс логов."""
        while True:
            await asyncio.sleep(10)  # Каждые 10 секунд
            try:
                await self._flush()
            except Exception as e:
                logger.error(f"Error in periodic flush: {e}")


# Глобальный экземпляр
_api_logger: Optional[APILogger] = None


def get_api_logger() -> APILogger:
    """Возвращает глобальный экземпляр APILogger."""
    global _api_logger
    if _api_logger is None:
        _api_logger = APILogger()
    return _api_logger


class APILoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для автоматического логирования всех запросов.
    """

    def __init__(self, app, api_prefix: str = "/api/v1"):
        super().__init__(app)
        self.api_prefix = api_prefix
        self.logger = get_api_logger()

    async def dispatch(self, request: Request, call_next):
        # Пропускаем не-API запросы
        if not request.url.path.startswith(self.api_prefix):
            return await call_next(request)

        start_time = datetime.now(timezone.utc)

        # Получаем размер запроса
        request_size = 0
        if request.headers.get("content-length"):
            try:
                request_size = int(request.headers["content-length"])
            except ValueError:
                pass

        # Выполняем запрос
        response = await call_next(request)

        # Вычисляем время ответа
        end_time = datetime.now(timezone.utc)
        response_time_ms = int((end_time - start_time).total_seconds() * 1000)

        # Получаем размер ответа
        response_size = 0
        if hasattr(response, 'headers') and response.headers.get("content-length"):
            try:
                response_size = int(response.headers["content-length"])
            except ValueError:
                pass

        # Получаем данные клиента из request.state
        client_id = None
        key_id = None
        if hasattr(request.state, 'client_data'):
            client_id = request.state.client_data.get('client_id')
            key_id = request.state.client_data.get('key_id')

        # Определяем тип запроса для биллинга
        is_billable = "/check" in request.url.path and request.method == "POST"
        check_id = None
        task_number = None

        if hasattr(request.state, 'check_id'):
            check_id = request.state.check_id
        if hasattr(request.state, 'task_number'):
            task_number = request.state.task_number

        # Логируем асинхронно
        if client_id:
            asyncio.create_task(
                self.logger.log(
                    client_id=client_id,
                    key_id=key_id,
                    endpoint=request.url.path,
                    method=request.method,
                    response_status=response.status_code,
                    response_time_ms=response_time_ms,
                    request_size=request_size,
                    response_size=response_size,
                    check_id=check_id,
                    task_number=task_number,
                    is_billable=is_billable
                )
            )

        return response


async def log_request(
    request: Request,
    response_status: int,
    response_time_ms: int,
    check_id: Optional[str] = None,
    task_number: Optional[int] = None
):
    """
    Вспомогательная функция для ручного логирования запроса.
    """
    api_logger = get_api_logger()

    client_id = None
    key_id = None
    if hasattr(request.state, 'client_data'):
        client_id = request.state.client_data.get('client_id')
        key_id = request.state.client_data.get('key_id')

    if client_id:
        await api_logger.log(
            client_id=client_id,
            key_id=key_id,
            endpoint=request.url.path,
            method=request.method,
            response_status=response_status,
            response_time_ms=response_time_ms,
            check_id=check_id,
            task_number=task_number,
            is_billable=check_id is not None
        )
