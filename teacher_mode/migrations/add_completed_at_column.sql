-- teacher_mode/migrations/add_completed_at_column.sql
-- Миграция для добавления колонки completed_at в таблицу homework_student_assignments

-- Добавляем колонку completed_at для отслеживания времени завершения задания учеником
ALTER TABLE homework_student_assignments ADD COLUMN completed_at DATETIME;

-- USAGE:
-- Запустить эту миграцию: python -c "import sqlite3; conn = sqlite3.connect('bot_database.db'); conn.executescript(open('teacher_mode/migrations/add_completed_at_column.sql').read()); conn.commit()"
