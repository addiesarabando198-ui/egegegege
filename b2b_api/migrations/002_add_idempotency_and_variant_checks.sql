-- Миграция 002: idempotency_key для b2b_checks + variant_checks из teacher_mode
-- Версия: 2026-03-01
-- Описание:
--   1. Добавляет колонку idempotency_key в b2b_checks для предотвращения дублей
--   2. Переносит создание variant_checks из динамического ensure_tables() в миграцию

-- ============================================================
-- 1. IDEMPOTENCY KEY для b2b_checks
-- ============================================================

ALTER TABLE b2b_checks ADD COLUMN idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_b2b_checks_idempotency
    ON b2b_checks(client_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;


-- ============================================================
-- 2. ТАБЛИЦА variant_checks (из teacher_mode)
-- ============================================================
-- Ранее создавалась динамически в variant_check_service.ensure_tables().
-- Теперь создаётся миграцией для стабильности.

CREATE TABLE IF NOT EXISTS variant_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    variant_source TEXT NOT NULL,
    variant_id TEXT,
    tasks_checked TEXT NOT NULL,
    student_name TEXT,
    results_json TEXT NOT NULL,
    total_score INTEGER,
    max_score INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_variant_checks_teacher
    ON variant_checks(teacher_id, created_at DESC);
