"""Плагин для задания 20."""

import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers
from core.states import ANSWERING_T20, SEARCHING, VIEWING_EXAMPLE, CONFIRMING_RESET

logger = logging.getLogger(__name__)

class Task20Plugin(BotPlugin):
    code = "task20"  # Изменить с "task20" на "t20"
    title = "🎯 Задание 20 (Суждения)"
    menu_priority = 16
    
    async def post_init(self, app):
        """Инициализация данных для задания 20."""
        try:
            await handlers.init_task20_data()
            logger.info(f"Task20 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task20 data: {e}")
    
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
                CommandHandler("task20", handlers.cmd_task20),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t20_practice$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t20_theory$"),
                    CallbackQueryHandler(handlers.how_to_write, pattern="^t20_how_to_write$"),
                    CallbackQueryHandler(handlers.good_examples, pattern="^t20_good_examples$"), 
                    CallbackQueryHandler(handlers.common_mistakes, pattern="^t20_common_mistakes$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.useful_phrases, pattern="^t20_useful_phrases$"),
                    CallbackQueryHandler(handlers.handle_theory_sections, pattern="^t20_(how_to_write|good_examples|common_mistakes|useful_phrases)$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t20_examples$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t20_progress$"),
                    CallbackQueryHandler(handlers.show_achievements, pattern="^t20_achievements$"),
                    CallbackQueryHandler(handlers.mistakes_mode, pattern="^t20_mistakes$"),
                    CallbackQueryHandler(handlers.settings_mode, pattern="^t20_settings$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),
                    CallbackQueryHandler(handlers.random_topic_all, pattern="^t20_random_all$"),

                    # Обработчики для выбора тем
                    CallbackQueryHandler(handlers.choose_topic, pattern="^t20_topic:"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t20_select_block$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t20_(new|retry)$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                    
                    # Навигация по темам
                    CallbackQueryHandler(handlers.block_menu, pattern="^t20_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t20_list_topics$"),
                    CallbackQueryHandler(handlers.select_topic, pattern=r"^t20_topic:\d+$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t20_random_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t20_list_topics:page:\d+$"),
                    # Дополнительные функции
                    CallbackQueryHandler(handlers.practice_stats, pattern="^t20_practice_stats$"),
                    CallbackQueryHandler(handlers.export_progress, pattern="^t20_export$"),
                    CallbackQueryHandler(handlers.detailed_progress, pattern="^t20_detailed_progress$"),
                    
                    # Настройки
                    CallbackQueryHandler(handlers.handle_settings_actions, pattern="^t20_(reset_progress|confirm_reset)$"),
                    CallbackQueryHandler(handlers.reset_progress, pattern="^t20_reset_progress$"),
                    CallbackQueryHandler(handlers.confirm_reset, pattern="^t20_confirm_reset$"),
                    
                    # Работа с банком примеров
                    CallbackQueryHandler(handlers.bank_nav, pattern=r"^t20_bank_nav:\d+$"),
                    CallbackQueryHandler(handlers.bank_search, pattern="^t20_bank_search$"),
                    CallbackQueryHandler(handlers.view_example, pattern="^t20_view_example:"),
                    CallbackQueryHandler(handlers.view_all_examples, pattern="^t20_all_examples$"),
                    CallbackQueryHandler(handlers.view_all_examples, pattern="^t20_all_examples:"),
                    CallbackQueryHandler(handlers.back_to_examples, pattern="^t20_back_examples$"),
                    CallbackQueryHandler(handlers.next_example, pattern="^t20_next_example$"),
                    CallbackQueryHandler(handlers.prev_example, pattern="^t20_prev_example$"),
                    CallbackQueryHandler(handlers.view_by_order, pattern="^t20_view_by_order$"),
                    CallbackQueryHandler(handlers.view_all_examples, pattern="^t20_view_all_examples"),
                    # Для совместимости
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_unexpected_message),
                ],
                
                states.ANSWERING_T20: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    MessageHandler(filters.Document.ALL, handlers.handle_answer_document_task20),
                    MessageHandler(filters.PHOTO, handlers.handle_answer_photo_task20),
                    CallbackQueryHandler(handlers.skip_question, pattern="^t20_skip$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t20_practice$"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t20_list_topics$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t20_(new|retry)$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t20_progress$"),

                ],
                
                states.SEARCHING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_bank_search),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t20_examples$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                ],
                
                states.VIEWING_EXAMPLE: [
                    CallbackQueryHandler(handlers.next_example, pattern="^t20_next_example$"),
                    CallbackQueryHandler(handlers.prev_example, pattern="^t20_prev_example$"),
                    CallbackQueryHandler(handlers.back_to_examples, pattern="^t20_back_examples$"),
                    CallbackQueryHandler(handlers.view_all_examples, pattern="^t20_view_all_examples$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t20_(new|retry)$"),
                ],
                
                states.CONFIRMING_RESET: [
                    CallbackQueryHandler(handlers.confirm_reset, pattern="^t20_confirm_reset$"),
                    CallbackQueryHandler(handlers.cancel_reset, pattern="^t20_cancel_reset$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
            ],
            name="task20_conversation",
            persistent=True,
            allow_reentry=True,
            per_message=False,
            per_chat=True,
            per_user=True
        )
        
        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        app.add_handler(
            CallbackQueryHandler(
                lambda u, c: u.callback_query.answer() if u.callback_query else None,
                pattern="^streak_ok$",
            )
        )
        app.add_handler(CallbackQueryHandler(handlers.handle_achievement_ok, pattern="^t20_achievement_ok$"))
        logger.info(f"Registered handlers for {self.title} plugin")

# Экспортируем плагин
plugin = Task20Plugin()