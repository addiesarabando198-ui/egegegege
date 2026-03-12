-- payment/migrations/add_consent_and_feedback.sql
-- Миграция для соответствия требованиям Т-Банка

-- Таблица для хранения согласий пользователей на автопродление
CREATE TABLE IF NOT EXISTS auto_renewal_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_id TEXT,
    amount INTEGER,
    period_days INTEGER DEFAULT 30,
    consent_text TEXT NOT NULL,
    consent_checkbox_state BOOLEAN DEFAULT 1,
    ip_address TEXT,
    user_agent TEXT,
    telegram_chat_id INTEGER,
    message_id INTEGER,  -- ID сообщения с согласием для аудита
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Таблица для логирования отмен подписок
CREATE TABLE IF NOT EXISTS cancellation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subscription_id TEXT,
    cancellation_type TEXT CHECK(cancellation_type IN ('auto_renewal', 'subscription')),
    reason TEXT,
    detailed_feedback TEXT,
    refund_requested BOOLEAN DEFAULT 0,
    refund_amount INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Таблица для обратной связи от пользователей
CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    feedback_type TEXT CHECK(feedback_type IN ('cancellation', 'support', 'general', 'complaint')),
    category TEXT,
    message TEXT,
    status TEXT DEFAULT 'new' CHECK(status IN ('new', 'in_progress', 'resolved', 'closed')),
    admin_response TEXT,
    admin_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Таблица для истории изменений автопродления (для аудита)
CREATE TABLE IF NOT EXISTS auto_renewal_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action TEXT CHECK(action IN ('enabled', 'disabled', 'modified', 'failed')),
    previous_state TEXT,
    new_state TEXT,
    reason TEXT,
    performed_by TEXT DEFAULT 'user', -- user, admin, system
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Таблица для хранения уведомлений о предстоящих списаниях
CREATE TABLE IF NOT EXISTS renewal_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    notification_type TEXT CHECK(notification_type IN ('3_days_before', '1_day_before', 'payment_success', 'payment_failed')),
    scheduled_date TIMESTAMP,
    sent_date TIMESTAMP,
    is_sent BOOLEAN DEFAULT 0,
    message_text TEXT,
    telegram_message_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Индексы для оптимизации
CREATE INDEX IF NOT EXISTS idx_consents_user ON auto_renewal_consents(user_id);
CREATE INDEX IF NOT EXISTS idx_cancellation_user ON cancellation_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON user_feedback(status, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_user ON auto_renewal_audit(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_scheduled ON renewal_notifications(scheduled_date, is_sent);

-- Представление для активных согласий
CREATE VIEW IF NOT EXISTS active_consents AS
SELECT 
    arc.user_id,
    arc.plan_id,
    arc.amount,
    arc.period_days,
    arc.created_at as consent_date,
    ars.enabled as auto_renewal_enabled,
    ars.next_renewal_date
FROM auto_renewal_consents arc
INNER JOIN auto_renewal_settings ars ON arc.user_id = ars.user_id
WHERE ars.enabled = 1
ORDER BY arc.created_at DESC;

-- Представление для анализа причин отмен
CREATE VIEW IF NOT EXISTS cancellation_analytics AS
SELECT 
    reason,
    COUNT(*) as count,
    DATE(created_at) as date
FROM cancellation_log
GROUP BY reason, DATE(created_at)
ORDER BY date DESC, count DESC;

-- Триггер для обновления updated_at в user_feedback
CREATE TRIGGER IF NOT EXISTS update_feedback_timestamp 
AFTER UPDATE ON user_feedback
BEGIN
    UPDATE user_feedback 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;