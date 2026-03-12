-- teacher_mode/migrations/add_teacher_trial_history.sql
-- Миграция для создания таблицы teacher_trial_history
-- Отслеживает использование пробного периода для учителей

-- Создаем таблицу для истории использования пробного периода учителями
CREATE TABLE IF NOT EXISTS teacher_trial_history (
    user_id INTEGER PRIMARY KEY,
    used_at DATETIME NOT NULL,
    trial_plan TEXT DEFAULT 'teacher_trial_7days',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Создаем индекс для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_teacher_trial_history_used_at ON teacher_trial_history(used_at);

-- USAGE:
-- Запустить эту миграцию:
-- sqlite3 quiz_async.db < teacher_mode/migrations/add_teacher_trial_history.sql
-- ИЛИ:
-- python -c "import sqlite3; conn = sqlite3.connect('quiz_async.db'); conn.executescript(open('teacher_mode/migrations/add_teacher_trial_history.sql').read()); conn.commit(); print('Migration completed!')"
