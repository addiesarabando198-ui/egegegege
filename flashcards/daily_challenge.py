"""
Ежедневный челлендж — мини-квиз на 5 вопросов,
объединяющий разные форматы и материалы.

Состав:
- 2 вопроса по Конституции (True/False или Multiple Choice)
- 2 вопроса по глоссарию (термин → определение)
- 1 вопрос «Собери пункт плана»

Один челлендж в день. Завершение засчитывается в daily streak.
"""

import logging
import random
import json
import os
from datetime import date, datetime, timezone
from typing import Dict, Any, List, Optional

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import states
from core.db import DATABASE_FILE
from core.error_handler import safe_handler
from core.utils import safe_edit_message
from core.streak_manager import get_streak_manager

from . import db as flashcard_db
from .quiz_handlers import (
    generate_true_false,
    generate_multiple_choice,
    _truncate,
)
from .leaderboard import add_xp, XP_DAILY_COMPLETE, XP_DAILY_BONUS_PER_CORRECT

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

CHALLENGE_SIZE = 5


# ============================================================
# DATABASE
# ============================================================

async def ensure_challenge_table() -> None:
    """Создаёт таблицу для хранения результатов челленджей."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_challenges (
                user_id INTEGER NOT NULL,
                challenge_date DATE NOT NULL,
                score INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                completed_at TEXT,
                PRIMARY KEY (user_id, challenge_date)
            )
        """)
        await db.commit()


async def get_today_challenge(user_id: int) -> Optional[Dict]:
    """Проверяет, проходил ли пользователь сегодняшний челлендж."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM daily_challenges WHERE user_id = ? AND challenge_date = ?",
            (user_id, today)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def save_challenge_result(user_id: int, score: int, total: int) -> None:
    """Сохраняет результат ежедневного челленджа."""
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            INSERT INTO daily_challenges (user_id, challenge_date, score, total, completed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, challenge_date) DO UPDATE SET
                score = excluded.score,
                total = excluded.total,
                completed_at = excluded.completed_at
        """, (user_id, today, score, total, now))
        await db.commit()


async def get_challenge_streak(user_id: int) -> int:
    """Считает серию дней подряд с пройденными челленджами."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("""
            SELECT challenge_date FROM daily_challenges
            WHERE user_id = ? AND completed_at IS NOT NULL
            ORDER BY challenge_date DESC
            LIMIT 60
        """, (user_id,))
        rows = await cursor.fetchall()

    if not rows:
        return 0

    streak = 0
    expected = date.today()

    for row in rows:
        d = date.fromisoformat(row[0])
        if d == expected:
            streak += 1
            expected = date.fromordinal(expected.toordinal() - 1)
        elif d < expected:
            break

    return streak


# ============================================================
# ГЕНЕРАЦИЯ ЧЕЛЛЕНДЖА
# ============================================================

def _load_plans_data() -> Dict:
    """Загружает данные планов."""
    path = os.path.join(BASE_DIR, 'data', 'plans_data_with_blocks.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def generate_plan_question(plans_data: Dict) -> Optional[Dict[str, Any]]:
    """
    Генерирует вопрос «Назовите ключевые пункты плана».

    Показывает тему → пользователь должен вспомнить основные пункты.
    Для удобства в Telegram используем формат Multiple Choice:
    показываем 4 пункта, один из которых НЕ относится к данной теме.
    """
    plans = plans_data.get('plans', {})
    if not plans:
        return None

    # Выбираем случайную тему с достаточным количеством пунктов
    viable_topics = [
        (name, data) for name, data in plans.items()
        if len(data.get('points_data', [])) >= 3
    ]

    if len(viable_topics) < 2:
        return None

    topic_name, topic_data = random.choice(viable_topics)
    points = topic_data.get('points_data', [])

    # Выбираем ключевой пункт из этой темы
    key_points = [p for p in points if p.get('is_potentially_key')]
    if not key_points:
        key_points = points

    correct_point = random.choice(key_points)
    correct_text = correct_point['point_text']

    # Берём 3 пункта из ДРУГИХ тем как дистракторы
    other_topics = [
        (n, d) for n, d in viable_topics
        if n != topic_name
    ]

    distractor_points = []
    random.shuffle(other_topics)
    for _, other_data in other_topics:
        other_pts = other_data.get('points_data', [])
        if other_pts:
            distractor_points.append(random.choice(other_pts)['point_text'])
        if len(distractor_points) >= 3:
            break

    if len(distractor_points) < 3:
        return None

    # Формируем варианты
    labels = ['А', 'Б', 'В', 'Г']
    options_raw = [correct_text] + distractor_points[:3]
    random.shuffle(options_raw)

    correct_index = options_raw.index(correct_text)

    options = []
    for i, opt_text in enumerate(options_raw):
        options.append({
            'label': labels[i],
            'text': _truncate(opt_text, 120),
            'is_correct': i == correct_index,
        })

    return {
        'type': 'plan_question',
        'question': f"Какой пункт относится к плану\n\n«{topic_name}»?",
        'options': options,
        'correct_index': correct_index,
        'correct_label': labels[correct_index],
        'explanation': f"Пункт плана: {correct_text}",
        'topic_name': topic_name,
    }


async def generate_daily_questions() -> List[Dict[str, Any]]:
    """Генерирует набор вопросов для ежедневного челленджа."""
    questions = []

    # 1-2) Конституция (True/False или MC)
    constitution_cards = await flashcard_db.get_cards_for_deck("constitution_rf")
    if len(constitution_cards) >= 4:
        q1 = generate_true_false(constitution_cards)
        if q1:
            questions.append(q1)
        q2 = generate_multiple_choice(constitution_cards)
        if q2:
            questions.append(q2)

    # 3-4) Глоссарий (из случайной категории)
    glossary_decks = ["glossary_economy", "glossary_philosophy", "glossary_law", "glossary_politics"]
    random.shuffle(glossary_decks)

    for deck_id in glossary_decks:
        if len(questions) >= 4:
            break
        cards = await flashcard_db.get_cards_for_deck(deck_id)
        if len(cards) >= 4:
            q = generate_multiple_choice(cards)
            if q:
                questions.append(q)

    # 5) Вопрос по планам
    plans_data = _load_plans_data()
    plan_q = generate_plan_question(plans_data)
    if plan_q:
        questions.append(plan_q)

    # Добиваем до 5 если не хватает
    all_decks = glossary_decks + ["constitution_rf"]
    while len(questions) < CHALLENGE_SIZE:
        deck_id = random.choice(all_decks)
        cards = await flashcard_db.get_cards_for_deck(deck_id)
        if len(cards) >= 4:
            q = generate_true_false(cards)
            if q:
                questions.append(q)
        if len(questions) >= CHALLENGE_SIZE:
            break

    random.shuffle(questions)
    return questions[:CHALLENGE_SIZE]


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

@safe_handler()
async def show_daily_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает экран ежедневного челленджа."""
    query = update.callback_query
    user_id = query.from_user.id

    existing = await get_today_challenge(user_id)
    streak = await get_challenge_streak(user_id)

    text = "<b>🏆 Ежедневный челлендж</b>\n\n"
    text += f"5 вопросов из разных разделов ЕГЭ.\n"
    text += f"Проходите каждый день для поддержания серии!\n\n"

    if streak > 0:
        text += f"🔥 Ваша серия: <b>{streak}</b> "
        text += f"{'день' if streak % 10 == 1 and streak != 11 else 'дней'} подряд\n\n"

    keyboard = []

    if existing and existing.get('completed_at'):
        score = existing['score']
        total = existing['total']
        pct = round(score / total * 100) if total > 0 else 0
        text += f"✅ Сегодняшний челлендж пройден!\n"
        text += f"Результат: <b>{score}/{total}</b> ({pct}%)\n\n"
        text += "Возвращайтесь завтра за новым челленджем!"

        keyboard.append([InlineKeyboardButton(
            "🔄 Пройти заново", callback_data="fc_daily_start"
        )])
    else:
        text += "📋 Сегодняшний челлендж доступен!"
        keyboard.append([InlineKeyboardButton(
            "🚀 Начать челлендж", callback_data="fc_daily_start"
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

    return states.FC_DAILY


@safe_handler()
async def start_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает ежедневный челлендж."""
    query = update.callback_query
    user_id = query.from_user.id

    questions = await generate_daily_questions()

    if not questions:
        await query.answer("Не удалось сгенерировать челлендж", show_alert=True)
        return states.FC_DAILY

    context.user_data['fc_daily'] = {
        'questions': questions,
        'current': 0,
        'total': len(questions),
        'correct': 0,
        'wrong': 0,
    }

    await _show_daily_question(query, context)
    return states.FC_DAILY


async def _show_daily_question(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает текущий вопрос челленджа."""
    daily = context.user_data.get('fc_daily', {})
    questions = daily.get('questions', [])
    idx = daily.get('current', 0)

    if idx >= len(questions):
        return

    q = questions[idx]
    total = daily['total']

    # Прогресс-бар
    filled = "🟢" * daily['correct'] + "🔴" * daily['wrong']
    remaining = "⚪" * (total - idx)
    progress = filled + remaining

    text = f"<b>🏆 Челлендж {idx + 1}/{total}</b>\n"
    text += f"{progress}\n\n"

    if q['type'] == 'true_false':
        text += "<b>Верно или неверно?</b>\n\n"
        text += f"{q['question']}\n"
        keyboard = [
            [
                InlineKeyboardButton("✅ Верно", callback_data="fc_daily_tf_true"),
                InlineKeyboardButton("❌ Неверно", callback_data="fc_daily_tf_false"),
            ],
        ]

    elif q['type'] in ('multiple_choice', 'plan_question'):
        text += f"{q['question']}\n\n"
        for opt in q['options']:
            text += f"<b>{opt['label']}.</b> {opt['text']}\n\n"
        keyboard = []
        row = []
        for i, opt in enumerate(q['options']):
            row.append(InlineKeyboardButton(
                opt['label'],
                callback_data=f"fc_daily_mc_{i}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def handle_daily_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа True/False в челлендже."""
    query = update.callback_query
    user_answer = query.data == "fc_daily_tf_true"

    daily = context.user_data.get('fc_daily', {})
    questions = daily.get('questions', [])
    idx = daily.get('current', 0)

    if idx >= len(questions):
        return states.FC_DAILY

    q = questions[idx]
    is_correct = user_answer == q.get('correct_answer', False)

    await _process_daily_answer(query, context, is_correct, q)
    return states.FC_DAILY


@safe_handler()
async def handle_daily_mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа Multiple Choice в челлендже."""
    query = update.callback_query
    chosen_idx = int(query.data.replace("fc_daily_mc_", ""))

    daily = context.user_data.get('fc_daily', {})
    questions = daily.get('questions', [])
    idx = daily.get('current', 0)

    if idx >= len(questions):
        return states.FC_DAILY

    q = questions[idx]
    is_correct = chosen_idx == q.get('correct_index', -1)

    await _process_daily_answer(query, context, is_correct, q)
    return states.FC_DAILY


async def _process_daily_answer(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    is_correct: bool,
    question: Dict,
) -> None:
    """Обрабатывает ответ и показывает фидбек / следующий вопрос."""
    daily = context.user_data.get('fc_daily', {})

    if is_correct:
        daily['correct'] += 1
    else:
        daily['wrong'] += 1

    idx = daily['current']
    daily['current'] = idx + 1

    # Краткий фидбек через alert
    if is_correct:
        feedback = "✅ Верно!"
    else:
        # Показываем правильный ответ
        if question['type'] == 'true_false':
            correct_str = "Верно" if question.get('correct_answer') else "Неверно"
            feedback = f"❌ Неверно! Ответ: {correct_str}"
        else:
            feedback = f"❌ Неверно! Ответ: {question.get('correct_label', '?')}"

    await query.answer(feedback, show_alert=False)

    # Следующий вопрос или результаты
    if daily['current'] >= len(daily['questions']):
        await _show_daily_results(query, context)
    else:
        await _show_daily_question(query, context)


async def _show_daily_results(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает результаты челленджа."""
    daily = context.user_data.get('fc_daily', {})
    user_id = query.from_user.id

    correct = daily.get('correct', 0)
    total = daily.get('total', 0)
    pct = round(correct / total * 100) if total > 0 else 0

    # Сохраняем результат
    await save_challenge_result(user_id, correct, total)

    # Обновляем стрик
    streak_manager = get_streak_manager()
    current_date = date.today().isoformat()
    last_activity = context.user_data.get('last_activity_date')

    if last_activity != current_date:
        await streak_manager.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date

    await streak_manager.update_correct_streak(user_id, pct >= 60)

    # Начисляем XP
    xp_earned = XP_DAILY_COMPLETE + correct * XP_DAILY_BONUS_PER_CORRECT
    await add_xp(user_id, xp_earned, 'daily', f'challenge_{date.today().isoformat()}')

    challenge_streak = await get_challenge_streak(user_id)

    text = "<b>🏆 Челлендж завершён!</b>\n\n"

    # Результат
    stars = "⭐" * correct + "☆" * (total - correct)
    text += f"{stars}\n\n"
    text += f"Результат: <b>{correct}/{total}</b> ({pct}%)\n\n"

    if pct == 100:
        text += "🏅 Идеальный результат! Вы великолепны!"
    elif pct >= 80:
        text += "🌟 Отлично! Почти безупречно!"
    elif pct >= 60:
        text += "👍 Хорошая работа! Продолжайте практиковать."
    else:
        text += "💪 Не сдавайтесь! Повторите материал в карточках."

    if challenge_streak > 1:
        text += f"\n\n🔥 Серия челленджей: <b>{challenge_streak}</b> дней подряд!"

    keyboard = [
        [InlineKeyboardButton("📋 К карточкам", callback_data="fc_back_to_decks")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
