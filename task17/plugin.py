"""Плагин для задания 17 ЕГЭ по обществознанию."""

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
from core.states import ANSWERING_T17
from . import handlers

logger = logging.getLogger(__name__)


class Task17Plugin(BotPlugin):
    code = "task17"
    title = "📖 Задание 17 (Анализ текста)"
    menu_priority = 14

    async def post_init(self, app):
        """Инициализация данных."""
        try:
            await handlers.init_task17_data()
            logger.info("Task17 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task17 data: {e}")

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
                CommandHandler("task17", handlers.cmd_task17),
            ],
            states={
                states.CHOOSING_MODE: [
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t17_practice$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t17_progress$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t17_menu$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t17_(new)$"),
                ],
                ANSWERING_T17: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, handlers.handle_answer
                    ),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t17_menu$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t17_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
            ],
            name="task17_conversation",
            persistent=True,
            allow_reentry=True,
            per_message=False,
            per_chat=True,
            per_user=True,
        )

        app.add_handler(conv_handler)
        logger.info(f"Registered handlers for {self.title} plugin")


plugin = Task17Plugin()
