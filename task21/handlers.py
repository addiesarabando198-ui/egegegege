"""
Обработчики для задания 21 (Анализ графиков спроса и предложения).

Задание на анализ графического изображения изменения спроса/предложения
на конкретном рынке и ответ на три вопроса.
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
task21_data: Dict[str, Any] = {}
task21_metadata: Dict[str, Any] = {}

# Импорт evaluator
try:
    from .evaluator import Task21Evaluator
    evaluator = Task21Evaluator()
    EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import evaluator: {e}")
    evaluator = None
    EVALUATOR_AVAILABLE = False

# Константы
MAX_SCORE = 3
TASK_CODE = "task21"
MAX_CAPTION_LENGTH = 1024


async def init_task21_data() -> None:
    """Инициализация данных задания 21."""
    global task21_data, task21_metadata

    try:
        # Путь к файлу данных
        data_path = os.path.join(
            os.path.dirname(__file__),
            'task21_questions.json'
        )

        logger.info(f"Task21: Loading data from {data_path}")

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            task21_data = data
            task21_metadata = data.get('metadata', {})
            # Поддерживаем оба варианта: 'questions' и 'tasks'
            questions_count = len(data.get('questions', []) or data.get('tasks', []))
            logger.info(f"Task21: Loaded {questions_count} questions successfully")

    except FileNotFoundError:
        logger.error(f"Task21 data file not found: {data_path}")
        task21_data = {"questions": [], "metadata": {}}
        task21_metadata = {}
    except Exception as e:
        logger.error(f"Failed to load task21 data: {e}")
        task21_data = {"questions": [], "metadata": {}}
        task21_metadata = {}


def register_handlers(app) -> None:
    """Регистрация обработчиков (вызывается из plugin.py)."""
    pass


@safe_handler()
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в модуль задания 21 из главного меню."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def cmd_task21(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task21 - вход в модуль."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню задания 21."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id

    # Получаем статистику пользователя
    stats = await get_user_stats(user_id)

    questions = task21_data.get('questions', []) or task21_data.get('tasks', [])

    text = f"""<b>📊 Задание 21 — Графики спроса и предложения</b>

Анализ графического изображения изменения спроса/предложения на конкретном рынке.

<b>Три вопроса:</b>
1. Как изменилась равновесная цена?
2. Что могло вызвать изменение? (фактор + объяснение)
3. Как изменятся показатели при условии?

<b>Система оценивания:</b>
• 3 балла — правильные ответы на 3 вопроса
• 2 балла — на 2 вопроса
• 1 балл — на 1 вопрос

<b>📈 Ваша статистика:</b>
• Решено: {stats['total_attempts']}
• Средний балл: {stats['avg_score']:.1f}/3"""

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t21_practice")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t21_progress")],
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
    question = get_random_question()

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

    # Формируем текст задания
    text = format_question_text(question)

    keyboard = [
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t21_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Проверяем наличие изображения
    image_url = question.get('image_url')

    try:
        # Удаляем предыдущее сообщение (анимация загрузки)
        try:
            await query.message.delete()
        except Exception:
            pass

        if image_url:
            # Проверяем путь к изображению
            # Путь может быть относительным или абсолютным
            if not os.path.isabs(image_url):
                # Относительный путь - строим от корня проекта
                project_root = os.path.dirname(os.path.dirname(__file__))
                image_path = os.path.join(project_root, image_url)
            else:
                image_path = image_url

            if os.path.exists(image_path):
                if len(text) <= MAX_CAPTION_LENGTH:
                    # Текст помещается в caption
                    with open(image_path, 'rb') as photo:
                        sent_msg = await context.bot.send_photo(
                            chat_id=user_id,
                            photo=photo,
                            caption=text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                else:
                    # Текст слишком длинный - отправляем отдельно
                    logger.info(f"Text too long ({len(text)} chars), sending separately")

                    with open(image_path, 'rb') as photo:
                        photo_msg = await context.bot.send_photo(
                            chat_id=user_id,
                            photo=photo,
                            caption="📊 График к заданию 21"
                        )

                    sent_msg = await context.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                    context.user_data['current_photo_message_id'] = photo_msg.message_id

                context.user_data['current_question_message_id'] = sent_msg.message_id
            else:
                logger.error(f"Image file not found: {image_path}")
                # Отправляем без изображения
                text = "⚠️ <i>Изображение графика не найдено</i>\n\n" + text
                sent_msg = await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
        else:
            # Нет изображения
            sent_msg = await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Error sending question: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Ошибка при отправке задания. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return states.CHOOSING_MODE

    return states.ANSWERING_T21


def get_random_question() -> Optional[Dict[str, Any]]:
    """Получить случайный вопрос."""
    # Поддерживаем оба варианта ключей: 'questions' и 'tasks'
    questions = task21_data.get('questions', []) or task21_data.get('tasks', [])

    logger.info(f"Task21: get_random_question called, questions count: {len(questions)}")

    if not questions:
        logger.warning("Task21: No questions available! task21_data may not be initialized.")
        return None

    return random.choice(questions)


def format_question_text(question: Dict[str, Any]) -> str:
    """Форматирование текста вопроса."""
    graph_description = question.get('graph_description', '')
    graph_notation = question.get('graph_notation', '')
    market_name = question.get('market_name', '')

    q1 = question.get('question_1', {})
    q2 = question.get('question_2', {})
    q3 = question.get('question_3', {})

    text = f"""<b>📊 Задание 21</b>

{graph_description}
{graph_notation}

<b>Вопросы:</b>

<b>1.</b> {q1.get('text', 'Как изменилась равновесная цена?')}

<b>2.</b> {q2.get('text', '')}

<b>3.</b> {q3.get('text', '')}

<i>Отправьте ответы (нумерованным списком или текстом):</i>
<code>1. ...
2. ...
3. ...</code>"""

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
        can_use, remaining, limit_msg = await freemium_manager.check_ai_limit(user_id, 'task21')

        if not can_use:
            # Показываем paywall с CTA
            keyboard = [
                [InlineKeyboardButton("💎 Попробовать за 1₽", callback_data="subscribe_start")],
                [InlineKeyboardButton("📋 Все тарифы", callback_data="subscribe")],
                [InlineKeyboardButton("◀️ Назад в меню", callback_data="t21_menu")],
            ]
            await update.message.reply_text(
                limit_msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return states.CHOOSING_MODE

        # Получаем информацию о подписке для дифференциации фидбека
        limit_info = await freemium_manager.get_limit_info(user_id, 'task21')
        is_premium = limit_info.get('is_premium', False)

    # Показываем анимацию проверки
    thinking_msg = await show_ai_evaluation_animation(
        update.message,
        duration=40
    )

    # Проверяем ответ через evaluator
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
        logger.info(f"[Task21] Daily streak updated for user {user_id}: {daily_current}/{daily_max}")

        # Показываем уведомление о дневном стрике для milestone значений
        if daily_current in [3, 5, 7, 10, 14, 20, 30, 50, 100]:
            await show_streak_notification(update, context, 'daily', daily_current)

    # Обновляем стрик правильных ответов
    correct_current, correct_max = await streak_manager.update_correct_streak(user_id, is_correct)
    logger.info(f"[Task21] Correct streak for user {user_id}: {correct_current}/{correct_max}")

    # Показываем уведомление о стрике правильных ответов для milestone значений
    if is_correct and correct_current in [3, 5, 7, 10, 14, 20, 30, 50, 100]:
        await show_streak_notification(update, context, 'correct', correct_current)
    # ========== КОНЕЦ ИНТЕГРАЦИИ СО СТРИКАМИ ==========

    # Формируем сообщение с результатом
    market_name = question.get('market_name', 'указанном рынке')
    curve_shifted = question.get('curve_shifted', '')
    shift_direction = question.get('shift_direction', '')

    curve_label = "предложения" if curve_shifted == "supply" else "спроса"
    direction_label = "вправо" if shift_direction == "right" else "влево"

    result_text = f"""<b>✅ Проверка завершена!</b>

<b>Рынок:</b> {market_name}
<b>Сдвиг:</b> кривая {curve_label} {direction_label}
<b>Ваш результат: {score}/{MAX_SCORE} балла</b>

{feedback}
"""

    if suggestions:
        result_text += "\n\n<b>💡 Рекомендации:</b>\n"
        for i, suggestion in enumerate(suggestions, 1):
            result_text += f"{i}. {suggestion}\n"

    # Добавляем информацию об оставшихся проверках для freemium
    if freemium_manager and not is_premium:
        limit_info = await freemium_manager.get_limit_info(user_id, 'task21')
        remaining_checks = limit_info.get('checks_remaining', 0)
        result_text += f"\n\n<i>🔋 Осталось бесплатных проверок: {remaining_checks}</i>"

    # Добавляем кнопки
    keyboard = [
        [InlineKeyboardButton("📚 Показать эталонные ответы", callback_data="t21_show_answers")],
        [InlineKeyboardButton("🔄 Новое задание", callback_data="t21_new")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="t21_progress")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t21_menu")],
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
                InlineKeyboardButton("◀️ Назад в меню", callback_data="t21_menu")
            ]])
        )
        return states.CHOOSING_MODE

    # Получаем текст эталонных ответов
    if EVALUATOR_AVAILABLE and evaluator:
        answers_text = evaluator.get_model_answers_text(question)
    else:
        answers_text = _format_model_answers(question)

    keyboard = [
        [InlineKeyboardButton("🔄 Новое задание", callback_data="t21_new")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t21_menu")],
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
    text = "<b>📚 Эталонные ответы:</b>\n\n"

    # Вопрос 1
    q1 = question.get('question_1', {})
    text += f"<b>1. {q1.get('text', 'Как изменилась равновесная цена?')}</b>\n"
    text += f"   Ответ: {q1.get('correct_answer', '')}\n\n"

    # Вопрос 2
    q2 = question.get('question_2', {})
    text += f"<b>2. {q2.get('text', '')}</b>\n"
    text += f"   Примеры ответов:\n"
    for example in q2.get('example_answers', []):
        text += f"   • {example}\n"
    text += "\n"

    # Вопрос 3
    q3 = question.get('question_3', {})
    text += f"<b>3. {q3.get('text', '')}</b>\n"
    for var in q3.get('variables_to_predict', []):
        text += f"   • {var.get('name', '')}: {var.get('correct_answer', '')}\n"

    return text


@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя."""
    query = update.callback_query
    user_id = query.from_user.id

    stats = await get_user_stats(user_id)
    detailed_stats = await get_detailed_stats(user_id)

    text = f"""<b>📊 Ваша статистика по заданию 21</b>

<b>Общая статистика:</b>
• Решено заданий: {stats['total_attempts']}
• Средний балл: {stats['avg_score']:.1f}/3
• Всего заданий в базе: {stats['total_tasks']}

<b>Распределение по баллам:</b>
• 3 балла: {detailed_stats['score_3']} раз
• 2 балла: {detailed_stats['score_2']} раз
• 1 балл: {detailed_stats['score_1']} раз
• 0 баллов: {detailed_stats['score_0']} раз
"""

    if stats['total_attempts'] > 0:
        success_rate = (detailed_stats['score_3'] / stats['total_attempts']) * 100
        text += f"\n<b>Процент максимальных баллов:</b> {success_rate:.1f}%"

    keyboard = [
        [InlineKeyboardButton("🎯 Решать задания", callback_data="t21_practice")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="t21_menu")],
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
    """Возврат в главное меню задания 21."""
    await show_main_menu(update, context)
    return states.CHOOSING_MODE


@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    return await handle_to_main_menu(update, context)


@safe_handler()
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel - выход из модуля."""
    await update.message.reply_text("Выход из задания 21.")
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
            FROM task21_attempts
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

        total_tasks = len(task21_data.get('questions', []) or task21_data.get('tasks', []))

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
            'total_tasks': len(task21_data.get('questions', []) or task21_data.get('tasks', []))
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
                SUM(CASE WHEN score = 0 THEN 1 ELSE 0 END) as score_0
            FROM task21_attempts
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
                'score_0': result['score_0'] or 0
            }
        else:
            return {'score_3': 0, 'score_2': 0, 'score_1': 0, 'score_0': 0}

    except Exception as e:
        logger.error(f"Error getting detailed stats: {e}")
        return {'score_3': 0, 'score_2': 0, 'score_1': 0, 'score_0': 0}


async def save_attempt(user_id: int, question_id: str, answer: str, score: int) -> None:
    """Сохранить попытку в БД."""
    try:
        conn = await db.get_db()

        # Проверяем существование таблицы
        await _ensure_table_exists(conn)

        await conn.execute(
            """
            INSERT INTO task21_attempts (user_id, question_id, answer, score, attempted_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (user_id, question_id, answer, score)
        )
        await conn.commit()

        logger.info(f"Saved task21 attempt: user={user_id}, question={question_id}, score={score}")

    except Exception as e:
        logger.error(f"Error saving attempt: {e}")


async def _ensure_table_exists(conn) -> None:
    """Создать таблицу если не существует."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS task21_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            answer TEXT NOT NULL,
            score INTEGER NOT NULL,
            attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    await conn.commit()
