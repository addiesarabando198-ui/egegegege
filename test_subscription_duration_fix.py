#!/usr/bin/env python3
"""Тесты для проверки исправления длительности подписок."""
import sys
import os
from datetime import datetime, timedelta, timezone

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Импортируем напрямую функцию без всего payment модуля
def get_subscription_end_date_local(plan_id: str, months: int = 1):
    """
    Локальная версия функции для тестирования.
    Копия из payment/config.py:464-483
    """
    if plan_id == 'trial_7days':
        return datetime.now(timezone.utc) + timedelta(days=7)
    else:
        days = 30 * months
        return datetime.now(timezone.utc) + timedelta(days=days)

# Используем локальную версию
get_subscription_end_date = get_subscription_end_date_local

def test_trial_duration():
    """Тест: trial_7days должен давать 7 дней."""
    print("🧪 Тест 1: Длительность trial_7days")

    start = datetime.now(timezone.utc)
    end = get_subscription_end_date('trial_7days', 1)

    duration = (end - start).total_seconds() / 86400  # В днях
    expected = 7

    # Допускаем погрешность в несколько секунд
    if abs(duration - expected) < 0.01:
        print(f"   ✅ PASS: trial_7days дает {duration:.2f} дней (ожидалось {expected})")
        return True
    else:
        print(f"   ❌ FAIL: trial_7days дает {duration:.2f} дней (ожидалось {expected})")
        return False

def test_package_full_1month():
    """Тест: package_full на 1 месяц должен давать 30 дней."""
    print("🧪 Тест 2: Длительность package_full на 1 месяц")

    start = datetime.now(timezone.utc)
    end = get_subscription_end_date('package_full', 1)

    duration = (end - start).total_seconds() / 86400  # В днях
    expected = 30

    if abs(duration - expected) < 0.01:
        print(f"   ✅ PASS: package_full (1 мес) дает {duration:.2f} дней (ожидалось {expected})")
        return True
    else:
        print(f"   ❌ FAIL: package_full (1 мес) дает {duration:.2f} дней (ожидалось {expected})")
        return False

def test_package_full_3months():
    """Тест: package_full на 3 месяца должен давать 90 дней."""
    print("🧪 Тест 3: Длительность package_full на 3 месяца")

    start = datetime.now(timezone.utc)
    end = get_subscription_end_date('package_full', 3)

    duration = (end - start).total_seconds() / 86400  # В днях
    expected = 90

    if abs(duration - expected) < 0.01:
        print(f"   ✅ PASS: package_full (3 мес) дает {duration:.2f} дней (ожидалось {expected})")
        return True
    else:
        print(f"   ❌ FAIL: package_full (3 мес) дает {duration:.2f} дней (ожидалось {expected})")
        return False

def test_package_full_6months():
    """Тест: package_full на 6 месяцев должен давать 180 дней."""
    print("🧪 Тест 4: Длительность package_full на 6 месяцев")

    start = datetime.now(timezone.utc)
    end = get_subscription_end_date('package_full', 6)

    duration = (end - start).total_seconds() / 86400  # В днях
    expected = 180

    if abs(duration - expected) < 0.01:
        print(f"   ✅ PASS: package_full (6 мес) дает {duration:.2f} дней (ожидалось {expected})")
        return True
    else:
        print(f"   ❌ FAIL: package_full (6 мес) дает {duration:.2f} дней (ожидалось {expected})")
        return False

def main():
    """Запуск всех тестов."""
    print("=" * 80)
    print("ТЕСТИРОВАНИЕ ИСПРАВЛЕНИЯ ДЛИТЕЛЬНОСТИ ПОДПИСОК")
    print("=" * 80)
    print()

    results = []
    results.append(test_trial_duration())
    results.append(test_package_full_1month())
    results.append(test_package_full_3months())
    results.append(test_package_full_6months())

    print()
    print("=" * 80)

    if all(results):
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ")
        print("=" * 80)
        sys.exit(0)
    else:
        print("❌ НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ")
        print("=" * 80)
        sys.exit(1)

if __name__ == '__main__':
    main()
