"""
Планировщик ежемесячного биллинга B2B клиентов.

Запускается как фоновая задача при старте приложения.
Первого числа каждого месяца в 10:00 MSK списывает оплату за предыдущий месяц.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from b2b_api.services.billing_service import BillingService

logger = logging.getLogger(__name__)

# Московское время = UTC+3
MSK_OFFSET = timedelta(hours=3)


def _now_msk() -> datetime:
    """Текущее время в MSK."""
    return datetime.now(timezone.utc) + MSK_OFFSET


def _seconds_until_next_billing() -> float:
    """
    Вычисляет количество секунд до следующего запуска биллинга.
    Биллинг: 1-е число каждого месяца в 10:00 MSK.
    """
    now = _now_msk()

    # Следующий 1-й день месяца
    if now.month == 12:
        next_run = now.replace(year=now.year + 1, month=1, day=1, hour=10, minute=0, second=0, microsecond=0)
    else:
        next_run = now.replace(month=now.month + 1, day=1, hour=10, minute=0, second=0, microsecond=0)

    delta = next_run - now
    return max(delta.total_seconds(), 0)


async def run_monthly_billing():
    """
    Запускает биллинг за предыдущий месяц.
    """
    now = _now_msk()

    # Биллим предыдущий месяц
    if now.month == 1:
        bill_year = now.year - 1
        bill_month = 12
    else:
        bill_year = now.year
        bill_month = now.month - 1

    logger.info(f"Starting monthly billing for {bill_year}-{bill_month:02d}")

    billing = BillingService()
    try:
        results = await billing.bill_all_clients(bill_year, bill_month)
        successful = sum(1 for r in results if r.get("payment", {}).get("success"))
        failed = len(results) - successful
        logger.info(
            f"Monthly billing completed: {successful} successful, {failed} failed "
            f"(total {len(results)} clients)"
        )
    except Exception as e:
        logger.error(f"Monthly billing failed: {e}", exc_info=True)


async def billing_scheduler_loop():
    """
    Основной цикл планировщика.
    Работает бесконечно, просыпаясь 1-го числа каждого месяца.
    """
    logger.info("Billing scheduler started")

    while True:
        wait_seconds = _seconds_until_next_billing()
        next_run = _now_msk() + timedelta(seconds=wait_seconds)
        logger.info(
            f"Next billing run scheduled at {next_run.strftime('%Y-%m-%d %H:%M MSK')} "
            f"(in {wait_seconds / 3600:.1f} hours)"
        )

        await asyncio.sleep(wait_seconds)
        await run_monthly_billing()

        # Небольшая пауза, чтобы не запустить дважды
        await asyncio.sleep(60)


def start_billing_scheduler():
    """
    Запускает планировщик как фоновую asyncio-задачу.
    Вызывается из app.py при startup.
    """
    task = asyncio.create_task(billing_scheduler_loop())
    logger.info("Billing scheduler task created")
    return task
