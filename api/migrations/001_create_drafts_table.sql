-- Создание таблицы для хранения черновиков заданий
-- Черновики позволяют учителям сохранять незавершенные задания

CREATE TABLE IF NOT EXISTS assignment_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT UNIQUE NOT NULL,
    teacher_id INTEGER NOT NULL,
    draft_data TEXT NOT NULL,  -- JSON с данными черновика
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES teacher_profiles(user_id) ON DELETE CASCADE
);

-- Индексы для ускорения запросов
CREATE INDEX IF NOT EXISTS idx_drafts_teacher_id ON assignment_drafts(teacher_id);
CREATE INDEX IF NOT EXISTS idx_drafts_draft_id ON assignment_drafts(draft_id);
CREATE INDEX IF NOT EXISTS idx_drafts_updated_at ON assignment_drafts(updated_at DESC);
