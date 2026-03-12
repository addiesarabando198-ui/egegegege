-- core/migrations/add_retention_system.sql
-- Миграция для добавления системы retention и engagement уведомлений

-- ==================== ТАБЛИЦЫ ====================

-- Таблица логирования отправленных уведомлений
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    segment TEXT NOT NULL,  -- BOUNCED, CURIOUS, TRIAL_USER, etc.
    trigger TEXT NOT NULL,  -- bounced_day1, trial_expiring_2days, etc.
    template_variant TEXT DEFAULT 'default',  -- Для A/B тестирования
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    clicked BOOLEAN DEFAULT 0,
    clicked_at TIMESTAMP NULL,
    converted BOOLEAN DEFAULT 0,  -- Оформил подписку после уведомления
    converted_at TIMESTAMP NULL,
    promo_code TEXT NULL,  -- Промокод из уведомления (если был)
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Таблица настроек уведомлений пользователя
CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id INTEGER PRIMARY KEY,
    enabled BOOLEAN DEFAULT 1,
    disabled_at TIMESTAMP NULL,
    disabled_reason TEXT NULL,  -- 'user_request', 'too_many_sends', 'bounced'
    last_notification_sent TIMESTAMP NULL,
    notification_count_today INTEGER DEFAULT 0,
    notification_count_week INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Таблица для отслеживания cooldown периодов
CREATE TABLE IF NOT EXISTS notification_cooldown (
    user_id INTEGER NOT NULL,
    trigger TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cooldown_until TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, trigger),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- ==================== ИНДЕКСЫ ДЛЯ ПРОИЗВОДИТЕЛЬНОСТИ ====================

-- Индексы для notification_log
CREATE INDEX IF NOT EXISTS idx_notification_log_user
ON notification_log(user_id);

CREATE INDEX IF NOT EXISTS idx_notification_log_sent
ON notification_log(sent_at);

CREATE INDEX IF NOT EXISTS idx_notification_log_segment
ON notification_log(segment, sent_at);

CREATE INDEX IF NOT EXISTS idx_notification_log_trigger
ON notification_log(trigger, sent_at);

CREATE INDEX IF NOT EXISTS idx_notification_log_converted
ON notification_log(converted, converted_at);

-- Индексы для notification_preferences
CREATE INDEX IF NOT EXISTS idx_notification_prefs_enabled
ON notification_preferences(enabled);

CREATE INDEX IF NOT EXISTS idx_notification_prefs_last_sent
ON notification_preferences(last_notification_sent);

-- Индексы для cooldown
CREATE INDEX IF NOT EXISTS idx_notification_cooldown_until
ON notification_cooldown(cooldown_until);

-- ==================== ПРЕДСТАВЛЕНИЯ ДЛЯ АНАЛИТИКИ ====================

-- Статистика уведомлений по сегментам
CREATE VIEW IF NOT EXISTS notification_stats_by_segment AS
SELECT
    segment,
    COUNT(*) as total_sent,
    SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) as total_clicked,
    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as total_converted,
    ROUND(100.0 * SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as click_rate,
    ROUND(100.0 * SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as conversion_rate
FROM notification_log
GROUP BY segment;

-- Статистика по триггерам
CREATE VIEW IF NOT EXISTS notification_stats_by_trigger AS
SELECT
    trigger,
    segment,
    COUNT(*) as total_sent,
    SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) as total_clicked,
    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as total_converted,
    ROUND(100.0 * SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as click_rate,
    ROUND(100.0 * SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as conversion_rate,
    DATE(sent_at) as date
FROM notification_log
GROUP BY trigger, segment, DATE(sent_at)
ORDER BY date DESC, conversion_rate DESC;

-- Дневная статистика
CREATE VIEW IF NOT EXISTS notification_stats_daily AS
SELECT
    DATE(sent_at) as date,
    COUNT(*) as total_sent,
    SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) as total_clicked,
    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as total_converted,
    ROUND(100.0 * SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as click_rate,
    ROUND(100.0 * SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as conversion_rate
FROM notification_log
GROUP BY DATE(sent_at)
ORDER BY date DESC;

-- Топ промокодов из уведомлений
CREATE VIEW IF NOT EXISTS notification_promo_performance AS
SELECT
    promo_code,
    COUNT(*) as times_sent,
    SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) as clicks,
    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as conversions,
    ROUND(100.0 * SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as conversion_rate
FROM notification_log
WHERE promo_code IS NOT NULL
GROUP BY promo_code
ORDER BY conversion_rate DESC;

-- Пользователи готовые для уведомлений (не в cooldown, не отписались)
CREATE VIEW IF NOT EXISTS users_ready_for_notifications AS
SELECT
    u.user_id,
    u.username,
    u.first_name,
    u.created_at,
    u.last_activity_date,
    np.last_notification_sent,
    np.notification_count_today,
    np.notification_count_week
FROM users u
LEFT JOIN notification_preferences np ON u.user_id = np.user_id
WHERE (np.enabled IS NULL OR np.enabled = 1)
    AND (np.notification_count_today IS NULL OR np.notification_count_today < 1)
    AND (np.notification_count_week IS NULL OR np.notification_count_week < 3)
    AND (np.last_notification_sent IS NULL
         OR datetime(np.last_notification_sent) < datetime('now', '-1 day'));

-- ==================== ТРИГГЕРЫ ====================

-- Триггер для автоматического сброса дневных счётчиков
-- (В SQLite нет встроенного планировщика, поэтому это нужно делать в коде)
-- Но можем создать триггер для обновления счётчиков

-- Триггер для инкремента счётчика при отправке уведомления
CREATE TRIGGER IF NOT EXISTS increment_notification_counters
AFTER INSERT ON notification_log
BEGIN
    INSERT OR REPLACE INTO notification_preferences (
        user_id,
        last_notification_sent,
        notification_count_today,
        notification_count_week
    )
    SELECT
        NEW.user_id,
        NEW.sent_at,
        COALESCE(
            (SELECT notification_count_today FROM notification_preferences WHERE user_id = NEW.user_id),
            0
        ) + 1,
        COALESCE(
            (SELECT notification_count_week FROM notification_preferences WHERE user_id = NEW.user_id),
            0
        ) + 1
    WHERE NOT EXISTS (
        SELECT 1 FROM notification_preferences WHERE user_id = NEW.user_id
    )
    OR EXISTS (
        SELECT 1 FROM notification_preferences WHERE user_id = NEW.user_id
    );

    UPDATE notification_preferences
    SET
        last_notification_sent = NEW.sent_at,
        notification_count_today = notification_count_today + 1,
        notification_count_week = notification_count_week + 1
    WHERE user_id = NEW.user_id;
END;

-- ==================== НАЧАЛЬНЫЕ ДАННЫЕ ====================

-- Создаём настройки по умолчанию для всех существующих пользователей
INSERT OR IGNORE INTO notification_preferences (user_id, enabled)
SELECT user_id, 1
FROM users;

-- ==================== КОММЕНТАРИИ ====================

-- USAGE:
-- 1. Запустить эту миграцию: python -c "import sqlite3; conn = sqlite3.connect('quiz_async.db'); conn.executescript(open('core/migrations/add_retention_system.sql').read()); conn.commit()"
-- 2. Проверить созданные таблицы: sqlite3 quiz_async.db ".tables"
-- 3. Посмотреть статистику: sqlite3 quiz_async.db "SELECT * FROM notification_stats_by_segment;"
