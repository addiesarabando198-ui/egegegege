#!/usr/bin/env python3
"""Быстрая проверка plan_id для пользователя 974972138."""

import sqlite3
import sys

DB_PATH = '/opt/ege-bot/quiz_async.db'
USER_ID = 974972138

try:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print(f"🔍 Проверка plan_id для user_id={USER_ID}\n")

    # Все подписки пользователя
    cursor.execute("""
        SELECT module_code, plan_id, is_active,
               datetime(expires_at) as expires,
               datetime(created_at) as created
        FROM module_subscriptions
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (USER_ID,))

    rows = cursor.fetchall()

    if not rows:
        print(f"❌ Подписки для user_id={USER_ID} не найдены")
        sys.exit(1)

    print(f"Найдено подписок: {len(rows)}\n")

    # Группируем по plan_id
    plans = {}
    for row in rows:
        plan = row['plan_id']
        if plan not in plans:
            plans[plan] = []
        plans[plan].append(row)

    print("📋 Plan ID используемые в подписках:")
    for plan_id, modules in plans.items():
        print(f"\n  Plan: {plan_id}")
        print(f"  Модулей: {len(modules)}")
        print(f"  Активен: {modules[0]['is_active']}")
        print(f"  Истекает: {modules[0]['expires']}")
        print(f"  Создан: {modules[0]['created']}")

        # Показываем первые 3 модуля
        print(f"  Модули: {', '.join([m['module_code'] for m in modules[:3]])}", end='')
        if len(modules) > 3:
            print(f" ... (еще {len(modules)-3})")
        else:
            print()

    # Проверяем trial_history
    print("\n\n🔍 Проверка trial_history:")
    cursor.execute("""
        SELECT datetime(trial_activated_at) as activated,
               datetime(trial_expires_at) as expires
        FROM trial_history
        WHERE user_id = ?
    """, (USER_ID,))

    trial = cursor.fetchone()
    if trial:
        print(f"  ✅ Trial был активирован: {trial['activated']}")
        print(f"  📅 Trial истекает: {trial['expires']}")
    else:
        print("  ℹ️  Trial не найден в истории")

    # Проверяем payments
    print("\n\n💳 Проверка платежей:")
    cursor.execute("""
        SELECT order_id, plan_id, status,
               COALESCE(amount, amount_kopecks/100) as amount_rub,
               datetime(created_at) as created,
               datetime(completed_at) as completed
        FROM payments
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (USER_ID,))

    payments = cursor.fetchall()
    if payments:
        for p in payments:
            print(f"\n  Order: {p['order_id']}")
            print(f"  Plan: {p['plan_id']}")
            print(f"  Status: {p['status']}")
            print(f"  Amount: {p['amount_rub']}₽")
            print(f"  Created: {p['created']}")
            print(f"  Completed: {p['completed']}")
    else:
        print("  ℹ️  Платежи не найдены")

    conn.close()

    # Итоговый вердикт
    print("\n" + "="*60)
    print("📊 ВЕРДИКТ:")
    print("="*60)

    main_plan = list(plans.keys())[0] if plans else None
    if main_plan == 'trial_7days':
        print("✅ Plan ID корректный: trial_7days")

        # Вычисляем фактическую длительность
        if plans[main_plan]:
            from datetime import datetime
            first_module = plans[main_plan][0]
            created = datetime.fromisoformat(first_module['created'])
            expires = datetime.fromisoformat(first_module['expires'])
            duration_days = (expires - created).days

            print(f"   Created: {first_module['created']}")
            print(f"   Expires: {first_module['expires']}")
            print(f"   Фактическая длительность: {duration_days} дней")

            if duration_days > 10:
                print(f"\n❌ НАЙДЕНА ПРОБЛЕМА!")
                print(f"   Ожидалось: 7 дней")
                print(f"   Получено: {duration_days} дней")
                print(f"\n   При ручной активации была указана неправильная дата expires_at")
                print(f"   Использовано: datetime('now', '+{duration_days} days')")
                print(f"   Нужно было: datetime('now', '+7 days')")
            else:
                print("   ✅ Длительность корректная (7 дней)")
    elif main_plan == 'package_full':
        print("❌ НАЙДЕНА ПРОБЛЕМА!")
        print("   Plan ID: package_full (30 дней)")
        print("   Ожидалось: trial_7days (7 дней)")
        print("\n   Пользователь получил package_full вместо trial_7days")
        print("   при ручной активации.")
    else:
        print(f"ℹ️  Plan ID: {main_plan}")

except Exception as e:
    print(f"❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
