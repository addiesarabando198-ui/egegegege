"""
Система XP и лидерборд для модуля карточек.

Очки (XP) начисляются за:
- Повторение карточки: +1 XP (правильный ответ), +0.5 XP (неправильный)
- Quiz верный ответ: +2 XP
- Ежедневный челлендж: +5 XP за прохождение + бонус за результат
- Конструктор планов: +2 XP за верный ответ
- Стрик-бонус: множитель x1.5 при стрике ≥7 дней

Лидерборд кешируется и пересчитывается при каждом запросе (данные актуальны).
"""

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.db import DATABASE_FILE
from core.error_handler import safe_handler
from core.utils import safe_edit_message
from core.streak_manager import get_streak_manager

logger = logging.getLogger(__name__)

# Награды XP
XP_CARD_CORRECT = 1
XP_CARD_WRONG = 0.5
XP_QUIZ_CORRECT = 2
XP_QUIZ_WRONG = 0
XP_DAILY_COMPLETE = 5
XP_DAILY_BONUS_PER_CORRECT = 1
XP_PLAN_CORRECT = 2
XP_PLAN_WRONG = 0

STREAK_BONUS_THRESHOLD = 7
STREAK_BONUS_MULTIPLIER = 1.5


# ============================================================
# DATABASE
# ============================================================

async def ensure_leaderboard_tables() -> None:
    """Создаёт таблицы для XP и лидерборда."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS flashcard_xp (
                user_id INTEGER NOT NULL,
                total_xp REAL DEFAULT 0,
                weekly_xp REAL DEFAULT 0,
                week_start DATE,
                cards_reviewed INTEGER DEFAULT 0,
                quizzes_completed INTEGER DEFAULT 0,
                challenges_completed INTEGER DEFAULT 0,
                plans_completed INTEGER DEFAULT 0,
                last_updated TEXT,
                PRIMARY KEY (user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS flashcard_xp_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                xp_amount REAL NOT NULL,
                source TEXT NOT NULL,
                details TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_xp_log_user
            ON flashcard_xp_log(user_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_xp_total
            ON flashcard_xp(total_xp DESC)
        """)
        await db.commit()
    logger.info("Leaderboard tables ensured")


async def add_xp(
    user_id: int,
    xp_amount: float,
    source: str,
    details: str = "",
    apply_streak_bonus: bool = True,
) -> float:
    """
    Начисляет XP пользователю.

    Args:
        user_id: ID пользователя
        xp_amount: Базовое кол-во XP
        source: Источник (card_review, quiz, daily, plan)
        details: Доп. информация
        apply_streak_bonus: Применить стрик-бонус

    Returns:
        Фактическое количество начисленных XP (с учётом бонуса)
    """
    if xp_amount <= 0:
        return 0.0

    # Стрик-бонус
    actual_xp = xp_amount
    if apply_streak_bonus:
        try:
            streak_manager = get_streak_manager()
            streak_info = await streak_manager.get_daily_streak_info(user_id)
            if streak_info and streak_info.get('current', 0) >= STREAK_BONUS_THRESHOLD:
                actual_xp = xp_amount * STREAK_BONUS_MULTIPLIER
        except Exception:
            pass  # Не критично

    now = datetime.now(timezone.utc).isoformat()
    today = date.today()
    # Начало текущей недели (понедельник)
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Обновляем или создаём запись XP
        await db.execute("""
            INSERT INTO flashcard_xp (user_id, total_xp, weekly_xp, week_start, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_xp = total_xp + ?,
                weekly_xp = CASE
                    WHEN week_start = ? THEN weekly_xp + ?
                    ELSE ?
                END,
                week_start = ?,
                last_updated = ?
        """, (
            user_id, actual_xp, actual_xp, week_start, now,
            actual_xp,
            week_start, actual_xp,
            actual_xp,
            week_start, now,
        ))

        # Обновляем счётчики
        counter_field = {
            'card_review': 'cards_reviewed',
            'quiz': 'quizzes_completed',
            'daily': 'challenges_completed',
            'plan': 'plans_completed',
        }.get(source)

        if counter_field:
            await db.execute(f"""
                UPDATE flashcard_xp SET {counter_field} = {counter_field} + 1
                WHERE user_id = ?
            """, (user_id,))

        # Логируем
        await db.execute("""
            INSERT INTO flashcard_xp_log (user_id, xp_amount, source, details)
            VALUES (?, ?, ?, ?)
        """, (user_id, actual_xp, source, details))

        await db.commit()

    return actual_xp


async def get_user_xp(user_id: int) -> Dict[str, Any]:
    """Возвращает XP-статистику пользователя."""
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM flashcard_xp WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()

    if not row:
        return {
            'total_xp': 0,
            'weekly_xp': 0,
            'cards_reviewed': 0,
            'quizzes_completed': 0,
            'challenges_completed': 0,
            'plans_completed': 0,
        }

    data = dict(row)
    # Сбрасываем weekly_xp если неделя сменилась
    if data.get('week_start') != week_start:
        data['weekly_xp'] = 0

    return data


async def get_leaderboard(
    period: str = "all",
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Возвращает топ пользователей.

    Args:
        period: "all" (всё время) или "week" (текущая неделя)
        limit: Количество позиций

    Returns:
        Список {user_id, xp, rank, username, first_name}
    """
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    if period == "week":
        xp_field = "weekly_xp"
        where_clause = "AND fx.week_start = ?"
        params = (week_start, limit)
    else:
        xp_field = "total_xp"
        where_clause = ""
        params = (limit,)

    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        query = f"""
            SELECT fx.user_id, fx.{xp_field} as xp,
                   fx.cards_reviewed, fx.quizzes_completed,
                   fx.challenges_completed, fx.plans_completed,
                   u.username, u.first_name
            FROM flashcard_xp fx
            LEFT JOIN users u ON fx.user_id = u.user_id
            WHERE fx.{xp_field} > 0 {where_clause}
            ORDER BY fx.{xp_field} DESC
            LIMIT ?
        """
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    result = []
    for i, row in enumerate(rows):
        data = dict(row)
        data['rank'] = i + 1
        result.append(data)

    return result


async def get_user_rank(user_id: int, period: str = "all") -> Dict[str, Any]:
    """Возвращает позицию пользователя в рейтинге."""
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    if period == "week":
        xp_field = "weekly_xp"
        where_clause = "AND week_start = ?"
        where_params = [week_start]
    else:
        xp_field = "total_xp"
        where_clause = ""
        where_params = []

    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Получаем XP пользователя
        cursor = await db.execute(
            f"SELECT {xp_field} as xp FROM flashcard_xp WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        user_xp = row[0] if row else 0

        # Считаем позицию
        cursor = await db.execute(f"""
            SELECT COUNT(*) FROM flashcard_xp
            WHERE {xp_field} > ? {where_clause}
        """, (user_xp, *where_params))
        row = await cursor.fetchone()
        rank = row[0] + 1 if row else 1

        # Общее кол-во участников
        cursor = await db.execute(f"""
            SELECT COUNT(*) FROM flashcard_xp
            WHERE {xp_field} > 0 {where_clause}
        """, tuple(where_params))
        row = await cursor.fetchone()
        total_users = row[0] if row else 0

    return {
        'rank': rank,
        'xp': user_xp,
        'total_users': total_users,
    }


# ============================================================
# XP УРОВНИ
# ============================================================

XP_LEVELS = [
    (0, "Новичок", "🌱"),
    (50, "Ученик", "📚"),
    (150, "Практикант", "🎯"),
    (400, "Знаток", "⭐"),
    (1000, "Эксперт", "💎"),
    (2500, "Мастер", "🏆"),
    (5000, "Легенда", "👑"),
]


def get_xp_level(total_xp: float) -> Dict[str, Any]:
    """Определяет уровень по XP."""
    current_level = XP_LEVELS[0]
    next_level = XP_LEVELS[1] if len(XP_LEVELS) > 1 else None

    for i, (threshold, name, icon) in enumerate(XP_LEVELS):
        if total_xp >= threshold:
            current_level = (threshold, name, icon)
            if i + 1 < len(XP_LEVELS):
                next_level = XP_LEVELS[i + 1]
            else:
                next_level = None

    return {
        'name': current_level[1],
        'icon': current_level[2],
        'threshold': current_level[0],
        'next_level': next_level,
    }


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

@safe_handler()
async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает экран лидерборда."""
    query = update.callback_query
    user_id = query.from_user.id

    # По умолчанию — общий рейтинг
    period = context.user_data.get('fc_lb_period', 'all')

    top = await get_leaderboard(period=period, limit=10)
    user_rank = await get_user_rank(user_id, period=period)
    user_xp_data = await get_user_xp(user_id)
    level = get_xp_level(user_xp_data.get('total_xp', 0))

    period_label = "🌍 Общий рейтинг" if period == "all" else "📅 Рейтинг недели"

    text = f"<b>🏅 Лидерборд — {period_label}</b>\n\n"

    if not top:
        text += "<i>Пока нет участников. Будьте первым!</i>\n\n"
    else:
        medals = ["🥇", "🥈", "🥉"]
        for entry in top:
            rank = entry['rank']
            medal = medals[rank - 1] if rank <= 3 else f"  {rank}."
            name = entry.get('first_name') or entry.get('username') or f"User {entry['user_id']}"
            xp = int(entry['xp'])

            # Подсвечиваем текущего пользователя
            if entry['user_id'] == user_id:
                text += f"<b>{medal} {name} — {xp} XP ← вы</b>\n"
            else:
                text += f"{medal} {name} — {xp} XP\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━\n\n"

    # Статистика текущего пользователя
    total_xp = int(user_xp_data.get('total_xp', 0))
    text += f"{level['icon']} <b>Ваш уровень: {level['name']}</b>\n"
    text += f"💰 XP: <b>{total_xp}</b>"

    if level['next_level']:
        needed = level['next_level'][0] - total_xp
        text += f"  (до «{level['next_level'][1]}»: {needed} XP)\n"
    else:
        text += " (максимальный уровень!)\n"

    text += f"📊 Позиция: <b>#{user_rank['rank']}</b>"
    if user_rank['total_users'] > 0:
        text += f" из {user_rank['total_users']}"
    text += "\n"

    # Детализация
    text += f"\n📈 <b>Активность:</b>\n"
    text += f"  🃏 Карточек повторено: {user_xp_data.get('cards_reviewed', 0)}\n"
    text += f"  🧩 Quiz пройдено: {user_xp_data.get('quizzes_completed', 0)}\n"
    text += f"  🏆 Челленджей: {user_xp_data.get('challenges_completed', 0)}\n"
    text += f"  📝 Планов: {user_xp_data.get('plans_completed', 0)}\n"

    # Кнопки
    keyboard = []

    if period == "all":
        keyboard.append([InlineKeyboardButton(
            "📅 Рейтинг недели", callback_data="fc_lb_week"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            "🌍 Общий рейтинг", callback_data="fc_lb_all"
        )])

    keyboard.append([InlineKeyboardButton(
        "◀️ Назад к карточкам", callback_data="fc_back_to_decks"
    )])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    from core import states
    return states.FC_MENU


@safe_handler()
async def switch_leaderboard_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает период лидерборда (общий / неделя)."""
    query = update.callback_query
    period = "week" if query.data == "fc_lb_week" else "all"
    context.user_data['fc_lb_period'] = period
    return await show_leaderboard(update, context)
