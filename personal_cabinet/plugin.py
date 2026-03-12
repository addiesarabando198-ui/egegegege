"""
Плагин личного кабинета пользователя.

Предоставляет доступ к:
- Информации о подписке и управлению автопродлением
- Статистике по всем модулям
- Настройкам (уведомления и т.д.)
"""

from core.plugin_base import BotPlugin
from telegram.ext import Application, CallbackQueryHandler, ConversationHandler, CommandHandler
import logging

logger = logging.getLogger(__name__)

# Импортируем обработчики
from .handlers import (
    show_personal_cabinet,
    show_subscription_info,
    show_statistics,
    show_settings,
    handle_notification_toggle,
    handle_auto_renewal_toggle,
    handle_buy_subscription,
    wrapper_teacher_menu,
    wrapper_connect_to_teacher,
    wrapper_homework_list,
    VIEWING
)


class PersonalCabinetPlugin(BotPlugin):
    """Плагин личного кабинета"""

    def __init__(self):
        self.code = "personal_cabinet"
        self.title = "👤 Личный кабинет"
        self.menu_priority = 100  # В самом конце меню

    def register(self, application: Application):
        """Регистрирует обработчики плагина"""
        logger.info(f"Registering {self.title} plugin...")

        # Создаем ConversationHandler для навигации внутри личного кабинета
        conversation_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    show_personal_cabinet,
                    pattern=f"^choose_{self.code}$"
                )
            ],
            states={
                VIEWING: [
                    CallbackQueryHandler(show_subscription_info, pattern="^cabinet_subscription$"),
                    CallbackQueryHandler(show_statistics, pattern="^cabinet_statistics$"),
                    CallbackQueryHandler(show_settings, pattern="^cabinet_settings$"),
                    CallbackQueryHandler(handle_notification_toggle, pattern="^cabinet_toggle_notifications$"),
                    CallbackQueryHandler(handle_auto_renewal_toggle, pattern="^cabinet_toggle_auto_renewal$"),
                    CallbackQueryHandler(handle_buy_subscription, pattern="^cabinet_buy_subscription$"),
                    # Wrapper функции для режима учителя (завершают ConversationHandler кабинета)
                    CallbackQueryHandler(wrapper_teacher_menu, pattern="^teacher_menu$"),
                    CallbackQueryHandler(wrapper_connect_to_teacher, pattern="^connect_to_teacher$"),
                    CallbackQueryHandler(wrapper_homework_list, pattern="^student_homework_list$"),
                    CallbackQueryHandler(show_personal_cabinet, pattern="^back_to_cabinet$"),
                ]
            },
            fallbacks=[
                CallbackQueryHandler(show_personal_cabinet, pattern="^back_to_cabinet$"),
            ],
            name="personal_cabinet_conversation",
            persistent=True,
            allow_reentry=True
        )

        application.add_handler(conversation_handler)
        logger.info(f"✓ {self.title} plugin registered")


# Экземпляр плагина для загрузки
plugin = PersonalCabinetPlugin()
