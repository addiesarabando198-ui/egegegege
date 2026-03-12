"""
Конструктор планов — интерактивный тренажёр для задания 24.

Режимы:
1. «Назови пункты» — показывает тему, нужно вспомнить ключевые пункты
2. «Допиши подпункты» — показан пункт, нужно выбрать его подпункты
3. «Что лишнее?» — 4 пункта, один не относится к теме

Данные берутся из data/plans_data_with_blocks.json (159 тем, 785 пунктов).
"""

import logging
import json
import os
import random
from datetime import date
from typing import Dict, Any, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import states
from core.error_handler import safe_handler
from core.utils import safe_edit_message
from core.streak_manager import get_streak_manager

from .quiz_handlers import _truncate
from .leaderboard import add_xp, XP_PLAN_CORRECT

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# Кэш данных планов
_plans_cache: Optional[Dict] = None


def _get_plans() -> Dict:
    """Загружает и кэширует данные планов."""
    global _plans_cache
    if _plans_cache is not None:
        return _plans_cache

    path = os.path.join(BASE_DIR, 'data', 'plans_data_with_blocks.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            _plans_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load plans data: {e}")
        _plans_cache = {}

    return _plans_cache


def _get_viable_topics(min_points: int = 3) -> List[tuple]:
    """Возвращает темы с достаточным количеством пунктов."""
    plans = _get_plans().get('plans', {})
    return [
        (name, data) for name, data in plans.items()
        if len(data.get('points_data', [])) >= min_points
    ]


# ============================================================
# БЛОКИ ТЕМ
# ============================================================

PLAN_BLOCKS = {
    'human': '🧠 Человек и общество',
    'economy': '💰 Экономика',
    'social': '👥 Социальные отношения',
    'politics': '🏛 Политика',
    'law': '⚖️ Право',
}


def _get_topics_by_block() -> Dict[str, List[tuple]]:
    """Группирует темы по блокам."""
    topics = _get_viable_topics()
    by_block: Dict[str, List[tuple]] = {k: [] for k in PLAN_BLOCKS}
    other = []

    block_keywords = {
        'human': ['человек', 'общество', 'познан', 'мировоззрен', 'деятельн',
                   'культур', 'наук', 'образован', 'глобализ', 'цивилизац',
                   'прогресс', 'свобод', 'сознан', 'мышлен', 'биосоциальн'],
        'economy': ['экономик', 'рынок', 'предприним', 'собственност',
                     'финанс', 'банк', 'налог', 'бюджет', 'инфляц',
                     'безработиц', 'торговл', 'производств'],
        'social': ['социальн', 'семь', 'стратификац', 'мобильност',
                    'конфликт', 'молодёж', 'этнос', 'нац', 'неравенств',
                    'девиант', 'контрол'],
        'politics': ['политик', 'государств', 'власт', 'демократ', 'партий',
                      'выбор', 'идеолог', 'федератив', 'режим', 'элит',
                      'гражданск_общ'],
        'law': ['прав', 'закон', 'конституц', 'суд', 'ответствен',
                'договор', 'труд', 'семейн_прав', 'уголовн', 'административн'],
    }

    for name, data in topics:
        block = data.get('block', '').lower()
        name_lower = name.lower()
        placed = False

        for block_id, keywords in block_keywords.items():
            if any(kw in name_lower or kw in block for kw in keywords):
                by_block[block_id].append((name, data))
                placed = True
                break

        if not placed:
            other.append((name, data))

    # Распределяем "другие" в самый маленький блок
    if other:
        smallest = min(by_block, key=lambda k: len(by_block[k]))
        by_block[smallest].extend(other)

    return by_block


# ============================================================
# ГЕНЕРАЦИЯ ВОПРОСОВ
# ============================================================

def generate_key_points_question(topics: List[tuple]) -> Optional[Dict]:
    """
    «Что лишнее?» — 4 пункта, один из другой темы.
    """
    if len(topics) < 2:
        return None

    topic_name, topic_data = random.choice(topics)
    points = topic_data.get('points_data', [])

    if len(points) < 2:
        return None

    # Берём 3 правильных пункта
    correct_points = random.sample(points, min(3, len(points)))

    # Берём 1 пункт из другой темы
    other_topics = [(n, d) for n, d in topics if n != topic_name]
    if not other_topics:
        return None

    other_name, other_data = random.choice(other_topics)
    other_points = other_data.get('points_data', [])
    if not other_points:
        return None

    wrong_point = random.choice(other_points)

    # Формируем варианты
    labels = ['А', 'Б', 'В', 'Г']
    all_options = [
        {'text': p['point_text'], 'correct': True} for p in correct_points[:3]
    ] + [{'text': wrong_point['point_text'], 'correct': False}]

    random.shuffle(all_options)

    wrong_index = next(i for i, o in enumerate(all_options) if not o['correct'])

    options = []
    for i, opt in enumerate(all_options):
        options.append({
            'label': labels[i],
            'text': _truncate(opt['text'], 120),
            'is_correct': not opt['correct'],  # "правильный ответ" = лишний пункт
        })

    return {
        'type': 'odd_one_out',
        'question': f"Какой пункт <b>НЕ</b> относится к плану\n\n«{topic_name}»?",
        'options': options,
        'correct_index': wrong_index,
        'correct_label': labels[wrong_index],
        'explanation': f"Этот пункт относится к теме «{other_name}»",
        'topic_name': topic_name,
    }


def generate_subpoints_question(topics: List[tuple]) -> Optional[Dict]:
    """
    «Допиши подпункты» — показываем пункт, нужно выбрать его подпункт.
    """
    # Ищем темы с подпунктами
    topics_with_subs = []
    for name, data in topics:
        for pt in data.get('points_data', []):
            if pt.get('sub_points') and len(pt['sub_points']) >= 2:
                topics_with_subs.append((name, data, pt))

    if len(topics_with_subs) < 2:
        return None

    chosen = random.choice(topics_with_subs)
    topic_name, topic_data, point = chosen

    correct_sub = random.choice(point['sub_points'])

    # Дистракторы — подпункты из других пунктов
    other_subs = []
    for n, d, p in topics_with_subs:
        if p != point and p.get('sub_points'):
            other_subs.extend(p['sub_points'])

    if len(other_subs) < 3:
        return None

    distractors = random.sample(other_subs, 3)

    labels = ['А', 'Б', 'В', 'Г']
    all_opts = [correct_sub] + distractors
    random.shuffle(all_opts)
    correct_idx = all_opts.index(correct_sub)

    options = []
    for i, opt_text in enumerate(all_opts):
        options.append({
            'label': labels[i],
            'text': _truncate(opt_text, 120),
            'is_correct': i == correct_idx,
        })

    return {
        'type': 'subpoints',
        'question': f"Какой подпункт относится к пункту\n\n«{_truncate(point['point_text'], 150)}»\n\nиз плана «{topic_name}»?",
        'options': options,
        'correct_index': correct_idx,
        'correct_label': labels[correct_idx],
        'explanation': f"Правильный подпункт: {correct_sub}",
    }


def generate_plan_session(block_id: Optional[str] = None, count: int = 8) -> List[Dict]:
    """Генерирует сессию вопросов по планам."""
    topics_by_block = _get_topics_by_block()

    if block_id and block_id in topics_by_block:
        topics = topics_by_block[block_id]
    else:
        # Все темы
        topics = _get_viable_topics()

    if len(topics) < 3:
        return []

    questions = []
    attempts = 0

    while len(questions) < count and attempts < count * 4:
        attempts += 1
        # Чередуем типы
        if len(questions) % 2 == 0:
            q = generate_key_points_question(topics)
        else:
            q = generate_subpoints_question(topics)

        if q is None:
            q = generate_key_points_question(topics)

        if q:
            questions.append(q)

    return questions


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

@safe_handler()
async def show_plan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню конструктора планов."""
    query = update.callback_query

    topics_by_block = _get_topics_by_block()

    text = "<b>📝 Конструктор планов</b>\n\n"
    text += "Тренажёр для задания 24 ЕГЭ.\n"
    text += "Проверьте знание структуры планов по разным блокам.\n\n"
    text += "Выберите блок:\n"

    keyboard = []
    for block_id, block_title in PLAN_BLOCKS.items():
        topic_count = len(topics_by_block.get(block_id, []))
        if topic_count > 0:
            keyboard.append([InlineKeyboardButton(
                f"{block_title} ({topic_count} тем)",
                callback_data=f"fc_plan_block_{block_id}"
            )])

    keyboard.append([InlineKeyboardButton(
        "🎲 Все блоки вперемешку",
        callback_data="fc_plan_block_all"
    )])
    keyboard.append([InlineKeyboardButton(
        "◀️ Назад к карточкам",
        callback_data="fc_back_to_decks"
    )])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.FC_PLAN


@safe_handler()
async def start_plan_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает сессию конструктора планов."""
    query = update.callback_query
    block_id = query.data.replace("fc_plan_block_", "")

    if block_id == "all":
        block_id = None

    questions = generate_plan_session(block_id, count=8)

    if not questions:
        await query.answer("Недостаточно данных для этого блока", show_alert=True)
        return states.FC_PLAN

    context.user_data['fc_plan_session'] = {
        'questions': questions,
        'current': 0,
        'total': len(questions),
        'correct': 0,
        'wrong': 0,
        'block_id': block_id,
    }

    await _show_plan_question(query, context)
    return states.FC_PLAN


async def _show_plan_question(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает текущий вопрос по планам."""
    session = context.user_data.get('fc_plan_session', {})
    questions = session.get('questions', [])
    idx = session.get('current', 0)

    if idx >= len(questions):
        return

    q = questions[idx]
    total = session['total']
    correct = session['correct']

    type_label = "Что лишнее?" if q['type'] == 'odd_one_out' else "Найди подпункт"

    text = f"<b>📝 Планы {idx + 1}/{total}</b>  (✅ {correct})\n"
    text += f"<i>{type_label}</i>\n\n"
    text += f"{q['question']}\n\n"

    for opt in q['options']:
        text += f"<b>{opt['label']}.</b> {opt['text']}\n\n"

    keyboard = []
    row = []
    for i, opt in enumerate(q['options']):
        row.append(InlineKeyboardButton(
            opt['label'],
            callback_data=f"fc_plan_ans_{i}"
        ))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⏹ Завершить", callback_data="fc_plan_end")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def handle_plan_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ на вопрос по планам."""
    query = update.callback_query
    chosen_idx = int(query.data.replace("fc_plan_ans_", ""))

    session = context.user_data.get('fc_plan_session', {})
    questions = session.get('questions', [])
    idx = session.get('current', 0)

    if idx >= len(questions):
        return states.FC_PLAN

    q = questions[idx]
    is_correct = chosen_idx == q['correct_index']

    if is_correct:
        session['correct'] += 1
        feedback = "✅ Верно!"
        user_id = query.from_user.id
        await add_xp(user_id, XP_PLAN_CORRECT, 'plan', f"plan_q_{idx}")
    else:
        session['wrong'] += 1
        feedback = f"❌ Неверно! Ответ: {q['correct_label']}"

    await query.answer(feedback, show_alert=False)

    session['current'] = idx + 1

    if session['current'] >= len(questions):
        await _show_plan_results(query, context)
    else:
        await _show_plan_question(query, context)

    return states.FC_PLAN


async def _show_plan_results(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает итоги сессии по планам."""
    session = context.user_data.get('fc_plan_session', {})
    user_id = query.from_user.id

    correct = session.get('correct', 0)
    total = session.get('total', 0)
    pct = round(correct / total * 100) if total > 0 else 0

    # Обновляем стрик
    streak_manager = get_streak_manager()
    current_date = date.today().isoformat()
    last_activity = context.user_data.get('last_activity_date')

    if last_activity != current_date:
        await streak_manager.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date

    if total > 0:
        await streak_manager.update_correct_streak(user_id, pct >= 50)

    text = "<b>📝 Конструктор планов — Итоги</b>\n\n"
    text += f"Правильных: <b>{correct}/{total}</b> ({pct}%)\n\n"

    if pct >= 80:
        text += "🌟 Отличное знание структуры планов!"
    elif pct >= 50:
        text += "📈 Хороший результат. Повторите слабые темы."
    else:
        text += "💪 Рекомендуем изучить планы в учебнике и повторить."

    keyboard = [
        [InlineKeyboardButton("🔄 Ещё раз", callback_data=f"fc_plan_block_{session.get('block_id') or 'all'}")],
        [InlineKeyboardButton("📝 Выбрать блок", callback_data="fc_plan_menu")],
        [InlineKeyboardButton("📋 К карточкам", callback_data="fc_back_to_decks")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def plan_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Досрочное завершение сессии планов."""
    query = update.callback_query
    await _show_plan_results(query, context)
    return states.FC_PLAN
