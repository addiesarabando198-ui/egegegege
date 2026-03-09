"""
B2B Billing Service — рекуррентные списания через Tinkoff (T-Bank).

Процесс биллинга:
1. Клиент привязывает карту через первый платёж (init с Recurrent=Y)
2. Tinkoff возвращает RebillId после успешной оплаты
3. Каждый месяц: агрегация использования → расчёт суммы → автосписание
"""

import logging
import uuid
import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from core.db import DATABASE_FILE
from b2b_api.middleware.api_key_auth import TIER_LIMITS
from b2b_api.schemas.client import ClientTier

logger = logging.getLogger(__name__)

# Цены по тарифам (в рублях/месяц)
TIER_PRICES_RUB = {
    ClientTier.FREE: 0,
    ClientTier.TRIAL: 0,
    ClientTier.BASIC: 2_900,
    ClientTier.STANDARD: 9_900,
    ClientTier.PREMIUM: 29_900,
    ClientTier.ENTERPRISE: 99_900,
}

# Цена за проверку сверх квоты (в рублях)
OVERAGE_PRICE_PER_CHECK_RUB = 5


class BillingService:
    """Сервис биллинга B2B клиентов."""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file

    # ------------------------------------------------------------------ #
    #  Привязка карты (первый платёж)
    # ------------------------------------------------------------------ #

    async def create_card_binding_payment(
        self,
        client_id: str,
        contact_email: str,
    ) -> Dict[str, Any]:
        """
        Создаёт платёж на 1₽ для привязки карты (Recurrent=Y).
        После успешной оплаты Tinkoff вернёт RebillId через webhook.

        Returns:
            dict с payment_url для перенаправления клиента
        """
        from payment.tinkoff import TinkoffPayment

        tinkoff = TinkoffPayment()
        order_id = f"b2b_bind_{client_id}_{uuid.uuid4().hex[:8]}"

        receipt_items = [
            tinkoff.build_receipt_item(
                name="Привязка карты для B2B",
                price_kopecks=100,  # 1 рубль
            )
        ]

        result = await tinkoff.init_payment(
            order_id=order_id,
            amount_kopecks=100,
            description="Привязка карты для автосписаний",
            user_email=contact_email,
            receipt_items=receipt_items,
            enable_recurrent=True,
            customer_key=f"b2b_{client_id}",
        )

        if result.get("success"):
            # Сохраняем order_id привязки
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    UPDATE b2b_clients
                    SET billing_order_id = ?, updated_at = ?
                    WHERE client_id = ?
                """, (order_id, datetime.now(timezone.utc).isoformat(), client_id))
                await db.commit()

            logger.info(f"Card binding payment created for {client_id}: {order_id}")
            return {
                "success": True,
                "payment_url": result["payment_url"],
                "order_id": order_id,
            }
        else:
            logger.error(f"Failed to create binding payment for {client_id}: {result}")
            return {"success": False, "error": result.get("error", "Unknown error")}

    async def save_rebill_id(self, client_id: str, rebill_id: str):
        """
        Сохраняет RebillId после успешной привязки карты.
        Вызывается из обработчика Tinkoff webhook.
        """
        async with aiosqlite.connect(self.database_file) as db:
            await db.execute("""
                UPDATE b2b_clients
                SET rebill_id = ?, billing_active = 1, updated_at = ?
                WHERE client_id = ?
            """, (rebill_id, datetime.now(timezone.utc).isoformat(), client_id))
            await db.commit()

        logger.info(f"Saved RebillId for client {client_id}")

    # ------------------------------------------------------------------ #
    #  Агрегация использования
    # ------------------------------------------------------------------ #

    async def aggregate_monthly_usage(
        self,
        client_id: str,
        year: int,
        month: int,
    ) -> Dict[str, Any]:
        """
        Агрегирует использование клиента за месяц.

        Returns:
            dict: total_checks, checks_by_task, tier, base_price, overage_checks, total_price
        """
        async with aiosqlite.connect(self.database_file) as db:
            db.row_factory = aiosqlite.Row

            # Получаем тариф клиента
            cursor = await db.execute(
                "SELECT tier, monthly_quota FROM b2b_clients WHERE client_id = ?",
                (client_id,),
            )
            client = await cursor.fetchone()
            if not client:
                raise ValueError(f"Client not found: {client_id}")

            tier = ClientTier(client["tier"])
            tier_limits = TIER_LIMITS.get(tier, TIER_LIMITS[ClientTier.BASIC])
            monthly_quota = client["monthly_quota"] or tier_limits.get("monthly_quota") or 0

            # Считаем проверки за месяц
            month_start = f"{year:04d}-{month:02d}-01"
            if month == 12:
                month_end = f"{year + 1:04d}-01-01"
            else:
                month_end = f"{year:04d}-{month + 1:02d}-01"

            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total,
                    task_number
                FROM b2b_checks
                WHERE client_id = ?
                  AND status = 'completed'
                  AND created_at >= ?
                  AND created_at < ?
                GROUP BY task_number
            """, (client_id, month_start, month_end))

            rows = await cursor.fetchall()

            checks_by_task = {}
            total_checks = 0
            for row in rows:
                task_num = str(row["task_number"])
                count = row["total"]
                checks_by_task[task_num] = count
                total_checks += count

            # Расчёт стоимости
            base_price = TIER_PRICES_RUB.get(tier, 0)
            overage_checks = max(0, total_checks - monthly_quota) if monthly_quota else 0
            overage_price = overage_checks * OVERAGE_PRICE_PER_CHECK_RUB
            total_price = base_price + overage_price

            return {
                "client_id": client_id,
                "year": year,
                "month": month,
                "tier": tier.value,
                "total_checks": total_checks,
                "checks_by_task": checks_by_task,
                "monthly_quota": monthly_quota,
                "base_price_rub": base_price,
                "overage_checks": overage_checks,
                "overage_price_rub": overage_price,
                "total_price_rub": total_price,
            }

    # ------------------------------------------------------------------ #
    #  Создание записи биллинга
    # ------------------------------------------------------------------ #

    async def create_billing_record(
        self,
        usage: Dict[str, Any],
    ) -> str:
        """
        Создаёт запись в b2b_billing_summary.

        Returns:
            invoice_id
        """
        invoice_id = f"inv_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self.database_file) as db:
            await db.execute("""
                INSERT INTO b2b_billing_summary (
                    client_id, year, month,
                    total_checks, checks_by_task,
                    tier, base_price_rub, overage_checks,
                    overage_price_rub, total_price_rub,
                    payment_status, invoice_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id, year, month) DO UPDATE SET
                    total_checks = excluded.total_checks,
                    checks_by_task = excluded.checks_by_task,
                    tier = excluded.tier,
                    base_price_rub = excluded.base_price_rub,
                    overage_checks = excluded.overage_checks,
                    overage_price_rub = excluded.overage_price_rub,
                    total_price_rub = excluded.total_price_rub,
                    invoice_id = excluded.invoice_id,
                    updated_at = excluded.updated_at
            """, (
                usage["client_id"], usage["year"], usage["month"],
                usage["total_checks"], json.dumps(usage["checks_by_task"]),
                usage["tier"], usage["base_price_rub"], usage["overage_checks"],
                usage["overage_price_rub"], usage["total_price_rub"],
                "pending", invoice_id,
                now, now,
            ))
            await db.commit()

        logger.info(
            f"Billing record created: {invoice_id} for {usage['client_id']} "
            f"({usage['year']}-{usage['month']:02d}): {usage['total_price_rub']}₽"
        )
        return invoice_id

    # ------------------------------------------------------------------ #
    #  Автосписание
    # ------------------------------------------------------------------ #

    async def charge_client(
        self,
        client_id: str,
        invoice_id: str,
        amount_rub: int,
        description: str,
    ) -> Dict[str, Any]:
        """
        Списывает деньги с привязанной карты клиента.

        Процесс:
        1. Init (без Recurrent=Y) — получаем PaymentId
        2. Charge с RebillId — фактическое списание
        """
        from payment.tinkoff import TinkoffPayment

        if amount_rub <= 0:
            # Бесплатный тариф или нулевой счёт
            await self._mark_paid(invoice_id, "free")
            return {"success": True, "status": "free", "amount": 0}

        # Получаем RebillId клиента
        async with aiosqlite.connect(self.database_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT rebill_id, contact_email, billing_active FROM b2b_clients WHERE client_id = ?",
                (client_id,),
            )
            client = await cursor.fetchone()

        if not client or not client["rebill_id"]:
            logger.warning(f"No RebillId for client {client_id}, cannot charge")
            return {"success": False, "error": "No card linked"}

        if not client["billing_active"]:
            logger.warning(f"Billing inactive for client {client_id}")
            return {"success": False, "error": "Billing inactive"}

        tinkoff = TinkoffPayment()
        order_id = f"b2b_{invoice_id}"
        amount_kopecks = amount_rub * 100

        # Шаг 1: Init
        init_result = await tinkoff.init_recurrent_payment(
            order_id=order_id,
            amount_kopecks=amount_kopecks,
            description=description,
            user_email=client["contact_email"],
        )

        if not init_result.get("success"):
            logger.error(f"Init failed for {client_id}: {init_result}")
            await self._mark_failed(invoice_id, init_result.get("error", "Init failed"))
            return {"success": False, "error": init_result.get("error")}

        payment_id = init_result["payment_id"]

        # Шаг 2: Charge
        charge_result = await tinkoff.charge_recurrent(
            payment_id=str(payment_id),
            rebill_id=client["rebill_id"],
        )

        if charge_result.get("success"):
            await self._mark_paid(invoice_id, str(payment_id))
            logger.info(
                f"Successfully charged {client_id}: {amount_rub}₽ "
                f"(payment_id={payment_id})"
            )
            return {
                "success": True,
                "status": "paid",
                "amount_rub": amount_rub,
                "payment_id": payment_id,
            }
        else:
            error = charge_result.get("error", "Charge failed")
            await self._mark_failed(invoice_id, error)
            logger.error(f"Charge failed for {client_id}: {error}")
            return {"success": False, "error": error}

    # ------------------------------------------------------------------ #
    #  Полный цикл биллинга для одного клиента
    # ------------------------------------------------------------------ #

    async def bill_client(
        self,
        client_id: str,
        year: int,
        month: int,
    ) -> Dict[str, Any]:
        """
        Полный цикл биллинга: агрегация → запись → списание.

        Returns:
            dict с результатом
        """
        # 1. Агрегация
        usage = await self.aggregate_monthly_usage(client_id, year, month)

        # 2. Создание записи
        invoice_id = await self.create_billing_record(usage)

        # 3. Списание
        description = (
            f"B2B подписка {usage['tier']} за "
            f"{usage['month']:02d}/{usage['year']}: "
            f"{usage['total_checks']} проверок"
        )

        result = await self.charge_client(
            client_id=client_id,
            invoice_id=invoice_id,
            amount_rub=usage["total_price_rub"],
            description=description,
        )

        return {
            "invoice_id": invoice_id,
            "usage": usage,
            "payment": result,
        }

    # ------------------------------------------------------------------ #
    #  Биллинг всех активных клиентов
    # ------------------------------------------------------------------ #

    async def bill_all_clients(self, year: int, month: int) -> list:
        """
        Выставляет счета всем активным платным клиентам.

        Returns:
            Список результатов биллинга
        """
        async with aiosqlite.connect(self.database_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT client_id, tier FROM b2b_clients
                WHERE status = 'active'
                  AND tier NOT IN ('free', 'trial')
                  AND billing_active = 1
            """)
            clients = await cursor.fetchall()

        results = []
        for client in clients:
            try:
                result = await self.bill_client(
                    client_id=client["client_id"],
                    year=year,
                    month=month,
                )
                results.append(result)
            except Exception as e:
                logger.error(
                    f"Billing failed for {client['client_id']}: {e}",
                    exc_info=True,
                )
                results.append({
                    "client_id": client["client_id"],
                    "error": str(e),
                })

        logger.info(f"Billing completed for {len(results)} clients ({year}-{month:02d})")
        return results

    # ------------------------------------------------------------------ #
    #  Получение истории биллинга
    # ------------------------------------------------------------------ #

    async def get_billing_history(
        self,
        client_id: str,
        limit: int = 12,
    ) -> list:
        """Возвращает историю биллинга клиента."""
        async with aiosqlite.connect(self.database_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM b2b_billing_summary
                WHERE client_id = ?
                ORDER BY year DESC, month DESC
                LIMIT ?
            """, (client_id, limit))
            rows = await cursor.fetchall()

            return [dict(row) for row in rows]

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы
    # ------------------------------------------------------------------ #

    async def _mark_paid(self, invoice_id: str, payment_id: str):
        """Помечает счёт как оплаченный."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database_file) as db:
            await db.execute("""
                UPDATE b2b_billing_summary
                SET payment_status = 'paid', paid_at = ?, updated_at = ?
                WHERE invoice_id = ?
            """, (now, now, invoice_id))
            await db.commit()

    async def _mark_failed(self, invoice_id: str, error: str):
        """Помечает счёт как неоплаченный с ошибкой."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database_file) as db:
            await db.execute("""
                UPDATE b2b_billing_summary
                SET payment_status = 'overdue', updated_at = ?
                WHERE invoice_id = ?
            """, (now, invoice_id))
            await db.commit()
        logger.warning(f"Invoice {invoice_id} marked as overdue: {error}")

    async def cancel_billing(self, client_id: str) -> Dict[str, Any]:
        """Отключает автосписание для клиента."""
        from payment.tinkoff import TinkoffPayment

        async with aiosqlite.connect(self.database_file) as db:
            await db.execute("""
                UPDATE b2b_clients
                SET billing_active = 0, rebill_id = NULL, updated_at = ?
                WHERE client_id = ?
            """, (datetime.now(timezone.utc).isoformat(), client_id))
            await db.commit()

        # Отменяем в Tinkoff
        tinkoff = TinkoffPayment()
        await tinkoff.cancel_recurrent(f"b2b_{client_id}")

        logger.info(f"Billing cancelled for {client_id}")
        return {"success": True, "client_id": client_id}
