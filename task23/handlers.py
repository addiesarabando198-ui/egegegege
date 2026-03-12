"""
Обработчики для задания 23 (Конституция РФ).

Поддерживает два типа вопросов:
- Model Type 1: Одна характеристика, три подтверждения
- Model Type 2: Три характеристики, по одному подтверждению
"""

import logging
import json
import random
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states, db
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

# Глобальные переменные для данных
task23_data: Dict[str, Any] = {}
task23_metadata: Dict[str, Any] = {}

# Импорт evaluator
try:
    from .evaluator import Task23Evaluator
    evaluator = Task23Evaluator()
    EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import evaluator: {e}")
    evaluator = None
    EVALUATOR_AVAILABLE = False

# Константы
MAX_SCORE = 3
TASK_CODE = "task23"


async def init_task23_data() -> None:
    """Инициализация данных задания 23."""
    global task23_data, task23_metadata

    try:
        # Путь к файлу данных
        data_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'data',
            'task23_questions.json'
        )

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            task23_data = data
            task23_metadata = data.get('metadata', {})
            questions_count = len(data.get('questions', []))
            logger.info(f"Loaded {questions_count} questions for task23")

    except FileNotFoundError:
        logger.error(f"Task23 data file not found: {data_path}")
        task23_data = {"questions": [], "metadata": {}}
        task23_metadata = {}
    except Exception as e:
        logger.error(f"Failed to load task23 data: {e}")
        task23_data = {"questions": [], "metadata": {}}
        task23_metadata = {}


def register_handlers(app) -> None:
    """Регистрация обработчиков (вызывается из plugin.py)."""
    pass


@safe_handler()
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в модуль задания 23 из главного меню."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def cmd_task23(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task23 - вход в модуль."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню задания 23."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id

    # Получаем статистику пользователя
    stats = await get_user_stats(user_id)

    questions = task23_data.get('questions', [])

    text = f"""<b>📜 Задание 23 — Конституция РФ</b>

Сформулируйте подтверждения характеристик конституционно-правового статуса РФ на основе Конституции.

<b>Система оценивания:</b>
• 3 балла — все 3 подтверждения верны
• 2 балла — 2 подтверждения верны
• 1 балл — 1 подтверждение верно

<b>📊 Ваша статистика:</b>
• Решено: {stats['total_attempts']} из {len(questions)}
• Средний балл: {stats['avg_score']:.1f}/3"""

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t23_practice")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t23_progress")],
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
    """Начать практику - выбор случайного задания любого типа."""
    return await _start_practice(update, context, model_type=None)


@safe_handler()
async def practice_type1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Практика только с заданиями типа 1."""
    return await _start_practice(update, context, model_type=1)


@safe_handler()
async def practice_type2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Практика только с заданиями типа 2."""
    return await _start_practice(update, context, model_type=2)


async def _start_practice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    model_type: Optional[int] = None
):
    """Начать практику с опциональным выбором типа задания."""
    query = update.callback_query
    user_id = query.from_user.id

    # Выбираем случайное задание
    question = get_random_question(model_type)

    if not question:
        await query.message.edit_text(
            "❌ Не удалось загрузить задание. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return states.CHOOSING_MODE

    # Сохраняем задание в контексте
    context.user_data['current_question'] = question
    context.user_data['task_start_time'] = datetime.now()

    # Формируем текст задания в зависимости от типа
    text = format_question_text(question)

    keyboard = [
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t23_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.ANSWERING_T23


def get_random_question(model_type: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Получить случайный вопрос."""
    questions = task23_data.get('questions', [])

    if not questions:
        return None

    if model_type is not None:
        questions = [q for q in questions if q.get('model_type') == model_type]

    if not questions:
        return None

    return random.choice(questions)


def format_question_text(question: Dict[str, Any]) -> str:
    """Форматирование текста вопроса."""
    model_type = question.get('model_type', 1)
    question_text = question.get('question_text', '')
    characteristics = question.get('characteristics', [])

    if model_type == 1:
        # Тип 1: одна характеристика, 3 подтверждения
        characteristic = characteristics[0] if characteristics else ""

        text = f"""<b>📜 Задание 23</b>

{question_text}

<b>Характеристика:</b>
<i>{characteristic}</i>

Отправьте ответ:
1. ...
2. ...
3. ..."""

    else:
        # Тип 2: три характеристики, по одному подтверждению
        chars_text = ""
        for i, char in enumerate(characteristics, 1):
            chars_text += f"{i}. {char}\n"

        text = f"""<b>📜 Задание 23</b>

{question_text}

<b>Характеристики:</b>
{chars_text}
Отправьте ответ:
1. ...
2. ...
3. ..."""

    return text


@safe_handler()
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    user_id = update.effective_user.id
    answer = update.message.text.strip()

    # Получаем текущее задание
    question = context.user_data.get('current_question')
    if not question:
        await update.message.reply_text(
            "❌ Ошибка: задание не найдено. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return states.CHOOSING_MODE

    # Проверка лимитов AI-проверок (freemium система)
    freemium_manager = context.bot_data.get('freemium_manager')
    is_premium = False

    if freemium_manager:
        can_use, remaining, limit_msg = await freemium_manager.check_ai_limit(user_id, 'task23')

        if not can_use:
            # Показываем paywall с CTA
            keyboard = [
                [InlineKeyboardButton("💎 Попробовать за 1₽", callback_data="subscribe_start")],
                [InlineKeyboardButton("📋 Все тарифы", callback_data="subscribe")],
                [InlineKeyboardButton("◀️ Назад в меню", callback_data="t23_menu")],
            ]
            await update.message.reply_text(
                limit_msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return states.CHOOSING_MODE

        # Получаем информацию о подписке для дифференциации фидбека
        limit_info = await freemium_manager.get_limit_info(user_id, 'task23')
        is_premium = limit_info.get('is_premium', False)

    # Показываем анимацию проверки
    thinking_msg = await show_ai_evaluation_animation(
        update.message,
        duration=40
    )

    # Проверяем ответ через AI
    if EVALUATOR_AVAILABLE and evaluator:
        try:
            result = await evaluator.evaluate(answer, question)
            score = result.total_score
            detailed_feedback = result.feedback
            suggestions = result.suggestions or []

            # Дифференцируем фидбек для premium/freemium
            if is_premium:
                feedback = detailed_feedback
            else:
                # Упрощенный фидбек для freemium пользователей
                if freemium_manager:
                    feedback = freemium_manager.simplify_feedback_for_freemium(
                        detailed_feedback,
                        score,
                        MAX_SCORE
                    )
                else:
                    feedback = detailed_feedback

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
    except Exception:
        pass

    # Регистрируем использование AI-проверки
    if freemium_manager:
        await db.increment_ai_check_usage(user_id)

    # Сохраняем результат в БД
    await save_attempt(user_id, question['id'], answer, score)

    # ========== ИНТЕГРАЦИЯ СО СТРИКАМИ И СТАТИСТИКОЙ ==========
    # Определяем, является ли ответ правильным (для стриков)
    is_correct = score >= 2  # 2+ балла из 3 считаем правильным

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
        logger.info(f"[Task23] Daily streak updated for user {user_id}: {daily_current}/{daily_max}")

        # Показываем уведомление о дневном стрике для milestone значений
        if daily_current in [3, 5, 7, 10, 14, 20, 30, 50, 100]:
            await show_streak_notification(update, context, 'daily', daily_current)

    # Обновляем стрик правильных ответов
    correct_current, correct_max = await streak_manager.update_correct_streak(user_id, is_correct)
    logger.info(f"[Task23] Correct streak for user {user_id}: {correct_current}/{correct_max}")

    # Показываем уведомление о стрике правильных ответов для milestone значений
    if is_correct and correct_current in [3, 5, 7, 10, 14, 20, 30, 50, 100]:
        await show_streak_notification(update, context, 'correct', correct_current)
    # ========== КОНЕЦ ИНТЕГРАЦИИ СО СТРИКАМИ ==========

    # Формируем сообщение с результатом
    model_type = question.get('model_type', 1)
    type_label = "Тип 1 (одна характеристика)" if model_type == 1 else "Тип 2 (три характеристики)"

    result_text = f"""<b>✅ Проверка завершена!</b>

<b>Задание:</b> {type_label}
<b>Ваш результат: {score}/{MAX_SCORE} балла</b>

{feedback}
"""

    if suggestions:
        result_text += "\n\n<b>💡 Рекомендации:</b>\n"
        for i, suggestion in enumerate(suggestions, 1):
            result_text += f"{i}. {suggestion}\n"

    # Добавляем информацию об оставшихся проверках для freemium
    if freemium_manager and not is_premium:
        limit_info = await freemium_manager.get_limit_info(user_id, 'task23')
        remaining_checks = limit_info.get('checks_remaining', 0)
        result_text += f"\n\n<i>🔋 Осталось бесплатных проверок: {remaining_checks}</i>"

    # Добавляем кнопку для показа эталонных ответов
    keyboard = [
        [InlineKeyboardButton("📚 Показать эталонные ответы", callback_data="t23_show_answers")],
        [InlineKeyboardButton("🔄 Новое задание", callback_data="t23_new")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t23_progress")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t23_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        result_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.CHOOSING_MODE


@safe_handler()
async def show_model_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать эталонные ответы."""
    query = update.callback_query

    question = context.user_data.get('current_question')
    if not question:
        await query.message.edit_text(
            "❌ Задание не найдено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад в меню", callback_data="t23_menu")
            ]])
        )
        return states.CHOOSING_MODE

    # Получаем текст эталонных ответов
    if EVALUATOR_AVAILABLE and evaluator:
        answers_text = evaluator.get_model_answers_text(question)
    else:
        answers_text = _format_model_answers(question)

    keyboard = [
        [InlineKeyboardButton("🔄 Новое задание", callback_data="t23_new")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t23_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message(
        query.message,
        answers_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return states.CHOOSING_MODE


def _format_model_answers(question: Dict[str, Any]) -> str:
    """Форматирование эталонных ответов."""
    model_type = question.get('model_type', 1)

    if model_type == 1:
        answers = question.get('model_answers', [])
        text = "<b>📚 Эталонные подтверждения (любые 3 из них):</b>\n\n"
        for i, ans in enumerate(answers, 1):
            text += f"{i}. {ans}\n\n"
    else:
        characteristics = question.get('characteristics', [])
        model_answers = question.get('model_answers', {})

        text = "<b>📚 Эталонные подтверждения:</b>\n\n"
        for i, char in enumerate(characteristics, 1):
            text += f"<b>{i}. {char}</b>\n"
            char_answers = model_answers.get(char, [])
            if char_answers:
                for ans in char_answers:
                    text += f"   • {ans}\n"
            text += "\n"

    return text


@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя."""
    query = update.callback_query
    user_id = query.from_user.id

    stats = await get_user_stats(user_id)
    detailed_stats = await get_detailed_stats(user_id)

    text = f"""<b>📊 Ваша статистика по заданию 23</b>

<b>Общая статистика:</b>
• Решено заданий: {stats['total_attempts']}
• Средний балл: {stats['avg_score']:.1f}/3
• Всего заданий: {stats['total_tasks']}

<b>Распределение по баллам:</b>
• 3 балла: {detailed_stats['score_3']} раз
• 2 балла: {detailed_stats['score_2']} раз
• 1 балл: {detailed_stats['score_1']} раз
• 0 баллов: {detailed_stats['score_0']} раз

<b>По типам заданий:</b>
• Тип 1 (одна характеристика): {detailed_stats['type1_count']} решено
• Тип 2 (три характеристики): {detailed_stats['type2_count']} решено
"""

    if stats['total_attempts'] > 0:
        success_rate = (detailed_stats['score_3'] / stats['total_attempts']) * 100
        text += f"\n<b>Процент максимальных баллов:</b> {success_rate:.1f}%"

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t23_practice")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t23_menu")],
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
    action = query.data.split('_')[-1]

    if action == 'new':
        return await practice_mode(update, context)
    else:
        await show_main_menu(update, context)
        return states.CHOOSING_MODE


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню задания 23."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    return await handle_to_main_menu(update, context)


@safe_handler()
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel - выход из модуля."""
    await update.message.reply_text("Выход из задания 23.")
    return ConversationHandler.END


# === Вспомогательные функции для работы с БД ===

async def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Получить статистику пользователя."""
    try:
        conn = await db.get_db()

        # Проверяем существование таблицы
        await _ensure_table_exists(conn)

        cursor = await conn.execute(
            """
            SELECT
                COUNT(*) as total_attempts,
                COALESCE(AVG(score), 0) as avg_score
            FROM task23_attempts
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

        total_tasks = len(task23_data.get('questions', []))

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
            'total_tasks': len(task23_data.get('questions', []))
        }


async def get_detailed_stats(user_id: int) -> Dict[str, int]:
    """Получить детальную статистику по баллам."""
    try:
        conn = await db.get_db()

        # Проверяем существование таблицы
        await _ensure_table_exists(conn)

        cursor = await conn.execute(
            """
            SELECT
                SUM(CASE WHEN score = 3 THEN 1 ELSE 0 END) as score_3,
                SUM(CASE WHEN score = 2 THEN 1 ELSE 0 END) as score_2,
                SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END) as score_1,
                SUM(CASE WHEN score = 0 THEN 1 ELSE 0 END) as score_0,
                SUM(CASE WHEN question_id LIKE 'task23_0%' AND CAST(SUBSTR(question_id, 8) AS INTEGER) <= 8 THEN 1 ELSE 0 END) as type1_count,
                SUM(CASE WHEN question_id LIKE 'task23_0%' AND CAST(SUBSTR(question_id, 8) AS INTEGER) > 8 THEN 1 ELSE 0 END) as type2_count
            FROM task23_attempts
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = await cursor.fetchone()

        if result:
            return {
                'score_3': result['score_3'] or 0,
                'score_2': result['score_2'] or 0,
                'score_1': result['score_1'] or 0,
                'score_0': result['score_0'] or 0,
                'type1_count': result['type1_count'] or 0,
                'type2_count': result['type2_count'] or 0
            }
        else:
            return {
                'score_3': 0, 'score_2': 0, 'score_1': 0, 'score_0': 0,
                'type1_count': 0, 'type2_count': 0
            }

    except Exception as e:
        logger.error(f"Error getting detailed stats: {e}")
        return {
            'score_3': 0, 'score_2': 0, 'score_1': 0, 'score_0': 0,
            'type1_count': 0, 'type2_count': 0
        }


async def save_attempt(
    user_id: int,
    question_id: str,
    answer: str,
    score: int
) -> None:
    """Сохранить попытку в БД."""
    try:
        conn = await db.get_db()

        # Проверяем существование таблицы
        await _ensure_table_exists(conn)

        await conn.execute(
            """
            INSERT INTO task23_attempts (user_id, question_id, answer, score, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (user_id, question_id, answer, score)
        )
        await conn.commit()
        logger.info(f"Saved attempt for user {user_id}, question {question_id}, score {score}")

    except Exception as e:
        logger.error(f"Error saving attempt: {e}")


async def _ensure_table_exists(conn) -> None:
    """Проверить и создать таблицу если не существует."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task23_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            answer TEXT,
            score INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.commit()
