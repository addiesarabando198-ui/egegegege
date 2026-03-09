-- Миграция для B2B API
-- Версия: 2026-02-12
-- Описание: Создание таблиц для B2B клиентов, API ключей, проверок и логирования

-- ============================================================
-- 1. ТАБЛИЦА B2B КЛИЕНТОВ
-- ============================================================

CREATE TABLE IF NOT EXISTS b2b_clients (
    client_id TEXT PRIMARY KEY,

    -- Информация о компании
    company_name TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    contact_phone TEXT,
    website TEXT,

    -- Статус и тариф
    status TEXT NOT NULL DEFAULT 'trial',  -- active, suspended, trial
    tier TEXT NOT NULL DEFAULT 'trial',    -- free, trial, basic, standard, premium, enterprise

    -- Лимиты (переопределяют дефолтные для тарифа если заданы)
    rate_limit_per_minute INTEGER,
    rate_limit_per_day INTEGER,
    monthly_quota INTEGER,

    -- Счётчики использования
    checks_today INTEGER DEFAULT 0,
    checks_this_month INTEGER DEFAULT 0,
    total_checks INTEGER DEFAULT 0,

    -- Дата последнего сброса счётчиков
    last_daily_reset TEXT,
    last_monthly_reset TEXT,

    -- Биллинг
    rebill_id TEXT,                   -- RebillId от Tinkoff для рекуррентных списаний
    billing_active INTEGER DEFAULT 0, -- Флаг активного автосписания
    billing_order_id TEXT,            -- order_id последнего платежа привязки карты

    -- Примечания (для админов)
    notes TEXT,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_activity_at TEXT,
    trial_expires_at TEXT
);

-- Индексы для b2b_clients
CREATE INDEX IF NOT EXISTS idx_b2b_clients_status ON b2b_clients(status);
CREATE INDEX IF NOT EXISTS idx_b2b_clients_tier ON b2b_clients(tier);
CREATE INDEX IF NOT EXISTS idx_b2b_clients_email ON b2b_clients(contact_email);


-- ============================================================
-- 2. ТАБЛИЦА API КЛЮЧЕЙ
-- ============================================================

CREATE TABLE IF NOT EXISTS b2b_api_keys (
    key_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,

    -- Ключ (хешированный)
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,  -- Первые 8 символов для идентификации

    -- Метаданные
    name TEXT NOT NULL,        -- Название ключа (напр. "Production", "Staging")
    scopes TEXT,               -- Разрешения через запятую: "check:create,check:read,questions:read"

    -- Статус
    is_active INTEGER DEFAULT 1,
    expires_at TEXT,

    -- Использование
    last_used_at TEXT,
    usage_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (client_id) REFERENCES b2b_clients(client_id)
);

-- Индексы для b2b_api_keys
CREATE INDEX IF NOT EXISTS idx_b2b_api_keys_hash ON b2b_api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_b2b_api_keys_client ON b2b_api_keys(client_id);
CREATE INDEX IF NOT EXISTS idx_b2b_api_keys_active ON b2b_api_keys(is_active);


-- ============================================================
-- 3. ТАБЛИЦА ПРОВЕРОК (ОЧЕРЕДЬ)
-- ============================================================

CREATE TABLE IF NOT EXISTS b2b_checks (
    check_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,

    -- Статус
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, processing, completed, failed

    -- Данные задания
    task_number INTEGER NOT NULL,
    task_text TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    topic TEXT,
    strictness TEXT DEFAULT 'standard',

    -- Результаты оценки
    total_score INTEGER,
    max_score INTEGER,
    criteria_scores TEXT,       -- JSON с оценками по критериям
    feedback TEXT,              -- Общий комментарий
    suggestions TEXT,           -- JSON с рекомендациями
    factual_errors TEXT,        -- JSON с фактическими ошибками
    detailed_feedback TEXT,     -- Полный JSON ответ от AI

    -- Метаданные клиента
    external_id TEXT,           -- ID в системе клиента
    callback_url TEXT,          -- URL для webhook
    idempotency_key TEXT,       -- Ключ идемпотентности
    metadata TEXT,              -- JSON с доп. данными клиента

    -- Ошибки
    error_message TEXT,

    -- Производительность
    processing_time_ms INTEGER,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT
);

-- Индексы для b2b_checks
CREATE INDEX IF NOT EXISTS idx_b2b_checks_client ON b2b_checks(client_id);
CREATE INDEX IF NOT EXISTS idx_b2b_checks_status ON b2b_checks(status);
CREATE INDEX IF NOT EXISTS idx_b2b_checks_created ON b2b_checks(created_at);
CREATE INDEX IF NOT EXISTS idx_b2b_checks_external ON b2b_checks(client_id, external_id);
CREATE INDEX IF NOT EXISTS idx_b2b_checks_task ON b2b_checks(task_number);
CREATE INDEX IF NOT EXISTS idx_b2b_checks_idempotency ON b2b_checks(client_id, idempotency_key);


-- ============================================================
-- 4. ТАБЛИЦА ЛОГОВ API ЗАПРОСОВ (для биллинга и аналитики)
-- ============================================================

CREATE TABLE IF NOT EXISTS b2b_api_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    key_id TEXT,

    -- Запрос
    endpoint TEXT NOT NULL,      -- /api/v1/check, /api/v1/questions, etc.
    method TEXT NOT NULL,        -- GET, POST, etc.
    request_size_bytes INTEGER,

    -- Ответ
    response_status INTEGER NOT NULL,
    response_time_ms INTEGER,
    response_size_bytes INTEGER,

    -- Детали (для биллинга)
    check_id TEXT,               -- Если это запрос на проверку
    task_number INTEGER,
    is_billable INTEGER DEFAULT 1,

    -- Timestamps
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (client_id) REFERENCES b2b_clients(client_id)
);

-- Индексы для b2b_api_logs
CREATE INDEX IF NOT EXISTS idx_b2b_logs_client ON b2b_api_logs(client_id);
CREATE INDEX IF NOT EXISTS idx_b2b_logs_timestamp ON b2b_api_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_b2b_logs_endpoint ON b2b_api_logs(endpoint);
CREATE INDEX IF NOT EXISTS idx_b2b_logs_billable ON b2b_api_logs(client_id, is_billable, timestamp);


-- ============================================================
-- 5. ТАБЛИЦА WEBHOOK ДОСТАВОК
-- ============================================================

CREATE TABLE IF NOT EXISTS b2b_webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id TEXT NOT NULL,
    client_id TEXT NOT NULL,

    -- URL и payload
    url TEXT NOT NULL,
    payload TEXT NOT NULL,

    -- Статус доставки
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, delivered, failed
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,

    -- Ответ сервера
    response_status INTEGER,
    response_body TEXT,
    error_message TEXT,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_attempt_at TEXT,
    delivered_at TEXT,

    FOREIGN KEY (check_id) REFERENCES b2b_checks(check_id),
    FOREIGN KEY (client_id) REFERENCES b2b_clients(client_id)
);

-- Индексы для webhook deliveries
CREATE INDEX IF NOT EXISTS idx_b2b_webhooks_status ON b2b_webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_b2b_webhooks_check ON b2b_webhook_deliveries(check_id);


-- ============================================================
-- 6. ТАБЛИЦА БИЛЛИНГА (помесячные итоги)
-- ============================================================

CREATE TABLE IF NOT EXISTS b2b_billing_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,

    -- Период
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,

    -- Использование
    total_checks INTEGER DEFAULT 0,
    checks_by_task TEXT,         -- JSON: {"19": 100, "20": 50, ...}

    -- Стоимость
    tier TEXT NOT NULL,
    base_price_rub INTEGER DEFAULT 0,
    overage_checks INTEGER DEFAULT 0,
    overage_price_rub INTEGER DEFAULT 0,
    total_price_rub INTEGER DEFAULT 0,

    -- Статус оплаты
    payment_status TEXT DEFAULT 'pending',  -- pending, paid, overdue
    invoice_id TEXT,
    paid_at TEXT,

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (client_id) REFERENCES b2b_clients(client_id),
    UNIQUE(client_id, year, month)
);

-- Индексы для billing
CREATE INDEX IF NOT EXISTS idx_b2b_billing_client ON b2b_billing_summary(client_id);
CREATE INDEX IF NOT EXISTS idx_b2b_billing_period ON b2b_billing_summary(year, month);
CREATE INDEX IF NOT EXISTS idx_b2b_billing_status ON b2b_billing_summary(payment_status);


-- ============================================================
-- 7. VIEWS ДЛЯ АНАЛИТИКИ
-- ============================================================

-- Активные клиенты с использованием
CREATE VIEW IF NOT EXISTS b2b_active_clients_view AS
SELECT
    c.client_id,
    c.company_name,
    c.tier,
    c.status,
    c.checks_today,
    c.checks_this_month,
    c.total_checks,
    c.monthly_quota,
    CASE
        WHEN c.monthly_quota IS NULL THEN 100
        WHEN c.monthly_quota = 0 THEN 0
        ELSE ROUND(100.0 * c.checks_this_month / c.monthly_quota, 1)
    END as quota_usage_percent,
    c.last_activity_at,
    (SELECT COUNT(*) FROM b2b_api_keys WHERE client_id = c.client_id AND is_active = 1) as active_keys_count
FROM b2b_clients c
WHERE c.status != 'suspended';


-- Статистика проверок по дням
CREATE VIEW IF NOT EXISTS b2b_daily_checks_view AS
SELECT
    client_id,
    date(created_at) as check_date,
    task_number,
    COUNT(*) as check_count,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
    AVG(processing_time_ms) as avg_processing_time_ms
FROM b2b_checks
GROUP BY client_id, date(created_at), task_number;
