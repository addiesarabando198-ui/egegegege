"""
Админские команды для анализа воронки конверсии.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from core import db, config

logger = logging.getLogger(__name__)


async def funnel_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику воронки конверсии."""
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    try:
        # Получаем статистику воронки
        stats = await db.get_funnel_stats()

        if not stats:
            await update.message.reply_text("❌ Не удалось получить статистику")
            return

        # Форматируем отчет
        total = stats.get('total_users', 0)
        answered = stats.get('answered_questions', 0)
        used_ai = stats.get('used_ai_check', 0)
        subscribers = stats.get('active_subscribers', 0)

        activation_rate = stats.get('activation_rate', 0)
        ai_usage_rate = stats.get('ai_usage_rate', 0)
        paid_conversion = stats.get('paid_conversion_rate', 0)

        text = f"""📊 <b>СТАТИСТИКА ВОРОНКИ</b>

👥 <b>Всего пользователей:</b> {total}

📈 <b>Этапы воронки:</b>

1️⃣ <b>Регистрация</b>
   • Всего: {total} (100%)

2️⃣ <b>Активация</b> (решили хотя бы 1 вопрос)
   • Активировано: {answered} ({activation_rate}%)
   • Bounced: {total - answered} ({100 - activation_rate:.1f}%)

3️⃣ <b>Использование AI</b>
   • Попробовали AI: {used_ai} ({ai_usage_rate}%)
   • Не попробовали: {total - used_ai} ({100 - ai_usage_rate:.1f}%)

4️⃣ <b>Конверсия в платящих</b>
   • Подписчики: {subscribers} ({paid_conversion}%)
   • Не платят: {total - subscribers} ({100 - paid_conversion:.1f}%)

💡 <b>Ключевые метрики:</b>
• Drop-off после регистрации: {100 - activation_rate:.1f}%
• AI adoption rate: {(used_ai / answered * 100) if answered > 0 else 0:.1f}%
• Conversion to paid: {paid_conversion}%
"""

        await update.message.reply_text(text, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error in funnel_stats_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cohort_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает когортную статистику."""
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    try:
        # Получаем когортную статистику
        cohorts = await db.get_cohort_stats(weeks=8)

        if not cohorts:
            await update.message.reply_text("❌ Нет данных по когортам")
            return

        # Форматируем отчет
        text = "📊 <b>КОГОРТНЫЙ АНАЛИЗ</b>\n\n"
        text += "По неделям регистрации:\n\n"

        for cohort in cohorts:
            week = cohort['cohort_week']
            users = cohort['users']
            answered = cohort['answered_questions']
            paying = cohort['paying_now']
            activation = cohort['activation_rate']
            conversion = cohort['conversion_rate']

            text += f"<b>{week}</b>: {users} юзеров\n"
            text += f"  • Активация: {answered} ({activation}%)\n"
            text += f"  • Платят: {paying} ({conversion}%)\n\n"

        text += "\n💡 <b>Insights:</b>\n"

        # Анализ трендов
        if len(cohorts) >= 2:
            latest = cohorts[0]
            previous = cohorts[1]

            latest_act = latest['activation_rate']
            prev_act = previous['activation_rate']

            if latest_act > prev_act:
                text += f"✅ Активация улучшилась: {latest_act}% vs {prev_act}%\n"
            elif latest_act < prev_act:
                text += f"⚠️ Активация снизилась: {latest_act}% vs {prev_act}%\n"

        await update.message.reply_text(text, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error in cohort_stats_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def onboarding_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику onboarding."""
    user_id = update.effective_user.id

    # Проверка админских прав
    if user_id not in config.ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа")
        return

    try:
        conn = await db.get_db()

        # Проверяем наличие полей onboarding
        has_onboarding = await db.check_column_exists(conn, 'users', 'onboarding_completed')

        if not has_onboarding:
            await update.message.reply_text("❌ Onboarding не настроен (нет полей в БД)")
            return

        # Статистика onboarding
        cursor = await conn.execute("""
            SELECT
                COUNT(*) as total_users,
                SUM(CASE WHEN onboarding_completed = 1 THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN onboarding_skipped = 1 THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN onboarding_completed = 0 AND onboarding_skipped = 0 THEN 1 ELSE 0 END) as not_started
            FROM users
            WHERE first_seen >= date('now', '-30 days')
        """)

        row = await cursor.fetchone()

        if not row:
            await update.message.reply_text("❌ Нет данных")
            return

        total = row[0]
        completed = row[1]
        skipped = row[2]
        not_started = row[3]

        completion_rate = (completed / total * 100) if total > 0 else 0
        skip_rate = (skipped / total * 100) if total > 0 else 0

        text = f"""📊 <b>ONBOARDING СТАТИСТИКА</b>
(за последние 30 дней)

👥 <b>Всего пользователей:</b> {total}

✅ <b>Завершили onboarding:</b> {completed} ({completion_rate:.1f}%)
⏭️ <b>Пропустили:</b> {skipped} ({skip_rate:.1f}%)
❓ <b>Не начали:</b> {not_started} ({(not_started / total * 100) if total > 0 else 0:.1f}%)

💡 <b>Ключевые метрики:</b>
• Completion rate: {completion_rate:.1f}%
• Skip rate: {skip_rate:.1f}%
• Not started rate: {(not_started / total * 100) if total > 0 else 0:.1f}%

🎯 <b>Цель:</b> 70%+ completion rate
"""

        # Добавляем анализ событий воронки
        cursor = await conn.execute("""
            SELECT
                event_type,
                COUNT(*) as count
            FROM funnel_events
            WHERE created_at >= datetime('now', '-30 days')
            GROUP BY event_type
            ORDER BY count DESC
        """)

        events = await cursor.fetchall()

        if events:
            text += "\n📈 <b>События воронки:</b>\n"
            for event in events:
                event_type = event[0]
                count = event[1]
                text += f"  • {event_type}: {count}\n"

        await update.message.reply_text(text, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error in onboarding_stats_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


def register_funnel_admin_handlers(application):
    """Регистрирует админские команды для анализа воронки."""
    application.add_handler(CommandHandler("funnel", funnel_stats_command))
    application.add_handler(CommandHandler("cohorts", cohort_stats_command))
    application.add_handler(CommandHandler("onboarding_stats", onboarding_stats_command))
    logger.info("Funnel admin handlers registered")
