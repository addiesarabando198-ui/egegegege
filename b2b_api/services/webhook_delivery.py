"""
Webhook delivery service для B2B API.

Реализует:
- Доставку webhook-уведомлений о завершении проверок
- HMAC-подпись для верификации подлинности
- Retry-логику с экспоненциальной задержкой
- Логирование доставок в БД
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import aiosqlite

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)

# Секрет для HMAC-подписи (один на всю систему, можно переопределить через env)
WEBHOOK_SIGNING_SECRET = os.getenv("B2B_WEBHOOK_SECRET", "b2b_webhook_default_secret")

# Настройки retry
MAX_ATTEMPTS = 3
RETRY_DELAYS = [5, 30, 120]  # секунды между попытками
WEBHOOK_TIMEOUT = 10  # секунд на запрос


def compute_hmac_signature(payload: str, secret: str) -> str:
    """Вычисляет HMAC-SHA256 подпись для payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


async def deliver_webhook(
    check_id: str,
    client_id: str,
    callback_url: str,
    result_data: dict,
):
    """
    Отправляет webhook-уведомление о завершении проверки.

    Пытается доставить до MAX_ATTEMPTS раз с экспоненциальной задержкой.
    Все попытки логируются в таблицу b2b_webhook_deliveries.
    """
    payload = json.dumps({
        "event": "check.completed",
        "check_id": check_id,
        "client_id": client_id,
        "data": result_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False)

    signature = compute_hmac_signature(payload, WEBHOOK_SIGNING_SECRET)

    # Создаём запись о доставке
    delivery_id = await _create_delivery_record(check_id, client_id, callback_url, payload)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        response_status = None
        response_body = None
        error_message = None

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": f"sha256={signature}",
                    "X-Webhook-Event": "check.completed",
                    "X-Webhook-Delivery-ID": str(delivery_id),
                    "X-Webhook-Attempt": str(attempt),
                    "User-Agent": "EGE-Superbot-B2B/1.1",
                }

                async with session.post(
                    callback_url,
                    data=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT),
                    ssl=True,
                ) as resp:
                    response_status = resp.status
                    response_body = await resp.text(encoding="utf-8")

                    if 200 <= response_status < 300:
                        # Успех
                        await _update_delivery_record(
                            delivery_id,
                            status="delivered",
                            attempts=attempt,
                            response_status=response_status,
                            response_body=response_body[:1000],
                        )
                        logger.info(
                            f"Webhook delivered: check={check_id}, "
                            f"url={callback_url}, attempt={attempt}, status={response_status}"
                        )
                        return

                    error_message = f"HTTP {response_status}: {response_body[:200]}"

        except asyncio.TimeoutError:
            error_message = f"Timeout after {WEBHOOK_TIMEOUT}s"
        except aiohttp.ClientError as e:
            error_message = f"Connection error: {e}"
        except Exception as e:
            error_message = f"Unexpected error: {e}"

        logger.warning(
            f"Webhook delivery failed: check={check_id}, attempt={attempt}/{MAX_ATTEMPTS}, "
            f"error={error_message}"
        )

        await _update_delivery_record(
            delivery_id,
            status="pending" if attempt < MAX_ATTEMPTS else "failed",
            attempts=attempt,
            response_status=response_status,
            response_body=(response_body or "")[:1000],
            error_message=error_message,
        )

        # Задержка перед следующей попыткой
        if attempt < MAX_ATTEMPTS:
            delay = RETRY_DELAYS[attempt - 1] if attempt - 1 < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
            await asyncio.sleep(delay)

    logger.error(f"Webhook delivery permanently failed: check={check_id}, url={callback_url}")


async def _create_delivery_record(
    check_id: str, client_id: str, url: str, payload: str
) -> int:
    """Создаёт запись о доставке в БД и возвращает ID."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                INSERT INTO b2b_webhook_deliveries
                    (check_id, client_id, url, payload, status, attempts, max_attempts, created_at)
                VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)
            """, (
                check_id, client_id, url, payload,
                MAX_ATTEMPTS,
                datetime.now(timezone.utc).isoformat()
            ))
            await db.commit()
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error creating webhook delivery record: {e}")
        return 0


async def _update_delivery_record(
    delivery_id: int,
    status: str,
    attempts: int,
    response_status: Optional[int] = None,
    response_body: Optional[str] = None,
    error_message: Optional[str] = None,
):
    """Обновляет запись о доставке."""
    if not delivery_id:
        return

    try:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(DATABASE_FILE) as db:
            delivered_at = now if status == "delivered" else None
            await db.execute("""
                UPDATE b2b_webhook_deliveries
                SET status = ?,
                    attempts = ?,
                    response_status = ?,
                    response_body = ?,
                    error_message = ?,
                    last_attempt_at = ?,
                    delivered_at = ?
                WHERE id = ?
            """, (
                status, attempts, response_status,
                response_body, error_message,
                now, delivered_at, delivery_id
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"Error updating webhook delivery record: {e}")
