"""
Обработчики для личного кабинета пользователя.
"""

import logging
import aiosqlite
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from core.db import DATABASE_FILE, get_user_streaks
from payment.subscription_manager import SubscriptionManager
from core.user_segments import get_segment_classifier

from .keyboards import (
    get_main_cabinet_keyboard,
    get_subscription_keyboard,
    get_statistics_keyboard,
    get_settings_keyboard
)

logger = logging.getLogger(__name__)

# Состояния
VIEWING = 1

# Инициализация менеджеров
subscription_manager = SubscriptionManager()
classifier = get_segment_classifier()


# ==================== WRAPPER ФУНКЦИИ ДЛЯ TEACHER MODE ====================
# Эти функции завершают ConversationHandler личного кабинета и позволяют
# teacher mode ConversationHandler перехватить управление

async def wrapper_teacher_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Wrapper для перехода в режим учителя.
    Завершает ConversationHandler личного кабинета и вызывает teacher_menu.
    """
    from teacher_mode.handlers import teacher_handlers

    # Сначала вызываем teacher_menu, который откроет меню учителя
    await teacher_handlers.teacher_menu(update, context)

    # Затем завершаем ConversationHandler личного кабинета
    # чтобы teacher_conv_handler мог перехватить управление
    return ConversationHandler.END


async def wrapper_connect_to_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Wrapper для подключения к учителю.
    Завершает ConversationHandler личного кабинета и вызывает enter_teacher_code_start.
    """
    from teacher_mode.handlers import student_handlers

    # Вызываем обработчик подключения к учителю
    await student_handlers.enter_teacher_code_start(update, context)

    # Завершаем ConversationHandler личного кабинета
    return ConversationHandler.END


async def wrapper_homework_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Wrapper для списка домашних заданий.
    Завершает ConversationHandler личного кабинета и вызывает homework_list.
    """
    from teacher_mode.handlers import student_handlers

    # Вызываем обработчик списка домашних заданий
    await student_handlers.homework_list(update, context)

    # Завершаем ConversationHandler личного кабинета
    return ConversationHandler.END


async def show_personal_cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает главное меню личного кабинета.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "друг"

    text = (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"Привет, {first_name}! 👋\n\n"
        f"Здесь ты можешь управлять своей подпиской, "
        f"отслеживать прогресс и настраивать уведомления.\n\n"
        f"📚 Выбери нужный раздел:"
    )

    keyboard = get_main_cabinet_keyboard()

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def show_subscription_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает информацию о подписке пользователя.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем информацию о модульных подписках
    modules_data = await subscription_manager.get_user_modules(user_id)
    has_subscription = bool(modules_data)

    # Формируем текст
    if has_subscription:
        # Пользователь имеет активные модули
        text = "💳 <b>Моя подписка</b>\n\n"
        text += "✅ <b>Ваши активные модули:</b>\n\n"

        module_names = {
            'test_part': '📝 Тестовая часть',
            'task19': '🎯 Задание 19',
            'task20': '📖 Задание 20',
            'task24': '💎 Задание 24',
            'task25': '✍️ Задание 25'
        }

        # Находим минимальное количество дней до истечения
        min_days_left = float('inf')
        closest_expiry_date = None

        for module in modules_data:
            name = module_names.get(module['module_code'], module['module_code'])
            expires = module['expires_at'].strftime('%d.%m.%Y')

            # Вычисляем дни до истечения
            days_left = (module['expires_at'] - datetime.now(timezone.utc)).days

            if days_left < min_days_left:
                min_days_left = days_left
                closest_expiry_date = module['expires_at']

            # Эмодзи статуса
            if days_left <= 3:
                days_emoji = "🔴"
            elif days_left <= 7:
                days_emoji = "🟡"
            else:
                days_emoji = "✅"

            text += f"{days_emoji} {name}\n   └ Действует до: {expires} ({days_left} дн.)\n\n"

        # Предупреждение если есть модули со скорым истечением
        if min_days_left <= 7:
            text += f"⚠️ <i>Некоторые модули скоро истекут! Продли подписку.</i>\n\n"

        # Проверка доступа к остальным модулям
        all_modules = ['test_part', 'task19', 'task20', 'task24', 'task25']
        active_module_codes = [m['module_code'] for m in modules_data]
        inactive_modules = [module_names[code] for code in all_modules if code not in active_module_codes]

        if inactive_modules:
            text += "❌ <b>Неактивные модули:</b>\n"
            text += ", ".join(inactive_modules) + "\n\n"
            text += "💡 <i>Добавь модули для полного доступа ко всем заданиям!</i>"

    else:
        # Нет активных модулей
        text = (
            f"💳 <b>Моя подписка</b>\n\n"
            f"🆓 <b>У тебя бесплатный доступ</b>\n\n"
            f"Ты можешь использовать:\n"
            f"• Бесплатные материалы\n"
            f"• 3 AI-проверки в неделю\n\n"
            f"💡 Оформи подписку, чтобы получить полный доступ ко всем заданиям!"
        )

    # Определяем параметры для клавиатуры
    # Для модульной системы автопродление не используется
    can_toggle_auto_renew = False
    auto_renew_enabled = False

    keyboard = get_subscription_keyboard(
        has_subscription=has_subscription,
        auto_renew_enabled=auto_renew_enabled,
        can_toggle_auto_renew=can_toggle_auto_renew
    )

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает статистику пользователя.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем статистику
    activity = await classifier.get_user_activity_stats(user_id)

    # Получаем стрики пользователя
    streaks = await get_user_streaks(user_id)

    if not activity:
        text = (
            "📊 <b>Статистика</b>\n\n"
            "❌ Не удалось загрузить статистику.\n"
            "Попробуй позже."
        )
        keyboard = get_statistics_keyboard()
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return VIEWING

    # Извлекаем данные
    answered_total = activity.get('answered_total', 0)
    answered_week = activity.get('answered_week', 0)
    ai_checks_total = activity.get('ai_checks_total', 0)
    ai_checks_today = activity.get('ai_checks_today', 0)
    days_since_reg = activity.get('days_since_registration', 0)
    days_inactive = activity.get('days_inactive', 0)
    created_at = activity.get('created_at')

    # Дата регистрации
    if created_at:
        reg_date_str = created_at.strftime("%d.%m.%Y")
    else:
        reg_date_str = "неизвестно"

    # Активность
    if days_inactive == 0:
        activity_status = "🟢 Активен сегодня"
    elif days_inactive == 1:
        activity_status = "🟡 Был вчера"
    elif days_inactive <= 7:
        activity_status = f"🟡 Неактивен {days_inactive} дн."
    else:
        activity_status = f"🔴 Неактивен {days_inactive} дн."

    # Получаем информацию о подписке для AI-лимита
    sub_info = await classifier.get_subscription_info(user_id)
    has_subscription = sub_info.get('has_subscription', False)

    if has_subscription:
        ai_limit_text = "♾️ Безлимит"
    else:
        ai_limit_text = f"{ai_checks_today}/3 использовано сегодня"

    # Формируем текст со стриками
    daily_current = streaks.get('current_daily', 0)
    daily_max = streaks.get('max_daily', 0)
    correct_current = streaks.get('current_correct', 0)
    correct_max = streaks.get('max_correct', 0)

    text = (
        f"📊 <b>Твоя статистика</b>\n\n"
        f"<b>📅 Зарегистрирован:</b> {reg_date_str}\n"
        f"<b>📆 Дней с нами:</b> {days_since_reg}\n"
        f"<b>🎯 Статус:</b> {activity_status}\n\n"
        f"<b>📝 Решено вопросов:</b>\n"
        f"• Всего: {answered_total}\n"
        f"• За неделю: {answered_week}\n\n"
        f"<b>🤖 AI-проверки:</b>\n"
        f"• Всего использовано: {ai_checks_total}\n"
        f"• Сегодня: {ai_limit_text}\n\n"
    )

    # Добавляем стрики, если они есть
    if daily_current > 0 or correct_current > 0 or daily_max > 0 or correct_max > 0:
        text += f"<b>🔥 Серии:</b>\n"
        text += f"• Дней подряд: {daily_current}"
        if daily_max > daily_current:
            text += f" (рекорд: {daily_max})"
        text += "\n"
        text += f"• Правильных подряд: {correct_current}"
        if correct_max > correct_current:
            text += f" (рекорд: {correct_max})"
        text += "\n\n"

    text += "💪 Продолжай в том же духе!"

    keyboard = get_statistics_keyboard()

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает настройки пользователя.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем статус уведомлений
    notifications_enabled = await get_notification_status(user_id)

    # Формируем текст
    notif_status = "✅ Включены" if notifications_enabled else "❌ Отключены"

    text = (
        f"⚙️ <b>Настройки</b>\n\n"
        f"<b>🔔 Уведомления:</b> {notif_status}\n\n"
        f"Здесь ты можешь управлять своими настройками.\n\n"
        f"💡 <i>Мы отправляем не более 1 уведомления в день с полезными "
        f"напоминаниями и персональными предложениями.</i>"
    )

    keyboard = get_settings_keyboard(notifications_enabled)

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return VIEWING


async def get_notification_status(user_id: int) -> bool:
    """
    Получает статус уведомлений пользователя.

    Args:
        user_id: ID пользователя

    Returns:
        True если уведомления включены, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT enabled FROM notification_preferences
                WHERE user_id = ?
            """, (user_id,))
            row = await cursor.fetchone()

            if row:
                return bool(row[0])
            else:
                # По умолчанию уведомления включены
                return True

    except Exception as e:
        logger.error(f"Error getting notification status for user {user_id}: {e}")
        return True


async def handle_notification_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Переключает статус уведомлений.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем текущий статус
    current_status = await get_notification_status(user_id)
    new_status = not current_status

    # Обновляем в БД
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                INSERT OR REPLACE INTO notification_preferences (
                    user_id, enabled, disabled_at, disabled_reason
                ) VALUES (?, ?, ?, ?)
            """, (
                user_id,
                1 if new_status else 0,
                None if new_status else datetime.now(timezone.utc).isoformat(),
                None if new_status else 'user_request'
            ))
            await db.commit()

        logger.info(f"User {user_id} {'enabled' if new_status else 'disabled'} notifications")

        # Показываем обновленные настройки
        await show_settings(update, context)

    except Exception as e:
        logger.error(f"Error toggling notifications for user {user_id}: {e}")
        await query.answer("❌ Ошибка при изменении настроек", show_alert=True)

    return VIEWING


async def handle_auto_renewal_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Переключает автопродление подписки.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        # Получаем информацию о подписке
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем текущий статус автопродления
            cursor = await db.execute("""
                SELECT auto_renew FROM subscriptions
                WHERE user_id = ? AND is_active = 1
                ORDER BY end_date DESC
                LIMIT 1
            """, (user_id,))
            row = await cursor.fetchone()

            if not row:
                await query.answer("❌ Нет активной подписки", show_alert=True)
                return VIEWING

            current_auto_renew = bool(row[0])
            new_auto_renew = not current_auto_renew

            # Обновляем статус
            await db.execute("""
                UPDATE subscriptions
                SET auto_renew = ?
                WHERE user_id = ? AND is_active = 1
            """, (1 if new_auto_renew else 0, user_id))
            await db.commit()

        logger.info(f"User {user_id} {'enabled' if new_auto_renew else 'disabled'} auto-renewal")

        # Показываем обновленную информацию о подписке
        await show_subscription_info(update, context)

    except Exception as e:
        logger.error(f"Error toggling auto-renewal for user {user_id}: {e}")
        await query.answer("❌ Ошибка при изменении автопродления", show_alert=True)

    return VIEWING


async def handle_buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Перенаправляет пользователя к покупке/продлению подписки.
    Напрямую открывает магазин подписок.
    """
    try:
        from payment.handlers import show_modular_interface

        # Прямой переход к магазину подписок
        await show_modular_interface(update, context)

        # Завершаем текущий ConversationHandler для перехода к процессу оплаты
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error redirecting to subscription shop: {e}")
        query = update.callback_query
        if query:
            await query.answer("❌ Ошибка при переходе к оформлению подписки", show_alert=True)
        return VIEWING
