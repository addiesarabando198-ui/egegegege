"""
Плагин для задания 23 (Конституция РФ).

Задание проверяет знание положений Конституции Российской Федерации.
Поддерживает два типа вопросов:
- Model Type 1: Одна характеристика, три подтверждения
- Model Type 2: Три характеристики, по одному подтверждению
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


class Task23Plugin(BotPlugin):
    """Плагин для задания 23 ЕГЭ по обществознанию (Конституция РФ)."""

    code = "task23"
    title = "📜 Задание 23 (Конституция РФ)"
    menu_priority = 18  # После task22

    async def post_init(self, app) -> None:
        """Инициализация данных для задания 23."""
        try:
            await handlers.init_task23_data()
            logger.info("Task23 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task23 data: {e}")

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
                CommandHandler("task23", handlers.cmd_task23),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Практика
                    CallbackQueryHandler(
                        handlers.practice_mode,
                        pattern="^t23_practice$"
                    ),
                    # Статистика
                    CallbackQueryHandler(
                        handlers.my_progress,
                        pattern="^t23_progress$"
                    ),
                    # Показ эталонных ответов
                    CallbackQueryHandler(
                        handlers.show_model_answers,
                        pattern="^t23_show_answers$"
                    ),
                    # Навигация
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                    CallbackQueryHandler(
                        handlers.return_to_menu,
                        pattern="^t23_menu$"
                    ),
                    CallbackQueryHandler(
                        handlers.handle_result_action,
                        pattern="^t23_(new)$"
                    ),
                ],

                states.ANSWERING_T23: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        handlers.handle_answer
                    ),
                    CallbackQueryHandler(
                        handlers.return_to_menu,
                        pattern="^t23_menu$"
                    ),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(
                    handlers.return_to_menu,
                    pattern="^t23_menu$"
                ),
                CallbackQueryHandler(
                    handlers.back_to_main_menu,
                    pattern="^to_main_menu$"
                ),
            ],
            name="task23_conversation",
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
                "command": "task23",
                "description": "Задание 23: Конституция РФ"
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
plugin = Task23Plugin()
