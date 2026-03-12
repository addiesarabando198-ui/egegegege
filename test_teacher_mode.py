#!/usr/bin/env python3
"""
Тестовый скрипт для проверки основной функциональности teacher_mode.
"""

import sys
import asyncio


def test_imports():
    """Тест импортов всех модулей"""
    print("🧪 Тестирование импортов...")

    try:
        from teacher_mode import models
        print("✅ models импортирован")
    except Exception as e:
        print(f"❌ Ошибка импорта models: {e}")
        return False

    try:
        from teacher_mode import states
        print("✅ states импортирован")
    except Exception as e:
        print(f"❌ Ошибка импорта states: {e}")
        return False

    try:
        from teacher_mode import plugin
        print("✅ plugin импортирован")
    except Exception as e:
        print(f"❌ Ошибка импорта plugin: {e}")
        return False

    return True


def test_models():
    """Тест создания моделей"""
    print("\n🧪 Тестирование моделей...")

    try:
        from teacher_mode.models import (
            TeacherProfile, AssignmentType, AssignmentStatus,
            StudentAssignmentStatus, TargetType
        )
        from datetime import datetime

        # Создаём тестовый профиль учителя
        profile = TeacherProfile(
            user_id=12345,
            teacher_code="TEACH-TEST01",
            display_name="Test Teacher",
            has_active_subscription=True,
            subscription_expires=datetime.now(),
            subscription_tier="teacher_basic",
            created_at=datetime.now()
        )

        print(f"✅ TeacherProfile создан: {profile.teacher_code}")
        print(f"   Max students: {profile.max_students}")

        # Тест enum
        assert AssignmentType.EXISTING_TOPICS.value == 'existing_topics'
        assert AssignmentType.CUSTOM.value == 'custom'
        assert AssignmentStatus.ACTIVE.value == 'active'
        print("✅ Enum работают корректно")

        return True

    except Exception as e:
        print(f"❌ Ошибка при тестировании моделей: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_code_generation():
    """Тест генерации уникальных кодов"""
    print("\n🧪 Тестирование генерации кодов...")

    try:
        from teacher_mode.services.teacher_service import generate_teacher_code
        from teacher_mode.services.gift_service import generate_promo_code

        # Генерируем коды учителя
        codes = [generate_teacher_code() for _ in range(10)]

        # Проверяем формат
        for code in codes:
            assert code.startswith("TEACH-"), f"Неверный формат кода: {code}"
            assert len(code) == 12, f"Неверная длина кода: {code}"

        # Проверяем уникальность
        assert len(set(codes)) == 10, "Коды не уникальны!"
        print(f"✅ Сгенерировано 10 уникальных кодов учителя")
        print(f"   Примеры: {codes[0]}, {codes[1]}")

        # Генерируем промокоды
        promo_codes = [generate_promo_code() for _ in range(5)]

        for code in promo_codes:
            assert code.startswith("GIFT-"), f"Неверный формат промокода: {code}"

        print(f"✅ Сгенерировано 5 уникальных промокодов")
        print(f"   Примеры: {promo_codes[0]}, {promo_codes[1]}")

        return True

    except Exception as e:
        print(f"❌ Ошибка при тестировании генерации кодов: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_payment_config():
    """Тест конфигурации платежей"""
    print("\n🧪 Тестирование платежной конфигурации...")

    try:
        from payment.config import (
            is_teacher_plan, is_student_plan,
            get_teacher_max_students, get_all_teacher_plans,
            get_student_discount_plan, get_plan_info
        )

        # Проверяем распознавание планов
        assert is_teacher_plan('teacher_basic') == True
        assert is_teacher_plan('student_with_teacher') == False
        assert is_student_plan('student_with_teacher') == True
        print("✅ Распознавание типов планов работает")

        # Проверяем лимиты
        assert get_teacher_max_students('teacher_basic') == 10
        assert get_teacher_max_students('teacher_standard') == 20
        assert get_teacher_max_students('teacher_premium') == -1  # безлимит
        print("✅ Лимиты учеников корректны")

        # Проверяем получение всех планов
        teacher_plans = get_all_teacher_plans()
        assert len(teacher_plans) == 3, f"Должно быть 3 плана учителя, получено {len(teacher_plans)}"
        print(f"✅ Получено {len(teacher_plans)} плана для учителей")

        # Проверяем скидочный план
        discount_plan_id = get_student_discount_plan()
        assert discount_plan_id is not None, "Скидочный план должен существовать"
        discount_plan = get_plan_info(discount_plan_id)
        assert discount_plan is not None, f"План {discount_plan_id} должен существовать в SUBSCRIPTION_PLANS"
        assert discount_plan['price_rub'] == 149, f"Цена должна быть 149₽, получено {discount_plan['price_rub']}₽"
        print("✅ Скидочный план для учеников: 149₽")

        return True

    except Exception as e:
        print(f"❌ Ошибка при тестировании платежной конфигурации: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_registration():
    """Тест регистрации плагина"""
    print("\n🧪 Тестирование регистрации плагина...")

    try:
        from teacher_mode.plugin import TeacherModePlugin

        plugin = TeacherModePlugin()

        assert plugin.code == "teacher_mode"
        assert plugin.title == "👨‍🏫 Режим учителя"
        assert plugin.menu_priority == 5
        print(f"✅ Плагин создан: {plugin.title}")
        print(f"   Код: {plugin.code}, Приоритет: {plugin.menu_priority}")

        # Проверяем, что есть entry_handler
        assert hasattr(plugin, 'entry_handler')
        print("✅ entry_handler определён")

        return True

    except Exception as e:
        print(f"❌ Ошибка при тестировании плагина: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Основная функция тестирования"""
    print("=" * 60)
    print("🚀 ЗАПУСК ТЕСТОВ TEACHER_MODE")
    print("=" * 60)

    tests = [
        ("Импорты", test_imports),
        ("Модели", test_models),
        ("Генерация кодов", test_code_generation),
        ("Платежная конфигурация", test_payment_config),
        ("Регистрация плагина", test_plugin_registration),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Критическая ошибка в тесте '{name}': {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"📊 РЕЗУЛЬТАТЫ: {passed} ✅ / {failed} ❌ / {passed + failed} всего")
    print("=" * 60)

    if failed == 0:
        print("🎉 Все тесты пройдены успешно!")
        return 0
    else:
        print(f"⚠️  {failed} тест(ов) не пройдено")
        return 1


if __name__ == "__main__":
    sys.exit(main())
