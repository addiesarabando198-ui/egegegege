"""
Плагин для задания 21 (Анализ графиков спроса и предложения).

Задание базового уровня сложности на анализ графического изображения,
иллюстрирующего изменения спроса/предложения на конкретном рынке.
"""

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

logger = logging.getLogger(__name__)


class Task21Plugin(BotPlugin):
    """Плагин для задания 21 ЕГЭ по обществознанию (Графики спроса и предложения)."""

    code = "task21"
    title = "📊 Задание 21 (Графики)"
    menu_priority = 16  # Перед task22

    async def post_init(self, app) -> None:
        """Инициализация данных для задания 21."""
        try:
            await handlers.init_task21_data()
            logger.info("Task21 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task21 data: {e}")

    def entry_handler(self):
        """Возвращает обработчик для входа из главного меню."""
        return CallbackQueryHandler(
            handlers.entry_from_menu,
            pattern=f"^choose_{self.code}$"
        )

    def register(self, app) -> None:
        """Регистрация обработчиков в приложении."""

        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$"
                ),
                CommandHandler("task21", handlers.cmd_task21),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Практика
                    CallbackQueryHandler(
                        handlers.practice_mode,
                        pattern="^t21_practice$"
                    ),
                    # Статистика
                    CallbackQueryHandler(
                        handlers.my_progress,
                        pattern="^t21_progress$"
                    ),
                    # Показ эталонных ответов
                    CallbackQueryHandler(
                        handlers.show_model_answers,
                        pattern="^t21_show_answers$"
                    ),
                    # Навигация
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                    CallbackQueryHandler(
                        handlers.return_to_menu,
                        pattern="^t21_menu$"
                    ),
                    CallbackQueryHandler(
                        handlers.handle_result_action,
                        pattern="^t21_(new)$"
                    ),
                ],

                states.ANSWERING_T21: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        handlers.handle_answer
                    ),
                    CallbackQueryHandler(
                        handlers.return_to_menu,
                        pattern="^t21_menu$"
                    ),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(
                    handlers.return_to_menu,
                    pattern="^t21_menu$"
                ),
                CallbackQueryHandler(
                    handlers.back_to_main_menu,
                    pattern="^to_main_menu$"
                ),
            ],
            name="task21_conversation",
            persistent=True,
            allow_reentry=True,
            per_message=False,
            per_chat=True,
            per_user=True
        )

        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        logger.info(f"Registered handlers for {self.title} plugin")

    def get_commands(self):
        """Возвращает список команд для меню."""
        return [
            {
                "command": "task21",
                "description": "Задание 21: Графики спроса и предложения"
            }
        ]

    def get_handlers(self):
        """Возвращает список обработчиков для регистрации."""
        return [
            ("entry", handlers.entry_from_menu),
            ("practice", handlers.practice_mode),
            ("answer", handlers.handle_answer),
            ("progress", handlers.my_progress),
            ("show_answers", handlers.show_model_answers),
            ("return_menu", handlers.return_to_menu),
            ("main_menu", handlers.back_to_main_menu),
        ]


# Экспортируем плагин
plugin = Task21Plugin()
