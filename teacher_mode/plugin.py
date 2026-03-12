"""
Плагин режима учителя.
"""

import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

from core.plugin_base import BotPlugin
from .handlers import teacher_handlers, student_handlers, analytics_handlers, quick_check_handlers, variant_check_handlers
from .states import TeacherStates, StudentStates

logger = logging.getLogger(__name__)


class TeacherModePlugin(BotPlugin):
    """Плагин режима учителя"""

    code = "teacher_mode"
    title = "👨‍🏫 Режим учителя"
    menu_priority = 5  # Высокий приоритет

    async def post_init(self, app: Application):
        """Инициализация плагина"""
        # Автоматически применяем миграции Quick Check если нужно
        await self._ensure_quick_check_tables()
        logger.info("Teacher mode plugin initialized")

    async def _ensure_quick_check_tables(self):
        """Создает таблицы Quick Check если их нет"""
        import aiosqlite
        from core.config import DATABASE_FILE
        import os

        try:
            async with aiosqlite.connect(DATABASE_FILE) as db:
                # Проверяем существование таблицы
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='quick_check_quotas'"
                )
                exists = await cursor.fetchone()

                if not exists:
                    logger.info("Quick Check tables not found, running migration...")

                    # Читаем SQL миграции
                    migration_path = os.path.join(
                        os.path.dirname(__file__),
                        'migrations',
                        'create_quick_checks_table.sql'
                    )

                    with open(migration_path, 'r', encoding='utf-8') as f:
                        migration_sql = f.read()

                    # Выполняем миграцию (разбиваем на statements, т.к. executescript не поддерживается)
                    statements = [s.strip() for s in migration_sql.split(';') if s.strip()]

                    for statement in statements:
                        if statement:
                            await db.execute(statement)

                    await db.commit()

                    logger.info("✅ Quick Check tables created successfully")
                else:
                    logger.debug("Quick Check tables already exist")

        except Exception as e:
            logger.error(f"Error ensuring Quick Check tables: {e}", exc_info=True)

    def entry_handler(self):
        """Возвращает обработчик для входа из главного меню"""
        return CallbackQueryHandler(
            teacher_handlers.teacher_menu,
            pattern=f"^choose_{self.code}$"
        )

    def register(self, app: Application):
        """Регистрация обработчиков"""

        # ConversationHandler для учителей
        teacher_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern=f"^choose_{self.code}$"),
            ],
            states={
                TeacherStates.TEACHER_MENU: [
                    # Основные пункты меню
                    CallbackQueryHandler(teacher_handlers.teacher_profile, pattern="^teacher_profile$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_subscriptions, pattern="^teacher_subscriptions$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_plan_details, pattern="^buy_teacher_"),

                    # Обработчики оплаты подписки (используем обработчики из payment)
                    CallbackQueryHandler(teacher_handlers.handle_teacher_subscription_payment, pattern="^pay_teacher_"),
                    CallbackQueryHandler(teacher_handlers.handle_payment_callback, pattern="^confirm_teacher_plan:"),
                    CallbackQueryHandler(teacher_handlers.handle_payment_callback, pattern="^duration_"),

                    # Ученики и статистика
                    CallbackQueryHandler(teacher_handlers.show_student_list, pattern="^teacher_students$"),
                    CallbackQueryHandler(analytics_handlers.show_statistics, pattern="^teacher_statistics$"),
                    CallbackQueryHandler(teacher_handlers.show_teacher_assignments, pattern="^teacher_my_assignments$"),
                    CallbackQueryHandler(teacher_handlers.show_homework_stats, pattern="^homework_stats_"),

                    # Аналитика
                    CallbackQueryHandler(analytics_handlers.show_students_analytics, pattern="^analytics_students$"),
                    CallbackQueryHandler(analytics_handlers.show_student_detailed_analytics, pattern="^analytics_student:"),
                    CallbackQueryHandler(analytics_handlers.show_group_analytics, pattern="^analytics_group$"),

                    # Просмотр ответов учеников
                    CallbackQueryHandler(teacher_handlers.view_homework_submissions, pattern="^homework_submissions:"),
                    CallbackQueryHandler(teacher_handlers.view_student_progress, pattern="^view_student_progress:"),
                    CallbackQueryHandler(teacher_handlers.view_answer_detail, pattern="^view_answer:"),
                    CallbackQueryHandler(teacher_handlers.initiate_comment_entry, pattern="^add_comment:"),
                    CallbackQueryHandler(teacher_handlers.initiate_score_override, pattern="^override_score:"),

                    # Статистика ученика
                    CallbackQueryHandler(teacher_handlers.show_student_statistics, pattern="^student_stats:"),

                    # Быстрая проверка работ
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                    CallbackQueryHandler(quick_check_handlers.start_single_check, pattern="^qc_check_single$"),
                    CallbackQueryHandler(quick_check_handlers.start_bulk_check, pattern="^qc_check_bulk$"),
                    CallbackQueryHandler(quick_check_handlers.show_history, pattern="^qc_history$"),
                    CallbackQueryHandler(quick_check_handlers.show_stats, pattern="^qc_stats$"),

                    # Проверка варианта
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),

                    # Подарки и промокоды
                    CallbackQueryHandler(teacher_handlers.show_gift_subscription_menu, pattern="^teacher_gift_menu$"),
                    CallbackQueryHandler(teacher_handlers.show_promo_codes_list, pattern="^gift_my_promos$"),
                    CallbackQueryHandler(teacher_handlers.start_create_promo_code, pattern="^gift_create_promo$"),
                    CallbackQueryHandler(teacher_handlers.set_promo_duration, pattern="^promo_duration_"),
                    CallbackQueryHandler(teacher_handlers.create_promo_code_handler, pattern="^promo_uses_"),

                    # Создание задания
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),

                    # Навигация
                    CallbackQueryHandler(teacher_handlers.back_to_personal_cabinet, pattern="^back_to_cabinet$"),
                ],
                TeacherStates.CREATE_ASSIGNMENT: [
                    # Выбор типа задания
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),

                    # Выбор учеников
                    CallbackQueryHandler(teacher_handlers.toggle_student_selection, pattern="^toggle_student_"),

                    # Ввод названия задания
                    CallbackQueryHandler(teacher_handlers.prompt_assignment_title, pattern="^assignment_enter_title$"),

                    # Установка дедлайна
                    CallbackQueryHandler(teacher_handlers.set_assignment_deadline, pattern="^assignment_set_deadline$"),

                    # Создание задания
                    CallbackQueryHandler(teacher_handlers.confirm_and_create_assignment, pattern="^deadline_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_ASSIGNMENT_TITLE: [
                    # Обработка текстового ввода названия задания (включая команду /skip)
                    MessageHandler(filters.TEXT, teacher_handlers.process_assignment_title_input),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_SELECTION_MODE: [
                    # Выбор способа отбора заданий
                    CallbackQueryHandler(teacher_handlers.select_selection_mode, pattern="^selection_mode_"),

                    # Смешанное задание
                    CallbackQueryHandler(teacher_handlers.toggle_mixed_module_selection, pattern="^toggle_mixed_module:"),
                    CallbackQueryHandler(teacher_handlers.proceed_with_mixed_selection, pattern="^proceed_mixed_selection$"),

                    # Назад к выбору типа задания
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_TOPICS: [
                    # Переключение выбора блоков
                    CallbackQueryHandler(teacher_handlers.toggle_block_selection, pattern="^toggle_block:"),

                    # Подтверждение выбора блоков
                    CallbackQueryHandler(teacher_handlers.confirm_topic_blocks, pattern="^topics_confirm_blocks$"),

                    # Переключение выбора тем
                    CallbackQueryHandler(teacher_handlers.toggle_topic_selection, pattern="^toggle_topic:"),

                    # Подтверждение выбора тем
                    CallbackQueryHandler(teacher_handlers.confirm_topics_selection, pattern="^topics_confirm_topics$"),

                    # Фильтр по номеру задания ЕГЭ
                    CallbackQueryHandler(teacher_handlers.toggle_exam_number_filter, pattern="^toggle_exam_num:"),
                    CallbackQueryHandler(teacher_handlers.exam_number_filter_select_all, pattern="^exam_num_select_all$"),
                    CallbackQueryHandler(teacher_handlers.exam_number_filter_deselect_all, pattern="^exam_num_deselect_all$"),
                    CallbackQueryHandler(teacher_handlers.confirm_exam_number_filter, pattern="^exam_num_confirm$"),

                    # Навигация назад
                    CallbackQueryHandler(teacher_handlers.show_topics_selection, pattern="^topics_back_to_topics$"),
                    CallbackQueryHandler(teacher_handlers.show_exam_number_filter, pattern="^topics_back_to_exam_filter$"),

                    # Неактивная кнопка-заголовок (игнорируем)
                    CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"),

                    # Назад к выбору типа задания
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_SPECIFIC_QUESTIONS: [
                    # Переключение выбора конкретного задания
                    CallbackQueryHandler(teacher_handlers.toggle_question_selection, pattern="^toggle_question:"),

                    # Выбор/снятие всех заданий
                    CallbackQueryHandler(teacher_handlers.select_all_questions, pattern="^select_all_questions$"),
                    CallbackQueryHandler(teacher_handlers.deselect_all_questions, pattern="^deselect_all_questions$"),

                    # Подтверждение выбора заданий
                    CallbackQueryHandler(teacher_handlers.confirm_selected_questions, pattern="^confirm_selected_questions$"),

                    # Навигация назад
                    CallbackQueryHandler(teacher_handlers.show_topics_selection, pattern="^topics_back_to_topics$"),
                    CallbackQueryHandler(teacher_handlers.show_exam_number_filter, pattern="^topics_back_to_exam_filter$"),

                    # Назад к выбору типа задания
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_QUESTION_NUMBERS: [
                    # Обработка текстового ввода номеров заданий
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_question_numbers_input),

                    # Подтверждение выбранных номеров
                    CallbackQueryHandler(teacher_handlers.confirm_numbers_selection, pattern="^confirm_numbers_selection$"),
                    CallbackQueryHandler(teacher_handlers.confirm_exam_numbers_selection, pattern="^confirm_exam_numbers_selection$"),

                    # Браузер заданий - выбор способа ввода
                    CallbackQueryHandler(teacher_handlers.show_manual_numbers_input, pattern="^numbers_manual_"),
                    CallbackQueryHandler(teacher_handlers.show_question_browser, pattern="^numbers_browser_"),

                    # Браузер заданий - навигация и выбор
                    CallbackQueryHandler(teacher_handlers.toggle_question_browser, pattern="^browser_toggle_"),
                    CallbackQueryHandler(teacher_handlers.navigate_question_browser, pattern="^browser_(next|prev)_page$"),
                    CallbackQueryHandler(teacher_handlers.start_browser_search, pattern="^browser_search$"),
                    CallbackQueryHandler(teacher_handlers.clear_browser_search, pattern="^browser_clear_search$"),
                    CallbackQueryHandler(teacher_handlers.cancel_browser_search, pattern="^browser_cancel_search$"),
                    CallbackQueryHandler(teacher_handlers.confirm_browser_selection, pattern="^browser_confirm$"),

                    # Возврат к выбору способа ввода
                    CallbackQueryHandler(teacher_handlers.select_selection_mode, pattern="^selection_mode_"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.BROWSER_SEARCH: [
                    # Обработка текстового ввода поискового запроса
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_browser_search),

                    # Отмена поиска
                    CallbackQueryHandler(teacher_handlers.cancel_browser_search, pattern="^browser_cancel_search$"),

                    # Общая отмена
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_QUESTION_COUNT: [
                    # Обработка текстового ввода количества заданий для режима "все"
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_question_count_input),

                    # Подтверждение сгенерированных заданий
                    CallbackQueryHandler(teacher_handlers.confirm_all_tasks_selection, pattern="^confirm_all_tasks_selection$"),
                    CallbackQueryHandler(teacher_handlers.confirm_mixed_selection, pattern="^confirm_mixed_selection$"),
                    CallbackQueryHandler(teacher_handlers.confirm_full_exam, pattern="^confirm_full_exam$"),

                    # Перегенерация
                    CallbackQueryHandler(teacher_handlers.regenerate_all_tasks, pattern="^regenerate_all_tasks$"),
                    CallbackQueryHandler(teacher_handlers.regenerate_full_exam, pattern="^regenerate_full_exam$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.select_task_type, pattern="^assign_task_"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTERING_COMMENT: [
                    # Обработка текстового ввода комментария
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_teacher_comment),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.cancel_comment_entry, pattern="^cancel_comment:"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.OVERRIDING_SCORE: [
                    # Обработка кнопок принятия/отклонения ответа
                    CallbackQueryHandler(teacher_handlers.process_score_override, pattern="^set_score_accept:"),
                    CallbackQueryHandler(teacher_handlers.process_score_override, pattern="^set_score_reject:"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.view_answer_detail, pattern="^view_answer:"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_CUSTOM_QUESTION: [
                    # Обработка текстового ввода кастомного вопроса
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_custom_question),

                    # Кнопки управления
                    CallbackQueryHandler(teacher_handlers.finish_custom_questions, pattern="^finish_custom_questions$"),
                    CallbackQueryHandler(teacher_handlers.review_custom_questions, pattern="^review_custom_questions$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.REVIEW_CUSTOM_QUESTIONS: [
                    # Кнопки управления списком вопросов
                    CallbackQueryHandler(teacher_handlers.add_more_custom_questions, pattern="^add_more_custom_questions$"),
                    CallbackQueryHandler(teacher_handlers.finish_custom_questions, pattern="^finish_custom_questions$"),
                    CallbackQueryHandler(teacher_handlers.delete_last_custom_question, pattern="^delete_last_custom_question$"),

                    # Отмена
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.SELECT_CUSTOM_QUESTION_TYPE: [
                    # Выбор типа задания для кастомного вопроса
                    CallbackQueryHandler(teacher_handlers.select_custom_question_type, pattern="^custom_type_"),

                    # Выбор ввода ответа или пропуск
                    CallbackQueryHandler(teacher_handlers.prompt_custom_question_answer, pattern="^enter_custom_answer_"),

                    # Отмена текущего вопроса
                    CallbackQueryHandler(teacher_handlers.cancel_current_custom_question, pattern="^cancel_current_custom_question$"),

                    # Отмена создания задания
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.ENTER_CUSTOM_QUESTION_ANSWER: [
                    # Обработка текстового ввода правильного ответа/критериев
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.process_custom_question_answer),

                    # Отмена текущего вопроса
                    CallbackQueryHandler(teacher_handlers.cancel_current_custom_question, pattern="^cancel_current_custom_question$"),

                    # Отмена создания задания
                    CallbackQueryHandler(teacher_handlers.create_assignment_start, pattern="^teacher_create_assignment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.PAYMENT_ENTERING_PROMO: [
                    # Обработка ввода промокода
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.handle_promo_input),

                    # Пропуск промокода
                    CallbackQueryHandler(teacher_handlers.handle_skip_promo, pattern="^skip_promo$"),

                    # Навигация назад к выбору длительности
                    CallbackQueryHandler(teacher_handlers.handle_back_to_duration, pattern="^back_to_duration_selection$"),

                    # Отмена платежа
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^cancel_payment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.PAYMENT_ENTERING_EMAIL: [
                    # Обработка ввода email для оплаты
                    MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_handlers.handle_payment_email_input),

                    # Отмена платежа
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^cancel_payment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE: [
                    # Обработчики для бесплатной активации и оплаты 1 рубля
                    CallbackQueryHandler(teacher_handlers.handle_free_activation_teacher, pattern="^activate_free$"),
                    CallbackQueryHandler(teacher_handlers.handle_pay_one_ruble_teacher, pattern="^pay_one_ruble$"),

                    # Обработка выбора типа оплаты (автопродление или разовая)
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^choose_auto_renewal$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^choose_no_auto_renewal$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^show_auto_renewal_terms$"),

                    # Дополнительные обработчики для экрана согласия
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^toggle_consent_checkbox$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^confirm_with_auto_renewal$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^need_consent_reminder$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^show_user_agreement$"),
                    CallbackQueryHandler(teacher_handlers.handle_auto_renewal_choice, pattern="^back_to_payment_choice$"),

                    # Навигация назад к длительности
                    CallbackQueryHandler(teacher_handlers.handle_back_to_duration, pattern="^back_to_duration$"),

                    # Отмена платежа
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^cancel_payment$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                # ============================================
                # Quick Check States
                # ============================================
                TeacherStates.QUICK_CHECK_MENU: [
                    # Все обработчики из TEACHER_MENU (для навигации внутри QC)
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                    CallbackQueryHandler(quick_check_handlers.start_single_check, pattern="^qc_check_single$"),
                    CallbackQueryHandler(quick_check_handlers.start_bulk_check, pattern="^qc_check_bulk$"),
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(quick_check_handlers.show_history, pattern="^qc_history$"),
                    CallbackQueryHandler(quick_check_handlers.show_stats, pattern="^qc_stats$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.QUICK_CHECK_SELECT_TYPE: [
                    # Одиночная проверка
                    CallbackQueryHandler(quick_check_handlers.select_task_type, pattern="^qc_type_"),
                    # Массовая проверка
                    CallbackQueryHandler(quick_check_handlers.select_bulk_task_type, pattern="^qc_bulk_"),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.QUICK_CHECK_ENTER_CONDITION: [
                    # Ввод условия задания (текст)
                    MessageHandler(filters.TEXT & ~filters.COMMAND, quick_check_handlers.process_task_condition),
                    # Ввод условия задания (фото, например график для задания 21)
                    MessageHandler(filters.PHOTO, quick_check_handlers.process_task_condition_photo),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                ],
                TeacherStates.QUICK_CHECK_ENTER_SOURCE_TEXT: [
                    # Ввод текста-источника для задания 18
                    MessageHandler(filters.TEXT & ~filters.COMMAND, quick_check_handlers.process_qc_source_text),
                    # Пропуск текста-источника
                    CallbackQueryHandler(quick_check_handlers.skip_qc_source_text, pattern="^qc_skip_source_text$"),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                ],
                TeacherStates.QUICK_CHECK_ENTER_ANSWER: [
                    # Ввод ответа ученика (одиночная проверка) — текст или фото
                    MessageHandler(filters.TEXT & ~filters.COMMAND, quick_check_handlers.process_single_answer),
                    MessageHandler(filters.PHOTO, quick_check_handlers.process_single_answer_photo),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                ],
                TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK: [
                    # Ввод ответов (массовая проверка) — текст, фото или документ
                    MessageHandler(filters.TEXT & ~filters.COMMAND, quick_check_handlers.process_bulk_answers),
                    MessageHandler(filters.PHOTO, quick_check_handlers.process_bulk_answer_photo),
                    MessageHandler(filters.Document.ALL, quick_check_handlers.process_bulk_answer_document),
                    # Запуск проверки собранных ответов
                    CallbackQueryHandler(quick_check_handlers.run_bulk_check, pattern="^qc_run_bulk_check$"),
                    # Очистка списка
                    CallbackQueryHandler(quick_check_handlers.clear_bulk_answers, pattern="^qc_clear_bulk_answers$"),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                ],
                # ============================================
                # Variant Check States (Проверка варианта)
                # ============================================
                TeacherStates.VARIANT_CHECK_SOURCE: [
                    # Выбор источника варианта
                    CallbackQueryHandler(variant_check_handlers.select_source, pattern="^vc_source_"),
                    CallbackQueryHandler(variant_check_handlers.enter_variant_id, pattern="^vc_enter_variant_id$"),
                    # Ввод ID варианта из бота (текстовый ввод)
                    MessageHandler(filters.TEXT & ~filters.COMMAND, variant_check_handlers.process_variant_id_input),
                    # Навигация
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VARIANT_CHECK_SELECT_TASKS: [
                    # Выбор набора заданий
                    CallbackQueryHandler(variant_check_handlers.select_tasks_preset, pattern="^vc_tasks_"),
                    # Переключение заданий в кастомном режиме
                    CallbackQueryHandler(variant_check_handlers.toggle_task, pattern="^vc_toggle_"),
                    # Выбор группы заданий
                    CallbackQueryHandler(variant_check_handlers.select_group, pattern="^vc_select_"),
                    # Подтверждение выбора
                    CallbackQueryHandler(variant_check_handlers.confirm_tasks, pattern="^vc_confirm_tasks$"),
                    # Навигация
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VARIANT_CHECK_ENTER_KEYS: [
                    # Ввод ключей (текстом)
                    MessageHandler(filters.TEXT & ~filters.COMMAND, variant_check_handlers.process_keys_input),
                    # Ввод ключей (файлом)
                    MessageHandler(filters.Document.ALL, variant_check_handlers.process_keys_document),
                    # Ввод ключей (фото)
                    MessageHandler(filters.PHOTO, variant_check_handlers.process_keys_photo),
                    # Навигация
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VARIANT_CHECK_ENTER_SOURCE_TEXT: [
                    # Ввод текста-источника для задания 18 (текстом)
                    MessageHandler(filters.TEXT & ~filters.COMMAND, variant_check_handlers.process_source_text_input),
                    # Пропуск текста-источника
                    CallbackQueryHandler(variant_check_handlers.skip_source_text, pattern="^vc_skip_source_text$"),
                    # Навигация
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VARIANT_CHECK_ENTER_ANSWER: [
                    # Ввод ответа ученика (текст)
                    MessageHandler(filters.TEXT & ~filters.COMMAND, variant_check_handlers.process_student_answer),
                    # Ввод ответа ученика (файл)
                    MessageHandler(filters.Document.ALL, variant_check_handlers.process_answer_document),
                    # Ввод ответа ученика (фото)
                    MessageHandler(filters.PHOTO, variant_check_handlers.process_answer_photo),
                    # Пропустить задание
                    CallbackQueryHandler(variant_check_handlers.skip_task, pattern="^vc_skip_task$"),
                    # Завершить ввод и проверить
                    CallbackQueryHandler(variant_check_handlers.finish_input_callback, pattern="^vc_finish_input$"),
                    # Навигация
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VARIANT_CHECK_CONFIRM: [
                    # Выбор режима (один/несколько учеников)
                    CallbackQueryHandler(variant_check_handlers.select_mode, pattern="^vc_mode_"),
                    # Навигация
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VARIANT_CHECK_RESULTS: [
                    # Подробные результаты
                    CallbackQueryHandler(variant_check_handlers.show_detailed_results, pattern="^vc_detailed_results$"),
                    CallbackQueryHandler(variant_check_handlers.back_to_results, pattern="^vc_back_to_results$"),
                    # Пакетный режим: следующий ученик
                    CallbackQueryHandler(variant_check_handlers.next_student, pattern="^vc_next_student$"),
                    # Сводка по классу
                    CallbackQueryHandler(variant_check_handlers.show_batch_summary, pattern="^vc_batch_summary$"),
                    # Новая проверка
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(quick_check_handlers.quick_check_menu, pattern="^quick_check_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
                TeacherStates.VARIANT_CHECK_BATCH_NEXT: [
                    # Ввод ответов следующего ученика (текст, файл, фото)
                    MessageHandler(filters.TEXT & ~filters.COMMAND, variant_check_handlers.process_student_answer),
                    MessageHandler(filters.Document.ALL, variant_check_handlers.process_answer_document),
                    MessageHandler(filters.PHOTO, variant_check_handlers.process_answer_photo),
                    CallbackQueryHandler(variant_check_handlers.skip_task, pattern="^vc_skip_task$"),
                    CallbackQueryHandler(variant_check_handlers.finish_input_callback, pattern="^vc_finish_input$"),
                    CallbackQueryHandler(variant_check_handlers.variant_check_menu, pattern="^vc_menu$"),
                    CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(teacher_handlers.teacher_menu, pattern="^teacher_menu$"),
            ],
            name="teacher_conversation",
            persistent=True,
            allow_reentry=True,
        )

        # ConversationHandler для учеников (подключение к учителю)
        student_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(student_handlers.enter_teacher_code_start, pattern="^connect_to_teacher$"),
            ],
            states={
                StudentStates.ENTER_TEACHER_CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, student_handlers.process_teacher_code),
                    CallbackQueryHandler(student_handlers.cancel_connection, pattern="^main_menu$"),
                ],
                StudentStates.CONFIRM_TEACHER: [
                    CallbackQueryHandler(student_handlers.confirm_teacher_connection, pattern="^confirm_teacher_connection$"),
                    CallbackQueryHandler(student_handlers.cancel_connection, pattern="^main_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(student_handlers.cancel_connection, pattern="^main_menu$"),
            ],
            name="student_connect_conversation",
            persistent=True,
            allow_reentry=True,
        )

        # ConversationHandler для выполнения домашних заданий
        homework_execution_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(student_handlers.show_homework_question, pattern="^hw_question:"),
            ],
            states={
                StudentStates.DOING_HOMEWORK: [
                    # Прием ответа от ученика
                    MessageHandler(filters.TEXT & ~filters.COMMAND, student_handlers.process_homework_answer),

                    # Возврат к списку вопросов
                    CallbackQueryHandler(student_handlers.start_homework, pattern="^start_homework_\\d+$"),

                    # Возврат в главное меню
                    CallbackQueryHandler(student_handlers.cancel_homework_execution, pattern="^main_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(student_handlers.cancel_homework_execution, pattern="^main_menu$"),
            ],
            name="homework_execution",
            persistent=True,
            allow_reentry=True,
        )

        # Обработчики для работы с ДЗ ученика (вне conversation)
        app.add_handler(CallbackQueryHandler(student_handlers.homework_list, pattern="^student_homework_list$"))
        app.add_handler(CallbackQueryHandler(student_handlers.view_homework, pattern="^homework_\\d+$"))
        app.add_handler(CallbackQueryHandler(student_handlers.start_homework, pattern="^start_homework_\\d+$"))
        app.add_handler(CallbackQueryHandler(student_handlers.show_homework_explanation, pattern="^hw_show_explanation:"))

        # Обработчики для работы с платежами (вне conversation)
        app.add_handler(CallbackQueryHandler(teacher_handlers.handle_check_payment, pattern="^check_payment$"))
        app.add_handler(CallbackQueryHandler(teacher_handlers.handle_cancel_payment, pattern="^cancel_payment$"))

        # Регистрация ConversationHandler'ов
        # ВАЖНО: Используем group=-40 чтобы teacher conversation обрабатывался
        # ПОСЛЕ payment conversation (group=-50), но с более высоким приоритетом чем обычные handlers (group=0)
        # Это предотвращает конфликты: payment ConversationHandler проверяется первым,
        # но если пользователь уже в teacher conversation, то teacher handlers будут обрабатывать callbacks
        app.add_handler(teacher_conv_handler, group=-40)
        app.add_handler(student_conv_handler, group=-40)
        app.add_handler(homework_execution_handler, group=-40)

        logger.info("Teacher mode plugin handlers registered (group=-40)")


# Экспорт экземпляра плагина
plugin = TeacherModePlugin()
