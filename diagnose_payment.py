#!/usr/bin/env python3
"""
Диагностическая утилита для проверки статуса платежей и подписок пользователей
"""
import sqlite3
import sys
import os
from datetime import datetime

# Попытка найти правильный путь к БД
POSSIBLE_DB_PATHS = [
    'quiz_async.db',  # Основной путь из core/config.py
    'data/ege_superbot.db',
    '/opt/ege-bot/quiz_async.db',
    '../quiz_async.db',
]

DATABASE_FILE = None
for db_path in POSSIBLE_DB_PATHS:
    if os.path.exists(db_path):
        DATABASE_FILE = db_path
        break

if not DATABASE_FILE:
    print("❌ База данных не найдена!")
    print("Проверьте следующие пути:")
    for path in POSSIBLE_DB_PATHS:
        print(f"  - {os.path.abspath(path)}")
    sys.exit(1)

print(f"✅ Используется БД: {os.path.abspath(DATABASE_FILE)}\n")

def diagnose_user_payment(user_id: int):
    """
    Диагностика платежей и подписок конкретного пользователя
    """
    print(f"\n{'='*80}")
    print(f"🔍 ДИАГНОСТИКА ПЛАТЕЖЕЙ И ПОДПИСОК ДЛЯ ПОЛЬЗОВАТЕЛЯ {user_id}")
    print(f"{'='*80}\n")

    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Информация о пользователе
    print("📋 1. ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ")
    print("-" * 80)
    cursor.execute(
        """SELECT user_id, first_seen, is_subscribed, subscription_expires,
                  monthly_usage_count, username, first_name, last_name,
                  current_daily_streak, max_daily_streak
           FROM users WHERE user_id = ?""",
        (user_id,)
    )
    user = cursor.fetchone()

    if user:
        print(f"  User ID: {user['user_id']}")
        print(f"  Username: @{user['username']}" if user['username'] else "  Username: None")
        print(f"  Name: {user['first_name'] or ''} {user['last_name'] or ''}".strip())
        print(f"  First seen: {user['first_seen']}")
        print(f"  Is subscribed (legacy): {user['is_subscribed']}")
        print(f"  Subscription expires (legacy): {user['subscription_expires']}")
        print(f"  Monthly usage count: {user['monthly_usage_count']}")
        print(f"  Daily streak: {user['current_daily_streak']} (max: {user['max_daily_streak']})")
    else:
        print(f"  ❌ Пользователь {user_id} не найден в таблице users!")
        conn.close()
        return

    # 2. Платежи пользователя
    print(f"\n💳 2. ПЛАТЕЖИ ПОЛЬЗОВАТЕЛЯ")
    print("-" * 80)
    cursor.execute(
        """SELECT order_id, payment_id, amount_kopecks, amount, plan_id, status,
                  created_at, updated_at, completed_at, metadata, promo_code
           FROM payments
           WHERE user_id = ?
           ORDER BY created_at DESC""",
        (user_id,)
    )
    payments = cursor.fetchall()

    if payments:
        for i, payment in enumerate(payments, 1):
            # Используем amount если есть, иначе amount_kopecks / 100
            amount_rub = payment['amount'] if payment['amount'] else (payment['amount_kopecks'] / 100 if payment['amount_kopecks'] else 0)

            print(f"\n  Платеж #{i}:")
            print(f"    Order ID: {payment['order_id']}")
            print(f"    Payment ID: {payment['payment_id']}")
            print(f"    Amount: {amount_rub} руб")
            print(f"    Plan ID: {payment['plan_id']}")
            print(f"    Status: {payment['status']}")
            print(f"    Created: {payment['created_at']}")
            print(f"    Completed: {payment['completed_at']}")
            if payment['promo_code']:
                print(f"    Promo code: {payment['promo_code']}")
            print(f"    Metadata: {payment['metadata']}")

            # Проверка webhook logs для этого платежа
            try:
                cursor.execute(
                    """SELECT created_at, status, payment_id
                       FROM webhook_logs
                       WHERE order_id = ?
                       ORDER BY created_at DESC LIMIT 3""",
                    (payment['order_id'],)
                )
                webhooks = cursor.fetchall()

                if webhooks:
                    print(f"    Webhooks received: {len(webhooks)}")
                    for j, wh in enumerate(webhooks, 1):
                        print(f"      #{j}: {wh['created_at']} - Status: {wh['status']}")
                else:
                    print(f"    ℹ️  Webhooks: не найдены")
            except sqlite3.OperationalError as e:
                # Таблица webhook_logs может иметь другую структуру или отсутствовать
                print(f"    ⚠️  Webhooks: ошибка проверки ({e})")
    else:
        print("  ℹ️  Платежи не найдены")

    # 3. Модульные подписки
    print(f"\n📦 3. МОДУЛЬНЫЕ ПОДПИСКИ (module_subscriptions)")
    print("-" * 80)
    cursor.execute(
        """SELECT id, module_code, plan_id, is_active, is_trial,
                  created_at, expires_at, payment_id
           FROM module_subscriptions
           WHERE user_id = ?
           ORDER BY created_at DESC""",
        (user_id,)
    )
    module_subs = cursor.fetchall()

    if module_subs:
        now = datetime.now()
        for i, sub in enumerate(module_subs, 1):
            if sub['expires_at']:
                expires_at = datetime.fromisoformat(sub['expires_at'].replace('Z', '+00:00'))
                # Убираем timezone для корректного сравнения
                if expires_at.tzinfo is not None:
                    expires_at = expires_at.replace(tzinfo=None)
            else:
                expires_at = None
            is_expired = expires_at and expires_at < now
            status_icon = "✅" if sub['is_active'] and not is_expired else "❌"

            print(f"\n  Подписка #{i}: {status_icon}")
            print(f"    Module: {sub['module_code']}")
            print(f"    Plan ID: {sub['plan_id']}")
            print(f"    Is active: {sub['is_active']}")
            print(f"    Is trial: {sub['is_trial']}")
            print(f"    Created: {sub['created_at']}")
            print(f"    Expires: {sub['expires_at']}")
            if sub['payment_id']:
                print(f"    Payment ID: {sub['payment_id']}")
            if is_expired:
                print(f"    ⚠️  ИСТЕКЛА")
    else:
        print("  ❌ Модульные подписки не найдены!")

    # 4. Унифицированные подписки (user_subscriptions)
    print(f"\n🎫 4. УНИФИЦИРОВАННЫЕ ПОДПИСКИ (user_subscriptions)")
    print("-" * 80)
    try:
        cursor.execute(
            """SELECT id, plan_id, payment_id, status, starts_at, expires_at,
                      created_at, activated_at, cancelled_at
               FROM user_subscriptions
               WHERE user_id = ?
               ORDER BY created_at DESC""",
            (user_id,)
        )
        user_subs = cursor.fetchall()
    except sqlite3.OperationalError as e:
        user_subs = None
        print(f"  ⚠️  Ошибка при чтении user_subscriptions: {e}")

    if user_subs:
        now = datetime.now()
        for i, sub in enumerate(user_subs, 1):
            if sub['expires_at']:
                expires_at = datetime.fromisoformat(sub['expires_at'].replace('Z', '+00:00'))
                # Убираем timezone для корректного сравнения
                if expires_at.tzinfo is not None:
                    expires_at = expires_at.replace(tzinfo=None)
            else:
                expires_at = None

            # status может быть 'active', 'cancelled', 'expired'
            is_active = sub['status'] == 'active'
            is_expired = expires_at and expires_at < now
            status_icon = "✅" if is_active and not is_expired else "❌"

            print(f"\n  Подписка #{i}: {status_icon}")
            print(f"    Plan ID: {sub['plan_id']}")
            print(f"    Status: {sub['status']}")
            print(f"    Payment ID: {sub['payment_id']}")
            print(f"    Starts: {sub['starts_at']}")
            print(f"    Expires: {sub['expires_at']}")
            print(f"    Created: {sub['created_at']}")
            if sub['activated_at']:
                print(f"    Activated: {sub['activated_at']}")
            if sub['cancelled_at']:
                print(f"    Cancelled: {sub['cancelled_at']}")
            if is_expired:
                print(f"    ⚠️  ИСТЕКЛА")
    elif user_subs is not None:
        print("  ℹ️  Унифицированные подписки не найдены")

    # 5. Профиль учителя (если есть)
    print(f"\n👨‍🏫 5. ПРОФИЛЬ УЧИТЕЛЯ (teacher_profiles)")
    print("-" * 80)
    try:
        cursor.execute(
            """SELECT user_id, teacher_code, display_name, has_active_subscription,
                      subscription_tier, subscription_expires, created_at
               FROM teacher_profiles
               WHERE user_id = ?""",
            (user_id,)
        )
        teacher = cursor.fetchone()

        if teacher:
            print(f"  ✅ Профиль учителя найден")
            print(f"    User ID: {teacher['user_id']}")
            print(f"    Teacher Code: {teacher['teacher_code']}")
            print(f"    Display Name: {teacher['display_name']}")
            print(f"    Has Active Subscription: {teacher['has_active_subscription']}")
            print(f"    Subscription Tier: {teacher['subscription_tier']}")
            print(f"    Subscription Expires: {teacher['subscription_expires']}")
            print(f"    Created: {teacher['created_at']}")
        else:
            print("  ℹ️  Профиль учителя не найден")
    except sqlite3.OperationalError as e:
        print(f"  ⚠️  Ошибка при чтении teacher_profiles: {e}")

    # 6. Рекуррентные платежи
    print(f"\n🔄 6. РЕКУРРЕНТНЫЕ ПЛАТЕЖИ (recurrent_payments)")
    print("-" * 80)
    cursor.execute(
        """SELECT id, rebill_id, status, created_at, next_charge_date,
                  last_charge_date, failed_attempts
           FROM recurrent_payments
           WHERE user_id = ?
           ORDER BY created_at DESC""",
        (user_id,)
    )
    recurrent = cursor.fetchall()

    if recurrent:
        for i, rec in enumerate(recurrent, 1):
            print(f"\n  Рекуррентный платеж #{i}:")
            print(f"    Rebill ID: {rec['rebill_id']}")
            print(f"    Status: {rec['status']}")
            print(f"    Created: {rec['created_at']}")
            print(f"    Next charge: {rec['next_charge_date']}")
            print(f"    Last charge: {rec['last_charge_date']}")
            print(f"    Failed attempts: {rec['failed_attempts']}")
    else:
        print("  ℹ️  Рекуррентные платежи не найдены")

    # 7. Проверка доступа к модулям (текущая дата)
    print(f"\n🔐 7. ТЕКУЩИЙ ДОСТУП К МОДУЛЯМ")
    print("-" * 80)

    modules_to_check = ['test_part', 'task19', 'task20', 'task21', 'task22',
                       'task23', 'task24', 'task25', 'teacher_mode']

    for module in modules_to_check:
        cursor.execute(
            """SELECT id FROM module_subscriptions
               WHERE user_id = ?
                 AND module_code = ?
                 AND is_active = 1
                 AND expires_at > datetime('now')""",
            (user_id, module)
        )
        access = cursor.fetchone()
        status = "✅ ДОСТУП ЕСТЬ" if access else "❌ НЕТ ДОСТУПА"
        print(f"  {module}: {status}")

    conn.close()

    print(f"\n{'='*80}")
    print("✅ ДИАГНОСТИКА ЗАВЕРШЕНА")
    print(f"{'='*80}\n")


def check_incomplete_payments():
    """
    Находит платежи со статусом 'completed' без активных подписок
    """
    print(f"\n{'='*80}")
    print(f"🔍 ПОИСК НЕСОГЛАСОВАННЫХ ПЛАТЕЖЕЙ")
    print(f"{'='*80}\n")

    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ищем completed платежи без активных подписок
    cursor.execute(
        """
        SELECT DISTINCT p.order_id, p.user_id, p.plan_id,
                        COALESCE(p.amount, p.amount_kopecks/100) as amount_rub,
                        p.created_at, p.completed_at
        FROM payments p
        LEFT JOIN module_subscriptions ms
          ON p.user_id = ms.user_id
          AND ms.is_active = 1
          AND ms.expires_at > datetime('now')
        WHERE p.status = 'completed'
          AND ms.id IS NULL
        ORDER BY p.created_at DESC
        """
    )
    payments = cursor.fetchall()

    if payments:
        print(f"⚠️  Найдено {len(payments)} платежей без активных подписок:\n")
        for payment in payments:
            print(f"  User ID: {payment['user_id']}")
            print(f"  Order ID: {payment['order_id']}")
            print(f"  Plan: {payment['plan_id']}")
            print(f"  Amount: {payment['amount_rub']} руб")
            print(f"  Created: {payment['created_at']}")
            print(f"  Completed: {payment['completed_at']}")
            print("-" * 80)
    else:
        print("✅ Все completed платежи имеют активные подписки")

    conn.close()
    print()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python diagnose_payment.py <user_id>")
        print("  python diagnose_payment.py check_incomplete")
        print("\nExamples:")
        print("  python diagnose_payment.py 974972138")
        print("  python diagnose_payment.py 1893563949")
        print("  python diagnose_payment.py check_incomplete")
        sys.exit(1)

    if sys.argv[1] == "check_incomplete":
        check_incomplete_payments()
    else:
        try:
            user_id = int(sys.argv[1])
            diagnose_user_payment(user_id)
        except ValueError:
            print(f"❌ Ошибка: '{sys.argv[1]}' не является корректным user_id")
            sys.exit(1)


if __name__ == "__main__":
    main()
