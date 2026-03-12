-- teacher_mode/migrations/add_deadline_reminders.sql
-- Миграция для добавления системы напоминаний о дедлайнах домашних заданий

-- ==================== ТАБЛИЦЫ ====================

-- Таблица логирования отправленных напоминаний о дедлайнах
CREATE TABLE IF NOT EXISTS deadline_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    homework_id INTEGER NOT NULL,
    hours_before INTEGER NOT NULL,  -- 24 или 3 (часы до дедлайна)
    sent_at TEXT NOT NULL,  -- ISO формат datetime
    UNIQUE(student_id, homework_id, hours_before),
    FOREIGN KEY (student_id) REFERENCES users(user_id),
    FOREIGN KEY (homework_id) REFERENCES homework_assignments(id) ON DELETE CASCADE
);

-- ==================== ИНДЕКСЫ ДЛЯ ПРОИЗВОДИТЕЛЬНОСТИ ====================

-- Индекс для быстрого поиска напоминаний по ученику
CREATE INDEX IF NOT EXISTS idx_deadline_reminders_student
ON deadline_reminders(student_id);

-- Индекс для быстрого поиска напоминаний по заданию
CREATE INDEX IF NOT EXISTS idx_deadline_reminders_homework
ON deadline_reminders(homework_id);

-- Индекс для проверки недавних напоминаний
CREATE INDEX IF NOT EXISTS idx_deadline_reminders_sent
ON deadline_reminders(sent_at);

-- Составной индекс для проверки дубликатов
CREATE INDEX IF NOT EXISTS idx_deadline_reminders_unique_check
ON deadline_reminders(student_id, homework_id, hours_before);

-- ==================== КОММЕНТАРИИ ====================

-- НАЗНАЧЕНИЕ:
-- Таблица используется для предотвращения дублирования напоминаний.
-- Перед отправкой напоминания система проверяет, не было ли оно уже отправлено
-- для данной комбинации student_id, homework_id и hours_before.

-- ИСПОЛЬЗОВАНИЕ:
-- 1. Scheduler запускается каждые 3 часа (job_queue)
-- 2. Проверяет задания с дедлайнами через 24 часа и 3 часа
-- 3. Отправляет персонализированные уведомления ученикам
-- 4. Логирует отправку в эту таблицу
-- 5. При повторной проверке пропускает уже отправленные напоминания

-- ЗАПУСК МИГРАЦИИ:
-- python -c "import sqlite3; conn = sqlite3.connect('bot_database.db'); conn.executescript(open('teacher_mode/migrations/add_deadline_reminders.sql').read()); conn.commit()"
