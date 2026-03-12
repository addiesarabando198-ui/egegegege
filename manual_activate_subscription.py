#!/usr/bin/env python3
"""
Вручную активирует подписку для платежа.
Используйте только если уверены, что платеж был оплачен в Tinkoff!

Usage: python3 manual_activate_subscription.py <order_id>
"""

import sys
import asyncio
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, '/opt/ege-bot')

from payment.subscription_manager import SubscriptionManager


async def manual_activate(order_id: str):
    """Вручную активирует подписку для order_id."""

    print(f"\n{'='*80}")
    print(f"РУЧНАЯ АКТИВАЦИЯ ПОДПИСКИ")
    print('='*80)
    print(f"Order ID: {order_id}")
    print()

    # Создаем subscription manager
    manager = SubscriptionManager()

    # Проверяем, не активирован ли уже
    is_activated = await manager.is_payment_already_activated(order_id)

    if is_activated:
        print(f"✅ Подписка уже активирована для этого платежа!")
        return True

    print(f"⚠️  Подписка НЕ активирована. Начинаю активацию...")

    # Активируем
    success = await manager.activate_subscription(order_id=order_id)

    if success:
        print(f"\n✅ УСПЕШНО! Подписка активирована для order_id: {order_id}")
        print(f"\nПроверьте результат:")
        print(f"  python3 check_payment_details.py {order_id}")
        return True
    else:
        print(f"\n❌ ОШИБКА! Не удалось активировать подписку.")
        print(f"Проверьте логи для деталей.")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 manual_activate_subscription.py <order_id>")
        print()
        print("Example:")
        print("  python3 manual_activate_subscription.py order_6258384661_1761646304_2017e6a6")
        sys.exit(1)

    order_id = sys.argv[1]

    print()
    print("="*80)
    print("ВНИМАНИЕ!")
    print("="*80)
    print("Этот скрипт вручную активирует подписку для указанного платежа.")
    print("Используйте его ТОЛЬКО если:")
    print("  1. Вы проверили в личном кабинете Tinkoff, что платеж ОПЛАЧЕН")
    print("  2. Webhook от Tinkoff не был получен или обработан")
    print("  3. Пользователь действительно оплатил, но не получил доступ")
    print()
    print("НЕПРАВИЛЬНОЕ использование приведет к предоставлению бесплатного доступа!")
    print("="*80)
    print()

    response = input(f"Вы уверены, что хотите активировать подписку для {order_id}? (yes/no): ")

    if response.lower() != 'yes':
        print("Отменено.")
        sys.exit(0)

    # Запускаем активацию
    success = asyncio.run(manual_activate(order_id))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
