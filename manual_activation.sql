-- =====================================================================
-- СКРИПТ ДЛЯ РУЧНОЙ АКТИВАЦИИ ПОДПИСОК
-- =====================================================================
-- Использование: sqlite3 quiz_async.db < manual_activation.sql
--
-- ВАЖНО: Сначала проверьте plan_id платежа через диагностику!
-- =====================================================================

-- 1. Проверка платежей для пользователей 974972138 и 1893563949
SELECT '=== ПЛАТЕЖИ ПОЛЬЗОВАТЕЛЯ 974972138 ===' AS '';
SELECT order_id, payment_id, plan_id, amount, status, created_at, completed_at
FROM payments
WHERE user_id = 974972138
ORDER BY created_at DESC
LIMIT 5;

SELECT '=== ПЛАТЕЖИ ПОЛЬЗОВАТЕЛЯ 1893563949 ===' AS '';
SELECT order_id, payment_id, plan_id, amount, status, created_at, completed_at
FROM payments
WHERE user_id = 1893563949
ORDER BY created_at DESC
LIMIT 5;

-- 2. Проверка существующих подписок
SELECT '=== ТЕКУЩИЕ ПОДПИСКИ 974972138 ===' AS '';
SELECT module_code, plan_id, is_active, expires_at, activated_at
FROM module_subscriptions
WHERE user_id = 974972138
ORDER BY activated_at DESC;

SELECT '=== ТЕКУЩИЕ ПОДПИСКИ 1893563949 ===' AS '';
SELECT module_code, plan_id, is_active, expires_at, activated_at
FROM module_subscriptions
WHERE user_id = 1893563949
ORDER BY activated_at DESC;

-- =====================================================================
-- АКТИВАЦИЯ ПОДПИСКИ ДЛЯ ПОЛЬЗОВАТЕЛЯ 974972138
-- =====================================================================
-- ВНИМАНИЕ: Раскомментируйте нужный блок в зависимости от plan_id!
-- =====================================================================

-- Вариант 1: package_full (30 дней, полный доступ)
-- INSERT OR REPLACE INTO module_subscriptions
-- (user_id, module_code, plan_id, expires_at, is_active, activated_at, created_at)
-- VALUES
--   (974972138, 'test_part', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task19', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task20', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task22', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task24', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task25', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- Вариант 2: trial_7days (7 дней, полный доступ)
-- INSERT OR REPLACE INTO module_subscriptions
-- (user_id, module_code, plan_id, expires_at, is_active, activated_at, created_at)
-- VALUES
--   (974972138, 'test_part', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task19', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task20', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task22', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task24', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task25', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- Вариант 3: teacher_basic (30 дней, режим учителя)
-- INSERT OR REPLACE INTO module_subscriptions
-- (user_id, module_code, plan_id, expires_at, is_active, activated_at, created_at)
-- VALUES
--   (974972138, 'test_part', 'teacher_basic', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task19', 'teacher_basic', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task20', 'teacher_basic', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task22', 'teacher_basic', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task24', 'teacher_basic', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'task25', 'teacher_basic', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (974972138, 'teacher_mode', 'teacher_basic', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
--
-- -- Создать профиль учителя (если нужно)
-- INSERT OR IGNORE INTO teacher_profiles
-- (teacher_id, teacher_code, name, has_active_subscription, subscription_tier, subscription_expires, created_at, updated_at)
-- VALUES
--   (974972138, 't_' || abs(random() % 100000000), 'Teacher', 1, 'teacher_basic', datetime('now', '+30 days'), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- =====================================================================
-- АКТИВАЦИЯ ПОДПИСКИ ДЛЯ ПОЛЬЗОВАТЕЛЯ 1893563949
-- =====================================================================
-- ВНИМАНИЕ: Раскомментируйте нужный блок в зависимости от plan_id!
-- =====================================================================

-- Вариант 1: package_full (30 дней, полный доступ)
-- INSERT OR REPLACE INTO module_subscriptions
-- (user_id, module_code, plan_id, expires_at, is_active, activated_at, created_at)
-- VALUES
--   (1893563949, 'test_part', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task19', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task20', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task22', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task24', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task25', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- Вариант 2: trial_7days (7 дней, полный доступ)
-- INSERT OR REPLACE INTO module_subscriptions
-- (user_id, module_code, plan_id, expires_at, is_active, activated_at, created_at)
-- VALUES
--   (1893563949, 'test_part', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task19', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task20', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task22', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task24', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
--   (1893563949, 'task25', 'trial_7days', datetime('now', '+7 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- =====================================================================
-- ПРОВЕРКА РЕЗУЛЬТАТА
-- =====================================================================

SELECT '=== ИТОГОВЫЕ ПОДПИСКИ 974972138 ===' AS '';
SELECT module_code, plan_id, is_active,
       CASE
         WHEN expires_at > datetime('now') THEN 'ACTIVE'
         ELSE 'EXPIRED'
       END as status,
       expires_at
FROM module_subscriptions
WHERE user_id = 974972138
ORDER BY module_code;

SELECT '=== ИТОГОВЫЕ ПОДПИСКИ 1893563949 ===' AS '';
SELECT module_code, plan_id, is_active,
       CASE
         WHEN expires_at > datetime('now') THEN 'ACTIVE'
         ELSE 'EXPIRED'
       END as status,
       expires_at
FROM module_subscriptions
WHERE user_id = 1893563949
ORDER BY module_code;

-- =====================================================================
-- ГОТОВО!
-- =====================================================================
