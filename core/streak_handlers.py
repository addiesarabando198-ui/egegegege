"""
Streak Callback Handlers - обработка действий пользователей связанных со стриками

Phase 2: Notifications
- Обработка нажатий на кнопки в уведомлениях
- Использование защит (freeze, repair, shield)
- Навигация в streak UI
- Tracking engagement для аналитики
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, Application
from telegram.constants import ParseMode

from core.streak_manager import get_streak_manager
from core.streak_ui import get_streak_ui
from core.milestone_notification_handler import get_milestone_notification_handler

logger = logging.getLogger(__name__)


# ============================================================
# MILESTONE CALLBACKS
# ============================================================

async def milestone_acknowledged_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик подтверждения milestone"""
    query = update.callback_query
    await query.answer("🎉 Отлично!")

    user_id = update.effective_user.id

    try:
        # Tracking engagement (TODO: нужно передавать milestone_type и value из callback_data)
        # Для полноценного tracking нужно изменить формат callback_data в streak_ui.py
        # Например: "milestone_ack:daily:7"

        await query.edit_message_text(
            "🎉 Поздравляем с достижением!\n\n"
            "Продолжай занятия и достигни еще больших высот! 💪",
            parse_mode=ParseMode.HTML
        )

        logger.info(f"User {user_id} acknowledged milestone")

    except Exception as e:
        logger.error(f"Error handling milestone acknowledgment: {e}", exc_info=True)
        await query.answer("Произошла ошибка", show_alert=True)


async def my_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику пользователя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        streak_manager = get_streak_manager()
        streak_ui = get_streak_ui()

        # Получаем информацию о стриках
        daily_info = await streak_manager.get_daily_streak_info(user_id)

        # Получаем correct streak из БД
        from core.db import get_user_streaks
        streaks = await get_user_streaks(user_id)

        current_daily = daily_info['current']
        max_daily = daily_info['max']
        level = daily_info['level']
        current_correct = streaks.get('current_correct', 0)
        max_correct = streaks.get('max_correct', 0)

        # Формируем текст статистики
        text = f"""
📊 <b>Твоя статистика</b>

🔥 <b>Дневной стрик</b>
Текущий: <b>{current_daily}</b> {streak_ui._pluralize_days(current_daily)}
Рекорд: <b>{max_daily}</b> {streak_ui._pluralize_days(max_daily)}
Уровень: {level.emoji} <b>{level.display_name}</b>

🎯 <b>Правильные ответы подряд</b>
Текущий: <b>{current_correct}</b>
Рекорд: <b>{max_correct}</b>

"""

        # Добавляем прогресс до следующего уровня
        progress = await streak_ui.get_progress_to_next_level(user_id)
        if progress:
            text += f"\n{progress}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏅 Мои достижения", callback_data="my_achievements")],
            [InlineKeyboardButton("📅 Календарь активности", callback_data="activity_calendar")],
            [InlineKeyboardButton("📚 Продолжить занятия", callback_data="to_main_menu")],
            [InlineKeyboardButton("« Назад", callback_data="to_main_menu")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Showed stats for user {user_id}")

    except Exception as e:
        logger.error(f"Error showing stats: {e}", exc_info=True)
        await query.answer("Произошла ошибка при загрузке статистики", show_alert=True)


# ============================================================
# STREAK REMINDER CALLBACKS
# ============================================================

async def about_freeze_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рассказывает о заморозке стрика"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        streak_manager = get_streak_manager()

        # Получаем количество доступных заморозок
        from core.db import get_user_streaks
        streaks = await get_user_streaks(user_id)
        freeze_count = streaks.get('freeze_count', 0)

        text = f"""
❄️ <b>Заморозка стрика</b>

Заморозка позволяет пропустить <b>1 день</b> без потери стрика!

<b>Как это работает:</b>
• Ты можешь не заниматься 1 день
• Твой стрик НЕ сгорит
• На следующий день продолжишь с того же значения

<b>У тебя сейчас:</b> {freeze_count} заморозок

<b>Как получить заморозки:</b>
• 🎁 За 7-дневный стрик (бесплатно)
• 🎁 За 30-дневный стрик (бесплатно)
• 🎁 За 60-дневный стрик (бесплатно)
• 💎 Купить за 49₽
• 👑 Premium подписка (безлимит)

<b>Автоматическое использование:</b>
Заморозка автоматически активируется, если ты пропустишь день и у тебя есть доступные заморозки.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡️ Открыть магазин защит", callback_data="streak_shop")],
            [InlineKeyboardButton("👑 Premium подписка", callback_data="about_premium")],
            [InlineKeyboardButton("✍️ Решить задание", callback_data="start_practice")],
            [InlineKeyboardButton("« Назад", callback_data="to_main_menu")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Showed freeze info for user {user_id}")

    except Exception as e:
        logger.error(f"Error showing freeze info: {e}", exc_info=True)
        await query.answer("Произошла ошибка", show_alert=True)


async def use_freeze_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Использует заморозку стрика"""
    query = update.callback_query

    user_id = update.effective_user.id

    try:
        streak_manager = get_streak_manager()

        # Получаем количество доступных заморозок
        from core.db import get_user_streaks
        streaks = await get_user_streaks(user_id)
        freeze_count = streaks.get('freeze_count', 0)

        if freeze_count <= 0:
            await query.answer(
                "❄️ У тебя нет доступных заморозок!\n\n"
                "Купи заморозку за 49₽ или получи Premium подписку.",
                show_alert=True
            )

            # Показываем экран покупки
            await about_freeze_callback(update, context)
            return

        # TODO: Реализовать логику ручного использования заморозки
        # (В текущей архитектуре заморозка применяется автоматически)

        await query.answer(
            "❄️ Заморозка применяется автоматически!\n\n"
            "Если ты пропустишь день, заморозка сохранит твой стрик.",
            show_alert=True
        )

        logger.info(f"User {user_id} attempted to manually use freeze")

    except Exception as e:
        logger.error(f"Error using freeze: {e}", exc_info=True)
        await query.answer("Произошла ошибка", show_alert=True)


async def about_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о Premium подписке"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        text = """
👑 <b>EGE Premium</b>

<b>Преимущества для стриков:</b>
❄️ Безлимитные заморозки стриков
🛡️ Автоматическая защита от потери
⚡ Бесплатное восстановление стрика
🎁 +5 AI-проверок каждый месяц

<b>Дополнительные возможности:</b>
✨ Безлимитные AI-проверки работ
📊 Детальная аналитика прогресса
🎯 Персональные рекомендации
🔔 Умные напоминания

<b>Стоимость:</b>
💎 249₽ / месяц

Подписка поможет сохранить твой стрик и подготовиться к ЕГЭ на максимум! 🚀
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Оформить Premium", callback_data="subscribe_premium")],
            [InlineKeyboardButton("« Назад", callback_data="to_main_menu")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Showed premium info for user {user_id}")

    except Exception as e:
        logger.error(f"Error showing premium info: {e}", exc_info=True)
        await query.answer("Произошла ошибка", show_alert=True)


# ============================================================
# NAVIGATION CALLBACKS
# ============================================================

async def start_practice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает практику (переход к решению заданий)"""
    query = update.callback_query
    await query.answer("Отлично! Начнем занятие! 💪")

    user_id = update.effective_user.id

    try:
        # Переходим в главное меню и автоматически начинаем практику
        from core.app import show_main_menu_with_access

        welcome_text = """
🎓 <b>Подготовка к ЕГЭ по обществознанию</b>

Используйте кнопки ниже для навигации:
"""
        kb = await show_main_menu_with_access(context, user_id)

        # Пытаемся отредактировать существующее сообщение
        try:
            await query.edit_message_text(
                welcome_text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception:
            # Если не удалось отредактировать - удаляем и отправляем новое
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.message.chat.send_message(
                welcome_text,
                reply_markup=kb,
                parse_mode="HTML"
            )

        logger.info(f"User {user_id} started practice from streak notification")

    except Exception as e:
        logger.error(f"Error starting practice: {e}", exc_info=True)
        await query.answer("Произошла ошибка", show_alert=True)


async def to_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает в главное меню"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        from core.app import show_main_menu_with_access

        welcome_text = """
🎓 <b>Подготовка к ЕГЭ по обществознанию</b>

Используйте кнопки ниже для навигации:
"""
        kb = await show_main_menu_with_access(context, user_id)

        # Пытаемся отредактировать существующее сообщение
        try:
            await query.edit_message_text(
                welcome_text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception:
            # Если не удалось отредактировать - удаляем и отправляем новое
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.message.chat.send_message(
                welcome_text,
                reply_markup=kb,
                parse_mode="HTML"
            )

        logger.info(f"User {user_id} returned to main menu from streak screen")

    except Exception as e:
        logger.error(f"Error returning to menu: {e}", exc_info=True)
        await query.answer("Произошла ошибка", show_alert=True)


# ============================================================
# ACHIEVEMENTS & CALENDAR CALLBACKS (Phase 4)
# ============================================================

async def my_achievements_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает достижения пользователя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        from core.streak_achievements import get_achievement_system
        achievement_system = get_achievement_system()

        # Получаем достижения пользователя
        achievements = await achievement_system.get_user_achievements(user_id)
        stats = await achievement_system.get_achievement_stats(user_id)

        if not achievements:
            text = """
🏅 <b>Достижения</b>

У тебя пока нет достижений!

Начни решать задания, поддерживай стрики и получай badges за свои успехи! 🚀

<b>Доступные категории:</b>
• 🔥 Стрики (7, 14, 30, 60, 100 дней)
• 🎯 Точность (5, 10, 20, 50 правильных)
• 📚 Объём (100, 500, 1000, 5000 заданий)
• ✨ Специальные достижения
"""
        else:
            text = f"""
🏅 <b>Твои достижения</b>

Получено: <b>{stats['total_earned']}</b> из {stats['total_available']}
Прогресс: <b>{stats['completion_percent']}%</b>

<b>Последние достижения:</b>

"""
            # Показываем последние 5 достижений
            for achievement in achievements[:5]:
                rarity_emoji = {'COMMON': '⚪', 'RARE': '🔵', 'EPIC': '🟣', 'LEGENDARY': '🟡'}.get(
                    achievement['rarity'], '⚪'
                )
                earned_date = datetime.fromisoformat(achievement['earned_at']).strftime("%d.%m")

                text += f"{achievement['emoji']} <b>{achievement['title']}</b> {rarity_emoji}\n"
                text += f"<i>{achievement['description']}</i>\n"
                text += f"📅 {earned_date}\n\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
            [InlineKeyboardButton("📅 Календарь активности", callback_data="activity_calendar")],
            [InlineKeyboardButton("« Назад", callback_data="to_main_menu")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Showed achievements for user {user_id}")

    except Exception as e:
        logger.error(f"Error showing achievements: {e}", exc_info=True)
        await query.answer("Произошла ошибка при загрузке достижений", show_alert=True)


async def activity_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает календарь активности"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        from core.activity_calendar import get_activity_calendar
        calendar = get_activity_calendar()

        # Получаем календарь и статистику
        calendar_text, period_stats = await calendar.get_calendar_heatmap(user_id, weeks=8)
        week_stats = await calendar.get_week_stats(user_id)
        month_stats = await calendar.get_month_stats(user_id)
        best_day = await calendar.get_best_day(user_id)

        text = calendar_text

        # Статистика за неделю
        if week_stats:
            text += f"\n📊 <b>Эта неделя:</b>\n"
            text += f"Активных дней: {week_stats['days_active']}/7\n"
            text += f"Решено заданий: {week_stats['total_questions']}\n"
            text += f"Точность: {week_stats['accuracy_percent']}%\n"

        # Статистика за месяц
        if month_stats:
            text += f"\n📆 <b>Этот месяц:</b>\n"
            text += f"Активных дней: {month_stats['days_active']}/{month_stats['days_in_month']}\n"
            text += f"Решено заданий: {month_stats['total_questions']}\n"
            text += f"Точность: {month_stats['accuracy_percent']}%\n"

        # Лучший день
        if best_day:
            best_date = datetime.fromisoformat(best_day['date']).strftime("%d.%m.%Y")
            text += f"\n🏆 <b>Лучший день:</b> {best_date}\n"
            text += f"Заданий: {best_day['questions_answered']} ({best_day['accuracy']}% точность)\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏅 Мои достижения", callback_data="my_achievements")],
            [InlineKeyboardButton("📊 Детальная статистика", callback_data="my_stats")],
            [InlineKeyboardButton("« Назад", callback_data="to_main_menu")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Showed activity calendar for user {user_id}")

    except Exception as e:
        logger.error(f"Error showing calendar: {e}", exc_info=True)
        await query.answer("Произошла ошибка при загрузке календаря", show_alert=True)


# ============================================================
# REGISTRATION
# ============================================================

def register_streak_handlers(application: Application):
    """Регистрирует все streak-related callback handlers"""

    # Milestone callbacks
    application.add_handler(
        CallbackQueryHandler(milestone_acknowledged_callback, pattern="^milestone_acknowledged$")
    )
    application.add_handler(
        CallbackQueryHandler(my_stats_callback, pattern="^my_stats$")
    )

    # Streak reminder callbacks
    application.add_handler(
        CallbackQueryHandler(about_freeze_callback, pattern="^about_freeze$")
    )
    application.add_handler(
        CallbackQueryHandler(use_freeze_callback, pattern="^use_freeze$")
    )
    application.add_handler(
        CallbackQueryHandler(about_premium_callback, pattern="^about_premium$")
    )

    # Navigation callbacks
    application.add_handler(
        CallbackQueryHandler(start_practice_callback, pattern="^start_practice$")
    )
    # ПРИМЕЧАНИЕ: Обработчик to_main_menu НЕ регистрируется здесь,
    # так как используется глобальный обработчик из menu_handlers.py
    # который корректно работает со всеми случаями.

    # Phase 4: Achievements & Calendar callbacks
    application.add_handler(
        CallbackQueryHandler(my_achievements_callback, pattern="^my_achievements$")
    )
    application.add_handler(
        CallbackQueryHandler(activity_calendar_callback, pattern="^activity_calendar$")
    )

    logger.info("Streak callback handlers registered (including Phase 4: Achievements & Calendar)")
