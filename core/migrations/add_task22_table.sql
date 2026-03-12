-- core/migrations/add_task22_table.sql
-- Миграция для добавления таблицы task22_attempts

-- Таблица для хранения попыток решения задания 22
CREATE TABLE IF NOT EXISTS task22_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    answer TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score >= 0 AND score <= 4),
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Индексы для производительности
CREATE INDEX IF NOT EXISTS idx_task22_attempts_user
ON task22_attempts(user_id);

CREATE INDEX IF NOT EXISTS idx_task22_attempts_task
ON task22_attempts(task_id);

CREATE INDEX IF NOT EXISTS idx_task22_attempts_date
ON task22_attempts(attempted_at);

CREATE INDEX IF NOT EXISTS idx_task22_attempts_score
ON task22_attempts(score);

-- Представление для статистики пользователя
CREATE VIEW IF NOT EXISTS task22_user_stats AS
SELECT
    user_id,
    COUNT(*) as total_attempts,
    ROUND(AVG(score), 2) as avg_score,
    MAX(score) as max_score,
    SUM(CASE WHEN score = 4 THEN 1 ELSE 0 END) as perfect_scores,
    MIN(attempted_at) as first_attempt,
    MAX(attempted_at) as last_attempt
FROM task22_attempts
GROUP BY user_id;

-- Представление для общей статистики по заданиям
CREATE VIEW IF NOT EXISTS task22_task_stats AS
SELECT
    task_id,
    COUNT(*) as total_attempts,
    ROUND(AVG(score), 2) as avg_score,
    COUNT(DISTINCT user_id) as unique_users,
    SUM(CASE WHEN score = 4 THEN 1 ELSE 0 END) as perfect_count,
    SUM(CASE WHEN score >= 3 THEN 1 ELSE 0 END) as good_count,
    ROUND(100.0 * SUM(CASE WHEN score = 4 THEN 1 ELSE 0 END) / COUNT(*), 2) as perfect_rate
FROM task22_attempts
GROUP BY task_id
ORDER BY avg_score DESC;

-- Представление для дневной статистики
CREATE VIEW IF NOT EXISTS task22_daily_stats AS
SELECT
    DATE(attempted_at) as date,
    COUNT(*) as total_attempts,
    COUNT(DISTINCT user_id) as unique_users,
    ROUND(AVG(score), 2) as avg_score,
    SUM(CASE WHEN score = 4 THEN 1 ELSE 0 END) as perfect_scores
FROM task22_attempts
GROUP BY DATE(attempted_at)
ORDER BY date DESC;

-- USAGE:
-- Применить миграцию: python run_migration.py core/migrations/add_task22_table.sql
