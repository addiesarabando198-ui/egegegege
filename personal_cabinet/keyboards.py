"""
Клавиатуры для личного кабинета.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_cabinet_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню личного кабинета.

    Returns:
        InlineKeyboardMarkup с кнопками основных разделов
    """
    keyboard = [
        [InlineKeyboardButton("💳 Моя подписка", callback_data="cabinet_subscription")],
        [InlineKeyboardButton("📊 Статистика", callback_data="cabinet_statistics")],
        [InlineKeyboardButton("📚 Мои домашние задания", callback_data="student_homework_list")],
        [InlineKeyboardButton("👨‍🏫 Для репетиторов: Режим учителя", callback_data="teacher_menu")],
        [InlineKeyboardButton("🎓 Для учеников: Подключиться к учителю", callback_data="connect_to_teacher")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="cabinet_settings")],
        [InlineKeyboardButton("❓ Помощь и поддержка", url="https://t.me/obshestvonapalcahsupport")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_subscription_keyboard(
    has_subscription: bool,
    auto_renew_enabled: bool = False,
    can_toggle_auto_renew: bool = False
) -> InlineKeyboardMarkup:
    """
    Клавиатура для раздела подписки.

    Args:
        has_subscription: Есть ли активная подписка
        auto_renew_enabled: Включено ли автопродление
        can_toggle_auto_renew: Можно ли переключать автопродление

    Returns:
        InlineKeyboardMarkup с соответствующими кнопками
    """
    keyboard = []

    # Кнопка автопродления (если доступно)
    if can_toggle_auto_renew:
        if auto_renew_enabled:
            keyboard.append([
                InlineKeyboardButton(
                    "🔴 Отключить автопродление",
                    callback_data="cabinet_toggle_auto_renewal"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    "🟢 Включить автопродление",
                    callback_data="cabinet_toggle_auto_renewal"
                )
            ])

    # Кнопка покупки/продления
    if has_subscription:
        keyboard.append([
            InlineKeyboardButton("🛒 Продлить подписку", callback_data="cabinet_buy_subscription")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("🛒 Оформить подписку", callback_data="cabinet_buy_subscription")
        ])

    # Навигация
    keyboard.extend([
        [InlineKeyboardButton("« Назад в кабинет", callback_data="back_to_cabinet")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

    return InlineKeyboardMarkup(keyboard)


def get_statistics_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура для раздела статистики.

    Returns:
        InlineKeyboardMarkup с навигацией
    """
    keyboard = [
        [InlineKeyboardButton("« Назад в кабинет", callback_data="back_to_cabinet")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard(notifications_enabled: bool) -> InlineKeyboardMarkup:
    """
    Клавиатура для раздела настроек.

    Args:
        notifications_enabled: Включены ли уведомления

    Returns:
        InlineKeyboardMarkup с настройками
    """
    keyboard = []

    # Переключатель уведомлений
    if notifications_enabled:
        keyboard.append([
            InlineKeyboardButton(
                "🔕 Отключить уведомления",
                callback_data="cabinet_toggle_notifications"
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                "🔔 Включить уведомления",
                callback_data="cabinet_toggle_notifications"
            )
        ])

    # Навигация
    keyboard.extend([
        [InlineKeyboardButton("« Назад в кабинет", callback_data="back_to_cabinet")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

    return InlineKeyboardMarkup(keyboard)
