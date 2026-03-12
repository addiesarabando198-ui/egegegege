"""
Обработчики callback-кнопок из retention уведомлений.
"""

import logging
import aiosqlite
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


async def handle_notification_disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отключить retention уведомления.

    Callback data: notifications_disable
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Отключаем уведомления
            await db.execute("""
                INSERT OR REPLACE INTO notification_preferences (
                    user_id, enabled, disabled_at, disabled_reason
                ) VALUES (?, 0, ?, 'user_request')
            """, (user_id, datetime.now(timezone.utc).isoformat()))
            await db.commit()

        # Сообщаем пользователю
        await query.edit_message_text(
            "✅ <b>Уведомления отключены</b>\n\n"
            "Мы больше не будем беспокоить тебя напоминаниями.\n\n"
            "💡 <i>Ты можешь включить уведомления в любой момент в разделе "
            "«Личный кабинет» → «Настройки».</i>",
            parse_mode='HTML'
        )

        logger.info(f"User {user_id} disabled retention notifications")

    except Exception as e:
        logger.error(f"Error disabling notifications for user {user_id}: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при отключении уведомлений.\n"
            "Попробуйте позже или напишите в поддержку."
        )


async def handle_notification_clicked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отслеживает клики по основным CTA-кнопкам в уведомлениях.

    Этот обработчик вызывается перед основным действием (например, subscribe_start).
    Он просто логирует клик для аналитики.

    Callback data: notification_clicked:<notification_id>
    """
    query = update.callback_query
    user_id = update.effective_user.id

    # Извлекаем ID уведомления из callback_data
    callback_data = query.data
    parts = callback_data.split(':')

    if len(parts) < 2:
        return

    notification_id = parts[1] if len(parts) > 1 else None

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Обновляем статус clicked в notification_log
            if notification_id:
                await db.execute("""
                    UPDATE notification_log
                    SET clicked = 1, clicked_at = ?
                    WHERE id = ?
                """, (datetime.now(timezone.utc).isoformat(), notification_id))
            else:
                # Если ID неизвестен, ищем последнее уведомление этого пользователя
                await db.execute("""
                    UPDATE notification_log
                    SET clicked = 1, clicked_at = ?
                    WHERE user_id = ? AND clicked = 0
                    ORDER BY sent_at DESC
                    LIMIT 1
                """, (datetime.now(timezone.utc).isoformat(), user_id))

            await db.commit()

        logger.info(f"User {user_id} clicked notification CTA")

    except Exception as e:
        logger.error(f"Error tracking notification click for user {user_id}: {e}")


async def handle_notification_enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Включить retention уведомления.

    Callback data: notifications_enable
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Включаем уведомления
            await db.execute("""
                INSERT OR REPLACE INTO notification_preferences (
                    user_id, enabled, disabled_at, disabled_reason
                ) VALUES (?, 1, NULL, NULL)
            """, (user_id,))
            await db.commit()

        # Сообщаем пользователю
        await query.edit_message_text(
            "✅ <b>Уведомления включены</b>\n\n"
            "Теперь ты будешь получать полезные напоминания и персональные предложения.\n\n"
            "💡 <i>Мы отправляем не более 1 уведомления в день.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )

        logger.info(f"User {user_id} enabled retention notifications")

    except Exception as e:
        logger.error(f"Error enabling notifications for user {user_id}: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при включении уведомлений.\n"
            "Попробуйте позже или напишите в поддержку."
        )


async def track_notification_conversion(user_id: int, promo_code: str = None):
    """
    Отслеживает конверсию из уведомления (покупка подписки).

    УЛУЧШЕНО: Теперь отслеживает конверсии в временном окне 14 дней,
    даже если пользователь не использовал промокод.

    Вызывается из payment handlers после успешной оплаты.

    Args:
        user_id: ID пользователя
        promo_code: Использованный промокод (если есть)
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            conversion_time = datetime.now(timezone.utc).isoformat()

            # Приоритет 1: Если есть промокод, отмечаем уведомление с этим промокодом
            if promo_code:
                cursor = await db.execute("""
                    UPDATE notification_log
                    SET converted = 1, converted_at = ?
                    WHERE user_id = ? AND promo_code = ?
                      AND converted = 0
                      AND sent_at > datetime('now', '-14 days')
                    ORDER BY sent_at DESC
                    LIMIT 1
                """, (conversion_time, user_id, promo_code))

                if cursor.rowcount > 0:
                    await db.commit()
                    logger.info(
                        f"Tracked conversion for user {user_id} with promo_code {promo_code} "
                        f"(matched by promo code)"
                    )
                    return

            # Приоритет 2: Отмечаем последнее кликнутое уведомление (в окне 14 дней)
            cursor = await db.execute("""
                UPDATE notification_log
                SET converted = 1, converted_at = ?
                WHERE user_id = ?
                  AND converted = 0
                  AND clicked = 1
                  AND sent_at > datetime('now', '-14 days')
                ORDER BY clicked_at DESC
                LIMIT 1
            """, (conversion_time, user_id))

            if cursor.rowcount > 0:
                await db.commit()
                logger.info(
                    f"Tracked conversion for user {user_id} "
                    f"(matched by clicked notification within 14 days)"
                )
                return

            # Приоритет 3: Отмечаем последнее уведомление (в окне 7 дней)
            # Даже если пользователь не кликал, но мог видеть и принять решение
            cursor = await db.execute("""
                UPDATE notification_log
                SET converted = 1, converted_at = ?
                WHERE user_id = ?
                  AND converted = 0
                  AND sent_at > datetime('now', '-7 days')
                ORDER BY sent_at DESC
                LIMIT 1
            """, (conversion_time, user_id))

            if cursor.rowcount > 0:
                await db.commit()
                logger.info(
                    f"Tracked conversion for user {user_id} "
                    f"(matched by recent notification within 7 days)"
                )
            else:
                logger.debug(
                    f"No suitable notification found for conversion tracking: user_id={user_id}"
                )

    except Exception as e:
        logger.error(f"Error tracking conversion for user {user_id}: {e}", exc_info=True)


def register_notification_handlers(application):
    """
    Регистрирует все обработчики уведомлений в приложении.

    Вызывается из core/app.py при инициализации бота.

    Args:
        application: telegram.ext.Application
    """
    from telegram.ext import CallbackQueryHandler

    # Отключить уведомления
    application.add_handler(CallbackQueryHandler(
        handle_notification_disable,
        pattern="^notifications_disable$"
    ))

    # Включить уведомления
    application.add_handler(CallbackQueryHandler(
        handle_notification_enable,
        pattern="^notifications_enable$"
    ))

    # Трекинг кликов (для аналитики)
    application.add_handler(CallbackQueryHandler(
        handle_notification_clicked,
        pattern="^notification_clicked:"
    ))

    logger.info("Notification handlers registered")
