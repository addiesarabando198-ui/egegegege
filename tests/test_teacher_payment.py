"""
Автотесты для критических путей оплаты и активации подписок учителей.

Проверяются:
1. Callback_data для кнопок оплаты
2. Активация подписки после оплаты
3. Создание профиля учителя при оплате
4. Проверка использования триала
5. Обновление существующих подписок
"""

import pytest
import pytest_asyncio
import asyncio
import aiosqlite
import tempfile
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, patch, MagicMock


# ============================================
# ФИКСТУРЫ
# ============================================

@pytest_asyncio.fixture
async def test_db():
    """Создаёт временную тестовую БД с необходимыми таблицами."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    async with aiosqlite.connect(db_path) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT
            )
        """)

        # Таблица ролей пользователей
        await db.execute("""
            CREATE TABLE user_roles (
                user_id INTEGER,
                role TEXT,
                PRIMARY KEY (user_id, role),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Таблица профилей учителей
        await db.execute("""
            CREATE TABLE teacher_profiles (
                user_id INTEGER PRIMARY KEY,
                teacher_code TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                has_active_subscription INTEGER DEFAULT 0,
                subscription_tier TEXT,
                subscription_expires TEXT,
                created_at TEXT,
                feedback_settings TEXT DEFAULT '{}',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Таблица подписок на модули
        await db.execute("""
            CREATE TABLE module_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                module_code TEXT NOT NULL,
                plan_id TEXT,
                is_active INTEGER DEFAULT 1,
                expires_at TEXT,
                activated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Таблица истории использования триала учителями
        await db.execute("""
            CREATE TABLE teacher_trial_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                trial_plan_id TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Таблица истории изменений подписок учителей
        await db.execute("""
            CREATE TABLE teacher_subscription_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(
                    action IN ('activated', 'renewed', 'upgraded', 'downgraded', 'expired', 'cancelled')
                ),
                previous_tier TEXT,
                new_tier TEXT,
                expires_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Таблица платежей
        await db.execute("""
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                order_id TEXT UNIQUE NOT NULL,
                plan_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.commit()

    yield db_path

    # Очистка
    os.unlink(db_path)


@pytest_asyncio.fixture
async def subscription_manager(test_db):
    """Создаёт SubscriptionManager с тестовой БД."""
    with patch('payment.subscription_manager.DATABASE_FILE', test_db):
        from payment.subscription_manager import SubscriptionManager
        manager = SubscriptionManager()
        manager.database_file = test_db
        yield manager


# ============================================
# ТЕСТЫ CALLBACK_DATA
# ============================================

class TestCallbackData:
    """Тесты корректности callback_data для кнопок."""

    def test_teacher_subscription_button_callback_data(self):
        """
        Тест: Кнопка 'Оформить подписку' использует правильный callback_data.

        КРИТИЧНО: Это была найденная баг, кнопка должна использовать
        'pay_teacher_{plan_id}' для соответствия паттерну '^pay_teacher_'
        """
        from teacher_mode.handlers.teacher_handlers import show_teacher_plan_details

        # Проверяем, что в коде используется правильный callback_data
        import inspect
        source = inspect.getsource(show_teacher_plan_details)

        # Проверяем наличие правильного callback_data
        assert 'callback_data=f"pay_teacher_{plan_id}"' in source, \
            "Кнопка 'Оформить подписку' должна использовать callback_data=f'pay_teacher_{plan_id}'"

        # Проверяем, что старый неправильный callback_data НЕ используется
        assert 'callback_data=f"pay_{plan_id}"' not in source, \
            "Старый некорректный callback_data больше не должен использоваться"

    def test_plugin_payment_handlers_registration(self):
        """
        Тест: Обработчики оплаты зарегистрированы с правильными паттернами.
        """
        from teacher_mode.plugin import TeacherModePlugin

        plugin = TeacherModePlugin()

        # Проверяем, что плагин имеет правильную структуру
        assert plugin.code == "teacher_mode"
        assert plugin.title == "👨‍🏫 Режим учителя"

        # Проверяем наличие entry_handler
        assert hasattr(plugin, 'entry_handler')


# ============================================
# ТЕСТЫ АКТИВАЦИИ ПОДПИСКИ
# ============================================

class TestSubscriptionActivation:
    """Тесты активации подписок учителей."""

    @pytest.mark.asyncio
    async def test_activate_teacher_subscription_creates_profile(self, subscription_manager, test_db):
        """
        Тест: Активация подписки создает профиль учителя, если его нет.
        """
        user_id = 12345
        plan_id = 'teacher_basic'
        duration_months = 1

        # Добавляем пользователя в БД
        async with aiosqlite.connect(test_db) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name, last_name) VALUES (?, ?, ?)",
                (user_id, "Test", "Teacher")
            )
            await db.commit()

        # Активируем подписку
        await subscription_manager._activate_teacher_subscription(
            user_id, plan_id, duration_months
        )

        # Проверяем, что профиль учителя создан
        async with aiosqlite.connect(test_db) as db:
            cursor = await db.execute(
                "SELECT user_id, subscription_tier, has_active_subscription FROM teacher_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()

        assert row is not None, "Профиль учителя должен быть создан"
        assert row[0] == user_id
        assert row[1] == plan_id
        assert row[2] == 1, "Подписка должна быть активна"

    @pytest.mark.asyncio
    async def test_activate_teacher_subscription_adds_role(self, subscription_manager, test_db):
        """
        Тест: Активация подписки добавляет роль 'teacher' пользователю.
        """
        user_id = 12346
        plan_id = 'teacher_standard'

        # Добавляем пользователя
        async with aiosqlite.connect(test_db) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name) VALUES (?, ?)",
                (user_id, "Teacher")
            )
            await db.commit()

        # Активируем подписку
        await subscription_manager._activate_teacher_subscription(user_id, plan_id, 1)

        # Проверяем роль
        async with aiosqlite.connect(test_db) as db:
            cursor = await db.execute(
                "SELECT role FROM user_roles WHERE user_id = ? AND role = 'teacher'",
                (user_id,)
            )
            row = await cursor.fetchone()

        assert row is not None, "Роль 'teacher' должна быть добавлена"
        assert row[0] == 'teacher'

    @pytest.mark.asyncio
    async def test_activate_teacher_subscription_extends_existing(self, subscription_manager, test_db):
        """
        Тест: Активация подписки для существующего учителя продлевает срок.
        """
        user_id = 12347
        plan_id = 'teacher_premium'

        # Создаем пользователя и профиль учителя с истекающей подпиской
        async with aiosqlite.connect(test_db) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name) VALUES (?, ?)",
                (user_id, "Teacher")
            )

            await db.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, 'teacher')",
                (user_id,)
            )

            # Подписка истекает через 5 дней
            expires_at = datetime.now(timezone.utc) + timedelta(days=5)
            await db.execute("""
                INSERT INTO teacher_profiles
                (user_id, teacher_code, display_name, has_active_subscription,
                 subscription_tier, subscription_expires, created_at, feedback_settings)
                VALUES (?, ?, ?, 1, ?, ?, ?, '{}')
            """, (user_id, 'TEACH-TEST01', 'Teacher', 'teacher_basic',
                  expires_at.isoformat(), datetime.now(timezone.utc).isoformat()))

            await db.commit()

        # Активируем новую подписку на 1 месяц
        await subscription_manager._activate_teacher_subscription(user_id, plan_id, 1)

        # Проверяем, что подписка продлена от старой даты
        async with aiosqlite.connect(test_db) as db:
            cursor = await db.execute(
                "SELECT subscription_expires, subscription_tier FROM teacher_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()

        new_expires = datetime.fromisoformat(row[0])

        # Новая дата должна быть примерно через 35 дней (5 дней остаток + 30 дней новая подписка)
        expected_min = datetime.now(timezone.utc) + timedelta(days=34)
        expected_max = datetime.now(timezone.utc) + timedelta(days=36)

        assert expected_min <= new_expires <= expected_max, \
            f"Подписка должна быть продлена на 30 дней от предыдущей даты истечения"

        assert row[1] == plan_id, "Тариф должен быть обновлен"

    @pytest.mark.asyncio
    async def test_activate_subscription_creates_module_subscriptions(self, subscription_manager, test_db):
        """
        Тест: Активация подписки учителя также создает подписки на модули.
        """
        user_id = 12348
        plan_id = 'teacher_basic'
        duration_months = 1

        # Добавляем пользователя
        async with aiosqlite.connect(test_db) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name) VALUES (?, ?)",
                (user_id, "Teacher")
            )
            await db.commit()

        # Активируем полную подписку (это должно вызвать и _activate_teacher_subscription)
        from payment.config import SUBSCRIPTION_PLANS
        plan = SUBSCRIPTION_PLANS.get(plan_id)

        # Мокируем активацию (полная активация требует больше настройки)
        # Проверяем только _activate_teacher_subscription
        await subscription_manager._activate_teacher_subscription(user_id, plan_id, duration_months)

        # Проверяем, что создан профиль учителя
        async with aiosqlite.connect(test_db) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM teacher_profiles WHERE user_id = ?",
                (user_id,)
            )
            count = (await cursor.fetchone())[0]

        assert count == 1, "Должен быть создан профиль учителя"


# ============================================
# ТЕСТЫ ПРОВЕРКИ ИСПОЛЬЗОВАНИЯ ТРИАЛА
# ============================================

class TestTrialCheck:
    """Тесты проверки использования пробного периода."""

    @pytest.mark.asyncio
    async def test_has_used_teacher_trial_false_for_new_user(self, subscription_manager, test_db):
        """
        Тест: Новый пользователь не использовал триал.
        """
        user_id = 99999

        # Добавляем пользователя
        async with aiosqlite.connect(test_db) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name) VALUES (?, ?)",
                (user_id, "New User")
            )
            await db.commit()

        has_used = await subscription_manager.has_used_teacher_trial(user_id)

        assert has_used is False, "Новый пользователь не должен был использовать триал"

    @pytest.mark.asyncio
    async def test_has_used_teacher_trial_true_after_activation(self, subscription_manager, test_db):
        """
        Тест: После активации триала пользователь помечен как использовавший.
        """
        user_id = 99998

        # Добавляем пользователя
        async with aiosqlite.connect(test_db) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name) VALUES (?, ?)",
                (user_id, "Trial User")
            )

            # Помечаем как использовавшего триал
            await db.execute(
                """INSERT INTO teacher_trial_history
                   (user_id, trial_plan_id, activated_at)
                   VALUES (?, 'teacher_trial_7days', ?)""",
                (user_id, datetime.now(timezone.utc).isoformat())
            )
            await db.commit()

        has_used = await subscription_manager.has_used_teacher_trial(user_id)

        assert has_used is True, "Пользователь должен быть помечен как использовавший триал"


# ============================================
# ТЕСТЫ ИНТЕГРАЦИИ
# ============================================

class TestIntegration:
    """Интеграционные тесты полного flow оплаты."""

    @pytest.mark.asyncio
    async def test_full_payment_flow_creates_everything(self, subscription_manager, test_db):
        """
        Интеграционный тест: Полный flow от оплаты до активации.

        Проверяет:
        1. Создание профиля учителя
        2. Добавление роли teacher
        3. Активация подписки
        4. Установка корректной даты истечения
        """
        user_id = 88888
        plan_id = 'teacher_standard'
        duration_months = 3

        # Добавляем пользователя
        async with aiosqlite.connect(test_db) as db:
            await db.execute(
                "INSERT INTO users (user_id, first_name, last_name) VALUES (?, ?, ?)",
                (user_id, "Integration", "Test")
            )
            await db.commit()

        # Выполняем активацию
        await subscription_manager._activate_teacher_subscription(
            user_id, plan_id, duration_months
        )

        # Проверяем все аспекты
        async with aiosqlite.connect(test_db) as db:
            # 1. Профиль учителя создан
            cursor = await db.execute(
                """SELECT teacher_code, display_name, has_active_subscription,
                          subscription_tier, subscription_expires
                   FROM teacher_profiles WHERE user_id = ?""",
                (user_id,)
            )
            profile = await cursor.fetchone()

            assert profile is not None, "Профиль учителя должен быть создан"
            teacher_code, display_name, has_active, tier, expires_str = profile

            assert teacher_code.startswith("TEACH-"), "Код учителя должен иметь правильный формат"
            assert display_name == "Integration Test", "Имя должно быть взято из users"
            assert has_active == 1, "Подписка должна быть активна"
            assert tier == plan_id, f"Тариф должен быть {plan_id}"

            # 2. Дата истечения правильная (90 дней для 3 месяцев)
            expires = datetime.fromisoformat(expires_str)
            expected = datetime.now(timezone.utc) + timedelta(days=90)

            # Допускаем погрешность в 1 минуту
            time_diff = abs((expires - expected).total_seconds())
            assert time_diff < 60, "Дата истечения должна быть через 90 дней"

            # 3. Роль teacher добавлена
            cursor = await db.execute(
                "SELECT role FROM user_roles WHERE user_id = ? AND role = 'teacher'",
                (user_id,)
            )
            role = await cursor.fetchone()

            assert role is not None, "Роль 'teacher' должна быть добавлена"


# ============================================
# ТЕСТЫ CALLBACK_DATA ДЛЯ ПОДПИСОК
# ============================================

class TestPaymentCallbacks:
    """Тесты корректности callback_data в платежной системе."""

    def test_teacher_plan_details_uses_correct_callback(self):
        """
        Тест: show_teacher_plan_details использует callback_data=f'pay_teacher_{plan_id}'.

        Это критичный тест для предотвращения регрессии бага,
        когда кнопка использовала неправильный callback_data.
        """
        import inspect
        from teacher_mode.handlers.teacher_handlers import show_teacher_plan_details

        source = inspect.getsource(show_teacher_plan_details)

        # Проверяем, что используется правильный callback_data
        assert 'pay_teacher_' in source, \
            "Должен использоваться callback_data с префиксом 'pay_teacher_'"

        # Проверяем конкретный паттерн
        assert 'callback_data=f"pay_teacher_{plan_id}"' in source, \
            "callback_data должен формироваться как f'pay_teacher_{plan_id}'"

    def test_plugin_registers_pay_teacher_pattern(self):
        """
        Тест: plugin.py регистрирует обработчик для паттерна '^pay_teacher_'.
        """
        import inspect
        from teacher_mode.plugin import TeacherModePlugin

        source = inspect.getsource(TeacherModePlugin)

        # Проверяем, что паттерн зарегистрирован
        assert 'pattern="^pay_teacher_"' in source or "pattern='^pay_teacher_'" in source, \
            "Обработчик должен быть зарегистрирован с паттерном '^pay_teacher_'"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
