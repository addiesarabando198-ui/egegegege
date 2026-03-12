-- Миграция: Добавление индексов для оптимизации производительности
-- Дата: 2025-12-16
-- Описание: Добавляет индексы для критичных запросов модуля Режим Учителя

-- ==================== ИНДЕКСЫ ДЛЯ HOMEWORK_STUDENT_ASSIGNMENTS ====================

-- Индекс для поиска заданий ученика по статусу
-- Используется в: get_student_homeworks(), count_new_homeworks()
CREATE INDEX IF NOT EXISTS idx_homework_student_assignments_student_status
ON homework_student_assignments(student_id, status);

-- Индекс для поиска всех назначений по homework_id
-- Используется в: get_homework_statistics(), get_homework_all_progress()
CREATE INDEX IF NOT EXISTS idx_homework_student_assignments_homework
ON homework_student_assignments(homework_id);

-- Составной индекс для обновления статусов
-- Используется в: update_student_assignment_status()
CREATE INDEX IF NOT EXISTS idx_homework_student_assignments_homework_student
ON homework_student_assignments(homework_id, student_id);


-- ==================== ИНДЕКСЫ ДЛЯ HOMEWORK_PROGRESS ====================

-- Индекс для получения прогресса ученика по заданию
-- Используется в: get_homework_student_progress(), get_completed_question_ids()
CREATE INDEX IF NOT EXISTS idx_homework_progress_homework_student
ON homework_progress(homework_id, student_id);

-- Индекс для поиска конкретного ответа
-- Используется в: get_question_progress()
CREATE INDEX IF NOT EXISTS idx_homework_progress_homework_student_question
ON homework_progress(homework_id, student_id, question_id);

-- Индекс для получения всего прогресса по заданию
-- Используется в: get_homework_all_progress(), analytics
CREATE INDEX IF NOT EXISTS idx_homework_progress_homework
ON homework_progress(homework_id);


-- ==================== ИНДЕКСЫ ДЛЯ HOMEWORK_ASSIGNMENTS ====================

-- Индекс для получения заданий учителя
-- Используется в: get_teacher_homeworks(), analytics
CREATE INDEX IF NOT EXISTS idx_homework_assignments_teacher
ON homework_assignments(teacher_id, status);

-- Индекс для поиска активных заданий с дедлайнами
-- Используется в: deadline_scheduler
CREATE INDEX IF NOT EXISTS idx_homework_assignments_deadline_status
ON homework_assignments(deadline, status)
WHERE deadline IS NOT NULL;


-- ==================== ИНДЕКСЫ ДЛЯ TEACHER_STUDENT_RELATIONSHIPS ====================

-- Индекс для получения активных учеников учителя
-- Используется в: get_teacher_students(), can_add_student()
CREATE INDEX IF NOT EXISTS idx_teacher_student_relationships_teacher_status
ON teacher_student_relationships(teacher_id, status);

-- Индекс для получения учителей ученика
-- Используется в: get_student_teachers()
CREATE INDEX IF NOT EXISTS idx_teacher_student_relationships_student_status
ON teacher_student_relationships(student_id, status);

-- Индекс для проверки связи учитель-ученик
-- Используется в: is_student_connected()
CREATE INDEX IF NOT EXISTS idx_teacher_student_relationships_both
ON teacher_student_relationships(teacher_id, student_id, status);


-- ==================== ИНДЕКСЫ ДЛЯ TEACHER_PROFILES ====================

-- Индекс для поиска по teacher_code
-- Используется в: get_teacher_by_code(), generate_teacher_code()
CREATE INDEX IF NOT EXISTS idx_teacher_profiles_code
ON teacher_profiles(teacher_code);

-- Индекс для поиска истекших подписок
-- Используется в: subscription_scheduler
CREATE INDEX IF NOT EXISTS idx_teacher_profiles_subscription_expires
ON teacher_profiles(subscription_expires, has_active_subscription)
WHERE subscription_expires IS NOT NULL;


-- ==================== ИНДЕКСЫ ДЛЯ DEADLINE_REMINDERS ====================

-- Индекс для проверки отправленных напоминаний
-- Используется в: has_recent_reminder()
CREATE INDEX IF NOT EXISTS idx_deadline_reminders_student_homework_sent
ON deadline_reminders(student_id, homework_id, sent_at);


-- ==================== ИНДЕКСЫ ДЛЯ GIFTED_SUBSCRIPTIONS ====================

-- Индекс для поиска активных подарочных подписок
-- Используется в: get_active_gifted_subscription()
CREATE INDEX IF NOT EXISTS idx_gifted_subscriptions_recipient_status
ON gifted_subscriptions(recipient_id, status, expires_at);


-- ==================== ИНДЕКСЫ ДЛЯ GIFT_PROMO_CODES ====================

-- Индекс для поиска промокода
-- Используется в: get_promo_code(), validate_and_use_promo_code()
CREATE INDEX IF NOT EXISTS idx_gift_promo_codes_code
ON gift_promo_codes(code);

-- Индекс для поиска промокодов учителя
-- Используется в: get_teacher_promo_codes()
CREATE INDEX IF NOT EXISTS idx_gift_promo_codes_creator
ON gift_promo_codes(creator_id);


-- ==================== ИНДЕКСЫ ДЛЯ PROMO_CODE_USAGE ====================

-- Индекс для проверки использования промокода
-- Используется в: validate_and_use_promo_code()
CREATE INDEX IF NOT EXISTS idx_promo_code_usage_code_student
ON promo_code_usage(promo_code, student_id);


-- ==================== СТАТИСТИКА ПО ИНДЕКСАМ ====================
-- После применения миграции рекомендуется выполнить:
-- ANALYZE;
-- Это обновит статистику для оптимизатора запросов SQLite
