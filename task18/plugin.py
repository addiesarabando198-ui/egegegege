"""Плагин для задания 18 ЕГЭ по обществознанию."""

import logging
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from core.plugin_base import BotPlugin
from core import states
from core.states import ANSWERING_T18, AWAITING_T17_TEXT
from . import handlers

logger = logging.getLogger(__name__)


class Task18Plugin(BotPlugin):
    code = "task18"
    title = "📝 Задание 18 (Понятие из текста)"
    menu_priority = 15

    async def post_init(self, app):
        """Инициализация данных."""
        try:
            await handlers.init_task18_data()
            logger.info("Task18 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task18 data: {e}")

    def entry_handler(self):
        return CallbackQueryHandler(
            handlers.entry_from_menu,
            pattern=f"^choose_{self.code}$",
        )

    def register(self, app):
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$",
                ),
                CommandHandler("task18", handlers.cmd_task18),
            ],
            states={
                states.CHOOSING_MODE: [
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t18_practice$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t18_progress$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t18_menu$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t18_(new)$"),
                ],
                AWAITING_T17_TEXT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, handlers.handle_task17_text
                    ),
                    CallbackQueryHandler(handlers.skip_task17_text, pattern="^t18_skip_t17$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t18_menu$"),
                ],
                ANSWERING_T18: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, handlers.handle_answer
                    ),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t18_menu$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t18_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
            ],
            name="task18_conversation",
            persistent=True,
            allow_reentry=True,
            per_message=False,
            per_chat=True,
            per_user=True,
        )

        app.add_handler(conv_handler)
        logger.info(f"Registered handlers for {self.title} plugin")


plugin = Task18Plugin()
