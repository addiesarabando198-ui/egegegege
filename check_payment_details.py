#!/usr/bin/env python3
"""
Детальная проверка платежа и webhook логов
"""

import sqlite3
from datetime import datetime

def check_payment_details(order_id: str):
    conn = sqlite3.connect('quiz_async.db')
    cursor = conn.cursor()

    print(f"\n{'='*80}")
    print(f"ДЕТАЛЬНАЯ ПРОВЕРКА ПЛАТЕЖА")
    print('='*80)

    # Получаем информацию о платеже
    cursor.execute(
        """
        SELECT payment_id, order_id, user_id, plan_id, amount, status,
               created_at, completed_at, metadata, rebill_id, is_recurrent, email
        FROM payments
        WHERE order_id = ?
        """,
        (order_id,)
    )
    payment = cursor.fetchone()

    if not payment:
        print(f"❌ Платеж не найден")
        conn.close()
        return

    payment_id, order_id, user_id, plan_id, amount, status, created_at, completed_at, metadata, rebill_id, is_recurrent, email = payment

    print(f"\n🔍 ИНФОРМАЦИЯ О ПЛАТЕЖЕ:")
    print(f"   Payment ID: {payment_id}")
    print(f"   Order ID: {order_id}")
    print(f"   User ID: {user_id}")
    print(f"   Plan ID: {plan_id}")
    print(f"   Amount: {amount} коп. ({amount/100:.2f} руб.)")
    print(f"   Status: {status}")
    print(f"   Created At: {created_at}")
    print(f"   Completed At: {completed_at}")
    print(f"   Email: {email}")
    print(f"   Metadata: {metadata}")
    print(f"   Rebill ID: {rebill_id}")
    print(f"   Is Recurrent: {is_recurrent}")

    # Проверяем webhook логи
    print(f"\n📨 WEBHOOK ЛОГИ:")
    cursor.execute(
        """
        SELECT id, order_id, status, payment_id, created_at, raw_data
        FROM webhook_logs
        WHERE order_id = ?
        ORDER BY created_at DESC
        """,
        (order_id,)
    )
    webhooks = cursor.fetchall()

    if webhooks:
        for wh in webhooks:
            wh_id, wh_order_id, wh_status, wh_payment_id, wh_created_at, raw_data = wh
            print(f"\n   🔹 Webhook ID: {wh_id}")
            print(f"      Status: {wh_status}")
            print(f"      Payment ID: {wh_payment_id}")
            print(f"      Created At: {wh_created_at}")
            print(f"      Raw Data: {raw_data[:200]}..." if len(raw_data) > 200 else f"      Raw Data: {raw_data}")
    else:
        print(f"   ❌ Webhook логи не найдены для этого order_id")
        print(f"   Это означает, что webhook от Tinkoff НЕ был получен или обработан.")

    # Проверяем подписки пользователя
    print(f"\n📋 ПОДПИСКИ ПОЛЬЗОВАТЕЛЯ {user_id}:")
    cursor.execute(
        """
        SELECT id, module_code, plan_id, expires_at, is_active, created_at
        FROM module_subscriptions
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    )
    subscriptions = cursor.fetchall()

    if subscriptions:
        for sub in subscriptions:
            sub_id, module_code, sub_plan_id, expires_at, is_active, sub_created_at = sub
            status_emoji = "✅" if is_active else "❌"
            print(f"\n   {status_emoji} ID: {sub_id}")
            print(f"      Module: {module_code}")
            print(f"      Plan: {sub_plan_id}")
            print(f"      Expires At: {expires_at}")
            print(f"      Is Active: {is_active}")
            print(f"      Created At: {sub_created_at}")
    else:
        print(f"   ❌ Нет подписок (ни активных, ни истекших)")

    # Проверяем историю уведомлений
    print(f"\n📬 ИСТОРИЯ УВЕДОМЛЕНИЙ:")
    try:
        cursor.execute(
            """
            SELECT id, user_id, order_id, notification_type
            FROM notification_history
            WHERE order_id = ?
            ORDER BY id DESC
            """,
            (order_id,)
        )
        notifications = cursor.fetchall()

        if notifications:
            for notif in notifications:
                notif_id, notif_user_id, notif_order_id, notif_type = notif
                print(f"\n   📧 Notification ID: {notif_id}")
                print(f"      Type: {notif_type}")
        else:
            print(f"   ❌ Уведомления не отправлялись")
    except Exception as e:
        print(f"   ⚠️  Не удалось получить историю уведомлений: {e}")

    # Все платежи пользователя
    print(f"\n📊 ВСЕ ПЛАТЕЖИ ПОЛЬЗОВАТЕЛЯ {user_id}:")
    cursor.execute(
        """
        SELECT payment_id, order_id, plan_id, amount, status, created_at
        FROM payments
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (user_id,)
    )
    all_payments = cursor.fetchall()

    for pay in all_payments:
        pay_id, pay_order_id, pay_plan_id, pay_amount, pay_status, pay_created_at = pay
        is_current = "👉 " if pay_order_id == order_id else "   "
        print(f"\n   {is_current}Payment ID: {pay_id}")
        print(f"      Order ID: {pay_order_id}")
        print(f"      Plan: {pay_plan_id}")
        print(f"      Amount: {pay_amount/100:.2f} руб.")
        print(f"      Status: {pay_status}")
        print(f"      Created At: {pay_created_at}")

    print(f"\n{'='*80}")
    print(f"ДИАГНОСТИКА:")
    print('='*80)

    if status == 'NEW':
        print(f"\n⚠️  Статус платежа: 'NEW'")

        if webhooks:
            # Webhook'и были получены, но платеж не активирован
            confirmed_count = sum(1 for wh in webhooks if wh[2] == 'CONFIRMED')
            authorized_count = sum(1 for wh in webhooks if wh[2] == 'AUTHORIZED')

            print(f"\n🔴 КРИТИЧЕСКАЯ ПРОБЛЕМА:")
            print(f"   ✅ Платеж был ОПЛАЧЕН (Amount: {amount/100:.2f} руб.)")
            print(f"   ✅ Webhook'и БЫЛИ ПОЛУЧЕНЫ ({len(webhooks)} шт.)")
            print(f"      - CONFIRMED: {confirmed_count}")
            print(f"      - AUTHORIZED: {authorized_count}")
            print(f"   ❌ НО статус платежа остался 'NEW'")
            print(f"   ❌ Подписки НЕ СОЗДАНЫ")
            print()
            print(f"   Причина:")
            print(f"   Это баг в старом коде обработки webhook'ов.")
            print(f"   Webhook'и были получены, но из-за ошибки в логике")
            print(f"   обработки дубликатов активация не произошла.")
            print()
            print(f"   📋 РЕШЕНИЕ:")
            print(f"   1. Активировать подписку ВРУЧНУЮ:")
            print(f"      cd /opt/ege-bot")
            print(f"      python3 manual_activate_subscription.py {order_id}")
            print()
            print(f"   2. ОБЯЗАТЕЛЬНО обновить код на сервере и перезапустить бота!")
            print(f"      git pull")
            print(f"      systemctl restart ege-bot  # или как у вас называется сервис")
            print()
            print(f"   Баг уже исправлен в новой версии кода.")
        else:
            # Webhook'ов нет
            print(f"   Это означает, что:")
            print(f"   1. Платеж был создан в системе Tinkoff")
            print(f"   2. Webhook от Tinkoff НЕ был получен")
            print(f"   3. Возможные причины:")
            print(f"      - Пользователь не завершил оплату")
            print(f"      - Оплата была отклонена банком")
            print(f"      - Webhook не дошел до сервера (проблемы с сетью)")
            print(f"      - Webhook был отправлен, но не был обработан (ошибка в коде)")

            print(f"\n   ❌ Webhook логи ОТСУТСТВУЮТ")
            print(f"   Рекомендации:")
            print(f"   1. Проверить в личном кабинете Tinkoff, был ли платеж оплачен")
            print(f"   2. Если оплачен, но webhook не пришел - проверить настройки webhook URL")
            print(f"   3. Если нужно активировать вручную - использовать:")
            print(f"      python3 manual_activate_subscription.py {order_id}")

    conn.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 check_payment_details.py <order_id>")
        sys.exit(1)

    order_id = sys.argv[1]
    check_payment_details(order_id)
