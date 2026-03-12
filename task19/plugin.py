"""Плагин для задания 19."""

import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)
from telegram import Update
from core.plugin_base import BotPlugin
from core import states
from . import handlers

logger = logging.getLogger(__name__)

async def handle_processing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для временного ответа."""
    if update.callback_query:
        await update.callback_query.answer("Обрабатывается...")
    return states.CHOOSING_MODE

async def handle_streak_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для подтверждения стрика."""
    if update.callback_query:
        await update.callback_query.answer()

class Task19Plugin(BotPlugin):
    code = "task19"
    title = "💡 Задание 19 (Примеры)"
    menu_priority = 15
    
    async def post_init(self, app):
        """Инициализация данных для задания 19."""
        try:
            await handlers.init_task19_data()
            logger.info(f"Task19 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task19 data: {e}")
            # Не падаем, даже если не удалось загрузить данные
            pass
    
    def entry_handler(self):
        """Возвращает обработчик для входа из главного меню."""
        return CallbackQueryHandler(
            handlers.entry_from_menu,
            pattern=f"^choose_{self.code}$"
        )
    
    def register(self, app):
        """Регистрация обработчиков в приложении."""
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$"
                ),
                CommandHandler("task19", handlers.cmd_task19),
                CommandHandler("task19_settings", handlers.cmd_task19_settings),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t19_theory$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t19_examples$"),
                    CallbackQueryHandler(handlers.show_progress_enhanced, pattern="^t19_progress$"),
                    CallbackQueryHandler(handlers.settings_mode, pattern="^t19_settings$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),

                    CallbackQueryHandler(
                        handlers.back_to_feedback,
                        pattern="^t19_back_to_feedback$"
                    ),
                    # Дополнительные действия
                    CallbackQueryHandler(handlers.reset_results, pattern="^t19_reset_confirm$"),
                    
                    # Обработчики для выбора тем
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                    
                    # Обработчики для кнопок результата (ВСЕ возможные варианты)
                    CallbackQueryHandler(handlers.handle_new_task, pattern="^t19_new$"),
                    CallbackQueryHandler(handlers.handle_retry, pattern="^t19_retry$"),
                    CallbackQueryHandler(handlers.handle_show_progress, pattern="^t19_progress$"),
                    CallbackQueryHandler(handlers.handle_theory, pattern="^t19_theory$"),
                    CallbackQueryHandler(handlers.handle_examples, pattern="^t19_examples$"),
                    CallbackQueryHandler(handlers.handle_achievements, pattern="^t19_achievements$"),
                    CallbackQueryHandler(handlers.handle_show_ideal, pattern="^t19_show_ideal$"),
                    
                    # Навигация по темам
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t19_list_topics($|:page:\d+)"),
                    CallbackQueryHandler(handlers.random_topic_all, pattern="^t19_random_all$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t19_random_block$"),



                    # Банк примеров
                    CallbackQueryHandler(handlers.bank_navigation, pattern="^t19_bank_nav:"),
                    CallbackQueryHandler(handlers.bank_search, pattern="^t19_bank_search$"),
                    
                    # Статистика
                    CallbackQueryHandler(handlers.detailed_progress, pattern="^t19_detailed_progress$"),
                    CallbackQueryHandler(handlers.export_results, pattern="^t19_export$"),
                    
                    # Теория - подразделы
                    CallbackQueryHandler(handlers.handle_theory_sections, pattern="^t19_(how_to_write|good_examples|common_mistakes|useful_phrases)$"),
                    
                    # Работа над ошибками
                    CallbackQueryHandler(handlers.retry_topic, pattern="^t19_retry_topic:"),
                    CallbackQueryHandler(handlers.mistakes_mode, pattern="^t19_mistakes$"),

                    # Детали достижений
                    CallbackQueryHandler(handlers.show_achievement_details, pattern="^t19_achievement:"),

                    # Сброс и подтверждения
                    CallbackQueryHandler(handlers.handle_settings_actions, pattern="^t19_(reset_progress|confirm_reset)$"),

                    # OCR обработчики
                    CallbackQueryHandler(handlers.handle_confirm_ocr, pattern="^t19_confirm_ocr$"),
                    CallbackQueryHandler(handlers.handle_edit_ocr, pattern="^t19_edit_ocr$"),
                    CallbackQueryHandler(handlers.handle_retry_photo, pattern="^t19_retry_photo$"),
                ],
                
                states.CHOOSING_BLOCK: [
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t19_list_topics$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t19_random_block$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                ],
                
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(handlers.select_topic, pattern="^t19_topic:"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t19_list_topics:page:\d+"),
                ],
                
                states.TASK19_WAITING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    MessageHandler(filters.Document.ALL, handlers.handle_answer_document_task19),
                    MessageHandler(filters.PHOTO, handlers.handle_answer_photo_task19),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                ],
                states.SEARCHING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_bank_search),
                ],
                states.AWAITING_FEEDBACK: [
                    CallbackQueryHandler(handlers.practice_mode, pattern="^next_topic$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^retry$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                CallbackQueryHandler(handle_processing, pattern="^t19_"),
            ],
            name="task19_conversation",
            persistent=True,
            allow_reentry=True,
            per_chat=True,
            per_user=True,
            per_message=False
        )
        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        app.add_handler(CallbackQueryHandler(
            handlers.achievement_ok,
            pattern="^achievement_ok$"
        ))
        app.add_handler(CallbackQueryHandler(handle_streak_ok, pattern="^streak_ok$"))
        logger.info(f"Registered handlers for {self.title} plugin")


# Экспортируем плагин
plugin = Task19Plugin()