"""
Дуэли — асинхронные соревнования между двумя пользователями.

Механика:
1. Пользователь A создаёт дуэль → получает код-приглашение
2. Пользователь B вводит код → присоединяется
3. Оба отвечают на одинаковые 10 вопросов (из случайной колоды)
4. Сравниваются результаты → определяется победитель
5. Победитель получает +10 XP бонус

Дуэли асинхронные: второй игрок может присоединиться и отвечать в любое время
(в течение 24 часов).
"""

import logging
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.db import DATABASE_FILE
from core.error_handler import safe_handler
from core.utils import safe_edit_message
from core import states

from . import db as flashcard_db
from .quiz_handlers import generate_quiz_questions, _truncate
from .leaderboard import add_xp

logger = logging.getLogger(__name__)

DUEL_SIZE = 10
DUEL_WIN_XP = 10
DUEL_PARTICIPATE_XP = 3
DUEL_EXPIRY_HOURS = 24


# ============================================================
# DATABASE
# ============================================================

async def ensure_duel_tables() -> None:
    """Создаёт таблицы для дуэлей."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS flashcard_duels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invite_code TEXT UNIQUE NOT NULL,
                deck_id TEXT,
                challenger_id INTEGER NOT NULL,
                opponent_id INTEGER,
                challenger_score INTEGER DEFAULT 0,
                challenger_total INTEGER DEFAULT 0,
                opponent_score INTEGER DEFAULT 0,
                opponent_total INTEGER DEFAULT 0,
                questions_json TEXT NOT NULL,
                status TEXT DEFAULT 'waiting',
                created_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT,
                expires_at TEXT
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_duel_invite
            ON flashcard_duels(invite_code)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_duel_users
            ON flashcard_duels(challenger_id, opponent_id)
        """)
        await db.commit()
    logger.info("Duel tables ensured")


def _generate_invite_code() -> str:
    """Генерирует 6-символьный код приглашения."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def create_duel(challenger_id: int, deck_id: str = None) -> Dict[str, Any]:
    """
    Создаёт новую дуэль.

    Если deck_id не указан, выбирается случайная колода с достаточным кол-вом карточек.
    """
    import json

    # Выбираем колоду
    if not deck_id:
        all_decks = await flashcard_db.get_all_decks()
        viable = []
        for d in all_decks:
            cards = await flashcard_db.get_cards_for_deck(d['id'])
            if len(cards) >= 4:
                viable.append((d, cards))
        if not viable:
            return {'error': 'Нет подходящих колод'}
        deck_data, cards = random.choice(viable)
        deck_id = deck_data['id']
    else:
        cards = await flashcard_db.get_cards_for_deck(deck_id)
        if len(cards) < 4:
            return {'error': 'В колоде недостаточно карточек'}

    # Генерируем вопросы
    questions = generate_quiz_questions(cards, DUEL_SIZE)
    if not questions:
        return {'error': 'Не удалось сгенерировать вопросы'}

    # Сериализуем вопросы
    questions_json = json.dumps(questions, ensure_ascii=False)

    invite_code = _generate_invite_code()
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(hours=DUEL_EXPIRY_HOURS)).isoformat()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            INSERT INTO flashcard_duels
            (invite_code, deck_id, challenger_id, questions_json, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (invite_code, deck_id, challenger_id, questions_json, expires))
        await db.commit()

    deck = await flashcard_db.get_deck(deck_id)
    deck_title = deck['title'] if deck else deck_id

    return {
        'invite_code': invite_code,
        'deck_id': deck_id,
        'deck_title': deck_title,
        'question_count': len(questions),
    }


async def join_duel(invite_code: str, opponent_id: int) -> Dict[str, Any]:
    """Присоединяет оппонента к дуэли."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM flashcard_duels WHERE invite_code = ?",
            (invite_code.upper(),)
        )
        row = await cursor.fetchone()

    if not row:
        return {'error': 'Дуэль не найдена. Проверьте код.'}

    duel = dict(row)

    if duel['status'] != 'waiting':
        return {'error': 'Эта дуэль уже завершена или занята.'}

    if duel['challenger_id'] == opponent_id:
        return {'error': 'Нельзя играть против себя!'}

    # Проверяем срок
    expires = datetime.fromisoformat(duel['expires_at'])
    if datetime.now(timezone.utc) > expires:
        return {'error': 'Время дуэли истекло (24 часа).'}

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "UPDATE flashcard_duels SET opponent_id = ?, status = 'active' WHERE id = ?",
            (opponent_id, duel['id'])
        )
        await db.commit()

    return {'duel_id': duel['id'], 'duel': duel}


async def save_duel_result(
    duel_id: int,
    user_id: int,
    score: int,
    total: int,
) -> Optional[Dict[str, Any]]:
    """Сохраняет результат одного из участников дуэли."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM flashcard_duels WHERE id = ?", (duel_id,)
        )
        row = await cursor.fetchone()

    if not row:
        return None

    duel = dict(row)

    # Определяем, кто записывает результат
    if user_id == duel['challenger_id']:
        field_score = 'challenger_score'
        field_total = 'challenger_total'
    elif user_id == duel['opponent_id']:
        field_score = 'opponent_score'
        field_total = 'opponent_total'
    else:
        return None

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(f"""
            UPDATE flashcard_duels SET {field_score} = ?, {field_total} = ?
            WHERE id = ?
        """, (score, total, duel_id))

        # Проверяем, оба ли завершили
        cursor = await db.execute(
            "SELECT * FROM flashcard_duels WHERE id = ?", (duel_id,)
        )
        row = await cursor.fetchone()
        updated = dict(row)

        both_done = (updated['challenger_total'] > 0 and updated['opponent_total'] > 0)

        if both_done:
            await db.execute(
                "UPDATE flashcard_duels SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), duel_id)
            )

        await db.commit()

    if both_done:
        return {
            'completed': True,
            'challenger_score': updated['challenger_score'],
            'challenger_total': updated['challenger_total'],
            'opponent_score': updated['opponent_score'],
            'opponent_total': updated['opponent_total'],
            'challenger_id': updated['challenger_id'],
            'opponent_id': updated['opponent_id'],
        }

    return {'completed': False}


async def get_user_duel_stats(user_id: int) -> Dict[str, Any]:
    """Статистика дуэлей пользователя."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Победы (challenger)
        cursor = await db.execute("""
            SELECT COUNT(*) FROM flashcard_duels
            WHERE status = 'completed'
              AND challenger_id = ?
              AND challenger_score > opponent_score
        """, (user_id,))
        wins_c = (await cursor.fetchone())[0]

        # Победы (opponent)
        cursor = await db.execute("""
            SELECT COUNT(*) FROM flashcard_duels
            WHERE status = 'completed'
              AND opponent_id = ?
              AND opponent_score > challenger_score
        """, (user_id,))
        wins_o = (await cursor.fetchone())[0]

        # Всего дуэлей
        cursor = await db.execute("""
            SELECT COUNT(*) FROM flashcard_duels
            WHERE status = 'completed'
              AND (challenger_id = ? OR opponent_id = ?)
        """, (user_id, user_id))
        total = (await cursor.fetchone())[0]

    return {
        'wins': wins_c + wins_o,
        'total': total,
        'losses': total - (wins_c + wins_o),
    }


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

@safe_handler()
async def show_duel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает главное меню дуэлей."""
    query = update.callback_query
    user_id = query.from_user.id

    duel_stats = await get_user_duel_stats(user_id)

    text = "<b>⚔️ Дуэли</b>\n\n"
    text += "Соревнуйтесь с друзьями!\n"
    text += "Создайте дуэль и отправьте код другу.\n"
    text += "Вы оба ответите на одинаковые вопросы, а потом узнаете, кто лучше.\n\n"

    if duel_stats['total'] > 0:
        text += f"<b>📊 Ваша статистика:</b>\n"
        text += f"  ⚔️ Дуэлей: {duel_stats['total']}\n"
        text += f"  🏆 Побед: {duel_stats['wins']}\n"
        text += f"  ❌ Поражений: {duel_stats['losses']}\n"

    keyboard = [
        [InlineKeyboardButton("⚔️ Создать дуэль", callback_data="fc_duel_create")],
        [InlineKeyboardButton("🔗 Присоединиться (ввести код)", callback_data="fc_duel_join")],
        [InlineKeyboardButton("◀️ Назад к карточкам", callback_data="fc_back_to_decks")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.FC_DUEL


@safe_handler()
async def create_duel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создаёт новую дуэль."""
    query = update.callback_query
    user_id = query.from_user.id

    result = await create_duel(user_id)

    if 'error' in result:
        await query.answer(result['error'], show_alert=True)
        return states.FC_DUEL

    invite_code = result['invite_code']
    context.user_data['fc_duel_code'] = invite_code

    text = f"<b>⚔️ Дуэль создана!</b>\n\n"
    text += f"📋 Колода: <b>{result['deck_title']}</b>\n"
    text += f"❓ Вопросов: {result['question_count']}\n\n"
    text += f"🔑 Код приглашения:\n\n"
    text += f"<code>{invite_code}</code>\n\n"
    text += "Отправьте этот код другу. Когда он присоединится,\n"
    text += "вы оба сможете пройти одинаковый Quiz.\n\n"
    text += "<i>Код действителен 24 часа.</i>"

    keyboard = [
        [InlineKeyboardButton("🎯 Начать свой Quiz", callback_data="fc_duel_start_quiz")],
        [InlineKeyboardButton("◀️ Назад", callback_data="fc_duel_menu")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.FC_DUEL


@safe_handler()
async def join_duel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просит ввести код дуэли."""
    query = update.callback_query

    text = "<b>🔗 Присоединиться к дуэли</b>\n\n"
    text += "Введите 6-символьный код, который вам прислал друг:"

    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="fc_duel_menu")]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    context.user_data['fc_duel_waiting_code'] = True
    return states.FC_DUEL


@safe_handler()
async def handle_duel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстового ввода (код дуэли)."""
    user_id = update.effective_user.id
    text_input = update.message.text.strip().upper()

    if not context.user_data.get('fc_duel_waiting_code'):
        return states.FC_DUEL

    context.user_data['fc_duel_waiting_code'] = False

    result = await join_duel(text_input, user_id)

    if 'error' in result:
        text = f"<b>❌ {result['error']}</b>\n\n"
        text += "Попробуйте другой код."

        keyboard = [
            [InlineKeyboardButton("🔗 Ввести код", callback_data="fc_duel_join")],
            [InlineKeyboardButton("◀️ Назад", callback_data="fc_duel_menu")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
        return states.FC_DUEL

    # Успешно присоединились
    import json
    duel = result['duel']
    questions = json.loads(duel['questions_json'])

    context.user_data['fc_duel_session'] = {
        'duel_id': result['duel_id'],
        'questions': questions,
        'current': 0,
        'total': len(questions),
        'correct': 0,
        'wrong': 0,
        'role': 'opponent',
    }

    deck = await flashcard_db.get_deck(duel['deck_id'])
    deck_title = deck['title'] if deck else 'Quiz'

    text = f"<b>⚔️ Вы присоединились к дуэли!</b>\n\n"
    text += f"📋 Колода: <b>{deck_title}</b>\n"
    text += f"❓ Вопросов: {len(questions)}\n\n"
    text += "Готовы начать?"

    keyboard = [
        [InlineKeyboardButton("🚀 Начать!", callback_data="fc_duel_go")],
        [InlineKeyboardButton("◀️ Назад", callback_data="fc_duel_menu")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )

    return states.FC_DUEL


@safe_handler()
async def start_duel_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает прохождение Quiz дуэли (для обоих участников)."""
    query = update.callback_query
    user_id = query.from_user.id

    session = context.user_data.get('fc_duel_session')

    if not session:
        # Challenger начинает — загружаем его дуэль
        invite_code = context.user_data.get('fc_duel_code')
        if not invite_code:
            await query.answer("Дуэль не найдена", show_alert=True)
            return states.FC_DUEL

        import json
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM flashcard_duels WHERE invite_code = ?",
                (invite_code,)
            )
            row = await cursor.fetchone()

        if not row:
            await query.answer("Дуэль не найдена", show_alert=True)
            return states.FC_DUEL

        duel = dict(row)
        questions = json.loads(duel['questions_json'])

        context.user_data['fc_duel_session'] = {
            'duel_id': duel['id'],
            'questions': questions,
            'current': 0,
            'total': len(questions),
            'correct': 0,
            'wrong': 0,
            'role': 'challenger',
        }
        session = context.user_data['fc_duel_session']

    # Показываем первый вопрос
    await _show_duel_question(query, context)
    return states.FC_DUEL


async def _show_duel_question(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает текущий вопрос дуэли."""
    session = context.user_data.get('fc_duel_session', {})
    questions = session.get('questions', [])
    idx = session.get('current', 0)

    if idx >= len(questions):
        return

    q = questions[idx]
    total = session['total']
    correct = session['correct']

    text = f"<b>⚔️ Дуэль {idx + 1}/{total}</b>"
    text += f"  (✅ {correct})\n\n"

    if q['type'] == 'true_false':
        text += "<b>Верно или неверно?</b>\n\n"
        text += f"{q['question']}\n"
        keyboard = [
            [
                InlineKeyboardButton("✅ Верно", callback_data="fc_duel_tf_true"),
                InlineKeyboardButton("❌ Неверно", callback_data="fc_duel_tf_false"),
            ],
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
                callback_data=f"fc_duel_mc_{i}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
    else:
        # Неизвестный тип — пропускаем
        session['current'] = idx + 1
        if session['current'] < len(questions):
            await _show_duel_question(query, context)
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def handle_duel_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка True/False ответа в дуэли."""
    query = update.callback_query
    user_answer = query.data == "fc_duel_tf_true"

    session = context.user_data.get('fc_duel_session', {})
    questions = session.get('questions', [])
    idx = session.get('current', 0)

    if idx >= len(questions):
        return states.FC_DUEL

    q = questions[idx]
    is_correct = user_answer == q.get('correct_answer', False)
    await _process_duel_answer(query, context, is_correct)
    return states.FC_DUEL


@safe_handler()
async def handle_duel_mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка Multiple Choice ответа в дуэли."""
    query = update.callback_query
    chosen_idx = int(query.data.replace("fc_duel_mc_", ""))

    session = context.user_data.get('fc_duel_session', {})
    questions = session.get('questions', [])
    idx = session.get('current', 0)

    if idx >= len(questions):
        return states.FC_DUEL

    q = questions[idx]
    is_correct = chosen_idx == q.get('correct_index', -1)
    await _process_duel_answer(query, context, is_correct)
    return states.FC_DUEL


async def _process_duel_answer(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    is_correct: bool,
) -> None:
    """Обрабатывает ответ в дуэли."""
    session = context.user_data.get('fc_duel_session', {})

    if is_correct:
        session['correct'] += 1
        feedback = "✅ Верно!"
    else:
        session['wrong'] += 1
        feedback = "❌ Неверно!"

    session['current'] += 1
    await query.answer(feedback, show_alert=False)

    if session['current'] >= len(session['questions']):
        await _finish_duel(query, context)
    else:
        await _show_duel_question(query, context)


async def _finish_duel(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Завершает дуэль для текущего игрока и показывает результаты."""
    user_id = query.from_user.id
    session = context.user_data.get('fc_duel_session', {})

    duel_id = session['duel_id']
    score = session['correct']
    total = session['total']

    # Сохраняем результат
    result = await save_duel_result(duel_id, user_id, score, total)

    # XP за участие
    await add_xp(user_id, DUEL_PARTICIPATE_XP, 'duel', f'duel_{duel_id}')

    pct = round(score / total * 100) if total > 0 else 0

    text = f"<b>⚔️ Ваш результат: {score}/{total} ({pct}%)</b>\n\n"

    if result and result.get('completed'):
        # Оба завершили — показываем итоги
        c_score = result['challenger_score']
        c_total = result['challenger_total']
        o_score = result['opponent_score']
        o_total = result['opponent_total']

        if session['role'] == 'challenger':
            my_score, their_score = c_score, o_score
        else:
            my_score, their_score = o_score, c_score

        text += "<b>🏆 Итоги дуэли:</b>\n\n"
        text += f"Вы: <b>{my_score}/{total}</b>\n"
        text += f"Соперник: <b>{their_score}/{total}</b>\n\n"

        if my_score > their_score:
            text += "🎉 <b>Вы победили!</b> +10 XP бонус!"
            await add_xp(user_id, DUEL_WIN_XP, 'duel', f'duel_win_{duel_id}')
        elif my_score < their_score:
            text += "😔 <b>Соперник оказался сильнее.</b> Не сдавайтесь!"
        else:
            text += "🤝 <b>Ничья!</b> Отличная битва!"
    else:
        text += "⏳ <b>Ожидаем соперника...</b>\n"
        text += "Когда соперник завершит свой Quiz, вы увидите результаты."

    keyboard = [
        [InlineKeyboardButton("⚔️ Новая дуэль", callback_data="fc_duel_create")],
        [InlineKeyboardButton("◀️ Меню дуэлей", callback_data="fc_duel_menu")],
        [InlineKeyboardButton("📋 К карточкам", callback_data="fc_back_to_decks")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    # Очищаем сессию
    context.user_data.pop('fc_duel_session', None)
