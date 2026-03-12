"""
Применение миграции для B2B API.
"""

import logging
import aiosqlite
import asyncio
import os
from datetime import datetime, timezone, timedelta

from core.db import DATABASE_FILE
from b2b_api.middleware.api_key_auth import generate_api_key

logger = logging.getLogger(__name__)

MIGRATION_DIR = os.path.dirname(__file__)
MIGRATION_FILE = os.path.join(MIGRATION_DIR, 'b2b_tables.sql')
MIGRATION_002_FILE = os.path.join(MIGRATION_DIR, '002_add_idempotency_and_variant_checks.sql')


async def apply_incremental_migrations():
    """Применяет инкрементальные миграции (002+)."""
    migrations = [
        ("002_idempotency_variant_checks", MIGRATION_002_FILE),
    ]

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Создаём таблицу миграций если нет
            await db.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)
            await db.commit()

            for name, filepath in migrations:
                # Проверяем, применена ли миграция
                cursor = await db.execute(
                    "SELECT 1 FROM _migrations WHERE name = ?", (name,)
                )
                if await cursor.fetchone():
                    logger.debug(f"Migration {name} already applied, skipping")
                    continue

                if not os.path.exists(filepath):
                    logger.warning(f"Migration file not found: {filepath}")
                    continue

                # Применяем миграцию
                with open(filepath, 'r', encoding='utf-8') as f:
                    sql_script = f.read()

                try:
                    await db.executescript(sql_script)
                    await db.execute(
                        "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
                        (name, datetime.now(timezone.utc).isoformat())
                    )
                    await db.commit()
                    logger.info(f"Applied migration: {name}")
                except Exception as e:
                    logger.error(f"Error applying migration {name}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error in incremental migrations: {e}", exc_info=True)


async def apply_b2b_migration():
    """
    Применяет миграцию для B2B API.

    Создает:
    - b2b_clients: клиенты
    - b2b_api_keys: API ключи
    - b2b_checks: очередь проверок
    - b2b_api_logs: логи запросов
    - b2b_webhook_deliveries: доставка webhook
    - b2b_billing_summary: биллинг
    """
    logger.info("Starting B2B API migration...")

    try:
        # Читаем SQL файл
        with open(MIGRATION_FILE, 'r', encoding='utf-8') as f:
            sql_script = f.read()

        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Выполняем миграцию
            await db.executescript(sql_script)
            await db.commit()

            logger.info("✓ B2B tables created successfully")

            # Проверяем, есть ли тестовый клиент
            cursor = await db.execute(
                "SELECT COUNT(*) FROM b2b_clients WHERE client_id = 'cli_demo'"
            )
            count = (await cursor.fetchone())[0]

            if count == 0:
                # Создаём демо-клиента для тестирования
                demo_client_id = "cli_demo"
                demo_key, demo_key_hash = generate_api_key("b2b_demo")

                await db.execute("""
                    INSERT INTO b2b_clients (
                        client_id,
                        company_name,
                        contact_email,
                        contact_name,
                        status,
                        tier,
                        rate_limit_per_minute,
                        rate_limit_per_day,
                        monthly_quota,
                        trial_expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    demo_client_id,
                    "Demo Company (Тестовый клиент)",
                    "demo@example.com",
                    "Demo User",
                    "trial",
                    "trial",
                    10,
                    200,
                    500,
                    (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
                ))

                await db.execute("""
                    INSERT INTO b2b_api_keys (
                        key_id,
                        client_id,
                        key_hash,
                        key_prefix,
                        name,
                        scopes,
                        is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    "key_demo_001",
                    demo_client_id,
                    demo_key_hash,
                    demo_key[:16],
                    "Demo API Key",
                    "check:create,check:read,questions:read",
                    1
                ))

                await db.commit()

                logger.info("✓ Demo client created")
                logger.info(f"  Client ID: {demo_client_id}")
                logger.info(f"  API Key: {demo_key}")
                logger.info("  (Save this key! It won't be shown again)")

            logger.info("B2B base migration completed successfully!")

            # Применяем инкрементальные миграции
            await apply_incremental_migrations()

            logger.info("B2B API migration completed successfully!")
            return True

    except Exception as e:
        logger.error(f"Error applying B2B migration: {e}", exc_info=True)
        return False


async def reset_daily_counters():
    """Сбрасывает дневные счётчики для всех клиентов."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE b2b_clients
                SET checks_today = 0,
                    last_daily_reset = ?
                WHERE checks_today > 0
            """, (datetime.now(timezone.utc).isoformat(),))
            await db.commit()

            logger.info("B2B daily counters reset")

    except Exception as e:
        logger.error(f"Error resetting B2B daily counters: {e}")


async def reset_monthly_counters():
    """Сбрасывает месячные счётчики и создаёт записи биллинга."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = datetime.now(timezone.utc)

            # Получаем всех клиентов с использованием
            cursor = await db.execute("""
                SELECT client_id, tier, checks_this_month, monthly_quota
                FROM b2b_clients
                WHERE checks_this_month > 0
            """)
            clients = await cursor.fetchall()

            for client_id, tier, checks, quota in clients:
                # Создаём запись биллинга за прошлый месяц
                prev_month = now.month - 1 if now.month > 1 else 12
                prev_year = now.year if now.month > 1 else now.year - 1

                await db.execute("""
                    INSERT OR REPLACE INTO b2b_billing_summary (
                        client_id,
                        year,
                        month,
                        total_checks,
                        tier,
                        payment_status
                    ) VALUES (?, ?, ?, ?, ?, 'pending')
                """, (client_id, prev_year, prev_month, checks, tier))

            # Сбрасываем счётчики
            await db.execute("""
                UPDATE b2b_clients
                SET checks_this_month = 0,
                    last_monthly_reset = ?
                WHERE checks_this_month > 0
            """, (now.isoformat(),))

            await db.commit()
            logger.info(f"B2B monthly counters reset for {len(clients)} clients")

    except Exception as e:
        logger.error(f"Error resetting B2B monthly counters: {e}")


async def create_client(
    company_name: str,
    contact_email: str,
    contact_name: str,
    tier: str = "trial",
    **kwargs
) -> tuple:
    """
    Создаёт нового B2B клиента.

    Returns:
        (client_id, api_key) или (None, None) при ошибке
    """
    import secrets

    try:
        client_id = f"cli_{secrets.token_hex(8)}"
        raw_key, key_hash = generate_api_key()
        key_id = f"key_{secrets.token_hex(8)}"

        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Создаём клиента
            await db.execute("""
                INSERT INTO b2b_clients (
                    client_id,
                    company_name,
                    contact_email,
                    contact_name,
                    contact_phone,
                    website,
                    status,
                    tier,
                    trial_expires_at,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, 'trial', ?, ?, ?)
            """, (
                client_id,
                company_name,
                contact_email,
                contact_name,
                kwargs.get('contact_phone'),
                kwargs.get('website'),
                tier,
                (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
                kwargs.get('notes')
            ))

            # Создаём API ключ
            await db.execute("""
                INSERT INTO b2b_api_keys (
                    key_id,
                    client_id,
                    key_hash,
                    key_prefix,
                    name,
                    scopes,
                    is_active
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (
                key_id,
                client_id,
                key_hash,
                raw_key[:16],
                "Production API Key",
                "check:create,check:read,questions:read"
            ))

            await db.commit()

            logger.info(f"Created B2B client: {client_id} ({company_name})")
            return client_id, raw_key

    except Exception as e:
        logger.error(f"Error creating B2B client: {e}")
        return None, None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    async def main():
        print("Applying B2B API migration...")
        success = await apply_b2b_migration()

        if success:
            print("\n✓ Migration successful!")
            print("\nTo create a new client, use:")
            print("  from b2b_api.migrations.apply_migration import create_client")
            print("  client_id, api_key = await create_client('Company', 'email@example.com', 'Contact Name')")
        else:
            print("\n✗ Migration failed!")

    asyncio.run(main())
