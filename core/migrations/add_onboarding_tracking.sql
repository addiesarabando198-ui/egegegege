-- Миграция для отслеживания onboarding и аналитики воронки

-- Добавляем поля для onboarding в users
ALTER TABLE users ADD COLUMN onboarding_completed BOOLEAN DEFAULT 0;
ALTER TABLE users ADD COLUMN onboarding_skipped BOOLEAN DEFAULT 0;
ALTER TABLE users ADD COLUMN onboarding_completed_at TIMESTAMP;

-- Таблица для аналитики воронки
CREATE TABLE IF NOT EXISTS funnel_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL, -- 'onboarding_started', 'onboarding_completed', 'first_answer', 'ai_check_used', 'trial_started', 'subscription_bought'
    event_data TEXT, -- JSON с дополнительными данными
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_funnel_events_user ON funnel_events(user_id);
CREATE INDEX IF NOT EXISTS idx_funnel_events_type ON funnel_events(event_type);
CREATE INDEX IF NOT EXISTS idx_funnel_events_created ON funnel_events(created_at);

-- View для анализа воронки
CREATE VIEW IF NOT EXISTS funnel_analysis AS
SELECT
    COUNT(DISTINCT u.user_id) as total_users,
    COUNT(DISTINCT CASE WHEN u.onboarding_completed = 1 THEN u.user_id END) as onboarding_completed,
    COUNT(DISTINCT CASE WHEN aq.user_id IS NOT NULL THEN u.user_id END) as answered_questions,
    COUNT(DISTINCT CASE WHEN al.user_id IS NOT NULL THEN u.user_id END) as used_ai_check,
    COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.plan_id = 'trial_7days' THEN u.user_id END) as trial_started,
    COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.plan_id != 'trial_7days' AND s.is_active = 1 THEN u.user_id END) as paying_subscribers,

    -- Проценты конверсии
    ROUND(COUNT(DISTINCT CASE WHEN u.onboarding_completed = 1 THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 2) as onboarding_rate,
    ROUND(COUNT(DISTINCT CASE WHEN aq.user_id IS NOT NULL THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 2) as activation_rate,
    ROUND(COUNT(DISTINCT CASE WHEN al.user_id IS NOT NULL THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 2) as ai_usage_rate,
    ROUND(COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.plan_id = 'trial_7days' THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 2) as trial_conversion_rate,
    ROUND(COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.plan_id != 'trial_7days' AND s.is_active = 1 THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 2) as paid_conversion_rate
FROM users u
LEFT JOIN answered_questions aq ON u.user_id = aq.user_id
LEFT JOIN user_ai_limits al ON u.user_id = al.user_id
LEFT JOIN subscriptions s ON u.user_id = s.user_id;

-- View для когортного анализа
CREATE VIEW IF NOT EXISTS cohort_analysis AS
SELECT
    strftime('%Y-%W', u.first_seen) as cohort_week,
    COUNT(DISTINCT u.user_id) as users,
    COUNT(DISTINCT CASE WHEN u.onboarding_completed = 1 THEN u.user_id END) as completed_onboarding,
    COUNT(DISTINCT CASE WHEN aq.user_id IS NOT NULL THEN u.user_id END) as answered_questions,
    COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.is_active = 1 THEN u.user_id END) as paying_now,

    ROUND(COUNT(DISTINCT CASE WHEN u.onboarding_completed = 1 THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 1) as onboarding_rate,
    ROUND(COUNT(DISTINCT CASE WHEN aq.user_id IS NOT NULL THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 1) as activation_rate,
    ROUND(COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.is_active = 1 THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 1) as conversion_rate
FROM users u
LEFT JOIN answered_questions aq ON u.user_id = aq.user_id
LEFT JOIN subscriptions s ON u.user_id = s.user_id
WHERE u.first_seen IS NOT NULL
GROUP BY cohort_week
ORDER BY cohort_week DESC;
