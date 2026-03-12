# full_exam/plugin.py
"""Плагин «Полный вариант ЕГЭ» — регистрация в боте."""

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
from . import handlers

logger = logging.getLogger(__name__)


class FullExamPlugin(BotPlugin):
    code = "full_exam"
    title = "📋 Полный вариант ЕГЭ"
    menu_priority = 5  # Выше тестовой части (10)

    def register(self, app):
        """Регистрация ConversationHandler для полного варианта."""

        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$",
                ),
            ],
            states={
                # ── Обзор варианта / меню ──
                states.FULL_EXAM_OVERVIEW: [
                    # Новый вариант / продолжить
                    CallbackQueryHandler(handlers.new_variant, pattern="^fe_new_variant$"),
                    CallbackQueryHandler(handlers.continue_variant, pattern="^fe_continue$"),
                    CallbackQueryHandler(handlers.my_results, pattern="^fe_my_results$"),

                    # Навигация по заданиям
                    CallbackQueryHandler(handlers.goto_task, pattern=r"^fe_goto_\d+$"),
                    CallbackQueryHandler(handlers.show_overview, pattern="^fe_overview$"),

                    # Завершение
                    CallbackQueryHandler(handlers.finish_variant, pattern="^fe_finish$"),
                    CallbackQueryHandler(handlers.finish_confirm, pattern="^fe_finish_confirm$"),

                    # Заглушки
                    CallbackQueryHandler(handlers.noop, pattern="^fe_noop$"),

                    # Возврат
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^main_menu$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^fe_back_to_menu$"),

                    # Подписка
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^pay_trial$"),
                ],

                # ── Ответ на тестовое задание (часть 1) ──
                states.FULL_EXAM_TEST_PART: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        handlers.check_test_answer,
                    ),
                    CallbackQueryHandler(handlers.goto_task, pattern=r"^fe_goto_\d+$"),
                    CallbackQueryHandler(handlers.skip_task, pattern=r"^fe_skip_\d+$"),
                    CallbackQueryHandler(handlers.show_overview, pattern="^fe_overview$"),
                    CallbackQueryHandler(handlers.finish_variant, pattern="^fe_finish$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^main_menu$"),
                ],

                # ── Ответ на задание второй части (AI-проверка) ──
                states.FULL_EXAM_PART2_ANSWER: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        handlers.check_part2_answer,
                    ),
                    CallbackQueryHandler(handlers.goto_task, pattern=r"^fe_goto_\d+$"),
                    CallbackQueryHandler(handlers.skip_task, pattern=r"^fe_skip_\d+$"),
                    CallbackQueryHandler(handlers.show_overview, pattern="^fe_overview$"),
                    CallbackQueryHandler(handlers.finish_variant, pattern="^fe_finish$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^main_menu$"),
                ],

                # ── Результаты ──
                states.FULL_EXAM_RESULTS: [
                    CallbackQueryHandler(handlers.new_variant, pattern="^fe_new_variant$"),
                    CallbackQueryHandler(handlers.detailed_review, pattern="^fe_detailed_review$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^main_menu$"),
                ],

                # ── Просмотр задания ──
                states.FULL_EXAM_TASK_REVIEW: [
                    CallbackQueryHandler(handlers.goto_task, pattern=r"^fe_goto_\d+$"),
                    CallbackQueryHandler(handlers.show_overview, pattern="^fe_overview$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^main_menu$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.back_to_main_menu),
                CallbackQueryHandler(
                    handlers.back_to_main_menu,
                    pattern="^main_menu$",
                ),
            ],
            allow_reentry=True,
            name=f"{self.code}_conversation",
            persistent=True,
        )

        app.add_handler(conv_handler)
        logger.info(f"FullExam plugin registered: {self.title}")


# Экземпляр для plugin_loader
plugin = FullExamPlugin()
