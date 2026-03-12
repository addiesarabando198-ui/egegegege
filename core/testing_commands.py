"""
Админские команды для тестирования систем бота перед запуском рекламы.

Эти команды позволяют:
- Протестировать onboarding
- Отправить себе тестовые уведомления
- Симулировать разные типы пользователей
- Проверить готовность к рекламе
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode
from core import db, config
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def test_onboarding_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /test_onboarding - запускает onboarding заново для админа.
    """
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    try:
        # Сбрасываем флаг onboarding
        conn = await db.get_db()
        await conn.execute("""
            UPDATE users
            SET onboarding_completed = 0,
                onboarding_skipped = 0,
                onboarding_completed_at = NULL
            WHERE user_id = ?
        """, (user_id,))
        await conn.commit()

        await update.message.reply_text(
            "✅ Onboarding сброшен!\n\n"
            "Теперь нажми /start чтобы пройти его заново.",
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Error in test_onboarding_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def test_notification_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /test_notification <trigger> - отправляет тестовое уведомление.

    Примеры:
    /test_notification bounced_day1
    /test_notification curious_day3
    /test_notification trial_expiring_1day
    """
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    if not context.args or len(context.args) < 1:
        # Показываем список доступных триггеров
        from core.notification_templates import NotificationTrigger

        triggers_list = "\n".join([f"• {t.value}" for t in NotificationTrigger])

        await update.message.reply_text(
            f"📋 <b>Доступные триггеры:</b>\n\n{triggers_list}\n\n"
            f"<b>Использование:</b>\n"
            f"/test_notification bounced_day1",
            parse_mode=ParseMode.HTML
        )
        return

    trigger_name = context.args[0]

    try:
        from core.notification_templates import NotificationTrigger, get_template
        from core.user_segments import UserSegment
        from core.retention_scheduler import get_retention_scheduler

        # Находим триггер
        trigger = None
        for t in NotificationTrigger:
            if t.value == trigger_name:
                trigger = t
                break

        if not trigger:
            await update.message.reply_text(f"❌ Триггер '{trigger_name}' не найден")
            return

        # Получаем scheduler
        scheduler = get_retention_scheduler()

        # Получаем активность пользователя
        activity = await scheduler.classifier.get_user_activity_stats(user_id)
        if not activity:
            activity = {
                'first_name': update.effective_user.first_name or 'Тестер',
                'answered_total': 5,
                'answered_week': 3,
                'days_since_registration': 3,
                'days_inactive': 2,
                'ai_checks_today': 1
            }

        # Обогащаем переменные
        variables = scheduler._enrich_variables(activity)

        # Отправляем уведомление
        success = await scheduler.send_notification(
            bot=context.bot,
            user_id=user_id,
            segment=UserSegment.BOUNCED,  # Не важно для теста
            trigger=trigger,
            variables=variables
        )

        if success:
            await update.message.reply_text(
                f"✅ Уведомление '{trigger_name}' отправлено!\n\n"
                f"Проверь выше ⬆️",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"❌ Не удалось отправить уведомление.\n"
                f"Возможно ты заблокировал его или достигнут лимит.",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error in test_notification_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def simulate_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /simulate_user <scenario> - симулирует поведение пользователя.

    Сценарии:
    - bounced: регистрация, 0 ответов
    - curious: регистрация 5 дней назад, 3 ответа
    - active: регистрация 20 дней назад, 50 ответов
    - reset: сброс всех данных
    """
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "📋 <b>Доступные сценарии:</b>\n\n"
            "• <code>bounced</code> - зарегистрирован 2 дня назад, 0 ответов\n"
            "• <code>curious</code> - зарегистрирован 5 дней назад, 3 ответа\n"
            "• <code>active</code> - зарегистрирован 20 дней назад, 50 ответов\n"
            "• <code>reset</code> - сброс всех данных\n\n"
            "<b>Использование:</b>\n"
            "/simulate_user bounced",
            parse_mode=ParseMode.HTML
        )
        return

    scenario = context.args[0].lower()

    try:
        conn = await db.get_db()

        if scenario == "reset":
            # Удаляем все данные пользователя
            await conn.execute("DELETE FROM answered_questions WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM user_ai_limits WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM notification_log WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM notification_cooldown WHERE user_id = ?", (user_id,))
            await conn.execute("""
                UPDATE users
                SET first_seen = datetime('now'),
                    last_activity_date = NULL,
                    onboarding_completed = 0,
                    onboarding_skipped = 0
                WHERE user_id = ?
            """, (user_id,))
            await conn.commit()

            await update.message.reply_text(
                "✅ Все данные сброшены!\n\n"
                "Теперь ты как новый пользователь.",
                parse_mode=ParseMode.HTML
            )
            return

        elif scenario == "bounced":
            # Bounced: регистрация 2 дня назад, 0 ответов
            registration_date = (datetime.now() - timedelta(days=2)).isoformat()

            await conn.execute("DELETE FROM answered_questions WHERE user_id = ?", (user_id,))
            await conn.execute("""
                UPDATE users
                SET first_seen = ?,
                    last_activity_date = ?,
                    onboarding_completed = 0
                WHERE user_id = ?
            """, (registration_date, registration_date, user_id))
            await conn.commit()

            await update.message.reply_text(
                "✅ Симуляция BOUNCED пользователя:\n\n"
                "• Регистрация: 2 дня назад\n"
                "• Ответов: 0\n"
                "• Onboarding: не пройден\n\n"
                "Завтра в 18:00 МСК придет retention уведомление!",
                parse_mode=ParseMode.HTML
            )

        elif scenario == "curious":
            # Curious: регистрация 5 дней назад, 3 ответа, неактивен 3 дня
            registration_date = (datetime.now() - timedelta(days=5)).isoformat()
            last_activity = (datetime.now() - timedelta(days=3)).isoformat()

            await conn.execute("DELETE FROM answered_questions WHERE user_id = ?", (user_id,))

            # Добавляем 3 ответа
            for i in range(3):
                await conn.execute("""
                    INSERT INTO answered_questions (user_id, question_id, is_correct, answered_at)
                    VALUES (?, ?, 1, ?)
                """, (user_id, f"test_{i}", last_activity))

            await conn.execute("""
                UPDATE users
                SET first_seen = ?,
                    last_activity_date = date(?),
                    onboarding_completed = 1
                WHERE user_id = ?
            """, (registration_date, last_activity, user_id))
            await conn.commit()

            await update.message.reply_text(
                "✅ Симуляция CURIOUS пользователя:\n\n"
                "• Регистрация: 5 дней назад\n"
                "• Ответов: 3\n"
                "• Последняя активность: 3 дня назад\n\n"
                "Завтра в 18:00 МСК придет retention уведомление!",
                parse_mode=ParseMode.HTML
            )

        elif scenario == "active":
            # Active: регистрация 20 дней назад, 50 ответов
            registration_date = (datetime.now() - timedelta(days=20)).isoformat()

            await conn.execute("DELETE FROM answered_questions WHERE user_id = ?", (user_id,))

            # Добавляем 50 ответов за последние 2 недели
            for i in range(50):
                days_ago = (i % 14)
                answered_date = (datetime.now() - timedelta(days=days_ago)).isoformat()
                await conn.execute("""
                    INSERT INTO answered_questions (user_id, question_id, is_correct, answered_at)
                    VALUES (?, ?, 1, ?)
                """, (user_id, f"test_{i}", answered_date))

            await conn.execute("""
                UPDATE users
                SET first_seen = ?,
                    last_activity_date = date('now'),
                    onboarding_completed = 1
                WHERE user_id = ?
            """, (registration_date, user_id))
            await conn.commit()

            await update.message.reply_text(
                "✅ Симуляция ACTIVE пользователя:\n\n"
                "• Регистрация: 20 дней назад\n"
                "• Ответов: 50\n"
                "• Последняя активность: сегодня\n\n"
                "Этому пользователю придут conversion-уведомления!",
                parse_mode=ParseMode.HTML
            )

        else:
            await update.message.reply_text(
                f"❌ Неизвестный сценарий: {scenario}\n\n"
                f"Доступные: bounced, curious, active, reset",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error in simulate_user_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def check_readiness_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /check_readiness - проверяет готовность бота к рекламе.
    """
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    try:
        report = "🔍 <b>ПРОВЕРКА ГОТОВНОСТИ К РЕКЛАМЕ</b>\n\n"
        all_ok = True

        # 1. Проверка onboarding
        conn = await db.get_db()
        has_onboarding = await db.check_column_exists(conn, 'users', 'onboarding_completed')

        if has_onboarding:
            report += "✅ Onboarding система: настроена\n"
        else:
            report += "❌ Onboarding система: НЕ настроена\n"
            all_ok = False

        # 2. Проверка retention
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='notification_log'
        """)
        has_retention = (await cursor.fetchone())[0] > 0

        if has_retention:
            cursor = await conn.execute("SELECT COUNT(*) FROM notification_log")
            notif_count = (await cursor.fetchone())[0]
            report += f"✅ Retention система: {notif_count} уведомлений отправлено\n"
        else:
            report += "❌ Retention система: НЕ настроена\n"
            all_ok = False

        # 3. Проверка аналитики
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='funnel_events'
        """)
        has_analytics = (await cursor.fetchone())[0] > 0

        if has_analytics:
            report += "✅ Аналитика воронки: настроена\n"
        else:
            report += "❌ Аналитика воронки: НЕ настроена\n"
            all_ok = False

        # 4. Проверка платежей
        if config.TINKOFF_TERMINAL_KEY and config.TINKOFF_SECRET_KEY:
            report += "✅ Платежная система: настроена\n"
        else:
            report += "⚠️ Платежная система: НЕ настроена (не критично для теста)\n"

        # 5. Проверка цен
        from payment.config import SUBSCRIPTION_PLANS
        if 'trial_7days' in SUBSCRIPTION_PLANS:
            trial_price = SUBSCRIPTION_PLANS['trial_7days']['price_rub']
            full_price = SUBSCRIPTION_PLANS['package_full']['price_rub']
            report += f"✅ Цены: Trial {trial_price}₽, Полная {full_price}₽\n"
        else:
            report += "❌ Цены: НЕ настроены\n"
            all_ok = False

        # 6. Проверка пользователей
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]

        cursor = await conn.execute("""
            SELECT COUNT(*) FROM users
            WHERE last_activity_date >= date('now', '-7 days')
        """)
        active_users = (await cursor.fetchone())[0]

        report += f"\n📊 <b>Статистика:</b>\n"
        report += f"• Всего пользователей: {total_users}\n"
        report += f"• Активных за неделю: {active_users}\n"

        # Финальная оценка
        report += f"\n{'='*30}\n"

        if all_ok:
            report += "✅ <b>БОТ ГОТОВ К РЕКЛАМЕ!</b>\n\n"
            report += "Рекомендации:\n"
            report += "1. Пригласите 20-30 знакомых для теста\n"
            report += "2. Наблюдайте метрики 1-2 недели\n"
            report += "3. Если onboarding completion >60% → запускайте микро-тест\n"
        else:
            report += "⚠️ <b>ЕСТЬ ПРОБЛЕМЫ</b>\n\n"
            report += "Исправьте ошибки выше перед рекламой!"

        await update.message.reply_text(report, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error in check_readiness_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def test_retention_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /test_retention - запускает retention систему вручную для теста.
    """
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    try:
        from core.retention_scheduler import get_retention_scheduler

        await update.message.reply_text(
            "🔄 Запускаю retention систему...\n\n"
            "Это может занять 1-2 минуты."
        )

        scheduler = get_retention_scheduler()

        # Запускаем отправку уведомлений
        await scheduler.send_daily_notifications(context)

        await update.message.reply_text(
            "✅ Retention система завершила работу!\n\n"
            "Проверь логи и используй /retention_stats для деталей.",
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Error in test_retention_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def diagnose_retention_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /diagnose_retention - диагностирует почему retention не работает.
    """
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    try:
        from core.user_segments import get_segment_classifier, UserSegment

        classifier = get_segment_classifier()

        report = "🔍 <b>ДИАГНОСТИКА RETENTION СИСТЕМЫ</b>\n\n"

        # Проверяем каждый сегмент
        segments_to_check = [
            (UserSegment.BOUNCED, "BOUNCED"),
            (UserSegment.LATE_BOUNCED, "LATE_BOUNCED"),
            (UserSegment.CURIOUS, "CURIOUS"),
            (UserSegment.ACTIVE_FREE, "ACTIVE_FREE"),
            (UserSegment.TRIAL_USER, "TRIAL_USER"),
            (UserSegment.PAYING_INACTIVE, "PAYING_INACTIVE"),
            (UserSegment.CHURN_RISK, "CHURN_RISK"),
            (UserSegment.CANCELLED, "CANCELLED"),
        ]

        total_users_in_segments = 0

        for segment, name in segments_to_check:
            users = await classifier.get_users_by_segment(segment, limit=200)
            count = len(users)
            total_users_in_segments += count

            if count > 0:
                report += f"✅ <b>{name}:</b> {count} пользователей\n"
            else:
                report += f"⚠️ <b>{name}:</b> 0 пользователей\n"

        # Общая статистика
        conn = await db.get_db()
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]

        report += f"\n📊 <b>Общая статистика:</b>\n"
        report += f"• Всего пользователей: {total_users}\n"
        report += f"• В retention сегментах: {total_users_in_segments}\n"

        # Проверяем bounced подробнее
        if total_users > 0:
            cursor = await conn.execute("""
                SELECT COUNT(*) FROM users u
                WHERE (SELECT COUNT(*) FROM answered_questions WHERE user_id = u.user_id) = 0
                AND datetime(u.first_seen) BETWEEN datetime('now', '-7 days') AND datetime('now', '-1 day')
            """)
            bounced_count = (await cursor.fetchone())[0]

            cursor = await conn.execute("""
                SELECT COUNT(*) FROM users u
                WHERE (SELECT COUNT(*) FROM answered_questions WHERE user_id = u.user_id) BETWEEN 1 AND 10
                AND date(u.last_activity_date) BETWEEN date('now', '-14 days') AND date('now', '-2 days')
            """)
            curious_count = (await cursor.fetchone())[0]

            report += f"\n🔍 <b>Детальная проверка:</b>\n"
            report += f"• Bounced (0 ответов, 1-7 дней): {bounced_count}\n"
            report += f"• Curious (1-10 ответов, неактивен 2-14 дней): {curious_count}\n"

            if bounced_count == 0 and curious_count == 0:
                report += f"\n⚠️ <b>ПРОБЛЕМА:</b> Нет пользователей подходящих под критерии!\n\n"
                report += f"<b>Решение:</b>\n"
                report += f"1. Используй /simulate_user bounced\n"
                report += f"2. Или пригласи реальных пользователей\n"

        # Проверяем блокировки
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM notification_preferences
            WHERE enabled = 0
        """)
        disabled_count = (await cursor.fetchone())[0]

        if disabled_count > 0:
            report += f"\n🔕 Отключили уведомления: {disabled_count} пользователей\n"

        # Финальные рекомендации
        report += f"\n{'='*30}\n"

        if total_users_in_segments > 0:
            report += f"✅ <b>Система работает корректно</b>\n\n"
            report += f"Уведомления будут отправлены при следующих условиях:\n"
            report += f"• Не превышен дневной лимит (2 в день для bounced/curious)\n"
            report += f"• Прошел cooldown (12ч для bounced/curious)\n"
            report += f"• Пользователь не отключил уведомления\n"
        else:
            report += f"⚠️ <b>Нет подходящих пользователей</b>\n\n"
            report += f"<b>Что делать:</b>\n"
            report += f"1. /simulate_user bounced - создать тестового пользователя\n"
            report += f"2. /test_retention - запустить отправку\n"
            report += f"3. Или дождаться реальных пользователей\n"

        await update.message.reply_text(report, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error in diagnose_retention_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {e}")


def register_testing_commands(application):
    """Регистрирует команды для тестирования."""
    application.add_handler(CommandHandler("test_onboarding", test_onboarding_command))
    application.add_handler(CommandHandler("test_notification", test_notification_command))
    application.add_handler(CommandHandler("simulate_user", simulate_user_command))
    application.add_handler(CommandHandler("check_readiness", check_readiness_command))
    application.add_handler(CommandHandler("test_retention", test_retention_command))
    application.add_handler(CommandHandler("diagnose_retention", diagnose_retention_command))

    logger.info("Testing commands registered")
