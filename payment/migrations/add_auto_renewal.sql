-- payment/migrations/add_auto_renewal.sql
-- Миграция для добавления поддержки автопродления подписок

-- Таблица для хранения настроек автопродления
CREATE TABLE IF NOT EXISTS auto_renewal_settings (
    user_id INTEGER PRIMARY KEY,
    enabled BOOLEAN DEFAULT 0,
    payment_method TEXT CHECK(payment_method IN ('card', 'recurrent')),
    recurrent_token TEXT,  -- RebillId от Т-Банка
    card_token TEXT,  -- Для будущего использования
    next_renewal_date TIMESTAMP,
    failures_count INTEGER DEFAULT 0,
    last_renewal_attempt TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для истории автопродлений
CREATE TABLE IF NOT EXISTS auto_renewal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_id TEXT NOT NULL,
    payment_id TEXT,
    order_id TEXT,
    status TEXT CHECK(status IN ('success', 'failed', 'pending')),
    amount INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Добавляем индексы для оптимизации
CREATE INDEX IF NOT EXISTS idx_auto_renewal_next_date 
ON auto_renewal_settings(next_renewal_date);

CREATE INDEX IF NOT EXISTS idx_auto_renewal_enabled 
ON auto_renewal_settings(enabled);

CREATE INDEX IF NOT EXISTS idx_renewal_history_user 
ON auto_renewal_history(user_id, created_at);

-- Добавляем колонки в существующую таблицу payments (если их нет)
-- Проверьте, есть ли эти колонки, и добавьте если нужно:
ALTER TABLE payments ADD COLUMN rebill_id TEXT;
ALTER TABLE payments ADD COLUMN is_recurrent BOOLEAN DEFAULT 0;
ALTER TABLE payments ADD COLUMN auto_renewal_enabled BOOLEAN DEFAULT 0;

-- Добавляем триггер для обновления updated_at
CREATE TRIGGER IF NOT EXISTS update_auto_renewal_timestamp 
AFTER UPDATE ON auto_renewal_settings
BEGIN
    UPDATE auto_renewal_settings 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE user_id = NEW.user_id;
END;

-- Представление для получения пользователей для автопродления
CREATE VIEW IF NOT EXISTS users_for_auto_renewal AS
SELECT 
    ars.user_id,
    ars.recurrent_token,
    ars.next_renewal_date,
    ars.failures_count,
    ms.plan_id,
    ms.expires_at,
    p.amount
FROM auto_renewal_settings ars
INNER JOIN module_subscriptions ms ON ars.user_id = ms.user_id
LEFT JOIN (
    SELECT user_id, plan_id, MAX(amount / 100) as amount
    FROM payments
    WHERE status = 'completed'
    GROUP BY user_id, plan_id
) p ON ars.user_id = p.user_id AND ms.plan_id = p.plan_id
WHERE 
    ars.enabled = 1 
    AND ars.recurrent_token IS NOT NULL
    AND ms.is_active = 1
    AND ms.expires_at <= datetime('now', '+1 day')
    AND ars.failures_count < 3;

-- Функция для проверки истекающих подписок (для SQLite используем представление)
CREATE VIEW IF NOT EXISTS expiring_subscriptions AS
SELECT 
    ms.user_id,
    ms.plan_id,
    ms.expires_at,
    ms.is_trial,
    p.amount / 100 as amount,
    ars.enabled as auto_renewal_enabled
FROM module_subscriptions ms
LEFT JOIN auto_renewal_settings ars ON ms.user_id = ars.user_id
LEFT JOIN (
    SELECT user_id, plan_id, MAX(amount) as amount
    FROM payments
    WHERE status = 'completed'
    GROUP BY user_id, plan_id
) p ON ms.user_id = p.user_id AND ms.plan_id = p.plan_id
WHERE 
    ms.is_active = 1
    AND ms.expires_at BETWEEN datetime('now') AND datetime('now', '+3 days');

-- Процедура для записи истории неудачных попыток
-- В SQLite нет хранимых процедур, поэтому это нужно делать в коде Python