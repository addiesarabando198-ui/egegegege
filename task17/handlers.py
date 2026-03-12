"""Обработчики для задания 17 ЕГЭ по обществознанию."""

import json
import logging
import os
import random
from datetime import date, datetime
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import db, states
from core.error_handler import safe_handler
from core.menu_handlers import handle_to_main_menu
from core.plugin_loader import build_main_menu
from core.states import ANSWERING_T17
from core.streak_manager import get_streak_manager
from core.ui_helpers import (
    get_motivational_message,
    get_personalized_greeting,
    show_ai_evaluation_animation,
    show_streak_notification,
)
from core.utils import safe_edit_message

logger = logging.getLogger(__name__)

TASK_CODE = "task17"
MAX_SCORE = 2

# Глобальные данные
passages_data: Dict[str, Any] = {}

# Evaluator
try:
    from .evaluator import Task17AIEvaluator

    evaluator = Task17AIEvaluator()
    EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import task17 evaluator: {e}")
    evaluator = None
    EVALUATOR_AVAILABLE = False


# ====================================================================
# Инициализация данных
# ====================================================================

async def init_task17_data():
    """Загрузка текстовых отрывков для заданий 17 (и 18)."""
    global passages_data

    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        json_path = os.path.join(base_dir, "data", "text_passages_17_18.json")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            passages_data = data
            count = len(data.get("passages", []))
            logger.info(f"Loaded {count} text passages for task17")
    except Exception as e:
        logger.error(f"Failed to load task17 data: {e}")
        passages_data = {"passages": [], "metadata": {}}


# ====================================================================
# Точки входа
# ====================================================================

@safe_handler()
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход из главного меню."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def cmd_task17(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task17."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


# ====================================================================
# Главное меню задания
# ====================================================================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню задания 17."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id

    stats = await get_user_stats(user_id)
    greeting = get_personalized_greeting(stats)

    text = f"""{greeting}

<b>📖 Задание 17 — Анализ текста</b>

Вам будет дан текстовый фрагмент и вопрос к нему. Нужно найти
и назвать конкретные элементы (функции, признаки, виды и т.д.),
которые <b>прямо названы в тексте</b>.

<b>Система оценивания (макс. 2 балла):</b>
• 2 балла — правильно названы все элементы
• 1 балл — правильно названа часть элементов
• 0 баллов — ответ неправильный

<b>📊 Ваша статистика:</b>
• Решено заданий: {stats['total_attempts']}
• Средний балл: {stats['avg_score']:.1f}/2
• Всего текстов: {stats['total_tasks']}"""

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t17_practice")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t17_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await safe_edit_message(
            query.message, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )


# ====================================================================
# Практика
# ====================================================================

@safe_handler()
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбрать случайный текст и показать задание 17."""
    query = update.callback_query

    passage = _get_random_passage()
    if not passage:
        await query.message.edit_text(
            "❌ Не удалось загрузить задание. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]]
            ),
        )
        return states.CHOOSING_MODE

    task17_data = passage.get("task17", {})

    # Сохраняем в контекст
    context.user_data["current_t17_passage"] = passage
    context.user_data["t17_start_time"] = datetime.now()

    text_fragment = passage["text"]
    question = task17_data.get("question", "")
    source = passage.get("source", "")

    msg = f"""<b>📖 Задание 17</b>

<b>Прочитайте текст и выполните задание.</b>

<i>{source}</i>

{text_fragment}

<b>Вопрос:</b>
{question}

💡 <i>Отправьте ответ одним сообщением. Перечислите элементы нумерованным списком.</i>"""

    keyboard = [
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t17_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    return ANSWERING_T17


def _get_random_passage() -> Optional[Dict[str, Any]]:
    """Выбрать случайный текстовый отрывок, у которого есть task17."""
    passages = passages_data.get("passages", [])
    valid = [p for p in passages if "task17" in p]
    if not valid:
        return None
    return random.choice(valid)


# ====================================================================
# Обработка ответа
# ====================================================================

@safe_handler()
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа ученика на задание 17."""
    user_id = update.effective_user.id
    answer = update.message.text.strip()

    passage = context.user_data.get("current_t17_passage")
    if not passage:
        await update.message.reply_text(
            "❌ Ошибка: задание не найдено. Начните заново.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]]
            ),
        )
        return states.CHOOSING_MODE

    task17 = passage.get("task17", {})

    # Собираем данные для evaluator
    eval_data = {
        "text": passage["text"],
        "question": task17.get("question", ""),
        "correct_answers": task17.get("correct_answers", []),
        "required_count": task17.get("required_count", 3),
        "scoring_notes": task17.get("scoring_notes", ""),
    }

    # Анимация проверки
    thinking_msg = await show_ai_evaluation_animation(update.message, duration=30)

    # AI-проверка
    if EVALUATOR_AVAILABLE and evaluator:
        try:
            result = await evaluator.evaluate(answer, eval_data)
            score = result.total_score
            feedback = result.feedback
            suggestions = result.suggestions or []
        except Exception as e:
            logger.error(f"Task17 evaluation error: {e}")
            score = 0
            feedback = "❌ Ошибка при проверке. Попробуйте позже."
            suggestions = []
    else:
        score = 0
        feedback = "❌ Сервис проверки временно недоступен."
        suggestions = []

    # Удалить анимацию
    try:
        await thinking_msg.delete()
    except Exception:
        pass

    # Сохранение результата
    await save_attempt(user_id, passage.get("id", 0), answer, score)

    # ---- стрики ----
    is_correct = score == MAX_SCORE
    await db.update_progress(user_id, TASK_CODE, is_correct)

    current_date = date.today().isoformat()
    last_activity = context.user_data.get("last_activity_date")
    streak_mgr = get_streak_manager()

    if last_activity != current_date:
        daily_current, daily_max, level = await streak_mgr.update_daily_streak(user_id)
        context.user_data["last_activity_date"] = current_date
        if daily_current in (3, 5, 7, 10, 14, 20, 30, 50, 100):
            await show_streak_notification(update, context, "daily", daily_current)

    correct_current, correct_max = await streak_mgr.update_correct_streak(user_id, is_correct)
    if is_correct and correct_current in (3, 5, 7, 10, 14, 20, 30, 50, 100):
        await show_streak_notification(update, context, "correct", correct_current)
    # ---- конец стриков ----

    result_text = f"""<b>✅ Проверка завершена!</b>

<b>Ваш результат: {score}/{MAX_SCORE} балла</b>

{feedback}
"""

    if suggestions:
        result_text += "\n<b>💡 Рекомендации:</b>\n"
        for i, s in enumerate(suggestions, 1):
            result_text += f"{i}. {s}\n"

    # Правильные ответы
    correct = task17.get("correct_answers", [])
    if correct:
        result_text += "\n<b>📚 Правильные ответы:</b>\n"
        for i, ca in enumerate(correct, 1):
            result_text += f"{i}. {ca}\n"

    keyboard = [
        [InlineKeyboardButton("🔄 Новое задание", callback_data="t17_new")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t17_progress")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t17_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        result_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


# ====================================================================
# Статистика
# ====================================================================

@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику."""
    query = update.callback_query
    user_id = query.from_user.id

    stats = await get_user_stats(user_id)
    detailed = await get_detailed_stats(user_id)

    text = f"""<b>📊 Ваша статистика по заданию 17</b>

<b>Общая статистика:</b>
• Решено заданий: {stats['total_attempts']}
• Средний балл: {stats['avg_score']:.1f}/2
• Всего текстов: {stats['total_tasks']}

<b>Распределение по баллам:</b>
• 2 балла: {detailed['score_2']} раз
• 1 балл: {detailed['score_1']} раз
• 0 баллов: {detailed['score_0']} раз
"""

    if stats["total_attempts"] > 0:
        rate = (detailed["score_2"] / stats["total_attempts"]) * 100
        text += f"\n<b>Процент максимальных баллов:</b> {rate:.1f}%"

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t17_practice")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t17_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message(
        query.message, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


# ====================================================================
# Навигация
# ====================================================================

@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Действие после результата (новое задание)."""
    query = update.callback_query
    action = query.data.split("_")[1]
    if action == "new":
        return await practice_mode(update, context)
    return await show_main_menu(update, context)


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 17."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    return await handle_to_main_menu(update, context)


@safe_handler()
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel."""
    await update.message.reply_text("Выход из задания 17.")
    return ConversationHandler.END


# ====================================================================
# Вспомогательные функции (БД)
# ====================================================================

async def get_user_stats(user_id: int) -> Dict[str, Any]:
    try:
        conn = await db.get_db()
        cursor = await conn.execute(
            """
            SELECT COUNT(*) as total_attempts,
                   COALESCE(AVG(score), 0) as avg_score
            FROM task17_attempts WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        total = row["total_attempts"] if row else 0
        avg = float(row["avg_score"]) if row else 0.0
    except Exception as e:
        logger.error(f"Error getting task17 stats: {e}")
        total, avg = 0, 0.0

    return {
        "total_attempts": total,
        "avg_score": avg,
        "total_tasks": len(passages_data.get("passages", [])),
    }


async def get_detailed_stats(user_id: int) -> Dict[str, int]:
    try:
        conn = await db.get_db()
        cursor = await conn.execute(
            """
            SELECT
                SUM(CASE WHEN score = 2 THEN 1 ELSE 0 END) as score_2,
                SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END) as score_1,
                SUM(CASE WHEN score = 0 THEN 1 ELSE 0 END) as score_0
            FROM task17_attempts WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        if row:
            return {
                "score_2": row["score_2"] or 0,
                "score_1": row["score_1"] or 0,
                "score_0": row["score_0"] or 0,
            }
    except Exception as e:
        logger.error(f"Error getting task17 detailed stats: {e}")

    return {"score_2": 0, "score_1": 0, "score_0": 0}


async def save_attempt(user_id: int, passage_id: int, answer: str, score: int):
    try:
        conn = await db.get_db()
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task17_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                passage_id INTEGER NOT NULL,
                answer TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        await conn.execute(
            """
            INSERT INTO task17_attempts (user_id, passage_id, answer, score, attempted_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (user_id, passage_id, answer, score),
        )
        await conn.commit()
        logger.info(f"Saved task17 attempt: user={user_id}, passage={passage_id}, score={score}")
    except Exception as e:
        logger.error(f"Error saving task17 attempt: {e}")
