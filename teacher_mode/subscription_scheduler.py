"""
Планировщик задач для управления подписками учителей.
"""
import logging
import aiosqlite
from datetime import datetime, timedelta
from telegram.ext import ContextTypes

from core.config import DATABASE_FILE
from teacher_mode.utils.datetime_utils import utc_now, parse_datetime_safe, ensure_timezone_aware

logger = logging.getLogger(__name__)


async def deactivate_expired_teacher_subscriptions(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Деактивирует истекшие подписки учителей.

    Эта задача запускается каждый час и:
    1. Находит учителей с истекшими подписками
    2. Сбрасывает флаг has_active_subscription
    3. Логирует количество деактивированных подписок

    Args:
        context: Контекст Telegram бота
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Находим истекшие подписки с информацией о тарифе
            cursor = await db.execute("""
                SELECT user_id, subscription_expires, subscription_tier
                FROM teacher_profiles
                WHERE has_active_subscription = 1
                AND subscription_expires IS NOT NULL
                AND subscription_expires < datetime('now')
            """)

            expired_teachers = await cursor.fetchall()

            if not expired_teachers:
                logger.debug("No expired teacher subscriptions found")
                return

            # Деактивируем истекшие подписки
            await db.execute("""
                UPDATE teacher_profiles
                SET has_active_subscription = 0
                WHERE has_active_subscription = 1
                AND subscription_expires < datetime('now')
            """)

            # Логируем истечение подписок в историю
            for user_id, expires_at, subscription_tier in expired_teachers:
                try:
                    await db.execute("""
                        INSERT INTO teacher_subscription_history
                        (user_id, plan_id, action, previous_tier, new_tier, expires_at, created_at)
                        VALUES (?, ?, 'expired', ?, NULL, ?, CURRENT_TIMESTAMP)
                    """, (user_id, subscription_tier, subscription_tier, expires_at))
                except Exception as log_error:
                    logger.error(f"Failed to log expiration for teacher {user_id}: {log_error}")

            await db.commit()

            count = len(expired_teachers)
            logger.info(f"✅ Deactivated {count} expired teacher subscription(s)")

            # Отправляем уведомления учителям об истечении подписки
            for user_id, expires_at, subscription_tier in expired_teachers:
                try:
                    await context.bot.send_message(
                        user_id,
                        "❌ <b>Ваша учительская подписка истекла</b>\n\n"
                        "Вы больше не можете:\n"
                        "• Добавлять новых учеников\n"
                        "• Создавать домашние задания\n"
                        "• Просматривать прогресс учеников\n\n"
                        "💡 Продлите подписку, чтобы восстановить доступ к функциям учителя.\n\n"
                        "Используйте команду /teacher для управления подпиской.",
                        parse_mode='HTML'
                    )
                    logger.info(f"Sent expiry notification to teacher {user_id}")
                except Exception as e:
                    logger.error(f"Failed to send expiry notification to teacher {user_id}: {e}")

    except Exception as e:
        logger.error(f"Error in deactivate_expired_teacher_subscriptions: {e}")
        import traceback
        traceback.print_exc()


async def check_expiring_teacher_subscriptions(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Проверяет подписки учителей, истекающие в ближайшие 3 дня.

    Отправляет предупреждающие уведомления учителям за:
    - 3 дня до истечения
    - 1 день до истечения

    Args:
        context: Контекст Telegram бота
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Находим подписки, истекающие в ближайшие 3 дня
            cursor = await db.execute("""
                SELECT user_id, subscription_expires, subscription_tier
                FROM teacher_profiles
                WHERE has_active_subscription = 1
                AND subscription_expires IS NOT NULL
                AND subscription_expires > datetime('now')
                AND subscription_expires <= datetime('now', '+3 days')
            """)

            expiring_teachers = await cursor.fetchall()

            if not expiring_teachers:
                logger.debug("No expiring teacher subscriptions found")
                return

            logger.info(f"Found {len(expiring_teachers)} expiring teacher subscription(s)")

            for row in expiring_teachers:
                user_id = row['user_id']
                expires_at = datetime.fromisoformat(row['subscription_expires'])
                tier = row['subscription_tier']

                # Вычисляем количество дней до истечения
                days_left = (ensure_timezone_aware(expires_at) - utc_now()).days

                # Отправляем уведомление только за 3 дня и за 1 день
                if days_left not in [3, 1]:
                    continue

                try:
                    if days_left == 3:
                        emoji = "⚠️"
                        urgency = "скоро"
                    elif days_left == 1:
                        emoji = "🚨"
                        urgency = "завтра"
                    else:
                        continue

                    # Получаем название тарифа
                    tier_names = {
                        'teacher_basic': 'Basic',
                        'teacher_standard': 'Standard',
                        'teacher_premium': 'Premium'
                    }
                    tier_name = tier_names.get(tier, tier)

                    message = (
                        f"{emoji} <b>Ваша учительская подписка истекает {urgency}!</b>\n\n"
                        f"📊 Текущий тариф: <b>{tier_name}</b>\n"
                        f"📅 Истекает: <b>{expires_at.strftime('%d.%m.%Y')}</b>\n\n"
                        f"После истечения подписки вы потеряете доступ к:\n"
                        f"• Добавлению новых учеников\n"
                        f"• Созданию домашних заданий\n"
                        f"• Просмотру прогресса учеников\n\n"
                        f"💡 <b>Продлите подписку прямо сейчас</b>, чтобы не прерывать работу с учениками.\n\n"
                        f"Используйте команду /teacher для управления подпиской."
                    )

                    await context.bot.send_message(
                        user_id,
                        message,
                        parse_mode='HTML'
                    )
                    logger.info(f"Sent expiring notification to teacher {user_id} ({days_left} days left)")

                except Exception as e:
                    logger.error(f"Failed to send expiring notification to teacher {user_id}: {e}")

    except Exception as e:
        logger.error(f"Error in check_expiring_teacher_subscriptions: {e}")
        import traceback
        traceback.print_exc()


def register_teacher_subscription_jobs(application) -> None:
    """
    Регистрирует фоновые задачи для управления подписками учителей.

    Args:
        application: Application instance
    """
    from datetime import time as dt_time
    from zoneinfo import ZoneInfo

    msk_tz = ZoneInfo("Europe/Moscow")

    # Задача 1: Деактивация истекших подписок (каждый час)
    application.job_queue.run_repeating(
        deactivate_expired_teacher_subscriptions,
        interval=3600,  # Каждый час
        first=60,  # Первый запуск через 1 минуту после старта
        name='deactivate_expired_teachers'
    )
    logger.info("✅ Registered job: deactivate_expired_teachers (every hour)")

    # Задача 2: Проверка истекающих подписок (каждый день в 10:00 МСК)
    application.job_queue.run_daily(
        check_expiring_teacher_subscriptions,
        time=dt_time(hour=10, minute=0, second=0, tzinfo=msk_tz),
        name='check_expiring_teachers'
    )
    logger.info("✅ Registered job: check_expiring_teachers (daily at 10:00 MSK)")
