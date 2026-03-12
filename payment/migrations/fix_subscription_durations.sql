-- Миграция для исправления длительности подписок
-- Проблема: trial_7days получал 30 дней вместо 7, package_full мог получить двойную длительность

-- ===============================================
-- ИСПРАВЛЕНИЕ ПРОБНЫХ ПОДПИСОК (trial_7days)
-- ===============================================

-- Обновляем все активные trial_7days подписки с неправильной длительностью
-- Устанавливаем expires_at = created_at + 7 дней

UPDATE module_subscriptions
SET expires_at = datetime(created_at, '+7 days')
WHERE plan_id = 'trial_7days'
  AND (
    -- Проверяем, что длительность больше 7 дней
    julianday(expires_at) - julianday(created_at) > 7.5
  );

-- ===============================================
-- ЛОГИРОВАНИЕ: Создаем таблицу для истории миграций
-- ===============================================

CREATE TABLE IF NOT EXISTS migration_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_name TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- Записываем факт применения миграции
INSERT OR IGNORE INTO migration_history (migration_name, description)
VALUES (
    'fix_subscription_durations_2024',
    'Исправление длительности подписок: trial_7days теперь дает 7 дней вместо 30'
);
