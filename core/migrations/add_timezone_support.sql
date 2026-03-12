-- Миграция для добавления поддержки часовых поясов и улучшения системы уведомлений
-- Версия: 2026-02-05

-- ============================================================
-- 1. Добавление timezone в notification_preferences
-- ============================================================

-- Добавляем поле timezone (если не существует)
ALTER TABLE notification_preferences ADD COLUMN timezone TEXT DEFAULT 'Europe/Moscow';

-- Добавляем предпочитаемый час для уведомлений (по умолчанию 18:00)
ALTER TABLE notification_preferences ADD COLUMN preferred_hour INTEGER DEFAULT 18;

-- Добавляем дату последнего сброса счётчика (для отслеживания)
ALTER TABLE notification_preferences ADD COLUMN last_count_reset_date TEXT;

-- ============================================================
-- 2. Добавление timezone в user_streaks
-- ============================================================

ALTER TABLE user_streaks ADD COLUMN timezone TEXT DEFAULT 'Europe/Moscow';

-- ============================================================
-- 3. Создание таблицы для часовых поясов пользователей
-- ============================================================

CREATE TABLE IF NOT EXISTS user_timezone_info (
    user_id INTEGER PRIMARY KEY,

    -- Часовой пояс
    timezone TEXT DEFAULT 'Europe/Moscow',
    utc_offset_hours INTEGER DEFAULT 3,  -- +3 для Москвы

    -- Как определён
    detection_method TEXT DEFAULT 'default',  -- 'default', 'user_selected', 'auto_detected'

    -- Оптимальное время для уведомлений (локальное)
    optimal_notification_hour INTEGER DEFAULT 18,

    -- Активные часы пользователя (когда обычно онлайн)
    typical_active_start_hour INTEGER DEFAULT 9,
    typical_active_end_hour INTEGER DEFAULT 22,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Индекс для быстрого поиска по часовому поясу
CREATE INDEX IF NOT EXISTS idx_user_timezone ON user_timezone_info(timezone);

-- ============================================================
-- 4. Расписание сброса счётчиков (для трекинга)
-- ============================================================

CREATE TABLE IF NOT EXISTS notification_reset_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reset_type TEXT NOT NULL,  -- 'daily', 'weekly'
    users_reset INTEGER DEFAULT 0,
    executed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 5. Популярные часовые пояса России
-- ============================================================

-- Справочная таблица часовых поясов
CREATE TABLE IF NOT EXISTS timezone_reference (
    timezone_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    utc_offset INTEGER NOT NULL,  -- в часах
    regions TEXT  -- примеры регионов
);

-- Заполняем популярные часовые пояса России
INSERT OR IGNORE INTO timezone_reference (timezone_id, display_name, utc_offset, regions) VALUES
    ('Europe/Kaliningrad', 'Калининград (UTC+2)', 2, 'Калининградская область'),
    ('Europe/Moscow', 'Москва (UTC+3)', 3, 'Москва, Санкт-Петербург, центральная Россия'),
    ('Europe/Samara', 'Самара (UTC+4)', 4, 'Самара, Ижевск'),
    ('Asia/Yekaterinburg', 'Екатеринбург (UTC+5)', 5, 'Екатеринбург, Пермь, Челябинск'),
    ('Asia/Omsk', 'Омск (UTC+6)', 6, 'Омск'),
    ('Asia/Krasnoyarsk', 'Красноярск (UTC+7)', 7, 'Красноярск, Новосибирск, Томск'),
    ('Asia/Irkutsk', 'Иркутск (UTC+8)', 8, 'Иркутск'),
    ('Asia/Yakutsk', 'Якутск (UTC+9)', 9, 'Якутск, Чита'),
    ('Asia/Vladivostok', 'Владивосток (UTC+10)', 10, 'Владивосток, Хабаровск'),
    ('Asia/Magadan', 'Магадан (UTC+11)', 11, 'Магадан, Сахалин'),
    ('Asia/Kamchatka', 'Камчатка (UTC+12)', 12, 'Камчатка, Чукотка');

-- ============================================================
-- 6. Создание view для пользователей, которым нужно отправить уведомление
-- ============================================================

-- View показывает пользователей, у которых сейчас оптимальное время для уведомления
CREATE VIEW IF NOT EXISTS users_optimal_notification_time AS
SELECT
    u.user_id,
    COALESCE(uti.timezone, 'Europe/Moscow') as timezone,
    COALESCE(uti.utc_offset_hours, 3) as utc_offset,
    COALESCE(np.preferred_hour, 18) as preferred_hour,
    -- Вычисляем текущий час в часовом поясе пользователя
    (strftime('%H', 'now', 'utc') + COALESCE(uti.utc_offset_hours, 3)) % 24 as user_local_hour
FROM users u
LEFT JOIN user_timezone_info uti ON u.user_id = uti.user_id
LEFT JOIN notification_preferences np ON u.user_id = np.user_id
WHERE np.enabled = 1 OR np.enabled IS NULL;
