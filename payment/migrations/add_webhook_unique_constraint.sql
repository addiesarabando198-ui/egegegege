-- Миграция: Добавление UNIQUE constraint в webhook_logs
-- Проблема: Дублирующиеся webhook обрабатывались много раз
-- Решение: Добавить уникальный индекс на (order_id, status)

-- Создаем новую таблицу с правильной структурой
CREATE TABLE IF NOT EXISTS webhook_logs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payment_id TEXT,
    data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(order_id, status)  -- КРИТИЧНО: предотвращает дубликаты
);

-- Копируем уникальные данные из старой таблицы
INSERT OR IGNORE INTO webhook_logs_new (order_id, status, payment_id, data, created_at)
SELECT DISTINCT order_id, status, payment_id, data, created_at
FROM webhook_logs
GROUP BY order_id, status
HAVING created_at = MIN(created_at);

-- Удаляем старую таблицу
DROP TABLE webhook_logs;

-- Переименовываем новую
ALTER TABLE webhook_logs_new RENAME TO webhook_logs;

-- Создаем индексы для производительности
CREATE INDEX IF NOT EXISTS idx_webhook_logs_order_id ON webhook_logs(order_id);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_created_at ON webhook_logs(created_at);

-- Записываем в историю миграций
INSERT OR IGNORE INTO migration_history (migration_name, description)
VALUES (
    'add_webhook_unique_constraint_2024',
    'Добавлен UNIQUE constraint на (order_id, status) для предотвращения дублирования webhook'
);
