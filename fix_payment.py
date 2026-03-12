#!/usr/bin/env python3
"""
Скрипт для исправления проблемных платежей.

Использование:
    python3 fix_payment.py <user_id>
    python3 fix_payment.py <user_id> --order-id <order_id>

Примеры:
    python3 fix_payment.py 6258384661
    python3 fix_payment.py 6258384661 --order-id order_6258384661_1234567890
"""

import sys
import sqlite3
from datetime import datetime, timedelta
import argparse


def fix_payment_for_user(user_id: int, order_id: str = None):
    """
    Исправляет платеж для пользователя.

    Args:
        user_id: ID пользователя
        order_id: ID заказа (опционально). Если не указан, будет исправлен последний платеж.
    """
    conn = sqlite3.connect('quiz_async.db')
    cursor = conn.cursor()

    print(f"\n{'='*80}")
    print(f"ИСПРАВЛЕНИЕ ПЛАТЕЖА ДЛЯ ПОЛЬЗОВАТЕЛЯ {user_id}")
    print('='*80)

    # Если order_id не указан, ищем последний платеж пользователя
    if not order_id:
        cursor.execute(
            """
            SELECT order_id, payment_id, plan_id, status, created_at
            FROM payments
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,)
        )
        result = cursor.fetchone()

        if not result:
            print(f"❌ Платежи не найдены для пользователя {user_id}")
            conn.close()
            return False

        order_id, payment_id, plan_id, status, created_at = result
        print(f"\n🔍 Найден последний платеж:")
        print(f"   Order ID: {order_id}")
        print(f"   Payment ID: {payment_id}")
        print(f"   Plan ID: {plan_id}")
        print(f"   Status: {status}")
        print(f"   Created At: {created_at}")
    else:
        # Проверяем, существует ли указанный order_id
        cursor.execute(
            """
            SELECT payment_id, plan_id, status, created_at, user_id
            FROM payments
            WHERE order_id = ?
            """,
            (order_id,)
        )
        result = cursor.fetchone()

        if not result:
            print(f"❌ Платеж с order_id {order_id} не найден")
            conn.close()
            return False

        payment_id, plan_id, status, created_at, db_user_id = result

        if db_user_id != user_id:
            print(f"⚠️  ВНИМАНИЕ: Order ID {order_id} принадлежит пользователю {db_user_id}, а не {user_id}!")
            response = input("Продолжить? (yes/no): ")
            if response.lower() != 'yes':
                conn.close()
                return False
            user_id = db_user_id

        print(f"\n🔍 Найден платеж:")
        print(f"   Order ID: {order_id}")
        print(f"   Payment ID: {payment_id}")
        print(f"   Plan ID: {plan_id}")
        print(f"   Status: {status}")
        print(f"   Created At: {created_at}")

    # Проверяем активные подписки
    cursor.execute(
        """
        SELECT id, module_code, plan_id, expires_at, is_active
        FROM module_subscriptions
        WHERE user_id = ? AND is_active = 1
        """,
        (user_id,)
    )
    subscriptions = cursor.fetchall()

    print(f"\n📋 Текущие активные подписки:")
    if subscriptions:
        for sub in subscriptions:
            sub_id, module_code, sub_plan_id, expires_at, is_active = sub
            print(f"   - {module_code} (план: {sub_plan_id}, истекает: {expires_at})")
    else:
        print(f"   ❌ Нет активных подписок")

    # Проверяем статус платежа
    if status == 'completed':
        if subscriptions:
            print(f"\n✅ Платеж имеет статус 'completed' и есть активные подписки.")
            print(f"   Исправление не требуется!")
            conn.close()
            return True
        else:
            print(f"\n⚠️  ПРОБЛЕМА: Платеж имеет статус 'completed', но НЕТ активных подписок!")
            print(f"   Это указывает на то, что активация подписки не удалась.")
    elif status == 'failed':
        if subscriptions:
            print(f"\n⚠️  ПРОБЛЕМА: Платеж имеет статус 'failed', НО ЕСТЬ активные подписки!")
            print(f"   Нужно изменить статус на 'completed'.")

            response = input("\nИзменить статус на 'completed'? (yes/no): ")
            if response.lower() == 'yes':
                cursor.execute(
                    """
                    UPDATE payments
                    SET status = 'completed',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                    """,
                    (order_id,)
                )
                conn.commit()
                print(f"✅ Статус платежа изменен на 'completed'")
                conn.close()
                return True
            else:
                print(f"❌ Изменения не внесены")
                conn.close()
                return False
        else:
            print(f"\n⚠️  Платеж имеет статус 'failed' и НЕТ активных подписок.")
            print(f"   Это ожидаемое поведение для неудачного платежа.")
            conn.close()
            return False
    elif status in ['pending', 'NEW']:
        print(f"\n⚠️  Платеж имеет статус '{status}' - платеж не был подтвержден.")

        if subscriptions:
            print(f"   Но есть активные подписки - возможно webhook не обработался правильно.")
            response = input(f"\nИзменить статус на 'completed'? (yes/no): ")
            if response.lower() == 'yes':
                cursor.execute(
                    """
                    UPDATE payments
                    SET status = 'completed',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                    """,
                    (order_id,)
                )
                conn.commit()
                print(f"✅ Статус платежа изменен на 'completed'")
                conn.close()
                return True
            else:
                print(f"❌ Изменения не внесены")
                conn.close()
                return False
        else:
            print(f"   Нет активных подписок - платеж действительно не был обработан.")
            conn.close()
            return False

    conn.close()
    return False


def main():
    parser = argparse.ArgumentParser(
        description='Исправление проблемных платежей',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s 6258384661
  %(prog)s 6258384661 --order-id order_6258384661_1234567890
        """
    )
    parser.add_argument('user_id', type=int, help='ID пользователя')
    parser.add_argument('--order-id', type=str, help='ID заказа (опционально)')

    args = parser.parse_args()

    try:
        fix_payment_for_user(args.user_id, args.order_id)
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
