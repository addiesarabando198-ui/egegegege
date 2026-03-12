"""Плагин для задания 22."""

import logging
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers
from core.states import ANSWERING_T22

logger = logging.getLogger(__name__)


class Task22Plugin(BotPlugin):
    code = "task22"
    title = "📝 Задание 22 (Анализ ситуаций)"
    menu_priority = 17

    async def post_init(self, app):
        """Инициализация данных для задания 22."""
        try:
            await handlers.init_task22_data()
            logger.info("Task22 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task22 data: {e}")

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
                CommandHandler("task22", handlers.cmd_task22),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t22_practice$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t22_progress$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t22_menu$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t22_(new)$"),
                ],

                ANSWERING_T22: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t22_menu$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t22_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
            ],
            name="task22_conversation",
            persistent=True,
            allow_reentry=True,
            per_message=False,
            per_chat=True,
            per_user=True
        )

        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        logger.info(f"Registered handlers for {self.title} plugin")


# Экспортируем плагин
plugin = Task22Plugin()
