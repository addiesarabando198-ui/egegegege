import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

# Импортируем константу ANSWERING_PARTS
from core.states import ANSWERING_PARTS, CHOOSING_BLOCK_T25

logger = logging.getLogger(__name__)

# Добавляем новые состояния из core.states

class Task25Plugin(BotPlugin):
    code = "task25"
    title = "✍️ Задание 25  (Развёрнутый ответ)"
    menu_priority = 20  # После task24 (19)
    
    async def post_init(self, app):
        """Инициализация данных для задания 25."""
        try:
            await handlers.init_task25_data()
            logger.info(f"Task25 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task25 data: {e}")
    
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
                CommandHandler("task25", handlers.cmd_task25),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t25_practice$"),
                    CallbackQueryHandler(handlers.by_difficulty, pattern="^t25_by_difficulty$"),
                    CallbackQueryHandler(handlers.recommended_topic, pattern="^t25_recommended$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t25_theory$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t25_examples$"),
                    CallbackQueryHandler(handlers.show_examples_block, pattern="^t25_examples_block:"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t25_progress$"),
                    CallbackQueryHandler(handlers.settings_mode, pattern="^t25_settings$"),
                    CallbackQueryHandler(handlers.list_all_topics, pattern="^t25_all_topics_list$"),
                    CallbackQueryHandler(handlers.list_by_difficulty, pattern="^t25_list_by_diff:"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),
                    CallbackQueryHandler(handlers.by_block, pattern="^t25_by_block$"),
                    CallbackQueryHandler(handlers.handle_difficulty_selected, pattern="^t25_diff:"),
                    # Обработчики для выбора тем
                    CallbackQueryHandler(handlers.select_block, pattern="^t25_select_block$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t25_(new|retry)$"),
                    CallbackQueryHandler(handlers.another_topic_from_current, pattern="^t25_another_topic$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                    
                    # Навигация по темам
                    CallbackQueryHandler(handlers.block_menu, pattern="^t25_block:"),
                    CallbackQueryHandler(handlers.show_topic_list, pattern="^t25_list_topics:"),
                    CallbackQueryHandler(handlers.show_topic_by_id, pattern="^t25_topic:"),
                    CallbackQueryHandler(handlers.random_topic_all, pattern="^t25_random_all$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t25_random_block$"),
                    
                    # Настройки
                    CallbackQueryHandler(handlers.handle_settings_change, pattern="^t25_set_mode:"),
                    CallbackQueryHandler(handlers.toggle_examples, pattern="^t25_toggle_examples$"),
                    CallbackQueryHandler(handlers.strictness_menu, pattern="^t25_strictness_menu$"),
                    CallbackQueryHandler(handlers.set_strictness, pattern="^t25_strictness:"),
                    
                    # Банк примеров
                    CallbackQueryHandler(handlers.search_examples, pattern="^t25_search_examples$"),
                    CallbackQueryHandler(handlers.examples_by_block, pattern="^t25_examples_by_block$"),
                    CallbackQueryHandler(handlers.best_examples, pattern="^t25_best_examples$"),
                    CallbackQueryHandler(handlers.show_topic_by_id, pattern="^t25_show_example:"),
                    CallbackQueryHandler(handlers.handle_example_navigation, pattern="^t25_example_nav:"),
                    CallbackQueryHandler(handlers.noop, pattern="^t25_noop$"),
                    CallbackQueryHandler(handlers.show_topic_by_id, pattern="^t25_try_topic:"),
                    
                    # Теория
                    CallbackQueryHandler(handlers.example_answers, pattern="^t25_example_answers$"),
                    CallbackQueryHandler(handlers.common_mistakes, pattern="^t25_common_mistakes$"),
                    
                    # Прогресс
                    CallbackQueryHandler(handlers.detailed_stats, pattern="^t25_detailed_stats$"),
                    CallbackQueryHandler(handlers.handle_export, pattern="^t25_export$"),
                    CallbackQueryHandler(handlers.handle_detailed_stats, pattern="^t25_detailed_progress$"),
                    CallbackQueryHandler(handlers.handle_reset_confirm, pattern="^t25_reset_confirm$"),
                    CallbackQueryHandler(handlers.handle_do_reset, pattern="^t25_do_reset$"),
                    CallbackQueryHandler(handlers.recommendations, pattern="^t25_recommendations$"),
                ],
                
                states.ANSWERING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.safe_handle_answer_task25),
                    MessageHandler(filters.Document.ALL, handlers.handle_answer_document_task25),
                    MessageHandler(filters.PHOTO, handlers.handle_answer_photo_task25),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t25_practice$"),
                    CallbackQueryHandler(handlers.another_topic_from_current, pattern="^t25_another_topic$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t25_random_block$"),
                    CallbackQueryHandler(handlers.block_menu, pattern="^t25_block:"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                ],

                ANSWERING_PARTS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer_parts),
                    MessageHandler(filters.Document.ALL, handlers.handle_answer_document_task25),
                    MessageHandler(filters.PHOTO, handlers.handle_answer_photo_task25),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t25_practice$"),
                    CallbackQueryHandler(handlers.block_menu, pattern="^t25_block:"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                ],
                
                CHOOSING_BLOCK_T25: [
                    CallbackQueryHandler(handlers.block_menu, pattern="^t25_block:"),
                    CallbackQueryHandler(handlers.show_topic_list, pattern="^t25_list_topics:"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t25_random_block$"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t25_select_block$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t25_practice$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                ],
                
                states.AWAITING_FEEDBACK: [
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t25_retry$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t25_new$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t25_progress$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                    CallbackQueryHandler(handlers.another_topic_from_current, pattern="^t25_another_topic$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t25_practice$"),
                ],
                
                states.SEARCHING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_bank_search),
                    CallbackQueryHandler(handlers.cancel_search, pattern="^t25_examples$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
            ],
            name="task25_conversation",
            persistent=True,
        )
        
        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        app.add_handler(
            CallbackQueryHandler(
                lambda u, c: u.callback_query.answer() if u.callback_query else None,
                pattern="^streak_ok$",
            )
        )

        # Дополнительные хендлеры, не охваченные ConversationHandler
        if hasattr(handlers, "register_task25_handlers"):
            handlers.register_task25_handlers(app)
        app.add_handler(CommandHandler("t25status", handlers.cmd_t25status))
        app.add_handler(CommandHandler("t25debug", handlers.cmd_debug_data))
        logger.info(f"Registered handlers for {self.title} plugin")

# Экспортируем плагин
plugin = Task25Plugin()

__all__ = ['plugin']