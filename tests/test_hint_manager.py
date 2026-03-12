"""
Тесты для HintManager - системы управления подсказками для AI.
"""

import pytest
import asyncio
import aiosqlite
import tempfile
import os
from pathlib import Path
from core.hint_manager import HintManager


@pytest.fixture
async def test_db():
    """Создаёт временную тестовую БД."""
    # Создаём временный файл
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    # Инициализируем схему БД
    async with aiosqlite.connect(db_path) as db:
        # Создаём необходимые таблицы
        await db.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY
            )
        """)

        await db.execute("""
            CREATE TABLE user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                feedback_type TEXT,
                message TEXT,
                status TEXT DEFAULT 'new',
                task_type TEXT,
                topic_name TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE task_specific_hints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                topic_name TEXT,
                hint_text TEXT NOT NULL,
                hint_category TEXT,
                priority INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT 1,
                created_from_complaint_id INTEGER,
                created_by_admin_id INTEGER,
                usage_count INTEGER DEFAULT 0,
                success_rate FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (created_from_complaint_id) REFERENCES user_feedback(id)
            )
        """)

        await db.execute("""
            CREATE TABLE hint_application_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hint_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                topic_name TEXT,
                task_type TEXT,
                was_helpful BOOLEAN,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (hint_id) REFERENCES task_specific_hints(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.commit()

    yield db_path

    # Удаляем временный файл после тестов
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.mark.asyncio
async def test_create_hint_from_complaint(test_db):
    """Тест создания подсказки из жалобы."""
    manager = HintManager(test_db)

    # Создаём тестовую жалобу
    async with aiosqlite.connect(test_db) as db:
        await db.execute("INSERT INTO users (user_id) VALUES (123)")
        cursor = await db.execute(
            "INSERT INTO user_feedback (user_id, feedback_type, message) VALUES (123, 'complaint', 'Test complaint')"
        )
        complaint_id = cursor.lastrowid
        await db.commit()

    # Создаём подсказку
    hint_id = await manager.create_hint_from_complaint(
        complaint_id=complaint_id,
        task_type='task24',
        topic_name='Политические партии',
        hint_text='Учитывай, что в России многопартийность разрешена.',
        hint_category='factual',
        priority=5,
        admin_id=1
    )

    assert hint_id > 0

    # Проверяем, что подсказка создана
    async with aiosqlite.connect(test_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM task_specific_hints WHERE id = ?", (hint_id,))
        hint = await cursor.fetchone()

        assert hint is not None
        assert hint['task_type'] == 'task24'
        assert hint['topic_name'] == 'Политические партии'
        assert hint['priority'] == 5
        assert hint['hint_category'] == 'factual'
        assert hint['is_active'] == 1


@pytest.mark.asyncio
async def test_get_active_hints(test_db):
    """Тест получения активных подсказок."""
    manager = HintManager(test_db)

    # Создаём несколько подсказок
    async with aiosqlite.connect(test_db) as db:
        # Подсказка 1: для конкретной темы
        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, topic_name, hint_text, hint_category, priority, is_active)
            VALUES ('task24', 'Политические партии', 'Подсказка 1', 'factual', 5, 1)
        """)

        # Подсказка 2: общая для task24
        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, topic_name, hint_text, hint_category, priority, is_active)
            VALUES ('task24', NULL, 'Подсказка 2', 'criteria', 4, 1)
        """)

        # Подсказка 3: неактивная
        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, topic_name, hint_text, hint_category, priority, is_active)
            VALUES ('task24', 'Политические партии', 'Подсказка 3', 'factual', 3, 0)
        """)

        # Подсказка 4: для другого типа задачи
        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, topic_name, hint_text, hint_category, priority, is_active)
            VALUES ('task19', 'Тема X', 'Подсказка 4', 'factual', 5, 1)
        """)

        await db.commit()

    # Получаем подсказки для конкретной темы
    hints = await manager.get_active_hints('task24', 'Политические партии')

    assert len(hints) == 2  # Должны получить подсказки 1 и 2 (тема + общая)
    assert hints[0]['priority'] == 5  # Самый высокий приоритет первым
    assert hints[1]['priority'] == 4


@pytest.mark.asyncio
async def test_format_hints_for_prompt(test_db):
    """Тест форматирования подсказок для промпта."""
    manager = HintManager(test_db)

    hints = [
        {
            "hint_id": 1,
            "hint_text": "Учитывай фактические аспекты.",
            "priority": 5,
            "hint_category": "factual",
            "usage_count": 10,
            "topic_name": "Тема 1"
        },
        {
            "hint_id": 2,
            "hint_text": "Проверяй структуру плана.",
            "priority": 4,
            "hint_category": "structural",
            "usage_count": 5,
            "topic_name": None
        }
    ]

    formatted = manager.format_hints_for_prompt(hints)

    assert "🔍 ВАЖНЫЕ УТОЧНЕНИЯ ДЛЯ ЭТОЙ ЗАДАЧИ:" in formatted
    assert "Фактические аспекты" in formatted
    assert "Структура плана/ответа" in formatted
    assert "Учитывай фактические аспекты." in formatted
    assert "Проверяй структуру плана." in formatted


@pytest.mark.asyncio
async def test_log_hint_usage(test_db):
    """Тест логирования использования подсказки."""
    manager = HintManager(test_db)

    # Создаём тестовые данные
    async with aiosqlite.connect(test_db) as db:
        await db.execute("INSERT INTO users (user_id) VALUES (456)")
        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, topic_name, hint_text, hint_category, priority)
            VALUES ('task24', 'Тема', 'Подсказка', 'factual', 5)
        """)
        await db.commit()

    # Логируем использование
    await manager.log_hint_usage(
        hint_id=1,
        user_id=456,
        topic_name='Тема',
        task_type='task24'
    )

    # Проверяем логи
    async with aiosqlite.connect(test_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM hint_application_log WHERE hint_id = 1")
        log = await cursor.fetchone()

        assert log is not None
        assert log['user_id'] == 456
        assert log['topic_name'] == 'Тема'
        assert log['task_type'] == 'task24'


@pytest.mark.asyncio
async def test_deactivate_hint(test_db):
    """Тест деактивации подсказки."""
    manager = HintManager(test_db)

    # Создаём подсказку
    async with aiosqlite.connect(test_db) as db:
        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, hint_text, hint_category, priority, is_active)
            VALUES ('task24', 'Подсказка', 'factual', 5, 1)
        """)
        await db.commit()

    # Деактивируем
    result = await manager.deactivate_hint(hint_id=1, admin_id=1)
    assert result is True

    # Проверяем, что подсказка деактивирована
    async with aiosqlite.connect(test_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT is_active FROM task_specific_hints WHERE id = 1")
        hint = await cursor.fetchone()
        assert hint['is_active'] == 0


@pytest.mark.asyncio
async def test_update_hint(test_db):
    """Тест обновления подсказки."""
    manager = HintManager(test_db)

    # Создаём подсказку
    async with aiosqlite.connect(test_db) as db:
        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, hint_text, hint_category, priority)
            VALUES ('task24', 'Старый текст', 'factual', 3)
        """)
        await db.commit()

    # Обновляем
    result = await manager.update_hint(
        hint_id=1,
        hint_text='Новый текст',
        priority=5
    )
    assert result is True

    # Проверяем изменения
    async with aiosqlite.connect(test_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM task_specific_hints WHERE id = 1")
        hint = await cursor.fetchone()
        assert hint['hint_text'] == 'Новый текст'
        assert hint['priority'] == 5


@pytest.mark.asyncio
async def test_get_hint_stats(test_db):
    """Тест получения статистики по подсказке."""
    manager = HintManager(test_db)

    # Создаём данные
    async with aiosqlite.connect(test_db) as db:
        await db.execute("INSERT INTO users (user_id) VALUES (789)")
        await db.execute("INSERT INTO users (user_id) VALUES (790)")

        await db.execute("""
            INSERT INTO task_specific_hints
            (task_type, hint_text, hint_category, priority, usage_count)
            VALUES ('task24', 'Подсказка', 'factual', 5, 10)
        """)

        # Добавляем логи применения
        await db.execute("""
            INSERT INTO hint_application_log (hint_id, user_id, topic_name, task_type)
            VALUES (1, 789, 'Тема', 'task24')
        """)
        await db.execute("""
            INSERT INTO hint_application_log (hint_id, user_id, topic_name, task_type)
            VALUES (1, 790, 'Тема', 'task24')
        """)

        await db.commit()

    # Получаем статистику
    stats = await manager.get_hint_stats(hint_id=1)

    assert stats is not None
    assert stats['usage_count'] == 10
    assert stats['unique_users_count'] == 2
    assert 'last_used' in stats


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
