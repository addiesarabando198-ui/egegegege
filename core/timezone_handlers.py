"""
Timezone Handlers - обработчики для выбора часового пояса

Позволяет пользователям:
- Выбрать свой часовой пояс
- Настроить время уведомлений
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, Application
from telegram.constants import ParseMode

from core.timezone_manager import get_timezone_manager, RUSSIA_TIMEZONES

logger = logging.getLogger(__name__)


async def show_timezone_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора часового пояса"""
    query = update.callback_query
    if query:
        await query.answer()

    user_id = update.effective_user.id
    tz_manager = get_timezone_manager()

    # Получаем текущий часовой пояс
    current_tz = await tz_manager.get_user_timezone(user_id)
    current_info = RUSSIA_TIMEZONES.get(current_tz, {'name': 'Москва', 'offset': 3})

    text = f"""
🌍 <b>Настройка часового пояса</b>

<b>Текущий часовой пояс:</b>
UTC+{current_info['offset']} ({current_info['name']})

Выбери свой часовой пояс, чтобы уведомления приходили в удобное время, а не посреди ночи.

<i>Это влияет на:</i>
• Напоминания о стриках
• Уведомления об истечении подписки
• Retention-сообщения
"""

    # Создаём кнопки для выбора (разделим на 2 колонки)
    keyboard = []
    tz_list = list(RUSSIA_TIMEZONES.items())

    for tz_id, info in tz_list:
        # Добавляем галочку для текущего часового пояса
        mark = " ✓" if tz_id == current_tz else ""
        button_text = f"UTC+{info['offset']} {info['name']}{mark}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"set_tz_{tz_id}")])

    # Кнопка назад
    keyboard.append([InlineKeyboardButton("« Назад", callback_data="to_main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )


async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Устанавливает часовой пояс пользователя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    tz_id = query.data.replace("set_tz_", "")

    tz_manager = get_timezone_manager()

    # Проверяем, что часовой пояс валидный
    if tz_id not in RUSSIA_TIMEZONES:
        await query.answer("Неизвестный часовой пояс", show_alert=True)
        return

    # Устанавливаем часовой пояс
    success = await tz_manager.set_user_timezone(user_id, tz_id, detection_method='user_selected')

    if success:
        tz_info = RUSSIA_TIMEZONES[tz_id]
        text = f"""
✅ <b>Часовой пояс установлен!</b>

<b>Твой часовой пояс:</b>
UTC+{tz_info['offset']} ({tz_info['name']})

Теперь уведомления будут приходить в удобное для тебя время (примерно в 18:00 по твоему времени).

<i>Ты всегда можешь изменить настройки в меню «Профиль».</i>
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"User {user_id} set timezone to {tz_id}")
    else:
        await query.answer("Ошибка при установке часового пояса", show_alert=True)


async def show_notification_time_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает настройки времени уведомлений"""
    query = update.callback_query
    if query:
        await query.answer()

    user_id = update.effective_user.id
    tz_manager = get_timezone_manager()

    # Получаем текущие настройки
    current_tz = await tz_manager.get_user_timezone(user_id)
    tz_info = RUSSIA_TIMEZONES.get(current_tz, {'name': 'Москва', 'offset': 3})

    text = f"""
🔔 <b>Настройки уведомлений</b>

<b>Твой часовой пояс:</b>
UTC+{tz_info['offset']} ({tz_info['name']})

<b>Время уведомлений:</b>
Примерно в 18:00 по твоему времени
(16:00-20:00 для обычных уведомлений)

<b>Тихие часы:</b>
22:00 - 08:00 (уведомления не отправляются)

<i>Критические уведомления о стриках могут приходить в любое время, чтобы ты не потерял стрик.</i>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Изменить часовой пояс", callback_data="timezone_select")],
        [InlineKeyboardButton("🔕 Отключить уведомления", callback_data="disable_notifications")],
        [InlineKeyboardButton("« Назад", callback_data="to_main_menu")]
    ])

    if query:
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )


def register_timezone_handlers(application: Application):
    """Регистрирует обработчики для часовых поясов"""

    # Выбор часового пояса
    application.add_handler(
        CallbackQueryHandler(show_timezone_selection, pattern="^timezone_select$")
    )

    # Установка часового пояса
    application.add_handler(
        CallbackQueryHandler(set_timezone, pattern="^set_tz_")
    )

    # Настройки времени уведомлений
    application.add_handler(
        CallbackQueryHandler(show_notification_time_settings, pattern="^notification_time_settings$")
    )

    logger.info("Timezone handlers registered")
