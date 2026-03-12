"""
Routes для управления клиентом B2B API.

GET /api/v1/me - информация о текущем клиенте
GET /api/v1/usage - статистика использования
"""

import logging
import json
import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import DATABASE_FILE
from b2b_api.schemas.client import (
    B2BClient,
    ClientStatus,
    ClientTier,
    UsageStatsResponse
)
from b2b_api.middleware.api_key_auth import verify_api_key, get_current_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["client"])


@router.get(
    "/me",
    response_model=B2BClient,
    summary="Информация о клиенте",
    description="""
Возвращает информацию о текущем клиенте, привязанном к API ключу.

Включает:
- Данные компании
- Текущий тариф и статус
- Лимиты запросов
- Статистику использования
    """
)
async def get_client_info(
    client: B2BClient = Depends(get_current_client)
) -> B2BClient:
    """
    Получает информацию о текущем клиенте.
    """
    return client


@router.get(
    "/usage",
    response_model=UsageStatsResponse,
    summary="Статистика использования",
    description="""
Возвращает детальную статистику использования API.

**Параметры:**
- `days` - количество дней для статистики (по умолчанию 30)

**Включает:**
- Общее количество запросов и проверок
- Разбивка по номерам заданий
- Ежедневная статистика
- Метрики производительности
    """
)
async def get_usage_stats(
    client_data: dict = Depends(verify_api_key),
    days: int = Query(30, ge=1, le=90, description="Количество дней")
) -> UsageStatsResponse:
    """
    Получает статистику использования API.
    """
    client_id = client_data['client_id']

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)

            # Общая статистика по проверкам
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_checks,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(processing_time_ms) as avg_time,
                    MAX(processing_time_ms) as max_time
                FROM b2b_checks
                WHERE client_id = ?
                  AND created_at >= ?
                  AND created_at <= ?
            """, (client_id, start_date.isoformat(), end_date.isoformat()))

            stats = await cursor.fetchone()

            # Статистика по заданиям
            cursor = await db.execute("""
                SELECT task_number, COUNT(*) as count
                FROM b2b_checks
                WHERE client_id = ?
                  AND created_at >= ?
                  AND created_at <= ?
                GROUP BY task_number
            """, (client_id, start_date.isoformat(), end_date.isoformat()))

            task_rows = await cursor.fetchall()
            checks_by_task = {str(row['task_number']): row['count'] for row in task_rows}

            # Ежедневная статистика
            cursor = await db.execute("""
                SELECT
                    date(created_at) as check_date,
                    COUNT(*) as checks
                FROM b2b_checks
                WHERE client_id = ?
                  AND created_at >= ?
                  AND created_at <= ?
                GROUP BY date(created_at)
                ORDER BY check_date
            """, (client_id, start_date.isoformat(), end_date.isoformat()))

            daily_rows = await cursor.fetchall()
            daily_breakdown = [
                {"date": row['check_date'], "checks": row['checks']}
                for row in daily_rows
            ]

            # Общее количество запросов из логов
            cursor = await db.execute("""
                SELECT COUNT(*) as total
                FROM b2b_api_logs
                WHERE client_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
            """, (client_id, start_date.isoformat(), end_date.isoformat()))

            logs_stats = await cursor.fetchone()
            total_requests = logs_stats['total'] if logs_stats else 0

            # P95 время обработки
            cursor = await db.execute("""
                SELECT processing_time_ms
                FROM b2b_checks
                WHERE client_id = ?
                  AND created_at >= ?
                  AND processing_time_ms IS NOT NULL
                ORDER BY processing_time_ms
            """, (client_id, start_date.isoformat()))

            times = [row[0] for row in await cursor.fetchall()]
            p95_time = 0
            if times:
                p95_index = int(len(times) * 0.95)
                p95_time = times[min(p95_index, len(times) - 1)]

            return UsageStatsResponse(
                client_id=client_id,
                period_start=start_date,
                period_end=end_date,
                total_requests=total_requests,
                total_checks=stats['total_checks'] or 0,
                successful_checks=stats['successful'] or 0,
                failed_checks=stats['failed'] or 0,
                checks_by_task=checks_by_task,
                daily_breakdown=daily_breakdown,
                avg_processing_time_ms=stats['avg_time'] or 0,
                p95_processing_time_ms=p95_time
            )

    except Exception as e:
        logger.error(f"Error getting usage stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get usage stats")


@router.get(
    "/limits",
    summary="Текущие лимиты",
    description="Возвращает текущее состояние лимитов клиента."
)
async def get_limits(
    client_data: dict = Depends(verify_api_key)
) -> dict:
    """
    Получает текущие лимиты клиента.
    """
    return {
        "rate_limits": {
            "per_minute": {
                "limit": client_data['rate_limit_per_minute'],
                "current": "See X-RateLimit headers in responses"
            },
            "per_day": {
                "limit": client_data['rate_limit_per_day'],
                "used": client_data['checks_today'],
                "remaining": client_data['rate_limit_per_day'] - client_data['checks_today']
            }
        },
        "quota": {
            "monthly_limit": client_data['monthly_quota'],
            "used": client_data['checks_this_month'],
            "remaining": (client_data['monthly_quota'] - client_data['checks_this_month'])
                        if client_data['monthly_quota'] else None
        },
        "tier": client_data['tier'],
        "scopes": client_data['scopes']
    }
