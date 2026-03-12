"""
Telegram-хендлеры для модуля карточек (Flashcards).

Основные экраны:
1. Главное меню карточек (список колод)
2. Меню колоды (статистика, начать повторение)
3. Экран карточки (лицевая сторона)
4. Экран карточки (обратная сторона + самооценка)
5. Итоги сессии повторения
"""

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Dict, Any, List, Optional

from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states, db
from core.error_handler import safe_handler
from core.utils import safe_edit_message
from core.menu_handlers import handle_to_main_menu
from core.streak_manager import get_streak_manager

from . import db as flashcard_db
from .sm2 import review_card
from .deck_generator import generate_all_decks, generate_mistakes_deck
from .daily_challenge import ensure_challenge_table
from .leaderboard import add_xp, ensure_leaderboard_tables, XP_CARD_CORRECT, XP_CARD_WRONG
from .teacher_decks import ensure_teacher_decks_tables
from .duels import ensure_duel_tables

logger = logging.getLogger(__name__)


# ============================================================
# ПРОВЕРКА ПОДПИСКИ
# ============================================================

async def _has_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, есть ли у пользователя активная подписка (любая)."""
    try:
        # Проверяем админов — у них всегда есть доступ
        from core import config
        admin_ids = []
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = [int(x.strip()) for x in config.ADMIN_IDS.split(',') if x.strip()]
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = config.ADMIN_IDS
        if user_id in admin_ids:
            return True

        subscription_manager = context.bot_data.get('subscription_manager')
        if not subscription_manager:
            from payment.subscription_manager import SubscriptionManager
            subscription_manager = SubscriptionManager()
        result = await subscription_manager.check_active_subscription(user_id)
        return result is not None
    except Exception as e:
        logger.warning(f"Error checking subscription for user {user_id}: {e}")
        return True  # При ошибке даём доступ, чтобы не блокировать


# Константы состояний
FC_MENU = states.FC_MENU
FC_DECK_VIEW = states.FC_DECK_VIEW
FC_REVIEWING = states.FC_REVIEWING


async def init_flashcards_data() -> None:
    """Инициализация: создание таблиц и генерация колод."""
    try:
        await flashcard_db.ensure_tables()
        await ensure_challenge_table()
        await ensure_leaderboard_tables()
        await ensure_teacher_decks_tables()
        await ensure_duel_tables()
        await generate_all_decks()
        # Экспортируем данные в статический JSON для WebApp
        await _export_webapp_json()
        logger.info("Flashcards module initialized")
    except Exception as e:
        logger.error(f"Failed to initialize flashcards: {e}", exc_info=True)


async def _export_webapp_json() -> None:
    """Генерирует flashcards-data.json для WebApp (чтобы не зависеть от API)."""
    try:
        data = await flashcard_db.export_all_decks_json()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        json_path = os.path.join(base_dir, 'WebApp', 'flashcards-data.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        logger.info(f"Exported {len(data)} decks to {json_path}")
    except Exception as e:
        logger.warning(f"Could not export webapp JSON: {e}")


# ============================================================
# ГЛАВНОЕ МЕНЮ КАРТОЧЕК
# ============================================================

@safe_handler()
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в модуль карточек из главного меню."""
    await show_decks_menu(update, context)
    return FC_MENU


@safe_handler()
async def cmd_flashcards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /flashcards."""
    await show_decks_menu(update, context)
    return FC_MENU


async def show_decks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список колод с прогрессом пользователя."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id

    has_sub = await _has_subscription(user_id, context)

    decks = await flashcard_db.get_all_decks()
    overall = await flashcard_db.get_user_overall_stats(user_id)

    text = "<b>🃏 Карточки для заучивания</b>\n\n"
    text += "Выберите колоду для повторения.\n"
    text += "Система запоминает, что вы знаете хорошо, а что нужно повторить чаще.\n\n"

    if not has_sub:
        text += "🔒 <i>Карточки доступны по подписке</i>\n\n"

    if overall['total_reviews'] > 0:
        text += f"<b>📊 Ваш прогресс:</b>\n"
        text += f"• Изучено карточек: {overall['unique_cards']}\n"
        text += f"• Всего повторений: {overall['total_reviews']}\n\n"

    # Группируем колоды по категориям
    categories: Dict[str, List[Dict]] = {}
    for deck in decks:
        cat = deck['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(deck)

    keyboard = []
    for cat_name, cat_decks in categories.items():
        for deck in cat_decks:
            deck_stats = await flashcard_db.get_deck_stats(user_id, deck['id'])
            due = deck_stats['due_today']
            total = deck_stats['total']
            mastered = deck_stats['mastered']

            # Индикатор прогресса
            if has_sub:
                if total > 0:
                    pct = int(mastered / total * 100)
                    if pct >= 80:
                        progress = "✅"
                    elif pct >= 40:
                        progress = "📗"
                    elif mastered > 0:
                        progress = "📘"
                    else:
                        progress = "🆕"
                else:
                    progress = "🆕"
            else:
                progress = "🔒"

            due_label = f" ({due} к повт.)" if due > 0 and has_sub else ""

            keyboard.append([InlineKeyboardButton(
                f"{deck['icon']} {deck['title']} {progress}{due_label}",
                callback_data=f"fc_deck_{deck['id']}"
            )])

    # Разделитель — режимы
    keyboard.append([InlineKeyboardButton(
        "🏆 Ежедневный челлендж", callback_data="fc_daily_menu"
    )])
    keyboard.append([
        InlineKeyboardButton("📝 Планы (зад. 24)", callback_data="fc_plan_menu"),
    ])
    keyboard.append([InlineKeyboardButton(
        "🔴 Мои ошибки", callback_data="fc_gen_mistakes"
    )])
    # Социальные элементы
    keyboard.append([
        InlineKeyboardButton("🏅 Лидерборд", callback_data="fc_leaderboard"),
        InlineKeyboardButton("⚔️ Дуэли", callback_data="fc_duel_menu"),
    ])
    keyboard.append([InlineKeyboardButton(
        "📖 Учительские колоды", callback_data="fc_teacher_menu"
    )])
    keyboard.append([InlineKeyboardButton(
        "🏠 Главное меню", callback_data="to_main_menu"
    )])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await safe_edit_message(
            query.message, text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )


# ============================================================
# МЕНЮ КОЛОДЫ
# ============================================================

@safe_handler()
async def show_deck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали колоды и статистику."""
    query = update.callback_query
    user_id = query.from_user.id

    deck_id = query.data.replace("fc_deck_", "")
    context.user_data['fc_current_deck'] = deck_id

    deck = await flashcard_db.get_deck(deck_id)
    if not deck:
        await query.answer("Колода не найдена", show_alert=True)
        return FC_MENU

    # --- Проверка подписки ---
    has_sub = await _has_subscription(user_id, context)
    if not has_sub:
        text = f"<b>🔒 {deck['icon']} {deck['title']}</b>\n\n"
        text += f"{deck.get('description', '')}\n\n"
        text += "Для доступа к карточкам необходима подписка.\n"
        text += "Оформите подписку, чтобы учить материал с помощью карточек!"

        keyboard = [
            [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
            [InlineKeyboardButton("◀️ Назад к колодам", callback_data="fc_back_to_decks")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(
            query.message, text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return FC_DECK_VIEW

    stats = await flashcard_db.get_deck_stats(user_id, deck_id)

    # Визуальный прогресс-бар
    total = stats['total']
    mastered = stats['mastered']
    reviewing = stats['reviewing']
    new = stats['new']

    if total > 0:
        bar_len = 20
        mastered_blocks = round(mastered / total * bar_len)
        reviewing_blocks = round(reviewing / total * bar_len)
        new_blocks = bar_len - mastered_blocks - reviewing_blocks
        progress_bar = "🟩" * mastered_blocks + "🟨" * reviewing_blocks + "⬜" * new_blocks
        pct = round(mastered / total * 100)
    else:
        progress_bar = "⬜" * 20
        pct = 0

    text = f"<b>{deck['icon']} {deck['title']}</b>\n\n"
    text += f"{deck.get('description', '')}\n\n"
    text += f"<b>Прогресс:</b> {pct}%\n"
    text += f"{progress_bar}\n\n"
    text += f"🟩 Выучено: {mastered}  "
    text += f"🟨 Изучаю: {reviewing}  "
    text += f"⬜ Новые: {new}\n\n"

    due = stats['due_today']
    if due > 0:
        text += f"📋 <b>К повторению сегодня: {due}</b>"
    else:
        text += "✅ <b>На сегодня всё повторено!</b>"

    keyboard = []
    if due > 0:
        keyboard.append([InlineKeyboardButton(
            f"🎯 Начать повторение ({due})",
            callback_data="fc_start_review"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            "🔄 Повторить все",
            callback_data="fc_start_review_all"
        )])

    # Quiz-режим (нужно минимум 4 карточки)
    if total >= 4:
        keyboard.append([InlineKeyboardButton(
            "🧩 Quiz-режим", callback_data="fc_start_quiz"
        )])

    # WebApp Swipe-режим
    try:
        from core.config import WEBAPP_URL
        parsed = urlparse(WEBAPP_URL)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        flashcards_url = f"{base_url}/WebApp/flashcards-app.html?deck_id={deck_id}"
        keyboard.append([InlineKeyboardButton(
            "📱 Swipe-режим (WebApp)",
            web_app=WebAppInfo(url=flashcards_url)
        )])
    except Exception:
        pass  # WebApp URL не настроен — пропускаем кнопку

    keyboard.append([InlineKeyboardButton(
        "◀️ Назад к колодам", callback_data="fc_back_to_decks"
    )])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return FC_DECK_VIEW


# ============================================================
# СЕССИЯ ПОВТОРЕНИЯ
# ============================================================

@safe_handler()
async def start_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает сессию повторения карточек."""
    query = update.callback_query
    user_id = query.from_user.id

    deck_id = context.user_data.get('fc_current_deck')
    if not deck_id:
        await query.answer("Выберите колоду", show_alert=True)
        return FC_MENU

    # Получаем карточки для повторения
    cards = await flashcard_db.get_cards_due_for_review(user_id, deck_id, limit=20)

    if not cards:
        await query.answer("Нет карточек для повторения!", show_alert=True)
        return FC_DECK_VIEW

    # Сохраняем сессию
    context.user_data['fc_session'] = {
        'cards': cards,
        'current_index': 0,
        'total': len(cards),
        'correct': 0,
        'again': 0,
        'hard': 0,
        'good': 0,
        'easy': 0,
        'started_at': datetime.now(timezone.utc).isoformat(),
    }

    # Показываем первую карточку
    await _show_card_front(query, context)
    return FC_REVIEWING


@safe_handler()
async def start_review_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает повторение всех карточек колоды (даже если не пора)."""
    query = update.callback_query
    user_id = query.from_user.id
    deck_id = context.user_data.get('fc_current_deck')

    if not deck_id:
        await query.answer("Выберите колоду", show_alert=True)
        return FC_MENU

    # Получаем все карточки колоды
    all_cards_raw = await flashcard_db.get_cards_for_deck(deck_id)

    # Преобразуем формат
    cards = []
    for c in all_cards_raw:
        cards.append({
            'card_id': c['id'],
            'deck_id': c['deck_id'],
            'front_text': c['front_text'],
            'back_text': c['back_text'],
            'hint': c.get('hint'),
            'easiness_factor': 2.5,
            'interval_days': 0,
            'repetition_number': 0,
            'is_new': 0,
            'total_reviews': 0,
        })

    if not cards:
        await query.answer("В колоде нет карточек!", show_alert=True)
        return FC_DECK_VIEW

    context.user_data['fc_session'] = {
        'cards': cards,
        'current_index': 0,
        'total': len(cards),
        'correct': 0,
        'again': 0,
        'hard': 0,
        'good': 0,
        'easy': 0,
        'started_at': datetime.now(timezone.utc).isoformat(),
    }

    await _show_card_front(query, context)
    return FC_REVIEWING


async def _show_card_front(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает лицевую сторону карточки."""
    session = context.user_data.get('fc_session', {})
    cards = session.get('cards', [])
    idx = session.get('current_index', 0)

    if idx >= len(cards):
        return

    card = cards[idx]
    total = session['total']

    # Индикатор новой карточки
    new_badge = " 🆕" if card.get('is_new') else ""

    text = f"<b>🃏 Карточка {idx + 1}/{total}{new_badge}</b>\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"{card['front_text']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "<i>Постарайтесь вспомнить ответ, затем нажмите «Показать ответ»</i>"

    keyboard = [
        [InlineKeyboardButton("👁 Показать ответ", callback_data="fc_show_back")],
    ]

    if card.get('hint'):
        keyboard.append([InlineKeyboardButton(
            "💡 Подсказка", callback_data="fc_show_hint"
        )])

    keyboard.append([InlineKeyboardButton(
        "⏹ Завершить", callback_data="fc_end_session"
    )])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def show_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подсказку к карточке."""
    query = update.callback_query
    session = context.user_data.get('fc_session', {})
    cards = session.get('cards', [])
    idx = session.get('current_index', 0)

    if idx >= len(cards):
        return FC_REVIEWING

    card = cards[idx]
    hint_text = card.get('hint', 'Подсказка отсутствует')

    await query.answer(f"💡 {hint_text}", show_alert=True)
    return FC_REVIEWING


@safe_handler()
async def show_card_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает обратную сторону карточки с кнопками самооценки."""
    query = update.callback_query
    session = context.user_data.get('fc_session', {})
    cards = session.get('cards', [])
    idx = session.get('current_index', 0)

    if idx >= len(cards):
        return FC_REVIEWING

    card = cards[idx]
    total = session['total']

    text = f"<b>🃏 Карточка {idx + 1}/{total}</b>\n\n"
    text += "<b>Вопрос:</b>\n"
    text += f"{card['front_text']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "<b>Ответ:</b>\n"
    text += f"{card['back_text']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "<b>Как хорошо вы это знали?</b>"

    keyboard = [
        [
            InlineKeyboardButton("🔴 Не помню", callback_data="fc_rate_0"),
            InlineKeyboardButton("🟠 Сложно", callback_data="fc_rate_1"),
        ],
        [
            InlineKeyboardButton("🟢 Помню", callback_data="fc_rate_2"),
            InlineKeyboardButton("🔵 Легко", callback_data="fc_rate_3"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return FC_REVIEWING


@safe_handler()
async def rate_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает самооценку пользователя и переходит к следующей карточке."""
    query = update.callback_query
    user_id = query.from_user.id

    # Получаем оценку
    rating = int(query.data.replace("fc_rate_", ""))

    session = context.user_data.get('fc_session', {})
    cards = session.get('cards', [])
    idx = session.get('current_index', 0)

    if idx >= len(cards):
        await _show_session_results(query, context)
        return FC_DECK_VIEW

    card = cards[idx]

    # Применяем SM-2
    result = review_card(
        quality=rating,
        repetition_number=card.get('repetition_number', 0),
        easiness_factor=card.get('easiness_factor', 2.5),
        interval_days=card.get('interval_days', 0),
    )

    # Сохраняем прогресс
    is_correct = rating >= 2
    await flashcard_db.update_card_progress(
        user_id=user_id,
        card_id=card['card_id'],
        deck_id=card['deck_id'],
        easiness_factor=result.easiness_factor,
        interval_days=result.interval_days,
        repetition_number=result.repetition_number,
        next_review=result.next_review.isoformat(),
        is_correct=is_correct,
    )

    # Начисляем XP
    xp = XP_CARD_CORRECT if is_correct else XP_CARD_WRONG
    await add_xp(user_id, xp, 'card_review', f"card_{card['card_id']}")

    # Обновляем статистику сессии
    rating_keys = {0: 'again', 1: 'hard', 2: 'good', 3: 'easy'}
    session[rating_keys[rating]] += 1
    if is_correct:
        session['correct'] += 1

    # Переходим к следующей карточке
    session['current_index'] = idx + 1

    if session['current_index'] >= len(cards):
        # Сессия завершена
        await _finish_session(query, context, user_id)
        return FC_DECK_VIEW
    else:
        # Следующая карточка
        await _show_card_front(query, context)
        return FC_REVIEWING


async def _finish_session(query, context, user_id: int) -> None:
    """Завершает сессию, обновляет стрик, показывает результаты."""
    # Обновляем стрик
    streak_manager = get_streak_manager()
    current_date = date.today().isoformat()
    last_activity = context.user_data.get('last_activity_date')

    if last_activity != current_date:
        await streak_manager.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date

    session = context.user_data.get('fc_session', {})
    correct = session.get('correct', 0)
    total = session.get('total', 0)

    if total > 0:
        is_correct = correct / total >= 0.5
        await streak_manager.update_correct_streak(user_id, is_correct)

    await _show_session_results(query, context)


async def _show_session_results(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает итоги сессии повторения."""
    session = context.user_data.get('fc_session', {})

    total = session.get('total', 0)
    again = session.get('again', 0)
    hard = session.get('hard', 0)
    good = session.get('good', 0)
    easy = session.get('easy', 0)
    reviewed = again + hard + good + easy

    # Прогресс-бар по оценкам
    if reviewed > 0:
        pct_good = round((good + easy) / reviewed * 100)
    else:
        pct_good = 0

    text = "<b>🏁 Сессия завершена!</b>\n\n"
    text += f"Повторено карточек: <b>{reviewed}</b> из {total}\n\n"

    text += "<b>Результаты:</b>\n"
    if again > 0:
        text += f"🔴 Не помню: {again}\n"
    if hard > 0:
        text += f"🟠 Сложно: {hard}\n"
    if good > 0:
        text += f"🟢 Помню: {good}\n"
    if easy > 0:
        text += f"🔵 Легко: {easy}\n"

    text += f"\n<b>Знание: {pct_good}%</b>\n"

    if pct_good >= 80:
        text += "\n🌟 Отличный результат! Продолжайте в том же духе!"
    elif pct_good >= 50:
        text += "\n📈 Хороший прогресс! Продолжайте повторять."
    else:
        text += "\n💪 Не сдавайтесь! Регулярное повторение — ключ к успеху."

    deck_id = context.user_data.get('fc_current_deck', '')

    keyboard = [
        [InlineKeyboardButton("🔄 Повторить ещё", callback_data="fc_start_review")],
        [InlineKeyboardButton("◀️ К колоде", callback_data=f"fc_deck_{deck_id}")],
        [InlineKeyboardButton("📋 Все колоды", callback_data="fc_back_to_decks")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@safe_handler()
async def end_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Досрочное завершение сессии."""
    query = update.callback_query
    user_id = query.from_user.id

    await _finish_session(query, context, user_id)
    return FC_DECK_VIEW


# ============================================================
# НАВИГАЦИЯ
# ============================================================

@safe_handler()
async def back_to_decks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к списку колод."""
    await show_decks_menu(update, context)
    return FC_MENU


@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    return await handle_to_main_menu(update, context)


@safe_handler()
async def generate_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерирует колоду карточек из ошибок пользователя."""
    query = update.callback_query
    user_id = query.from_user.id

    await query.answer("⏳ Генерирую карточки из ваших ошибок...", show_alert=False)

    try:
        count = await generate_mistakes_deck(user_id)
    except Exception as e:
        logger.error(f"Failed to generate mistakes deck: {e}", exc_info=True)
        count = 0

    if count == 0:
        await query.answer(
            "У вас пока нет ошибок или не удалось создать карточки. "
            "Порешайте задания, а потом возвращайтесь!",
            show_alert=True
        )
        return FC_MENU

    # Переходим к созданной колоде
    deck_id = f"mistakes_{user_id}"
    context.user_data['fc_current_deck'] = deck_id

    deck = await flashcard_db.get_deck(deck_id)
    if not deck:
        await show_decks_menu(update, context)
        return FC_MENU

    stats = await flashcard_db.get_deck_stats(user_id, deck_id)

    text = f"<b>🔴 Карточки из ошибок</b>\n\n"
    text += f"Создано <b>{count}</b> карточек на основе ваших ошибок.\n"
    text += f"Повторяйте их, чтобы не допускать тех же ошибок на экзамене!\n\n"
    text += f"📋 К повторению: <b>{stats['due_today']}</b>"

    keyboard = [
        [InlineKeyboardButton(
            f"🎯 Начать повторение ({stats['due_today']})",
            callback_data="fc_start_review"
        )],
        [InlineKeyboardButton("◀️ Назад к колодам", callback_data="fc_back_to_decks")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        query.message, text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return FC_DECK_VIEW


@safe_handler()
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel — выход из модуля."""
    await update.message.reply_text("Выход из карточек.")
    return ConversationHandler.END


# ============================================================
# ОБРАБОТКА ДАННЫХ ИЗ WEBAPP (sendData)
# ============================================================

async def handle_webapp_review_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает результаты сессии повторения из WebApp.

    WebApp отправляет JSON:
    {
        "action": "review_results",
        "deck_id": "...",
        "reviews": [{"card_id": "...", "rating": 0-3}, ...]
    }
    """
    try:
        data = json.loads(update.effective_message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError):
        return

    if data.get('action') != 'review_results':
        return

    user_id = update.effective_user.id
    deck_id = data.get('deck_id', '')
    reviews = data.get('reviews', [])

    if not reviews:
        return

    correct_count = 0
    total_count = len(reviews)

    for rev in reviews:
        card_id = rev.get('card_id', '')
        rating = rev.get('rating', 0)
        if not card_id:
            continue

        # SM-2
        progress = await flashcard_db.get_card_progress(user_id, card_id)
        rep_number = progress.get('repetition_number', 0) if progress else 0
        ef = progress.get('easiness_factor', 2.5) if progress else 2.5
        interval = progress.get('interval_days', 0) if progress else 0

        result = review_card(
            quality=rating,
            repetition_number=rep_number,
            easiness_factor=ef,
            interval_days=interval,
        )

        is_correct = rating >= 2
        if is_correct:
            correct_count += 1

        await flashcard_db.update_card_progress(
            user_id=user_id,
            card_id=card_id,
            deck_id=deck_id,
            easiness_factor=result.easiness_factor,
            interval_days=result.interval_days,
            repetition_number=result.repetition_number,
            next_review=result.next_review.isoformat(),
            is_correct=is_correct,
        )

        # XP
        xp = XP_CARD_CORRECT if is_correct else XP_CARD_WRONG
        await add_xp(user_id, xp, 'card_review', f'webapp_{card_id}')

    # Обновляем стрик
    streak_manager = get_streak_manager()
    current_date = date.today().isoformat()
    last_activity = context.user_data.get('last_activity_date')
    if last_activity != current_date:
        await streak_manager.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date

    if total_count > 0:
        is_good = correct_count / total_count >= 0.5
        await streak_manager.update_correct_streak(user_id, is_good)

    # Подтверждение
    pct = round(correct_count / total_count * 100) if total_count > 0 else 0
    await update.effective_message.reply_text(
        f"✅ Результаты из WebApp сохранены!\n\n"
        f"Повторено: {total_count} карточек\n"
        f"Знание: {pct}%",
        parse_mode=ParseMode.HTML,
    )
