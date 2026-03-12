"""
Quiz-режимы для карточек: Верно/Неверно и Выбор из вариантов.

Генерирует вопросы на основе существующих карточек и данных.
Работает с любой колодой — карточки используются как источник фактов.
"""

import logging
import random
from datetime import date, datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import states
from core.error_handler import safe_handler
from core.utils import safe_edit_message
from core.streak_manager import get_streak_manager

from . import db as flashcard_db
from .leaderboard import add_xp, XP_QUIZ_CORRECT

logger = logging.getLogger(__name__)

QUIZ_SESSION_SIZE = 10


# ============================================================
# ГЕНЕРАЦИЯ ВОПРОСОВ
# ============================================================

def generate_true_false(cards: List[Dict]) -> Optional[Dict[str, Any]]:
    """
    Генерирует вопрос Верно/Неверно из набора карточек.

    Стратегия:
    - 50% вопросов верные (настоящая пара front→back)
    - 50% неверные (front одной карточки + back другой)
    """
    if len(cards) < 2:
        return None

    is_true = random.choice([True, False])
    card = random.choice(cards)

    if is_true:
        # Верное утверждение
        statement_front = card['front_text']
        statement_back = card['back_text']
    else:
        # Неверное — берём back от другой карточки
        other_cards = [c for c in cards if c['id'] != card['id']]
        if not other_cards:
            return None
        wrong_card = random.choice(other_cards)
        statement_front = card['front_text']
        statement_back = wrong_card['back_text']

    # Сокращаем текст для удобства
    front_short = _truncate(statement_front, 200)
    back_short = _truncate(statement_back, 200)

    return {
        'type': 'true_false',
        'question': f"{front_short}\n\n➡️ {back_short}",
        'correct_answer': is_true,
        'card_id': card['id'],
        'explanation_front': card['front_text'],
        'explanation_back': card['back_text'],
    }


def generate_multiple_choice(cards: List[Dict]) -> Optional[Dict[str, Any]]:
    """
    Генерирует вопрос с выбором из 4 вариантов.

    Показывает front_text карточки, нужно выбрать правильный back_text
    из 4 вариантов (1 правильный + 3 дистрактора).
    """
    if len(cards) < 4:
        return None

    # Выбираем правильную карточку
    correct_card = random.choice(cards)

    # Выбираем 3 дистрактора
    other_cards = [c for c in cards if c['id'] != correct_card['id']]
    distractors = random.sample(other_cards, min(3, len(other_cards)))

    # Формируем варианты ответов
    options = [correct_card] + distractors
    random.shuffle(options)

    correct_index = options.index(correct_card)

    option_labels = ['А', 'Б', 'В', 'Г']
    formatted_options = []
    for i, opt in enumerate(options):
        formatted_options.append({
            'label': option_labels[i],
            'text': _truncate(opt['back_text'], 150),
            'is_correct': opt['id'] == correct_card['id'],
        })

    return {
        'type': 'multiple_choice',
        'question': correct_card['front_text'],
        'options': formatted_options,
        'correct_index': correct_index,
        'correct_label': option_labels[correct_index],
        'card_id': correct_card['id'],
        'explanation': correct_card['back_text'],
    }


def generate_quiz_questions(
    cards: List[Dict],
    count: int = QUIZ_SESSION_SIZE,
) -> List[Dict[str, Any]]:
    """
    Генерирует набор вопросов разных типов для Quiz-сессии.

    Чередует True/False и Multiple Choice.
    """
    questions = []
    attempts = 0
    max_attempts = count * 3

    while len(questions) < count and attempts < max_attempts:
        attempts += 1

        if len(questions) % 2 == 0:
            q = generate_true_false(cards)
        else:
            q = generate_multiple_choice(cards)

        if q is None:
            # Пробуем другой тип
            if len(questions) % 2 == 0:
                q = generate_multiple_choice(cards)
            else:
                q = generate_true_false(cards)

        if q:
            questions.append(q)

    return questions


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

@safe_handler()
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает Quiz-сессию для выбранной колоды."""
    query = update.callback_query
    user_id = query.from_user.id

    deck_id = context.user_data.get('fc_current_deck')
    if not deck_id:
        await query.answer("Выберите колоду", show_alert=True)
        return states.FC_MENU

    deck = await flashcard_db.get_deck(deck_id)
    cards = await flashcard_db.get_cards_for_deck(deck_id)

    if len(cards) < 4:
        await query.answer(
            "Нужно минимум 4 карточки для Quiz-режима", show_alert=True
        )
        return states.FC_DECK_VIEW

    questions = generate_quiz_questions(cards, QUIZ_SESSION_SIZE)

    if not questions:
        await query.answer("Не удалось сгенерировать вопросы", show_alert=True)
        return states.FC_DECK_VIEW

    context.user_data['fc_quiz'] = {
        'questions': questions,
        'current': 0,
        'total': len(questions),
        'correct': 0,
        'wrong': 0,
        'deck_title': deck['title'] if deck else '',
        'deck_id': deck_id,
    }

    await _show_quiz_question(query, context)
    return states.FC_QUIZ


async def _show_quiz_question(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает текущий вопрос Quiz."""
    quiz = context.user_data.get('fc_quiz', {})
    questions = quiz.get('questions', [])
    idx = quiz.get('current', 0)

    if idx >= len(questions):
        return

    q = questions[idx]
    total = quiz['total']
    correct = quiz['correct']

    # Заголовок
    text = f"<b>🧩 Quiz {idx + 1}/{total}</b>"
    text += f"  (✅ {correct})\n\n"

    if q['type'] == 'true_false':
        text += "<b>Верно или неверно?</b>\n\n"
        text += f"{q['question']}\n"

        keyboard = [
            [
                InlineKeyboardButton("✅ Верно", callback_data="fc_quiz_tf_true"),
                InlineKeyboardButton("❌ Неверно", callback_data="fc_quiz_tf_false"),
            ],
            [InlineKeyboardButton("⏹ Завершить", callback_data="fc_quiz_end")],
        ]

    elif q['type'] == 'multiple_choice':
        text += f"{q['question']}\n\n"
        for opt in q['options']:
            text += f"<b>{opt['label']}.</b> {opt['text']}\n\n"

        keyboard = []
        row = []
        for i, opt in enumerate(q['options']):
            row.append(InlineKeyboardButton(
                opt['label'],
                callback_data=f"fc_quiz_mc_{i}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⏹ Завершить", callback_data="fc_quiz_end")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def handle_tf_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа Верно/Неверно."""
    query = update.callback_query
    user_answer = query.data == "fc_quiz_tf_true"

    quiz = context.user_data.get('fc_quiz', {})
    questions = quiz.get('questions', [])
    idx = quiz.get('current', 0)

    if idx >= len(questions):
        return states.FC_QUIZ

    q = questions[idx]
    is_correct = user_answer == q['correct_answer']

    await _show_quiz_feedback(query, context, is_correct, q)
    return states.FC_QUIZ


@safe_handler()
async def handle_mc_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа Multiple Choice."""
    query = update.callback_query
    chosen_idx = int(query.data.replace("fc_quiz_mc_", ""))

    quiz = context.user_data.get('fc_quiz', {})
    questions = quiz.get('questions', [])
    idx = quiz.get('current', 0)

    if idx >= len(questions):
        return states.FC_QUIZ

    q = questions[idx]
    is_correct = chosen_idx == q['correct_index']

    await _show_quiz_feedback(query, context, is_correct, q)
    return states.FC_QUIZ


async def _show_quiz_feedback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    is_correct: bool,
    question: Dict,
) -> None:
    """Показывает результат ответа и переходит к следующему вопросу."""
    quiz = context.user_data.get('fc_quiz', {})

    if is_correct:
        quiz['correct'] += 1
        emoji = "✅"
        verdict = "Верно!"
        # XP за правильный ответ
        user_id = query.from_user.id
        await add_xp(user_id, XP_QUIZ_CORRECT, 'quiz', f"quiz_{quiz.get('deck_id', '')}")
    else:
        quiz['wrong'] += 1
        emoji = "❌"
        verdict = "Неверно!"

    idx = quiz['current']
    total = quiz['total']

    text = f"<b>🧩 Quiz {idx + 1}/{total}</b>\n\n"
    text += f"<b>{emoji} {verdict}</b>\n\n"

    # Показываем правильный ответ
    if question['type'] == 'true_false':
        correct_str = "Верно" if question['correct_answer'] else "Неверно"
        text += f"Правильный ответ: <b>{correct_str}</b>\n\n"
        text += f"<i>{_truncate(question['explanation_back'], 300)}</i>"
    elif question['type'] == 'multiple_choice':
        text += f"Правильный ответ: <b>{question['correct_label']}</b>\n\n"
        text += f"<i>{_truncate(question['explanation'], 300)}</i>"

    # Переходим к следующему вопросу
    quiz['current'] = idx + 1

    if quiz['current'] >= len(quiz['questions']):
        keyboard = [
            [InlineKeyboardButton("📊 Результаты", callback_data="fc_quiz_results")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("➡️ Следующий вопрос", callback_data="fc_quiz_next")],
            [InlineKeyboardButton("⏹ Завершить", callback_data="fc_quiz_end")],
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def quiz_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает следующий вопрос Quiz."""
    query = update.callback_query
    await _show_quiz_question(query, context)
    return states.FC_QUIZ


@safe_handler()
async def quiz_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает итоги Quiz-сессии."""
    query = update.callback_query
    user_id = query.from_user.id

    quiz = context.user_data.get('fc_quiz', {})
    correct = quiz.get('correct', 0)
    wrong = quiz.get('wrong', 0)
    total_answered = correct + wrong
    deck_title = quiz.get('deck_title', '')
    deck_id = quiz.get('deck_id', '')

    if total_answered > 0:
        pct = round(correct / total_answered * 100)
    else:
        pct = 0

    text = f"<b>🧩 Quiz завершён: {deck_title}</b>\n\n"
    text += f"Правильных: <b>{correct}</b> из {total_answered}\n"
    text += f"Точность: <b>{pct}%</b>\n\n"

    if pct >= 90:
        text += "🌟 Великолепно! Вы отлично знаете материал!"
    elif pct >= 70:
        text += "👍 Хороший результат! Ещё немного практики."
    elif pct >= 50:
        text += "📈 Неплохо, но стоит повторить карточки."
    else:
        text += "💪 Не сдавайтесь! Попробуйте сначала режим карточек."

    # Обновляем стрик
    streak_manager = get_streak_manager()
    current_date = date.today().isoformat()
    last_activity = context.user_data.get('last_activity_date')

    if last_activity != current_date:
        await streak_manager.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date

    if total_answered > 0:
        await streak_manager.update_correct_streak(user_id, pct >= 50)

    keyboard = [
        [InlineKeyboardButton("🔄 Новый Quiz", callback_data="fc_start_quiz")],
        [InlineKeyboardButton("◀️ К колоде", callback_data=f"fc_deck_{deck_id}")],
        [InlineKeyboardButton("📋 Все колоды", callback_data="fc_back_to_decks")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.FC_DECK_VIEW


@safe_handler()
async def quiz_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Досрочное завершение Quiz."""
    return await quiz_results(update, context)


# ============================================================
# HELPERS
# ============================================================

def _truncate(text: str, max_len: int) -> str:
    """Обрезает текст до указанной длины."""
    if not text:
        return ""
    # Берём только первую строку/абзац если текст длинный
    lines = text.strip().split('\n')
    result = lines[0]
    if len(result) > max_len:
        return result[:max_len - 1] + "…"
    if len(lines) > 1 and len(result) < max_len // 2:
        # Добавляем ещё строк если первая короткая
        for line in lines[1:]:
            if len(result) + len(line) + 1 > max_len:
                break
            result += "\n" + line
    return result
