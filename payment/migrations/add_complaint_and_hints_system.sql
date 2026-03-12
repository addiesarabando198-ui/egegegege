-- payment/migrations/add_complaint_and_hints_system.sql
-- Миграция для системы жалоб учеников и автоматического улучшения промптов AI

-- ==========================================
-- 1. РАСШИРЕНИЕ ТАБЛИЦЫ user_feedback
-- ==========================================
-- Добавляем поля для контекста AI-проверки и жалоб

-- Проверяем, существует ли таблица user_feedback
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

-- Добавляем новые колонки для жалоб на AI-проверку
-- Используем ALTER TABLE для добавления новых полей
ALTER TABLE user_feedback ADD COLUMN task_type TEXT;
ALTER TABLE user_feedback ADD COLUMN topic_name TEXT;
ALTER TABLE user_feedback ADD COLUMN user_answer TEXT;
ALTER TABLE user_feedback ADD COLUMN ai_feedback TEXT;
ALTER TABLE user_feedback ADD COLUMN k1_score INTEGER;
ALTER TABLE user_feedback ADD COLUMN k2_score INTEGER;
ALTER TABLE user_feedback ADD COLUMN complaint_reason TEXT;
ALTER TABLE user_feedback ADD COLUMN resolution_type TEXT CHECK(resolution_type IN ('approved', 'rejected', 'partial'));

-- ==========================================
-- 2. ТАБЛИЦА task_specific_hints (КЛЮЧЕВАЯ)
-- ==========================================
-- Хранит подсказки для AI, созданные на основе одобренных жалоб

CREATE TABLE IF NOT EXISTS task_specific_hints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Контекст задачи
    task_type TEXT NOT NULL,  -- 'task24', 'task19', 'task20', 'task25'
    topic_name TEXT,           -- Для Task24: конкретная тема (например, "Политические партии")
                               -- NULL = применяется ко всем темам этого типа задачи

    -- Текст подсказки
    hint_text TEXT NOT NULL,   -- Сама подсказка для AI: "Учитывай, что..."
    hint_category TEXT CHECK(hint_category IN ('factual', 'structural', 'terminology', 'criteria', 'general')),
                               -- Категория подсказки:
                               --   factual: фактические аспекты
                               --   structural: структура ответа/плана
                               --   terminology: терминология
                               --   criteria: критерии оценки
                               --   general: общие рекомендации

    -- Приоритет и активность
    priority INTEGER DEFAULT 1 CHECK(priority >= 1 AND priority <= 5),
                               -- 1-5 (чем выше, тем важнее)
                               -- Влияет на порядок отображения в промпте
    is_active BOOLEAN DEFAULT 1,
                               -- Можно отключить подсказку без удаления

    -- Метаданные для отслеживания
    created_from_complaint_id INTEGER,  -- Ссылка на жалобу, которая привела к созданию
    created_by_admin_id INTEGER,        -- ID администратора, создавшего подсказку
    usage_count INTEGER DEFAULT 0,      -- Сколько раз подсказка применялась
    success_rate FLOAT,                 -- Опционально: % случаев, когда помогла
                                        -- Вычисляется через аналитику

    -- Временные метки
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,               -- Опционально: срок действия подсказки
                                        -- Полезно для временных изменений в КИМ

    FOREIGN KEY (created_from_complaint_id) REFERENCES user_feedback(id)
);

-- Индексы для быстрого поиска подсказок
CREATE INDEX IF NOT EXISTS idx_hints_task_topic
ON task_specific_hints(task_type, topic_name, is_active);

CREATE INDEX IF NOT EXISTS idx_hints_priority
ON task_specific_hints(priority DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_hints_active
ON task_specific_hints(is_active, expires_at);

-- ==========================================
-- 3. ТАБЛИЦА hint_application_log
-- ==========================================
-- Логирует каждое применение подсказки для аналитики

CREATE TABLE IF NOT EXISTS hint_application_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hint_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    topic_name TEXT,
    task_type TEXT,
    was_helpful BOOLEAN,  -- Опционально: была ли подсказка полезной
                          -- Можно определить через отсутствие жалоб после проверки
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (hint_id) REFERENCES task_specific_hints(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Индексы для аналитики
CREATE INDEX IF NOT EXISTS idx_hint_log_hint
ON hint_application_log(hint_id, applied_at);

CREATE INDEX IF NOT EXISTS idx_hint_log_user
ON hint_application_log(user_id, applied_at);

-- ==========================================
-- 4. ПРЕДСТАВЛЕНИЯ ДЛЯ АНАЛИТИКИ
-- ==========================================

-- Представление: Активные подсказки с статистикой использования
CREATE VIEW IF NOT EXISTS active_hints_with_stats AS
SELECT
    tsh.id,
    tsh.task_type,
    tsh.topic_name,
    tsh.hint_text,
    tsh.hint_category,
    tsh.priority,
    tsh.usage_count,
    tsh.created_at,
    tsh.expires_at,
    COUNT(DISTINCT hal.user_id) as unique_users_count,
    AVG(CASE WHEN hal.was_helpful = 1 THEN 1.0 ELSE 0.0 END) as calculated_success_rate
FROM task_specific_hints tsh
LEFT JOIN hint_application_log hal ON tsh.id = hal.hint_id
WHERE tsh.is_active = 1
  AND (tsh.expires_at IS NULL OR tsh.expires_at > datetime('now'))
GROUP BY tsh.id
ORDER BY tsh.priority DESC, tsh.usage_count DESC;

-- Представление: Жалобы, ожидающие обработки
CREATE VIEW IF NOT EXISTS pending_complaints AS
SELECT
    uf.id,
    uf.user_id,
    uf.task_type,
    uf.topic_name,
    uf.complaint_reason,
    uf.message,
    uf.k1_score,
    uf.k2_score,
    uf.created_at,
    (SELECT COUNT(*)
     FROM user_feedback uf2
     WHERE uf2.user_id = uf.user_id
       AND uf2.feedback_type = 'complaint'
       AND uf2.status = 'resolved') as user_resolved_complaints_count
FROM user_feedback uf
WHERE uf.feedback_type = 'complaint'
  AND uf.status = 'new'
ORDER BY uf.created_at ASC;

-- Представление: Статистика жалоб по темам
CREATE VIEW IF NOT EXISTS complaints_by_topic AS
SELECT
    task_type,
    topic_name,
    COUNT(*) as total_complaints,
    SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved_count,
    SUM(CASE WHEN resolution_type = 'approved' THEN 1 ELSE 0 END) as approved_count,
    AVG(k1_score) as avg_k1_score,
    AVG(k2_score) as avg_k2_score,
    MAX(created_at) as last_complaint_date
FROM user_feedback
WHERE feedback_type = 'complaint'
  AND topic_name IS NOT NULL
GROUP BY task_type, topic_name
ORDER BY total_complaints DESC;

-- Представление: Эффективность подсказок
CREATE VIEW IF NOT EXISTS hint_effectiveness AS
SELECT
    tsh.id as hint_id,
    tsh.hint_text,
    tsh.topic_name,
    tsh.priority,
    tsh.usage_count,
    tsh.created_at,
    COUNT(DISTINCT hal.user_id) as users_affected,
    -- Количество жалоб ДО создания подсказки
    (SELECT COUNT(*)
     FROM user_feedback uf
     WHERE uf.topic_name = tsh.topic_name
       AND uf.feedback_type = 'complaint'
       AND uf.created_at < tsh.created_at
       AND uf.created_at >= datetime(tsh.created_at, '-30 days')
    ) as complaints_before,
    -- Количество жалоб ПОСЛЕ создания подсказки
    (SELECT COUNT(*)
     FROM user_feedback uf
     WHERE uf.topic_name = tsh.topic_name
       AND uf.feedback_type = 'complaint'
       AND uf.created_at >= tsh.created_at
       AND uf.created_at <= datetime(tsh.created_at, '+30 days')
    ) as complaints_after
FROM task_specific_hints tsh
LEFT JOIN hint_application_log hal ON tsh.id = hal.hint_id
WHERE tsh.is_active = 1
GROUP BY tsh.id
ORDER BY tsh.usage_count DESC;

-- ==========================================
-- 5. ТРИГГЕРЫ
-- ==========================================

-- Триггер: Обновление updated_at при изменении жалобы
CREATE TRIGGER IF NOT EXISTS update_feedback_timestamp
AFTER UPDATE ON user_feedback
BEGIN
    UPDATE user_feedback
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- Триггер: Автоматическое увеличение usage_count при применении подсказки
-- (альтернатива ручному увеличению в коде)
CREATE TRIGGER IF NOT EXISTS increment_hint_usage
AFTER INSERT ON hint_application_log
BEGIN
    UPDATE task_specific_hints
    SET usage_count = usage_count + 1
    WHERE id = NEW.hint_id;
END;

-- ==========================================
-- 6. НАЧАЛЬНЫЕ ДАННЫЕ (опционально)
-- ==========================================

-- Примеры подсказок для демонстрации системы
-- В продакшене эти данные будут создаваться администраторами через жалобы

-- Пример 1: Фактическая подсказка для темы "Политические партии"
INSERT OR IGNORE INTO task_specific_hints
(task_type, topic_name, hint_text, hint_category, priority, created_by_admin_id, is_active)
VALUES
('task24', 'Политические партии',
 'Учитывай, что в России разрешены многопартийность и плюрализм согласно Конституции РФ. Упоминание только одной партии в контексте примера НЕ является фактической ошибкой, если контекст изложен правильно.',
 'factual', 5, 0, 1);

-- Пример 2: Структурная подсказка для темы "Уровни научного познания"
INSERT OR IGNORE INTO task_specific_hints
(task_type, topic_name, hint_text, hint_category, priority, created_by_admin_id, is_active)
VALUES
('task24', 'Уровни научного познания',
 'Для темы "Уровни научного познания" допустимы ТОЛЬКО 2 подпункта (эмпирический и теоретический уровни) — это научно обоснованная классификация согласно методологии науки. Не требуй 3 подпункта для этой темы.',
 'structural', 5, 0, 1);

-- Пример 3: Терминологическая подсказка
INSERT OR IGNORE INTO task_specific_hints
(task_type, topic_name, hint_text, hint_category, priority, created_by_admin_id, is_active)
VALUES
('task24', 'Социальный контроль',
 'Термины "санкции" и "меры воздействия" являются синонимами в контексте социального контроля. Не засчитывай это как терминологическую ошибку или неточность.',
 'terminology', 4, 0, 1);

-- Пример 4: Общая подсказка для всех задач Task24
INSERT OR IGNORE INTO task_specific_hints
(task_type, topic_name, hint_text, hint_category, priority, created_by_admin_id, is_active)
VALUES
('task24', NULL,
 'При оценке фактической точности (K2) различай фактические ОШИБКИ от просто неполного раскрытия темы. Неполное раскрытие влияет на K1, но НЕ должно обнулять K2.',
 'criteria', 5, 0, 1);

-- ==========================================
-- 7. ИНДЕКСЫ user_feedback (если не созданы ранее)
-- ==========================================

CREATE INDEX IF NOT EXISTS idx_feedback_status
ON user_feedback(status, created_at);

CREATE INDEX IF NOT EXISTS idx_feedback_type
ON user_feedback(feedback_type, status);

CREATE INDEX IF NOT EXISTS idx_feedback_user
ON user_feedback(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_feedback_task_topic
ON user_feedback(task_type, topic_name, status);

-- ==========================================
-- КОНЕЦ МИГРАЦИИ
-- ==========================================
