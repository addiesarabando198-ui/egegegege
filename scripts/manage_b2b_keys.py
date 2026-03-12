#!/usr/bin/env python3
"""
Утилита для управления B2B клиентами и API-ключами.

Работает с существующим модулем b2b_api (таблицы b2b_clients, b2b_api_keys и т.д.).

Использование:
  python scripts/manage_b2b_keys.py create-client --name "Онлайн-школа Плюс" --email admin@school.ru --contact "Иванов Иван"
  python scripts/manage_b2b_keys.py create-key --client-id cli_xxx --name "Production"
  python scripts/manage_b2b_keys.py list-clients
  python scripts/manage_b2b_keys.py list-keys
  python scripts/manage_b2b_keys.py deactivate-key --key-id key_xxx
  python scripts/manage_b2b_keys.py stats
  python scripts/manage_b2b_keys.py apply-migration
"""

import argparse
import asyncio
import secrets
import sys
import os

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiosqlite
from core.config import DATABASE_FILE
from b2b_api.middleware.api_key_auth import generate_api_key


async def apply_migration():
    """Применяет миграцию B2B таблиц."""
    from b2b_api.migrations.apply_migration import apply_b2b_migration
    success = await apply_b2b_migration()
    if success:
        print("Migration applied successfully.")
    else:
        print("Migration failed! Check logs.")


async def create_client(
    company_name: str,
    contact_email: str,
    contact_name: str,
    tier: str = "trial",
    phone: str = None,
    website: str = None,
):
    """Создаёт нового B2B-клиента и API-ключ для него."""
    from datetime import datetime, timezone, timedelta

    client_id = f"cli_{secrets.token_hex(8)}"
    raw_key, key_hash = generate_api_key()
    key_id = f"key_{secrets.token_hex(8)}"

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            """
            INSERT INTO b2b_clients (
                client_id, company_name, contact_email, contact_name,
                contact_phone, website, status, tier, trial_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'trial', ?, ?)
            """,
            (
                client_id,
                company_name,
                contact_email,
                contact_name,
                phone,
                website,
                tier,
                (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
            ),
        )

        await db.execute(
            """
            INSERT INTO b2b_api_keys (
                key_id, client_id, key_hash, key_prefix, name, scopes, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                key_id,
                client_id,
                key_hash,
                raw_key[:16],
                "Production API Key",
                "check:create,check:read,questions:read",
            ),
        )
        await db.commit()

    print("=" * 60)
    print("B2B Client created successfully!")
    print(f"  Client ID:     {client_id}")
    print(f"  Company:       {company_name}")
    print(f"  Contact:       {contact_name} ({contact_email})")
    print(f"  Tier:          {tier}")
    print()
    print(f"  API Key ID:    {key_id}")
    print(f"  API KEY:       {raw_key}")
    print()
    print("  IMPORTANT: Save this API key now! It cannot be retrieved later.")
    print("=" * 60)


async def create_key(client_id: str, name: str = "API Key", scopes: str = None):
    """Создаёт дополнительный API-ключ для существующего клиента."""
    if scopes is None:
        scopes = "check:create,check:read,questions:read"

    raw_key, key_hash = generate_api_key()
    key_id = f"key_{secrets.token_hex(8)}"

    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Проверяем, что клиент существует
        cursor = await db.execute(
            "SELECT company_name FROM b2b_clients WHERE client_id = ?",
            (client_id,),
        )
        row = await cursor.fetchone()
        if not row:
            print(f"Error: Client '{client_id}' not found.")
            return

        await db.execute(
            """
            INSERT INTO b2b_api_keys (
                key_id, client_id, key_hash, key_prefix, name, scopes, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (key_id, client_id, key_hash, raw_key[:16], name, scopes),
        )
        await db.commit()

    print("=" * 60)
    print("API Key created successfully!")
    print(f"  Key ID:        {key_id}")
    print(f"  Client:        {client_id} ({row[0]})")
    print(f"  Name:          {name}")
    print(f"  Scopes:        {scopes}")
    print()
    print(f"  API KEY:       {raw_key}")
    print()
    print("  IMPORTANT: Save this API key now! It cannot be retrieved later.")
    print("=" * 60)


async def list_clients():
    """Показывает всех B2B-клиентов."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM b2b_api_keys
                    WHERE client_id = c.client_id AND is_active = 1) as active_keys
            FROM b2b_clients c
            ORDER BY c.created_at DESC
            """
        )
        rows = await cursor.fetchall()

    if not rows:
        print("No B2B clients found.")
        return

    print(
        f"{'Client ID':<20} | {'Company':<25} | {'Tier':<10} | "
        f"{'Status':<10} | {'Month':>6} | {'Quota':>6} | {'Keys':>4}"
    )
    print("-" * 100)

    for r in rows:
        print(
            f"{r['client_id']:<20} | {r['company_name'][:25]:<25} | "
            f"{r['tier']:<10} | {r['status']:<10} | "
            f"{r['checks_this_month']:>6} | "
            f"{(r['monthly_quota'] or '-'):>6} | "
            f"{r['active_keys']:>4}"
        )


async def list_keys():
    """Показывает все API-ключи."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT k.*, c.company_name
            FROM b2b_api_keys k
            LEFT JOIN b2b_clients c ON k.client_id = c.client_id
            ORDER BY k.created_at DESC
            """
        )
        rows = await cursor.fetchall()

    if not rows:
        print("No API keys found.")
        return

    print(
        f"{'Key ID':<20} | {'Prefix':<18} | {'Name':<20} | "
        f"{'Client':<20} | {'Used':>6} | {'Active':>6}"
    )
    print("-" * 100)

    for r in rows:
        print(
            f"{r['key_id']:<20} | {r['key_prefix']:<18} | "
            f"{r['name'][:20]:<20} | "
            f"{(r['company_name'] or '-')[:20]:<20} | "
            f"{r['usage_count']:>6} | "
            f"{'Yes' if r['is_active'] else 'No':>6}"
        )


async def deactivate_key(key_id: str):
    """Деактивирует API-ключ."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "UPDATE b2b_api_keys SET is_active = 0 WHERE key_id = ?",
            (key_id,),
        )
        if cursor.rowcount == 0:
            print(f"Error: Key '{key_id}' not found.")
            return
        await db.commit()
    print(f"API key '{key_id}' deactivated.")


async def show_stats(client_id: str = None):
    """Показывает статистику проверок."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row

        if client_id:
            cursor = await db.execute(
                """
                SELECT task_number, status, COUNT(*) as cnt,
                       AVG(processing_time_ms) as avg_time
                FROM b2b_checks
                WHERE client_id = ?
                GROUP BY task_number, status
                """,
                (client_id,),
            )
        else:
            cursor = await db.execute(
                """
                SELECT task_number, status, COUNT(*) as cnt,
                       AVG(processing_time_ms) as avg_time
                FROM b2b_checks
                GROUP BY task_number, status
                """
            )

        rows = await cursor.fetchall()

    if not rows:
        print("No checks found.")
        return

    print(f"{'Task #':<8} | {'Status':<12} | {'Count':>6} | {'Avg Time (ms)':>14}")
    print("-" * 50)
    for r in rows:
        avg_time = f"{r['avg_time']:.0f}" if r['avg_time'] else "-"
        print(
            f"{r['task_number']:<8} | {r['status']:<12} | "
            f"{r['cnt']:>6} | {avg_time:>14}"
        )


def main():
    parser = argparse.ArgumentParser(description="B2B API Client & Key Management")
    subparsers = parser.add_subparsers(dest="command")

    # apply migration
    subparsers.add_parser("apply-migration", help="Apply B2B database migration")

    # create client
    p_client = subparsers.add_parser("create-client", help="Create new B2B client with API key")
    p_client.add_argument("--name", required=True, help="Company name")
    p_client.add_argument("--email", required=True, help="Contact email")
    p_client.add_argument("--contact", required=True, help="Contact person name")
    p_client.add_argument("--tier", default="trial", help="Tier: free/trial/basic/standard/premium/enterprise")
    p_client.add_argument("--phone", default=None, help="Contact phone")
    p_client.add_argument("--website", default=None, help="Company website")

    # create key
    p_key = subparsers.add_parser("create-key", help="Create additional API key for existing client")
    p_key.add_argument("--client-id", required=True, help="Client ID (cli_xxx)")
    p_key.add_argument("--name", default="API Key", help="Key name/description")
    p_key.add_argument("--scopes", default=None, help="Scopes (comma-separated)")

    # list
    subparsers.add_parser("list-clients", help="List all B2B clients")
    subparsers.add_parser("list-keys", help="List all API keys")

    # deactivate key
    p_deact = subparsers.add_parser("deactivate-key", help="Deactivate an API key")
    p_deact.add_argument("--key-id", required=True, help="Key ID to deactivate (key_xxx)")

    # stats
    p_stats = subparsers.add_parser("stats", help="Show check statistics")
    p_stats.add_argument("--client-id", default=None, help="Filter by client ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "apply-migration":
        asyncio.run(apply_migration())
    elif args.command == "create-client":
        asyncio.run(
            create_client(args.name, args.email, args.contact, args.tier, args.phone, args.website)
        )
    elif args.command == "create-key":
        asyncio.run(create_key(args.client_id, args.name, args.scopes))
    elif args.command == "list-clients":
        asyncio.run(list_clients())
    elif args.command == "list-keys":
        asyncio.run(list_keys())
    elif args.command == "deactivate-key":
        asyncio.run(deactivate_key(args.key_id))
    elif args.command == "stats":
        asyncio.run(show_stats(args.client_id))


if __name__ == "__main__":
    main()
