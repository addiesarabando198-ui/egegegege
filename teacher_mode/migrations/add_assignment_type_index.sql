-- Миграция: Добавление индекса на assignment_type
-- Дата: 2026-01-06
-- Описание: Добавляет индекс на поле assignment_type для быстрой фильтрации заданий по типу

-- ИСПРАВЛЕНО: Индекс на assignment_type для оптимизации фильтрации
-- Используется в: get_assignments(), API фильтрация по типу задания
CREATE INDEX IF NOT EXISTS idx_homework_assignments_type
ON homework_assignments(assignment_type);

-- Составной индекс для комбинированной фильтрации по учителю и типу
-- Используется в: get_teacher_homeworks() с фильтром по типу
CREATE INDEX IF NOT EXISTS idx_homework_assignments_teacher_type
ON homework_assignments(teacher_id, assignment_type, status);

-- Обновляем статистику для оптимизатора запросов
ANALYZE homework_assignments;
