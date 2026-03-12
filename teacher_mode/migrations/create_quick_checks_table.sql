-- Миграция: Создание таблицы для быстрых проверок работ учителями
-- Дата: 2025-12-20
-- Описание: Таблица для хранения проверок работ, не связанных с заданиями в боте

CREATE TABLE IF NOT EXISTS quick_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,

    -- Тип и содержание задания
    task_type TEXT NOT NULL,  -- 'task19', 'task20', 'task24', 'task25', 'custom'
    task_condition TEXT NOT NULL,  -- Условие задания

    -- Ответ ученика
    student_answer TEXT NOT NULL,
    student_id INTEGER,  -- Опционально - если хотим привязать к ученику

    -- Результат проверки
    ai_feedback TEXT,  -- Обратная связь от AI
    is_correct BOOLEAN,  -- Правильно/неправильно
    score INTEGER,  -- Оценка (опционально, для будущего)

    -- Комментарий учителя
    teacher_comment TEXT,

    -- Метаданные
    tags TEXT,  -- JSON массив тегов для категоризации
    template_name TEXT,  -- Если проверка создана из шаблона

    -- Timestamps
    created_at TEXT NOT NULL,
    updated_at TEXT,

    -- Внешние ключи
    FOREIGN KEY (teacher_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- Индексы для оптимизации запросов
CREATE INDEX IF NOT EXISTS idx_quick_checks_teacher
    ON quick_checks(teacher_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quick_checks_student
    ON quick_checks(student_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quick_checks_task_type
    ON quick_checks(task_type);

CREATE INDEX IF NOT EXISTS idx_quick_checks_created
    ON quick_checks(created_at DESC);

-- Таблица для шаблонов заданий (для экономии времени учителей)
CREATE TABLE IF NOT EXISTS quick_check_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    template_name TEXT NOT NULL,  -- Название шаблона
    task_type TEXT NOT NULL,
    task_condition TEXT NOT NULL,
    tags TEXT,  -- JSON массив тегов
    usage_count INTEGER DEFAULT 0,  -- Счетчик использований
    created_at TEXT NOT NULL,
    updated_at TEXT,

    FOREIGN KEY (teacher_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_templates_teacher
    ON quick_check_templates(teacher_id, template_name);

-- Таблица для учета квот проверок
CREATE TABLE IF NOT EXISTS quick_check_quotas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL UNIQUE,

    -- Квоты
    monthly_limit INTEGER NOT NULL DEFAULT 100,  -- Месячный лимит
    used_this_month INTEGER NOT NULL DEFAULT 0,  -- Использовано в этом месяце

    -- Период
    current_period_start TEXT NOT NULL,  -- Начало текущего периода
    current_period_end TEXT NOT NULL,  -- Конец текущего периода

    -- Дополнительные пакеты
    bonus_checks INTEGER DEFAULT 0,  -- Бонусные проверки (не сгорают)

    -- Timestamps
    last_reset_at TEXT,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (teacher_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_quotas_teacher
    ON quick_check_quotas(teacher_id);
