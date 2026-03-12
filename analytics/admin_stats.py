"""
Админские обработчики для статистики по источникам трафика и рекламным кампаниям.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from core.admin_tools import admin_only
from analytics.utm_tracker import get_campaign_stats
import aiosqlite
from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)


@admin_only
async def traffic_sources_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Статистика по источникам трафика (UTM-метки).
    """
    query = update.callback_query
    try:
        await query.answer("Загрузка статистики по источникам...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    text = "📊 <b>Источники трафика (30 дней)</b>\n\n"

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Статистика по источникам
            cursor = await db.execute("""
                SELECT
                    us.source,
                    us.medium,
                    COUNT(DISTINCT us.user_id) as total_users,
                    COUNT(DISTINCT CASE
                        WHEN c.conversion_type = 'trial_purchase' THEN c.user_id
                    END) as trial_conversions,
                    COUNT(DISTINCT CASE
                        WHEN c.conversion_type = 'subscription_purchase' THEN c.user_id
                    END) as paid_conversions,
                    COALESCE(SUM(CASE
                        WHEN c.conversion_type = 'subscription_purchase' THEN c.value_rub
                        ELSE 0
                    END), 0) as total_revenue
                FROM user_sources us
                LEFT JOIN conversions c ON us.user_id = c.user_id
                WHERE us.created_at >= datetime('now', '-30 days')
                GROUP BY us.source, us.medium
                ORDER BY total_users DESC
                LIMIT 10
            """)

            rows = await cursor.fetchall()

            if rows:
                text += "<b>Топ-10 источников:</b>\n\n"

                for row in rows:
                    source = row['source'] or 'direct'
                    medium = row['medium'] or '-'
                    users = row['total_users']
                    trial_conv = row['trial_conversions']
                    paid_conv = row['paid_conversions']
                    revenue = row['total_revenue']

                    trial_cr = (trial_conv / users * 100) if users > 0 else 0
                    paid_cr = (paid_conv / users * 100) if users > 0 else 0

                    text += f"<b>{source} / {medium}</b>\n"
                    text += f"  • Пользователей: {users}\n"
                    text += f"  • Trial: {trial_conv} ({trial_cr:.1f}%)\n"
                    text += f"  • Платящих: {paid_conv} ({paid_cr:.1f}%)\n"
                    text += f"  • Доход: {revenue:.0f}₽\n\n"
            else:
                text += "Данных пока нет.\n\n"
                text += "<i>💡 UTM-метки появятся, когда пользователи начнут приходить по рекламным ссылкам.</i>"

    except Exception as e:
        logger.error(f"Error getting traffic sources stats: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 По кампаниям", callback_data="admin:campaign_stats"),
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:traffic_sources")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def campaign_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Детальная статистика по рекламным кампаниям.
    """
    query = update.callback_query
    try:
        await query.answer("Загрузка статистики по кампаниям...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    text = "📈 <b>Рекламные кампании (30 дней)</b>\n\n"

    try:
        stats = await get_campaign_stats(days=30)

        if stats['campaigns']:
            text += "<b>Эффективность кампаний:</b>\n\n"

            for camp in stats['campaigns']:
                campaign = camp['campaign'] or 'без имени'
                source = camp['source'] or 'unknown'
                users = camp['total_users']
                trial_conv = camp['trial_conversions']
                paid_conv = camp['paid_conversions']
                trial_cr = camp['trial_cr']
                paid_cr = camp['paid_cr']
                revenue = camp['total_revenue']

                # ROI можно рассчитать если известен бюджет
                text += f"<b>📱 {campaign}</b> ({source})\n"
                text += f"  • Пользователей: {users}\n"
                text += f"  • Trial CR: {trial_cr}% ({trial_conv} шт)\n"
                text += f"  • Paid CR: {paid_cr}% ({paid_conv} шт)\n"
                text += f"  • Выручка: {revenue:.0f}₽\n"

                # Средний чек
                if paid_conv > 0:
                    avg_check = revenue / paid_conv
                    text += f"  • Средний чек: {avg_check:.0f}₽\n"

                text += "\n"
        else:
            text += "Кампаний пока нет.\n\n"
            text += "<i>💡 Создайте ссылки с UTM-метками для отслеживания эффективности рекламы.</i>\n\n"
            text += "<b>Пример ссылки для Яндекс.Директ:</b>\n"
            text += "<code>https://t.me/your_bot?start=source-yandex_medium-cpc_campaign-ege2025_yclid-{yclid}</code>"

    except Exception as e:
        logger.error(f"Error getting campaign stats: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 По источникам", callback_data="admin:traffic_sources"),
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:campaign_stats")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def cohort_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Когортный анализ пользователей по источникам.
    Показывает retention по неделям для разных источников.
    """
    query = update.callback_query
    try:
        await query.answer("Загрузка когортного анализа...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    text = "📊 <b>Когортный анализ (Retention)</b>\n\n"

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Cohort анализ: retention Day 1, 7, 30 по источникам
            cursor = await db.execute("""
                WITH user_activity AS (
                    SELECT
                        u.user_id,
                        us.source,
                        us.created_at as registration_date,
                        MAX(CASE
                            WHEN julianday(u.last_activity_date) - julianday(us.created_at) >= 1
                            THEN 1 ELSE 0
                        END) as active_day1,
                        MAX(CASE
                            WHEN julianday(u.last_activity_date) - julianday(us.created_at) >= 7
                            THEN 1 ELSE 0
                        END) as active_day7,
                        MAX(CASE
                            WHEN julianday(u.last_activity_date) - julianday(us.created_at) >= 30
                            THEN 1 ELSE 0
                        END) as active_day30
                    FROM users u
                    LEFT JOIN user_sources us ON u.user_id = us.user_id
                    WHERE us.created_at >= datetime('now', '-60 days')
                    GROUP BY u.user_id, us.source, us.created_at
                )
                SELECT
                    source,
                    COUNT(*) as total_users,
                    SUM(active_day1) as retained_day1,
                    SUM(active_day7) as retained_day7,
                    SUM(active_day30) as retained_day30
                FROM user_activity
                WHERE source IS NOT NULL
                GROUP BY source
                ORDER BY total_users DESC
                LIMIT 5
            """)

            rows = await cursor.fetchall()

            if rows:
                text += "<b>Retention по источникам (60 дней):</b>\n\n"

                for row in rows:
                    source = row['source'] or 'direct'
                    total = row['total_users']
                    day1 = row['retained_day1']
                    day7 = row['retained_day7']
                    day30 = row['retained_day30']

                    r_day1 = (day1 / total * 100) if total > 0 else 0
                    r_day7 = (day7 / total * 100) if total > 0 else 0
                    r_day30 = (day30 / total * 100) if total > 0 else 0

                    text += f"<b>{source}</b> ({total} польз.)\n"
                    text += f"  • Day 1: {r_day1:.0f}% ({day1} активных)\n"
                    text += f"  • Day 7: {r_day7:.0f}% ({day7} активных)\n"
                    text += f"  • Day 30: {r_day30:.0f}% ({day30} активных)\n\n"
            else:
                text += "Данных для анализа пока недостаточно."

    except Exception as e:
        logger.error(f"Error in cohort analysis: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:cohort_analysis"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def ab_test_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Статистика A/B тестов онбординга.
    Показывает эффективность разных вариантов онбординга.
    """
    query = update.callback_query
    try:
        await query.answer("Загрузка A/B тестов...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    text = "🧪 <b>A/B тесты онбординга</b>\n\n"

    try:
        from analytics.ab_testing import get_test_stats, get_winning_variant

        stats = await get_test_stats('onboarding_flow', days=30)

        if stats['variants']:
            text += "<b>Варианты онбординга (30 дней):</b>\n\n"

            # Описание вариантов
            variant_names = {
                'control': '🅰️ Контроль (AI-демо → вопрос → trial)',
                'no_question': '🅱️ Без вопроса (AI-демо → сразу trial)',
                'instant_value': '🅲 Мгновенная ценность (вопрос → AI-демо → trial)'
            }

            for var in stats['variants']:
                variant_key = var['variant']
                variant_name = variant_names.get(variant_key, f"Вариант {variant_key}")

                users = var['total_users']
                trial_conv = var['trial_conversions']
                paid_conv = var['paid_conversions']
                trial_cr = var['trial_cr']
                paid_cr = var['paid_cr']
                revenue = var['revenue']

                text += f"<b>{variant_name}</b>\n"
                text += f"  • Пользователей: {users}\n"
                text += f"  • Trial CR: {trial_cr}% ({trial_conv} шт)\n"
                text += f"  • Paid CR: {paid_cr}% ({paid_conv} шт)\n"
                text += f"  • Выручка: {revenue:.0f}₽\n"

                if users > 0:
                    # Средний чек
                    if paid_conv > 0:
                        avg_check = revenue / paid_conv
                        text += f"  • Средний чек: {avg_check:.0f}₽\n"

                text += "\n"

            # Определяем победителя
            winner_trial = await get_winning_variant('onboarding_flow', 'trial_cr')
            winner_paid = await get_winning_variant('onboarding_flow', 'paid_cr')

            text += "<b>🏆 Лучшие варианты:</b>\n"
            text += f"  • По Trial CR: {variant_names.get(winner_trial, winner_trial)}\n"
            text += f"  • По Paid CR: {variant_names.get(winner_paid, winner_paid)}\n\n"

            text += "<i>💡 Используй данные для выбора лучшего варианта онбординга</i>"

        else:
            text += "Данных пока нет.\n\n"
            text += "<i>💡 A/B тесты автоматически запускаются для новых пользователей.</i>\n\n"
            text += "<b>Варианты:</b>\n"
            text += "  • <b>Контроль:</b> AI-демо → вопрос → trial\n"
            text += "  • <b>Без вопроса:</b> AI-демо → сразу trial\n"
            text += "  • <b>Мгновенная ценность:</b> вопрос → AI-демо → trial"

    except Exception as e:
        logger.error(f"Error getting A/B test stats: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:ab_test_stats"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
