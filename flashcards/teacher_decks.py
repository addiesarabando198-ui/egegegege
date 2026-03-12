"""
Учительские колоды — учитель создаёт карточки, ученики получают доступ.

Интеграция с teacher_mode:
- Используется teacher_student_relationships для определения учеников
- Учитель создаёт колоду → автоматически доступна ученикам
- Ученики видят колоды учителя в своём меню карточек
"""

import logging
from datetime import datetime, timezone
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

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE
# ============================================================

async def ensure_teacher_decks_tables() -> None:
    """Создаёт таблицы для учительских колод."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Связь учитель → колода
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teacher_deck_ownership (
                teacher_id INTEGER NOT NULL,
                deck_id TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (teacher_id, deck_id)
            )
        """)
        # Карточки, которые учитель добавляет вручную (черновик)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teacher_deck_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                deck_title TEXT NOT NULL,
                deck_description TEXT DEFAULT '',
                cards_json TEXT DEFAULT '[]',
                status TEXT DEFAULT 'draft',
                created_at TEXT DEFAULT (datetime('now')),
                published_at TEXT
            )
        """)
        await db.commit()
    logger.info("Teacher decks tables ensured")


async def is_teacher(user_id: int) -> bool:
    """Проверяет, является ли пользователь учителем."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "SELECT 1 FROM user_roles WHERE user_id = ? AND role = 'teacher'",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return True
        # Также проверяем teacher_profiles
        cursor = await db.execute(
            "SELECT 1 FROM teacher_profiles WHERE user_id = ?",
            (user_id,)
        )
        return await cursor.fetchone() is not None


async def get_teacher_students(teacher_id: int) -> List[int]:
    """Получает ID учеников учителя."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "SELECT student_id FROM teacher_student_relationships "
            "WHERE teacher_id = ? AND status = 'active'",
            (teacher_id,)
        )
        rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_student_teachers(student_id: int) -> List[int]:
    """Получает ID учителей ученика."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "SELECT teacher_id FROM teacher_student_relationships "
            "WHERE student_id = ? AND status = 'active'",
            (student_id,)
        )
        rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_teacher_decks_for_student(student_id: int) -> List[Dict]:
    """Получает колоды учителей, доступные ученику."""
    teachers = await get_student_teachers(student_id)
    if not teachers:
        return []

    placeholders = ','.join('?' * len(teachers))

    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(f"""
            SELECT fd.*, tdo.teacher_id,
                   tp.display_name as teacher_name
            FROM flashcard_decks fd
            JOIN teacher_deck_ownership tdo ON fd.id = tdo.deck_id
            LEFT JOIN teacher_profiles tp ON tdo.teacher_id = tp.user_id
            WHERE tdo.teacher_id IN ({placeholders})
        """, teachers)
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


async def get_teacher_own_decks(teacher_id: int) -> List[Dict]:
    """Получает колоды, созданные учителем."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT fd.*, tdo.created_at as assigned_at
            FROM flashcard_decks fd
            JOIN teacher_deck_ownership tdo ON fd.id = tdo.deck_id
            WHERE tdo.teacher_id = ?
        """, (teacher_id,))
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


async def create_teacher_deck(
    teacher_id: int,
    title: str,
    description: str,
    cards: List[Dict],
) -> str:
    """
    Создаёт колоду от имени учителя.

    Args:
        teacher_id: ID учителя
        title: Название колоды
        description: Описание
        cards: [{front_text, back_text, hint?}]

    Returns:
        deck_id созданной колоды
    """
    deck_id = f"teacher_{teacher_id}_{int(datetime.now(timezone.utc).timestamp())}"

    await flashcard_db.upsert_deck(
        deck_id=deck_id,
        title=title,
        description=description,
        category="Учительская",
        icon="📖",
        is_premium=0,
    )

    card_items = []
    for i, card in enumerate(cards):
        card_items.append({
            'id': f"fc_t{teacher_id}_{i}",
            'deck_id': deck_id,
            'front_text': card['front_text'],
            'back_text': card['back_text'],
            'hint': card.get('hint'),
            'sort_order': i,
        })

    if card_items:
        await flashcard_db.bulk_upsert_cards(card_items)
        await flashcard_db.update_deck_card_count(deck_id)

    # Регистрируем владение
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO teacher_deck_ownership (teacher_id, deck_id) VALUES (?, ?)",
            (teacher_id, deck_id)
        )
        await db.commit()

    logger.info(f"Teacher {teacher_id} created deck '{title}' with {len(card_items)} cards")
    return deck_id


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

@safe_handler()
async def show_teacher_decks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню учительских колод."""
    query = update.callback_query
    user_id = query.from_user.id

    teacher = await is_teacher(user_id)

    if teacher:
        # Учитель: показываем его колоды + кнопку создания
        decks = await get_teacher_own_decks(user_id)

        text = "<b>📖 Учительские колоды</b>\n\n"

        if decks:
            text += f"У вас <b>{len(decks)}</b> колод:\n\n"
        else:
            text += "У вас пока нет собственных колод.\n"
            text += "Создайте колоду, и ваши ученики получат к ней доступ!\n\n"

        keyboard = []
        for deck in decks:
            students = await get_teacher_students(user_id)
            keyboard.append([InlineKeyboardButton(
                f"📖 {deck['title']} ({deck.get('card_count', 0)} карт.)",
                callback_data=f"fc_deck_{deck['id']}"
            )])

        keyboard.append([InlineKeyboardButton(
            "➕ Создать колоду", callback_data="fc_teacher_create"
        )])
        keyboard.append([InlineKeyboardButton(
            "◀️ Назад к карточкам", callback_data="fc_back_to_decks"
        )])

    else:
        # Ученик: показываем колоды учителей
        decks = await get_teacher_decks_for_student(user_id)

        text = "<b>📖 Колоды от учителя</b>\n\n"

        if decks:
            text += f"Доступно <b>{len(decks)}</b> колод от учителей:\n\n"
        else:
            text += "У вас пока нет колод от учителя.\n"
            text += "Подключитесь к учителю через код, чтобы получить доступ.\n\n"

        keyboard = []
        for deck in decks:
            teacher_name = deck.get('teacher_name', 'Учитель')
            keyboard.append([InlineKeyboardButton(
                f"📖 {deck['title']} ({teacher_name})",
                callback_data=f"fc_deck_{deck['id']}"
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

    return states.FC_MENU


@safe_handler()
async def start_create_deck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс создания колоды (учитель)."""
    query = update.callback_query
    user_id = query.from_user.id

    if not await is_teacher(user_id):
        await query.answer("Только учителя могут создавать колоды", show_alert=True)
        return states.FC_MENU

    context.user_data['fc_teacher_draft'] = {
        'step': 'title',
        'title': '',
        'description': '',
        'cards': [],
    }

    text = "<b>➕ Создание колоды</b>\n\n"
    text += "Введите <b>название</b> колоды:\n\n"
    text += "<i>Например: «Термины по теме Экономика» или «Подготовка к контрольной»</i>"

    keyboard = [[InlineKeyboardButton(
        "❌ Отмена", callback_data="fc_teacher_menu"
    )]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.FC_TEACHER


@safe_handler()
async def handle_teacher_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод при создании колоды."""
    user_id = update.effective_user.id
    text_input = update.message.text.strip()

    draft = context.user_data.get('fc_teacher_draft', {})
    step = draft.get('step', '')

    if step == 'title':
        draft['title'] = text_input
        draft['step'] = 'description'

        text = f"<b>➕ Создание: «{text_input}»</b>\n\n"
        text += "Введите <b>описание</b> колоды (или отправьте «-» чтобы пропустить):"

        keyboard = [[InlineKeyboardButton(
            "❌ Отмена", callback_data="fc_teacher_menu"
        )]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
        return states.FC_TEACHER

    elif step == 'description':
        if text_input != '-':
            draft['description'] = text_input
        draft['step'] = 'cards'

        text = f"<b>➕ Создание: «{draft['title']}»</b>\n\n"
        text += "Теперь добавляйте карточки.\n\n"
        text += "Формат: <b>вопрос | ответ</b>\n"
        text += "Одна карточка на строку. Можно отправить несколько строк сразу.\n\n"
        text += "<i>Пример:\n"
        text += "Инфляция | Устойчивое повышение общего уровня цен\n"
        text += "ВВП | Стоимость всех конечных товаров и услуг</i>"

        keyboard = [
            [InlineKeyboardButton(
                f"✅ Завершить ({len(draft['cards'])} карт.)",
                callback_data="fc_teacher_finish"
            )],
            [InlineKeyboardButton("❌ Отмена", callback_data="fc_teacher_menu")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
        return states.FC_TEACHER

    elif step == 'cards':
        # Парсим карточки из текста
        lines = text_input.strip().split('\n')
        added = 0
        for line in lines:
            line = line.strip()
            if '|' not in line:
                continue
            parts = line.split('|', 1)
            front = parts[0].strip()
            back = parts[1].strip()
            if front and back:
                draft['cards'].append({
                    'front_text': front,
                    'back_text': back,
                })
                added += 1

        total = len(draft['cards'])

        text = f"<b>➕ «{draft['title']}»</b>\n\n"
        if added > 0:
            text += f"✅ Добавлено: <b>{added}</b> карточек\n"
        else:
            text += "⚠️ Не удалось распознать карточки. Используйте формат: <b>вопрос | ответ</b>\n"
        text += f"📋 Всего в колоде: <b>{total}</b>\n\n"
        text += "Продолжайте добавлять или нажмите «Завершить»."

        keyboard = [
            [InlineKeyboardButton(
                f"✅ Завершить ({total} карт.)",
                callback_data="fc_teacher_finish"
            )],
            [InlineKeyboardButton("❌ Отмена", callback_data="fc_teacher_menu")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
        return states.FC_TEACHER

    return states.FC_TEACHER


@safe_handler()
async def finish_create_deck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает создание колоды и публикует её."""
    query = update.callback_query
    user_id = query.from_user.id

    draft = context.user_data.get('fc_teacher_draft', {})
    cards = draft.get('cards', [])

    if not cards:
        await query.answer(
            "Добавьте хотя бы одну карточку перед завершением!",
            show_alert=True
        )
        return states.FC_TEACHER

    title = draft.get('title', 'Колода учителя')
    description = draft.get('description', '')

    deck_id = await create_teacher_deck(
        teacher_id=user_id,
        title=title,
        description=description,
        cards=cards,
    )

    students = await get_teacher_students(user_id)
    student_count = len(students)

    text = f"<b>✅ Колода создана!</b>\n\n"
    text += f"📖 <b>{title}</b>\n"
    text += f"🃏 Карточек: {len(cards)}\n"

    if student_count > 0:
        text += f"👥 Доступна <b>{student_count}</b> ученикам\n"
    else:
        text += "👥 Подключите учеников, чтобы они получили доступ\n"

    context.user_data.pop('fc_teacher_draft', None)

    keyboard = [
        [InlineKeyboardButton(
            "🎯 Открыть колоду", callback_data=f"fc_deck_{deck_id}"
        )],
        [InlineKeyboardButton("📖 Мои колоды", callback_data="fc_teacher_menu")],
        [InlineKeyboardButton("◀️ К карточкам", callback_data="fc_back_to_decks")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.FC_MENU
