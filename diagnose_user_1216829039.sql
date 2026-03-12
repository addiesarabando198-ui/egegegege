-- SQL диагностика пользователя 1216829039
-- Запустить: sqlite3 quiz_async.db < diagnose_user_1216829039.sql

.mode column
.headers on
.width 20 15 15 20 20

-- 1. Платежи пользователя
SELECT
    '=== ПЛАТЕЖИ ===' as info;

SELECT
    order_id,
    plan_id,
    amount_kopecks / 100.0 as amount_rub,
    status,
    created_at,
    completed_at
FROM payments
WHERE user_id = 1216829039
ORDER BY created_at;

-- 2. Подписки пользователя
SELECT
    '=== ПОДПИСКИ ===' as info;

SELECT
    module_code,
    plan_id,
    created_at,
    expires_at,
    is_active,
    julianday(expires_at) - julianday(created_at) as duration_days
FROM module_subscriptions
WHERE user_id = 1216829039
ORDER BY created_at;

-- 3. История пробного периода
SELECT
    '=== TRIAL HISTORY ===' as info;

SELECT
    trial_activated_at,
    trial_expires_at
FROM trial_history
WHERE user_id = 1216829039;

-- 4. Webhook логи
SELECT
    '=== WEBHOOK LOGS ===' as info;

SELECT
    order_id,
    status,
    payment_id,
    created_at
FROM webhook_logs
WHERE order_id IN (
    SELECT order_id FROM payments WHERE user_id = 1216829039
)
ORDER BY created_at;
