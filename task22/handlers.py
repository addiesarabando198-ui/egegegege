"""Обработчики для задания 22."""

import logging
import json
import random
from typing import Optional, Dict, Any
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states, db
from core.states import ANSWERING_T22
from core.error_handler import safe_handler
from core.plugin_loader import build_main_menu
from core.utils import safe_edit_message
from core.menu_handlers import handle_to_main_menu
from core.ui_helpers import (
    show_thinking_animation,
    show_ai_evaluation_animation,
    get_personalized_greeting,
    get_motivational_message,
    show_streak_notification,
)
from core.streak_manager import get_streak_manager

logger = logging.getLogger(__name__)

# Константы
TASK_CODE = "task22"
MAX_SCORE = 4

# Глобальные переменные для данных
task22_data = {}

# Импорт evaluator
try:
    from .evaluator import Task22AIEvaluator
    evaluator = Task22AIEvaluator()
    EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import evaluator: {e}")
    evaluator = None
    EVALUATOR_AVAILABLE = False


async def init_task22_data():
    """Инициализация данных задания 22."""
    global task22_data

    try:
        import os
        current_dir = os.path.dirname(__file__)
        json_path = os.path.join(current_dir, 'task22_topics.json')

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            task22_data = data
            logger.info(f"Loaded {len(data.get('tasks', []))} tasks for task22")

    except Exception as e:
        logger.error(f"Failed to load task22 data: {e}")
        task22_data = {"tasks": [], "metadata": {}}


@safe_handler()
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в модуль задания 22 из главного меню."""
    query = update.callback_query
    user_id = query.from_user.id

    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def cmd_task22(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task22 - вход в модуль."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать главное меню задания 22."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id

    # Получаем статистику пользователя
    stats = await get_user_stats(user_id)

    greeting = get_personalized_greeting(stats)
    text = f"""{greeting}

<b>📝 Задание 22 - Анализ ситуаций</b>

Задание 22 представляет собой задание-задачу. Оно содержит описание конкретной ситуации и четыре вопроса.

<b>Система оценивания:</b>
• 4 балла - правильные ответы на 4 вопроса
• 3 балла - правильные ответы на 3 вопроса
• 2 балла - правильные ответы на 2 вопроса
• 1 балл - правильный ответ на 1 вопрос

<b>📝 Формат ответа:</b>
Отправляйте все 4 ответа одним сообщением в виде нумерованного списка:
1. Ваш ответ на первый вопрос
2. Ваш ответ на второй вопрос
3. Ваш ответ на третий вопрос
4. Ваш ответ на четвёртый вопрос

<b>📊 Ваша статистика:</b>
• Решено заданий: {stats['total_attempts']}
• Средний балл: {stats['avg_score']:.1f}/4
• Всего заданий доступно: {stats['total_tasks']}"""

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t22_practice")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t22_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await safe_edit_message(
            query.message,
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )


@safe_handler()
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать практику - выбор случайного задания."""
    query = update.callback_query
    user_id = query.from_user.id

    # Выбираем случайное задание
    task = get_random_task()

    if not task:
        await query.message.edit_text(
            "❌ Не удалось загрузить задание. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return states.CHOOSING_MODE

    # Сохраняем задание в контексте
    context.user_data['current_task'] = task
    context.user_data['task_start_time'] = datetime.now()

    # Формируем текст задания
    text = f"""<b>📝 Задание 22</b>

<b>Описание ситуации:</b>
{task['description']}

<b>Вопросы:</b>
"""
    for i, question in enumerate(task['questions'], 1):
        text += f"{i}. {question}\n"

    text += """\n💡 <i>Ответьте на все 4 вопроса нумерованным списком (1. ... 2. ... 3. ... 4. ...)</i>"""

    keyboard = [
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t22_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return ANSWERING_T22


def get_random_task() -> Optional[Dict[str, Any]]:
    """Получить случайное задание."""
    tasks = task22_data.get('tasks', [])
    if not tasks:
        return None
    return random.choice(tasks)


@safe_handler()
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    user_id = update.effective_user.id
    answer = update.message.text.strip()

    # Получаем текущее задание
    task = context.user_data.get('current_task')
    if not task:
        await update.message.reply_text(
            "❌ Ошибка: задание не найдено. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return states.CHOOSING_MODE

    # Показываем анимацию проверки
    thinking_msg = await show_ai_evaluation_animation(
        update.message,
        duration=40
    )

    # Проверяем ответ через AI
    if EVALUATOR_AVAILABLE and evaluator:
        try:
            result = await evaluator.evaluate(answer, task)
            score = result.total_score
            feedback = result.feedback
            suggestions = result.suggestions
        except Exception as e:
            logger.error(f"Error evaluating answer: {e}")
            score = 0
            feedback = "❌ Ошибка при проверке ответа. Попробуйте позже."
            suggestions = []
    else:
        score = 0
        feedback = "❌ Сервис проверки временно недоступен."
        suggestions = []

    # Удаляем анимацию
    try:
        await thinking_msg.delete()
    except:
        pass

    # Сохраняем результат в БД
    await save_attempt(user_id, task['id'], answer, score)

    # ========== ИНТЕГРАЦИЯ СО СТРИКАМИ И СТАТИСТИКОЙ ==========
    # Определяем, является ли ответ правильным (для стриков)
    is_correct = score >= 3  # 3+ балла из 4 считаем правильным

    # Обновляем общую статистику прогресса
    await db.update_progress(user_id, TASK_CODE, is_correct)

    # Обновляем дневной стрик (только раз в день)
    current_date = date.today().isoformat()
    last_activity_date = context.user_data.get('last_activity_date')
    streak_manager = get_streak_manager()

    daily_current = 0
    if last_activity_date != current_date:
        daily_current, daily_max, level = await streak_manager.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date
        logger.info(f"[Task22] Daily streak updated for user {user_id}: {daily_current}/{daily_max}")

        # Показываем уведомление о дневном стрике для milestone значений
        if daily_current in [3, 5, 7, 10, 14, 20, 30, 50, 100]:
            await show_streak_notification(update, context, 'daily', daily_current)

    # Обновляем стрик правильных ответов
    correct_current, correct_max = await streak_manager.update_correct_streak(user_id, is_correct)
    logger.info(f"[Task22] Correct streak for user {user_id}: {correct_current}/{correct_max}")

    # Показываем уведомление о стрике правильных ответов для milestone значений
    if is_correct and correct_current in [3, 5, 7, 10, 14, 20, 30, 50, 100]:
        await show_streak_notification(update, context, 'correct', correct_current)
    # ========== КОНЕЦ ИНТЕГРАЦИИ СО СТРИКАМИ ==========

    # Формируем сообщение с результатом
    result_text = f"""<b>✅ Проверка завершена!</b>

<b>Ваш результат: {score}/4 балла</b>

{feedback}
"""

    if suggestions:
        result_text += "\n\n<b>💡 Рекомендации:</b>\n"
        for i, suggestion in enumerate(suggestions, 1):
            result_text += f"{i}. {suggestion}\n"

    # Показываем правильные ответы
    result_text += "\n\n<b>📚 Правильные ответы:</b>\n"
    for i, correct_answer in enumerate(task['correct_answers'], 1):
        result_text += f"{i}. {correct_answer}\n"

    keyboard = [
        [InlineKeyboardButton("🔄 Новое задание", callback_data="t22_new")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t22_progress")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t22_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.CHOOSING_MODE


@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя."""
    query = update.callback_query
    user_id = query.from_user.id

    stats = await get_user_stats(user_id)
    detailed_stats = await get_detailed_stats(user_id)

    text = f"""<b>📊 Ваша статистика по заданию 22</b>

<b>Общая статистика:</b>
• Решено заданий: {stats['total_attempts']}
• Средний балл: {stats['avg_score']:.1f}/4
• Всего заданий доступно: {stats['total_tasks']}

<b>Распределение по баллам:</b>
• 4 балла: {detailed_stats['score_4']} раз
• 3 балла: {detailed_stats['score_3']} раз
• 2 балла: {detailed_stats['score_2']} раз
• 1 балл: {detailed_stats['score_1']} раз
• 0 баллов: {detailed_stats['score_0']} раз
"""

    if stats['total_attempts'] > 0:
        success_rate = (detailed_stats['score_4'] / stats['total_attempts']) * 100
        text += f"\n<b>Процент максимальных баллов:</b> {success_rate:.1f}%"

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t22_practice")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t22_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message(
        query.message,
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.CHOOSING_MODE


@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после результата (новое задание)."""
    query = update.callback_query
    action = query.data.split('_')[1]

    if action == 'new':
        return await practice_mode(update, context)
    else:
        return await show_main_menu(update, context)


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню задания 22."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    return await handle_to_main_menu(update, context)


@safe_handler()
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel - выход из модуля."""
    await update.message.reply_text("Выход из задания 22.")
    return ConversationHandler.END


# === Вспомогательные функции ===

async def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Получить статистику пользователя."""
    try:
        conn = await db.get_db()
        cursor = await conn.execute(
            """
            SELECT
                COUNT(*) as total_attempts,
                COALESCE(AVG(score), 0) as avg_score
            FROM task22_attempts
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = await cursor.fetchone()

        if result:
            total_attempts = result['total_attempts']
            avg_score = float(result['avg_score'])
        else:
            total_attempts = 0
            avg_score = 0.0

        total_tasks = len(task22_data.get('tasks', []))

        return {
            'total_attempts': total_attempts,
            'avg_score': avg_score,
            'total_tasks': total_tasks
        }

    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        return {
            'total_attempts': 0,
            'avg_score': 0.0,
            'total_tasks': len(task22_data.get('tasks', []))
        }


async def get_detailed_stats(user_id: int) -> Dict[str, int]:
    """Получить детальную статистику по баллам."""
    try:
        conn = await db.get_db()
        cursor = await conn.execute(
            """
            SELECT
                SUM(CASE WHEN score = 4 THEN 1 ELSE 0 END) as score_4,
                SUM(CASE WHEN score = 3 THEN 1 ELSE 0 END) as score_3,
                SUM(CASE WHEN score = 2 THEN 1 ELSE 0 END) as score_2,
                SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END) as score_1,
                SUM(CASE WHEN score = 0 THEN 1 ELSE 0 END) as score_0
            FROM task22_attempts
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = await cursor.fetchone()

        if result:
            return {
                'score_4': result['score_4'] or 0,
                'score_3': result['score_3'] or 0,
                'score_2': result['score_2'] or 0,
                'score_1': result['score_1'] or 0,
                'score_0': result['score_0'] or 0,
            }
        else:
            return {
                'score_4': 0,
                'score_3': 0,
                'score_2': 0,
                'score_1': 0,
                'score_0': 0,
            }

    except Exception as e:
        logger.error(f"Error getting detailed stats: {e}")
        return {
            'score_4': 0,
            'score_3': 0,
            'score_2': 0,
            'score_1': 0,
            'score_0': 0,
        }


async def save_attempt(user_id: int, task_id: int, answer: str, score: int):
    """Сохранить попытку решения задания."""
    try:
        conn = await db.get_db()
        await conn.execute(
            """
            INSERT INTO task22_attempts (user_id, task_id, answer, score, attempted_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (user_id, task_id, answer, score)
        )
        await conn.commit()
        logger.info(f"Saved task22 attempt for user {user_id}: task_id={task_id}, score={score}")

    except Exception as e:
        logger.error(f"Error saving task22 attempt: {e}")
