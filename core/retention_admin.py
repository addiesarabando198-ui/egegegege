"""
Админские команды для мониторинга retention системы.
"""

import logging
import aiosqlite
from datetime import datetime, date
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

from core.db import DATABASE_FILE
from core.admin_tools import admin_only

logger = logging.getLogger(__name__)


@admin_only
async def retention_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает статистику retention системы по сегментам.

    Команда: /retention_stats
    """
    # Определяем источник вызова (команда или callback)
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    await message.reply_text("📊 Загружаю статистику retention...")

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Общая статистика за всё время
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_sent,
                    SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) as total_clicked,
                    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as total_converted
                FROM notification_log
            """)
            overall = await cursor.fetchone()

            if not overall or overall[0] == 0:
                await message.reply_text(
                    "ℹ️ <b>Уведомления ещё не отправлялись</b>\n\n"
                    "Первая отправка запланирована на 17:00.\n"
                    "Проверьте статистику после первой отправки.",
                    parse_mode=ParseMode.HTML
                )
                return

            total_sent, total_clicked, total_converted = overall
            click_rate = (total_clicked / total_sent * 100) if total_sent > 0 else 0
            conv_rate = (total_converted / total_sent * 100) if total_sent > 0 else 0

            # Статистика по сегментам
            cursor = await db.execute("""
                SELECT
                    segment,
                    COUNT(*) as total,
                    SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) as clicked,
                    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as converted,
                    ROUND(100.0 * SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as click_rate,
                    ROUND(100.0 * SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as conv_rate
                FROM notification_log
                GROUP BY segment
                ORDER BY conv_rate DESC, total DESC
            """)
            segments = await cursor.fetchall()

            # Статистика за сегодня
            cursor = await db.execute("""
                SELECT COUNT(*)
                FROM notification_log
                WHERE DATE(sent_at) = DATE('now')
            """)
            today_sent = (await cursor.fetchone())[0]

            # Статистика за последние 7 дней
            cursor = await db.execute("""
                SELECT COUNT(*)
                FROM notification_log
                WHERE sent_at >= datetime('now', '-7 days')
            """)
            week_sent = (await cursor.fetchone())[0]

            # Формируем сообщение
            msg = "📊 <b>RETENTION СТАТИСТИКА</b>\n\n"

            msg += "📈 <b>Общая статистика:</b>\n"
            msg += f"  • Всего отправлено: {total_sent}\n"
            msg += f"  • Кликов: {total_clicked} ({click_rate:.1f}%)\n"
            msg += f"  • Конверсий: {total_converted} ({conv_rate:.1f}%)\n"
            msg += f"  • Сегодня: {today_sent}\n"
            msg += f"  • За неделю: {week_sent}\n\n"

            if segments:
                msg += "🎯 <b>По сегментам:</b>\n\n"

                for segment, total, clicked, converted, click_rate_seg, conv_rate_seg in segments:
                    # Эмодзи для сегментов
                    emoji = {
                        'BOUNCED': '🚀',
                        'CURIOUS': '🔄',
                        'ACTIVE_FREE': '💎',
                        'TRIAL_USER': '🎁',
                        'PAYING_INACTIVE': '😴',
                        'CHURN_RISK': '⚠️',
                        'CANCELLED': '💔'
                    }.get(segment, '📧')

                    msg += f"{emoji} <b>{segment}</b>\n"
                    msg += f"  Отправлено: {total} | Кликов: {clicked} ({click_rate_seg}%) | "
                    msg += f"Конверсий: {converted} ({conv_rate_seg}%)\n\n"

            # Последние отправленные уведомления
            cursor = await db.execute("""
                SELECT segment, trigger, sent_at, clicked, converted
                FROM notification_log
                ORDER BY sent_at DESC
                LIMIT 5
            """)
            recent = await cursor.fetchall()

            if recent:
                msg += "🕐 <b>Последние 5 уведомлений:</b>\n"
                for segment, trigger, sent_at, clicked, converted in recent:
                    # Парсим дату
                    try:
                        sent_dt = datetime.fromisoformat(sent_at)
                        time_str = sent_dt.strftime("%d.%m %H:%M")
                    except (ValueError, AttributeError):
                        time_str = "???"

                    status = "✅" if converted else ("👆" if clicked else "📤")
                    msg += f"{status} {time_str} | {segment[:12]} | {trigger[:20]}\n"

            # Кнопки
            keyboard = [
                [InlineKeyboardButton("🎁 Статистика промокодов", callback_data="retention:promo_stats")],
                [InlineKeyboardButton("🔄 Обновить", callback_data="retention:refresh_stats")],
                [InlineKeyboardButton("❌ Закрыть", callback_data="retention:close")]
            ]

            await message.reply_text(
                msg,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Error in retention_stats: {e}", exc_info=True)
        await message.reply_text(
            f"❌ Ошибка при загрузке статистики:\n{e}"
        )


@admin_only
async def promo_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает эффективность промокодов из retention системы.

    Команда: /promo_stats
    """
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    await message.reply_text("🎁 Загружаю статистику промокодов...")

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Статистика по промокодам из уведомлений
            cursor = await db.execute("""
                SELECT
                    promo_code,
                    COUNT(*) as times_sent,
                    SUM(CASE WHEN clicked = 1 THEN 1 ELSE 0 END) as clicks,
                    SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as conversions,
                    ROUND(100.0 * SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as conv_rate
                FROM notification_log
                WHERE promo_code IS NOT NULL
                GROUP BY promo_code
                ORDER BY conv_rate DESC, conversions DESC
            """)
            promo_stats = await cursor.fetchall()

            if not promo_stats:
                msg = "ℹ️ <b>Промокоды ещё не отправлялись</b>\n\n"
                msg += "Промокоды будут включены в уведомления начиная с первой отправки.\n\n"

                # Показываем список созданных промокодов
                cursor = await db.execute("""
                    SELECT code, discount_percent
                    FROM promo_codes
                    WHERE code IN ('TOP20', 'TRIAL20', 'LASTDAY25', 'COMEBACK30',
                                   'STAY15', 'SAVE25', 'URGENT30', 'RETURN40', 'LAST50')
                    ORDER BY discount_percent ASC
                """)
                codes = await cursor.fetchall()

                if codes:
                    msg += "📋 <b>Созданные retention промокоды:</b>\n"
                    for code, discount in codes:
                        msg += f"  • {code} — {discount}% скидка\n"

                await message.reply_text(msg, parse_mode=ParseMode.HTML)
                return

            # Формируем сообщение
            msg = "🎁 <b>СТАТИСТИКА ПРОМОКОДОВ</b>\n\n"

            total_with_promo = sum(p[1] for p in promo_stats)
            total_conversions = sum(p[3] for p in promo_stats)

            msg += f"📊 Уведомлений с промокодами: {total_with_promo}\n"
            msg += f"💰 Конверсий через промокоды: {total_conversions}\n\n"

            msg += "📈 <b>Топ промокодов по эффективности:</b>\n\n"

            for promo_code, times_sent, clicks, conversions, conv_rate in promo_stats:
                # Получаем скидку для промокода
                cursor = await db.execute(
                    "SELECT discount_percent FROM promo_codes WHERE code = ?",
                    (promo_code,)
                )
                discount_row = await cursor.fetchone()
                discount = discount_row[0] if discount_row else 0

                msg += f"🏷️ <b>{promo_code}</b> ({discount}% скидка)\n"
                msg += f"  Отправлено: {times_sent} | Кликов: {clicks} | "
                msg += f"Конверсий: {conversions} ({conv_rate}%)\n\n"

            # Кнопки
            keyboard = [
                [InlineKeyboardButton("📊 Общая статистика", callback_data="retention:overall_stats")],
                [InlineKeyboardButton("🔄 Обновить", callback_data="retention:promo_stats")],
                [InlineKeyboardButton("❌ Закрыть", callback_data="retention:close")]
            ]

            await message.reply_text(
                msg,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Error in promo_stats: {e}", exc_info=True)
        await message.reply_text(
            f"❌ Ошибка при загрузке статистики:\n{e}"
        )


@admin_only
async def test_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет тестовое retention уведомление админу.

    Команда: /test_notification [trigger]

    Примеры:
        /test_notification bounced_day1
        /test_notification trial_expiring_2days
        /test_notification churn_risk_3days
    """
    user_id = update.effective_user.id

    # Проверяем аргументы
    if not context.args:
        msg = "🧪 <b>Тестовые уведомления</b>\n\n"
        msg += "Используйте: <code>/test_notification [trigger]</code>\n\n"
        msg += "📋 <b>Доступные триггеры:</b>\n\n"
        msg += "<b>BOUNCED:</b>\n"
        msg += "  • bounced_day1\n"
        msg += "  • bounced_day3\n\n"
        msg += "<b>CURIOUS:</b>\n"
        msg += "  • curious_day3\n"
        msg += "  • curious_day7\n\n"
        msg += "<b>TRIAL:</b>\n"
        msg += "  • trial_day3\n"
        msg += "  • trial_expiring_2days\n"
        msg += "  • trial_expiring_1day\n"
        msg += "  • trial_expired\n\n"
        msg += "<b>CHURN_RISK:</b>\n"
        msg += "  • churn_risk_7days\n"
        msg += "  • churn_risk_3days\n"
        msg += "  • churn_risk_1day\n\n"
        msg += "<b>CANCELLED:</b>\n"
        msg += "  • cancelled_day1\n"
        msg += "  • cancelled_day3\n"
        msg += "  • cancelled_day7\n\n"
        msg += "<b>ACTIVE_FREE:</b>\n"
        msg += "  • active_free_day10\n"
        msg += "  • active_free_day20\n"
        msg += "  • active_free_limit_warning\n\n"
        msg += "<b>PAYING_INACTIVE:</b>\n"
        msg += "  • paying_inactive_day3\n"
        msg += "  • paying_inactive_day7\n"
        msg += "  • paying_inactive_day14\n"

        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    trigger_name = context.args[0].upper()

    try:
        from core.notification_templates import get_template, NotificationTrigger
        from core.user_segments import UserSegment

        # Маппинг триггеров
        trigger_map = {
            'BOUNCED_DAY1': NotificationTrigger.BOUNCED_DAY1,
            'BOUNCED_DAY3': NotificationTrigger.BOUNCED_DAY3,
            'CURIOUS_DAY3': NotificationTrigger.CURIOUS_DAY3,
            'CURIOUS_DAY7': NotificationTrigger.CURIOUS_DAY7,
            'TRIAL_DAY3': NotificationTrigger.TRIAL_DAY3,
            'TRIAL_EXPIRING_2DAYS': NotificationTrigger.TRIAL_EXPIRING_2DAYS,
            'TRIAL_EXPIRING_1DAY': NotificationTrigger.TRIAL_EXPIRING_1DAY,
            'TRIAL_EXPIRED': NotificationTrigger.TRIAL_EXPIRED,
            'CHURN_RISK_7DAYS': NotificationTrigger.CHURN_RISK_7DAYS,
            'CHURN_RISK_3DAYS': NotificationTrigger.CHURN_RISK_3DAYS,
            'CHURN_RISK_1DAY': NotificationTrigger.CHURN_RISK_1DAY,
            'CANCELLED_DAY1': NotificationTrigger.CANCELLED_DAY1,
            'CANCELLED_DAY3': NotificationTrigger.CANCELLED_DAY3,
            'CANCELLED_DAY7': NotificationTrigger.CANCELLED_DAY7,
            'ACTIVE_FREE_DAY10': NotificationTrigger.ACTIVE_FREE_DAY10,
            'ACTIVE_FREE_DAY20': NotificationTrigger.ACTIVE_FREE_DAY20,
            'ACTIVE_FREE_LIMIT_WARNING': NotificationTrigger.ACTIVE_FREE_LIMIT_WARNING,
            'PAYING_INACTIVE_DAY3': NotificationTrigger.PAYING_INACTIVE_DAY3,
            'PAYING_INACTIVE_DAY7': NotificationTrigger.PAYING_INACTIVE_DAY7,
            'PAYING_INACTIVE_DAY14': NotificationTrigger.PAYING_INACTIVE_DAY14,
        }

        if trigger_name not in trigger_map:
            await update.message.reply_text(
                f"❌ Неизвестный триггер: {trigger_name}\n\n"
                f"Используйте /test_notification без аргументов для списка доступных триггеров."
            )
            return

        trigger = trigger_map[trigger_name]
        template = get_template(trigger)

        if not template:
            await update.message.reply_text(f"❌ Шаблон для триггера {trigger_name} не найден")
            return

        # Получаем имя пользователя
        first_name = update.effective_user.first_name or "друг"

        # Тестовые данные
        variables = {
            'first_name': first_name,
            'answered_total': 42,
            'ai_checks_total': 15,
            'days_to_ege': (date(2026, 6, 11) - date.today()).days,
            'days_until_expiry': 2,
            'trial_savings': 50
        }

        # Рендерим шаблон
        message_text = template.render(variables)

        # Создаём кнопки
        keyboard = []
        for button in template.buttons:
            keyboard.append([InlineKeyboardButton(button['text'], callback_data=button['callback_data'])])

        # Отправляем
        await update.message.reply_text(
            f"🧪 <b>Тестовое уведомление: {trigger_name}</b>\n\n"
            f"─────────────────────────\n\n"
            f"{message_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )

        logger.info(f"Admin {user_id} tested notification: {trigger_name}")

    except Exception as e:
        logger.error(f"Error in test_notification: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Ошибка при отправке тестового уведомления:\n{e}"
        )


async def handle_retention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback-кнопок для retention админки"""
    query = update.callback_query
    await query.answer()

    action = query.data.split(':')[1] if ':' in query.data else ''

    if action == 'refresh_stats' or action == 'overall_stats':
        # Обновить общую статистику - используем оригинальный update с правильным from_user
        await retention_stats(update, context)
        await query.message.delete()

    elif action == 'promo_stats':
        await promo_stats(update, context)
        await query.message.delete()

    elif action == 'close':
        await query.message.delete()


def register_retention_admin_handlers(app):
    """Регистрирует retention admin команды"""
    from telegram.ext import CallbackQueryHandler

    app.add_handler(CommandHandler("retention_stats", retention_stats))
    app.add_handler(CommandHandler("promo_stats", promo_stats))
    app.add_handler(CommandHandler("test_notification", test_notification))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(
        handle_retention_callback,
        pattern="^retention:"
    ))

    logger.info("Retention admin handlers registered")
