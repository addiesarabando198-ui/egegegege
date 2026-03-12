"""
Обработчики для модуля «Полный вариант ЕГЭ».

FSM-состояния (из core.states):
  FULL_EXAM_OVERVIEW     — обзор варианта с навигацией
  FULL_EXAM_TEST_PART    — ответ на задание тестовой части (1-16)
  FULL_EXAM_PART2_ANSWER — ответ на задание второй части (17-25)
  FULL_EXAM_RESULTS      — итоговые результаты
  FULL_EXAM_TASK_REVIEW  — просмотр конкретного задания
"""

import logging
import json
import random
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states, db
from core.config import DATABASE_FILE
from core.error_handler import safe_handler
from core.plugin_loader import build_main_menu
from core.utils import safe_edit_message
from core.ui_helpers import show_thinking_animation

from . import keyboards
from .generator import generate_variant, replace_task_in_variant, ExamVariant, ExamTask
from .scoring import (
    get_max_score_for_task,
    calculate_part1_score,
    calculate_part2_score,
    primary_to_secondary,
    format_results_summary,
    PART2_MAX_SCORES,
    MAX_TOTAL_SCORE,
)

logger = logging.getLogger(__name__)

ALL_TASK_NUMS = list(range(1, 17)) + list(range(17, 26))

TASK_NAMES = {
    17: "Анализ текста",
    18: "Понятие из текста",
    19: "Примеры и иллюстрации",
    20: "Суждения",
    21: "Графики спроса и предложения",
    22: "Анализ ситуаций",
    23: "Конституция РФ",
    24: "Сложный план",
    25: "Обоснование с примерами",
}


# ──────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────

def _get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Получить user_id из update и сохранить в context."""
    if "user_id" in context.user_data:
        return context.user_data["user_id"]
    user = update.effective_user
    if user:
        context.user_data["user_id"] = user.id
        return user.id
    return None


def _get_variant(context: ContextTypes.DEFAULT_TYPE) -> Optional[ExamVariant]:
    """Получить текущий вариант из user_data."""
    data = context.user_data.get("fe_variant_data")
    if data:
        try:
            return ExamVariant.from_dict(data)
        except Exception as e:
            logger.error(f"Ошибка десериализации варианта: {e}")
    return None


def _save_variant(context: ContextTypes.DEFAULT_TYPE, variant: ExamVariant):
    """Сохранить вариант в user_data."""
    context.user_data["fe_variant_data"] = variant.to_dict()


def _get_answered(context: ContextTypes.DEFAULT_TYPE) -> Set[int]:
    """Множество отвеченных заданий."""
    return set(context.user_data.get("fe_answered", []))


def _get_scores(context: ContextTypes.DEFAULT_TYPE) -> Dict[int, int]:
    """Текущие баллы по заданиям."""
    raw = context.user_data.get("fe_scores", {})
    return {int(k): v for k, v in raw.items()}


def _mark_answered(context: ContextTypes.DEFAULT_TYPE, exam_num: int, score: int):
    """Пометить задание как отвеченное с баллом."""
    answered = list(context.user_data.get("fe_answered", []))
    if exam_num not in answered:
        answered.append(exam_num)
    context.user_data["fe_answered"] = answered

    scores = context.user_data.get("fe_scores", {})
    scores[str(exam_num)] = score
    context.user_data["fe_scores"] = scores


def _save_feedback(context: ContextTypes.DEFAULT_TYPE, exam_num: int, feedback: str):
    """Сохранить AI-фидбэк для задания."""
    feedbacks = context.user_data.get("fe_feedbacks", {})
    feedbacks[str(exam_num)] = feedback
    context.user_data["fe_feedbacks"] = feedbacks


async def _check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка платной подписки."""
    sub_mgr = context.bot_data.get("subscription_manager")
    if not sub_mgr:
        logger.warning("subscription_manager не найден в bot_data")
        return False
    try:
        return await sub_mgr.check_module_access(user_id, "full_exam")
    except Exception:
        try:
            return await sub_mgr.check_active_subscription(user_id)
        except Exception as e:
            logger.error(f"Ошибка проверки подписки: {e}")
            return False


# ──────────────────────────────────────────────────────────────
# Точка входа
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход из главного меню бота."""
    query = update.callback_query
    await query.answer()

    user_id = _get_user_id(update, context)
    if not user_id:
        await query.edit_message_text("Ошибка: не удалось определить пользователя.")
        return ConversationHandler.END

    # Проверка подписки
    has_access = await _check_subscription(user_id, context)
    if not has_access:
        await query.edit_message_text(
            "📝 <b>Полный вариант ЕГЭ</b>\n\n"
            "Этот модуль доступен по подписке.\n"
            "Пройдите полный вариант из 23 заданий "
            "(тестовая часть + развёрнутые ответы) "
            "с проверкой ИИ и подробной аналитикой.\n\n"
            "💎 Оформите подписку, чтобы получить доступ!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Оформить подписку", callback_data="pay_trial")],
                [InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")],
            ]),
        )
        return states.FULL_EXAM_OVERVIEW

    # Есть ли незавершённый вариант?
    has_active = context.user_data.get("fe_variant_data") is not None
    if has_active:
        answered = _get_answered(context)
        total = len(ALL_TASK_NUMS)
        kb = keyboards.get_entry_keyboard_with_continue()
        await query.edit_message_text(
            "📝 <b>Полный вариант ЕГЭ</b>\n\n"
            f"У вас есть незавершённый вариант ({len(answered)}/{total} заданий).\n"
            "Вы можете продолжить или начать новый.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await query.edit_message_text(
            "📝 <b>Полный вариант ЕГЭ</b>\n\n"
            "Пройдите полный вариант экзамена:\n"
            "• 16 заданий тестовой части\n"
            "• 9 заданий с развёрнутым ответом (17-25)\n"
            "• Проверка ИИ для второй части\n"
            "• Подробная аналитика результатов\n\n"
            "Вы можете переключаться между заданиями "
            "и завершить вариант в любой момент.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.get_entry_keyboard(),
        )
    return states.FULL_EXAM_OVERVIEW


# ──────────────────────────────────────────────────────────────
# Генерация нового варианта
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def new_variant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация нового варианта."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "⏳ Генерирую вариант...\n"
        "Подбираю задания из разных блоков и тем.",
        parse_mode=ParseMode.HTML,
    )

    variant = generate_variant()

    # Очищаем предыдущий прогресс
    context.user_data["fe_variant_data"] = variant.to_dict()
    context.user_data["fe_answered"] = []
    context.user_data["fe_scores"] = {}
    context.user_data["fe_feedbacks"] = {}
    context.user_data["fe_user_answers"] = {}

    return await _show_overview(query.message, context, edit=True)


@safe_handler()
async def continue_variant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продолжение незавершённого варианта."""
    query = update.callback_query
    await query.answer()
    return await _show_overview(query.message, context, edit=True)


# ──────────────────────────────────────────────────────────────
# Обзор варианта
# ──────────────────────────────────────────────────────────────

async def _show_overview(message, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    """Показ обзора варианта с кнопками заданий."""
    variant = _get_variant(context)
    if not variant:
        text = "⚠️ Вариант не найден. Начните новый."
        kb = keyboards.get_entry_keyboard()
        if edit:
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.reply_text(text, reply_markup=kb)
        return states.FULL_EXAM_OVERVIEW

    answered = _get_answered(context)

    total = len(variant.tasks)
    done = len(answered)

    part1_done = len([n for n in range(1, 17) if n in answered])
    part2_done = len([n for n in range(17, 26) if n in answered])

    text = (
        f"📝 <b>Вариант {variant.variant_id}</b>\n\n"
        f"Выполнено: {done}/{total} заданий\n"
        f"Часть 1: {part1_done}/16\n"
        f"Часть 2: {part2_done}/7\n\n"
        "Результаты будут показаны после завершения варианта.\n"
        "Нажмите на задание, чтобы перейти к нему:"
    )

    kb = keyboards.get_overview_keyboard(answered)

    if edit:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    return states.FULL_EXAM_OVERVIEW


@safe_handler()
async def show_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback-обработчик для возврата к обзору."""
    query = update.callback_query
    await query.answer()
    return await _show_overview(query.message, context, edit=True)


# ──────────────────────────────────────────────────────────────
# Переход к конкретному заданию
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def goto_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к конкретному заданию из обзора."""
    query = update.callback_query
    await query.answer()

    # Извлекаем номер задания из callback_data
    data = query.data  # fe_goto_N
    try:
        exam_num = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return await _show_overview(query.message, context, edit=True)

    variant = _get_variant(context)
    if not variant:
        return await _show_overview(query.message, context, edit=True)

    task = variant.get_task(exam_num)
    if not task:
        await query.edit_message_text(
            f"⚠️ Задание №{exam_num} не найдено в варианте.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 К обзору", callback_data="fe_overview")
            ]]),
        )
        return states.FULL_EXAM_OVERVIEW

    context.user_data["fe_current_task"] = exam_num

    # Проверяем, отвечено ли уже
    answered = _get_answered(context)
    if exam_num in answered:
        return await _show_answered_task(query.message, context, exam_num, task, edit=True)

    # Показываем задание
    if 1 <= exam_num <= 16:
        return await _show_test_task(query.message, context, exam_num, task, edit=True)
    else:
        return await _show_part2_task(query.message, context, exam_num, task, edit=True)


# ──────────────────────────────────────────────────────────────
# Показ заданий тестовой части (1-16)
# ──────────────────────────────────────────────────────────────

async def _show_test_task(message, context, exam_num: int, task: ExamTask, edit: bool = True):
    """Показ задания тестовой части."""
    q = task.task_data
    q_type = q.get("type", "text")

    text = f"📝 <b>Задание №{exam_num}</b>"
    if task.block:
        text += f" • {task.block}"
    text += "\n" + "━" * 30 + "\n\n"

    # Формируем текст вопроса
    if q_type == "matching":
        text += f"{q.get('instruction', '')}\n\n"
        col1 = q.get("column1_options", {})
        col2 = q.get("column2_options", {})
        if col1:
            text += f"<b>{q.get('column1_header', 'А')}:</b>\n"
            for letter, option in sorted(col1.items()):
                text += f"{letter}) {option}\n"
            text += "\n"
        if col2:
            text += f"<b>{q.get('column2_header', '1')}:</b>\n"
            for digit, option in sorted(col2.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                text += f"{digit}. {option}\n"
        text += f"\n✍️ <i>Введите {len(col1)} цифр без пробелов</i>"
    else:
        question_text = q.get("question", q.get("question_text", q.get("text", "")))
        text += f"{question_text}\n\n"
        if q_type == "multiple_choice":
            text += "✍️ <i>Введите цифры ответов без пробелов</i>"
        elif q_type == "single_choice":
            text += "✍️ <i>Введите одну цифру ответа</i>"
        else:
            text += "✍️ <i>Введите ваш ответ</i>"

    kb = keyboards.get_task_nav_keyboard(exam_num, ALL_TASK_NUMS)
    if edit:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    return states.FULL_EXAM_TEST_PART


# ──────────────────────────────────────────────────────────────
# Показ заданий второй части (19-25)
# ──────────────────────────────────────────────────────────────

async def _show_part2_task(message, context, exam_num: int, task: ExamTask, edit: bool = True):
    """Показ задания второй части."""
    data = task.task_data
    name = TASK_NAMES.get(exam_num, f"Задание {exam_num}")
    max_score = PART2_MAX_SCORES.get(exam_num, 0)

    text = f"📝 <b>Задание №{exam_num} — {name}</b>"
    if task.block:
        text += f"\n📚 Блок: {task.block}"
    text += f"\n🎯 Максимальный балл: {max_score}"
    text += "\n" + "━" * 30 + "\n\n"

    # Формируем текст задания в зависимости от типа
    if exam_num in (17, 18):
        # Задания 17 и 18 основаны на общем тексте
        passage_text = data.get("text", "")
        source = data.get("source", "")
        question = data.get("question", "")
        if source:
            text += f"<b>Источник:</b> {source}\n\n"
        text += f"{passage_text}\n\n"
        if question:
            text += f"<b>Вопрос:</b>\n{question}"
    elif exam_num == 19:
        text += data.get("task_text", "")
    elif exam_num == 20:
        text += data.get("task_text", "")
    elif exam_num == 21:
        market = data.get("market_name", "")
        desc = data.get("graph_description", "")
        text += f"<b>Рынок: {market}</b>\n\n{desc}\n\n"
        for i in range(1, 4):
            q_data = data.get(f"question_{i}", {})
            q_text = q_data.get("text", "") if isinstance(q_data, dict) else ""
            text += f"<b>{i}.</b> {q_text}\n"
    elif exam_num == 22:
        text += data.get("description", "") + "\n\n"
        questions = data.get("questions", [])
        for i, q in enumerate(questions, 1):
            text += f"<b>{i}.</b> {q}\n"
    elif exam_num == 23:
        text += data.get("question_text", "")
    elif exam_num == 24:
        topic_name = data.get("topic_name", "")
        text += f'<b>Составьте сложный план по теме:</b>\n«{topic_name}»\n\n'
        text += (
            "План должен содержать не менее трёх пунктов, "
            "непосредственно раскрывающих тему, "
            "из которых два или более детализированы в подпунктах."
        )
    elif exam_num == 25:
        parts = data.get("parts", {})
        title = data.get("title", "")
        text += f"<b>Тема: {title}</b>\n\n"
        for part_key in ["part1", "part2", "part3"]:
            part_text = parts.get(part_key, "")
            if part_text:
                text += f"{part_text}\n\n"

    text += "\n✍️ <i>Напишите ваш ответ текстовым сообщением</i>"

    kb = keyboards.get_task_nav_keyboard(exam_num, ALL_TASK_NUMS)
    if edit:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    return states.FULL_EXAM_PART2_ANSWER


# ──────────────────────────────────────────────────────────────
# Показ уже отвеченного задания
# ──────────────────────────────────────────────────────────────

async def _show_answered_task(message, context, exam_num: int, task: ExamTask, edit: bool = True):
    """Показ задания, на которое уже дан ответ (без раскрытия результата)."""
    user_answers = context.user_data.get("fe_user_answers", {})
    user_answer = user_answers.get(str(exam_num), "—")

    name = TASK_NAMES.get(exam_num, f"Задание {exam_num}")
    if 1 <= exam_num <= 16:
        name = "Тестовая часть"

    text = (
        f"✔️ <b>Задание №{exam_num} — {name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Ваш ответ:</b>\n{user_answer[:500]}\n\n"
        f"<i>Результат будет показан после завершения варианта.</i>"
    )

    kb = keyboards.get_after_answer_keyboard(exam_num)
    if edit:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    return states.FULL_EXAM_OVERVIEW


# ──────────────────────────────────────────────────────────────
# Проверка ответа — тестовая часть
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def check_test_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка ответа на задание тестовой части."""
    user_answer = update.message.text.strip()
    exam_num = context.user_data.get("fe_current_task")

    if exam_num is None:
        return await _show_overview(update.message, context, edit=False)

    variant = _get_variant(context)
    if not variant:
        return await _show_overview(update.message, context, edit=False)

    task = variant.get_task(exam_num)
    if not task:
        return await _show_overview(update.message, context, edit=False)

    # Нормализация ответа
    q = task.task_data
    q_type = q.get("type", "text")
    correct = q.get("answer", "")

    normalized_user = _normalize_answer(user_answer, q_type)
    normalized_correct = _normalize_answer(correct, q_type)
    is_correct = normalized_user == normalized_correct

    max_score = get_max_score_for_task(exam_num)
    earned = max_score if is_correct else 0

    # Сохраняем результат (баллы скрыты до завершения)
    _mark_answered(context, exam_num, earned)
    answers = context.user_data.get("fe_user_answers", {})
    answers[str(exam_num)] = user_answer
    context.user_data["fe_user_answers"] = answers

    answered = _get_answered(context)
    total = len(ALL_TASK_NUMS)

    text = f"✅ Ответ принят ({len(answered)}/{total})"

    kb = keyboards.get_after_answer_keyboard(exam_num)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    return states.FULL_EXAM_OVERVIEW


def _normalize_answer(answer: str, q_type: str) -> str:
    """Нормализация ответа для сравнения."""
    if not answer:
        return ""
    processed = answer.strip().replace(" ", "").replace(",", "")
    if q_type == "multiple_choice":
        digits = "".join(filter(str.isdigit, processed))
        return "".join(sorted(set(digits)))
    elif q_type in ("matching", "sequence", "single_choice"):
        return "".join(filter(str.isdigit, processed))
    else:
        return processed.lower()


# ──────────────────────────────────────────────────────────────
# Проверка ответа — вторая часть (AI)
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def check_part2_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка ответа на задание второй части (AI-оценка)."""
    user_answer = update.message.text.strip()
    exam_num = context.user_data.get("fe_current_task")

    if exam_num is None or not (17 <= exam_num <= 25):
        return await _show_overview(update.message, context, edit=False)

    variant = _get_variant(context)
    if not variant:
        return await _show_overview(update.message, context, edit=False)

    task = variant.get_task(exam_num)
    if not task:
        return await _show_overview(update.message, context, edit=False)

    # Показываем подтверждение приёма
    thinking_msg = await update.message.reply_text("⏳ Сохраняю ваш ответ...")

    # Вызываем AI-оценку (результат скрыт до завершения)
    try:
        score, feedback = await _evaluate_part2(exam_num, task, user_answer, context)
    except Exception as e:
        logger.error(f"Ошибка AI-оценки задания {exam_num}: {e}")
        score = 0
        feedback = "⚠️ Не удалось получить оценку ИИ."

    max_score = PART2_MAX_SCORES.get(exam_num, 0)
    score = min(score, max_score)

    # Сохраняем (скрыто от пользователя до завершения)
    _mark_answered(context, exam_num, score)
    answers = context.user_data.get("fe_user_answers", {})
    answers[str(exam_num)] = user_answer
    context.user_data["fe_user_answers"] = answers
    _save_feedback(context, exam_num, feedback)

    answered = _get_answered(context)
    total = len(ALL_TASK_NUMS)

    text = f"✅ Ответ принят ({len(answered)}/{total})"

    kb = keyboards.get_after_answer_keyboard(exam_num)

    try:
        await thinking_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    return states.FULL_EXAM_OVERVIEW


async def _evaluate_part2(
    exam_num: int,
    task: ExamTask,
    user_answer: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple:
    """
    Делегирует AI-оценку в соответствующий модуль.
    Returns: (score: int, feedback: str)
    """
    data = task.task_data

    try:
        if exam_num == 17:
            return await _eval_task17(data, user_answer)
        elif exam_num == 18:
            return await _eval_task18(data, user_answer)
        elif exam_num == 19:
            return await _eval_task19(data, user_answer)
        elif exam_num == 20:
            return await _eval_task20(data, user_answer)
        elif exam_num == 21:
            return await _eval_task21(data, user_answer)
        elif exam_num == 22:
            return await _eval_task22(data, user_answer)
        elif exam_num == 23:
            return await _eval_task23(data, user_answer)
        elif exam_num == 24:
            return await _eval_task24(data, user_answer)
        elif exam_num == 25:
            return await _eval_task25(data, user_answer)
    except ImportError as e:
        logger.warning(f"Модуль оценки для задания {exam_num} недоступен: {e}")
    except Exception as e:
        logger.error(f"Ошибка оценки задания {exam_num}: {e}", exc_info=True)

    return 0, "⚠️ Оценка временно недоступна."


async def _eval_task17(data: dict, answer: str) -> tuple:
    """Оценка задания 17 через модуль task17."""
    from task17.evaluator import Task17AIEvaluator
    evaluator = Task17AIEvaluator()
    result = await evaluator.evaluate(answer, data)
    return result.total_score, result.feedback


async def _eval_task18(data: dict, answer: str) -> tuple:
    """Оценка задания 18 через модуль task18."""
    from task18.evaluator import Task18AIEvaluator
    evaluator = Task18AIEvaluator()
    result = await evaluator.evaluate(answer, data)
    return result.total_score, result.feedback


async def _eval_task19(data: dict, answer: str) -> tuple:
    """Оценка задания 19 через существующий модуль."""
    from task19.evaluator import Task19AIEvaluator
    evaluator = Task19AIEvaluator()
    topic_title = data.get("title", "")
    task_text = data.get("task_text", "")
    result = await evaluator.evaluate(
        answer=answer,
        topic=topic_title,
        task_text=task_text,
    )
    score = getattr(result, "score", 0)
    feedback = getattr(result, "feedback", str(result))
    return score, feedback


async def _eval_task20(data: dict, answer: str) -> tuple:
    """Оценка задания 20 через существующий модуль."""
    try:
        from task20.evaluator import Task20AIEvaluator
        evaluator = Task20AIEvaluator()
        result = await evaluator.evaluate(
            answer=answer,
            topic=data.get("title", ""),
            task_text=data.get("task_text", ""),
        )
        score = getattr(result, "score", 0)
        feedback = getattr(result, "feedback", str(result))
        return score, feedback
    except ImportError:
        return 0, "⚠️ Модуль оценки задания 20 недоступен."


async def _eval_task21(data: dict, answer: str) -> tuple:
    """Оценка задания 21 (графики) — по ключевым словам."""
    total = 0
    feedback_parts = []
    for i in range(1, 4):
        q_data = data.get(f"question_{i}", {})
        if not isinstance(q_data, dict):
            continue
        correct = q_data.get("correct_answer", "").lower()
        keywords = q_data.get("acceptable_keywords", [])
        q_text = q_data.get("text", f"Вопрос {i}")

        # Проверяем ответ по ключевым словам
        answer_lower = answer.lower()
        matched = correct in answer_lower or any(kw.lower() in answer_lower for kw in keywords)
        if matched:
            total += 1
            feedback_parts.append(f"✅ {q_text}: верно")
        else:
            feedback_parts.append(f"❌ {q_text}: ожидался ответ «{correct}»")

    feedback = "\n".join(feedback_parts)
    return total, feedback


async def _eval_task22(data: dict, answer: str) -> tuple:
    """Оценка задания 22 через AI."""
    try:
        from task22.evaluator import Task22AIEvaluator
        evaluator = Task22AIEvaluator()
        result = await evaluator.evaluate(
            answer=answer,
            task_data=data,
        )
        score = getattr(result, "score", 0)
        feedback = getattr(result, "feedback", str(result))
        return score, feedback
    except ImportError:
        # Фолбэк: простая проверка
        correct_answers = data.get("correct_answers", [])
        matched = 0
        for ca in correct_answers:
            if ca.lower()[:20] in answer.lower():
                matched += 1
        return min(matched, 4), f"Совпадений с эталоном: {matched}/{len(correct_answers)}"


async def _eval_task23(data: dict, answer: str) -> tuple:
    """Оценка задания 23 через AI."""
    try:
        from task23.evaluator import Task23AIEvaluator
        evaluator = Task23AIEvaluator()
        result = await evaluator.evaluate(
            answer=answer,
            task_data=data,
        )
        score = getattr(result, "score", 0)
        feedback = getattr(result, "feedback", str(result))
        return score, feedback
    except ImportError:
        model_answers = data.get("model_answers", [])
        matched = sum(1 for ma in model_answers if ma.lower()[:15] in answer.lower())
        return min(matched, 3), f"Совпадений с моделью: {matched}/{len(model_answers)}"


async def _eval_task24(data: dict, answer: str) -> tuple:
    """Оценка задания 24 (план) через существующий чекер."""
    try:
        from task24.checker import PlanBotData
        from task24.ai_checker import get_ai_checker

        topic_name = data.get("topic_name", "")
        plan_data = data.get("plan_data", {})

        ai_checker = get_ai_checker()
        if ai_checker:
            result = await ai_checker.check_plan(
                user_plan=answer,
                topic=topic_name,
                reference_plan=plan_data,
            )
            score = getattr(result, "score", result.get("score", 0) if isinstance(result, dict) else 0)
            feedback = getattr(result, "feedback", result.get("feedback", str(result)) if isinstance(result, dict) else str(result))
            return min(score, 4), feedback

    except (ImportError, AttributeError) as e:
        logger.warning(f"AI-чекер задания 24 недоступен: {e}")

    return 0, "⚠️ Автопроверка плана временно недоступна."


async def _eval_task25(data: dict, answer: str) -> tuple:
    """Оценка задания 25 через существующий модуль."""
    try:
        from task25.evaluator import Task25AIEvaluator
        evaluator = Task25AIEvaluator()
        result = await evaluator.evaluate(
            answer=answer,
            topic_data=data,
        )
        score = getattr(result, "score", 0)
        feedback = getattr(result, "feedback", str(result))
        return min(score, 6), feedback
    except ImportError:
        return 0, "⚠️ Модуль оценки задания 25 недоступен."


# ──────────────────────────────────────────────────────────────
# Пропуск задания
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def skip_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск текущего задания."""
    query = update.callback_query
    await query.answer("Задание пропущено")

    data = query.data  # fe_skip_N
    try:
        exam_num = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return await _show_overview(query.message, context, edit=True)

    return await _show_overview(query.message, context, edit=True)


# ──────────────────────────────────────────────────────────────
# Завершение варианта
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def finish_variant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение завершения."""
    query = update.callback_query
    await query.answer()

    answered = _get_answered(context)
    total = len(ALL_TASK_NUMS)
    unanswered = total - len(answered)

    if unanswered > 0:
        text = (
            f"⚠️ <b>Вы не ответили на {unanswered} из {total} заданий.</b>\n\n"
            "Пропущенные задания будут оценены в 0 баллов.\n"
            "Завершить вариант?"
        )
    else:
        text = "Все задания выполнены! Завершить и показать результаты?"

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=keyboards.get_finish_confirm_keyboard(),
    )
    return states.FULL_EXAM_OVERVIEW


@safe_handler()
async def finish_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждённое завершение — показ результатов."""
    query = update.callback_query
    await query.answer()

    user_id = _get_user_id(update, context)
    answered = _get_answered(context)
    scores = _get_scores(context)

    # Подготовка данных для scoring
    part1_answers = {}
    for num in range(1, 17):
        if num in answered:
            part1_answers[num] = scores.get(num, 0) > 0

    part2_scores = {}
    for num in range(17, 26):
        part2_scores[num] = scores.get(num, 0)

    # Формируем результат
    results_text = format_results_summary(part1_answers, part2_scores)

    # Сохраняем результаты в БД
    try:
        await _save_exam_results(user_id, context)
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов: {e}")

    # Очищаем данные варианта
    context.user_data.pop("fe_variant_data", None)
    context.user_data.pop("fe_answered", None)
    context.user_data.pop("fe_scores", None)
    context.user_data.pop("fe_feedbacks", None)
    context.user_data.pop("fe_user_answers", None)
    context.user_data.pop("fe_current_task", None)

    await query.edit_message_text(
        results_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.get_results_keyboard(),
    )
    return states.FULL_EXAM_RESULTS


async def _save_exam_results(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение результатов варианта в БД."""
    import aiosqlite

    variant_data = context.user_data.get("fe_variant_data", {})
    scores = _get_scores(context)
    answered = _get_answered(context)

    # Считаем итоговые баллы
    part1_answers = {n: (scores.get(n, 0) > 0) for n in range(1, 17) if n in answered}
    p1_score, _ = calculate_part1_score(part1_answers)
    part2_scores = {n: scores.get(n, 0) for n in range(17, 26)}
    p2_score, _ = calculate_part2_score(part2_scores)
    total_primary = p1_score + p2_score
    secondary = primary_to_secondary(total_primary)

    try:
        conn = await db.get_db()

        # Создаём таблицу если не существует
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS full_exam_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                variant_id TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                part1_score INTEGER DEFAULT 0,
                part2_score INTEGER DEFAULT 0,
                total_primary INTEGER DEFAULT 0,
                secondary_score INTEGER DEFAULT 0,
                tasks_answered INTEGER DEFAULT 0,
                scores_detail TEXT,
                variant_data TEXT
            )
        """)

        await conn.execute(
            """INSERT INTO full_exam_results
               (user_id, variant_id, completed_at, part1_score, part2_score,
                total_primary, secondary_score, tasks_answered, scores_detail, variant_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                variant_data.get("variant_id", ""),
                datetime.now(timezone.utc).isoformat(),
                p1_score,
                p2_score,
                total_primary,
                secondary,
                len(answered),
                json.dumps(scores),
                json.dumps(variant_data),
            ),
        )
        await conn.commit()
        logger.info(f"Результаты варианта сохранены: user={user_id}, score={total_primary}/{MAX_TOTAL_SCORE}")
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов в БД: {e}")


# ──────────────────────────────────────────────────────────────
# Мои результаты
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def my_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ истории результатов."""
    query = update.callback_query
    await query.answer()

    user_id = _get_user_id(update, context)
    if not user_id:
        return states.FULL_EXAM_OVERVIEW

    try:
        conn = await db.get_db()

        # Проверяем существование таблицы
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='full_exam_results'"
        )
        if not await cursor.fetchone():
            await query.edit_message_text(
                "📊 <b>Мои результаты</b>\n\nВы ещё не завершили ни одного варианта.",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboards.get_entry_keyboard(),
            )
            return states.FULL_EXAM_OVERVIEW

        cursor = await conn.execute(
            """SELECT variant_id, completed_at, total_primary, secondary_score, tasks_answered
               FROM full_exam_results
               WHERE user_id = ?
               ORDER BY completed_at DESC
               LIMIT 10""",
            (user_id,),
        )
        rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"Ошибка загрузки результатов: {e}")
        rows = []

    if not rows:
        text = "📊 <b>Мои результаты</b>\n\nВы ещё не завершили ни одного варианта."
    else:
        text = "📊 <b>Мои результаты</b>\n\n"
        for i, row in enumerate(rows, 1):
            v_id = row[0]
            completed = row[1][:10] if row[1] else "—"
            total_p = row[2]
            secondary = row[3]
            tasks_done = row[4]
            text += (
                f"<b>{i}.</b> {completed} — "
                f"{total_p}/{MAX_TOTAL_SCORE} перв. ({secondary}/100 вт.) "
                f"[{tasks_done}/23]\n"
            )

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=keyboards.get_entry_keyboard(),
    )
    return states.FULL_EXAM_OVERVIEW


# ──────────────────────────────────────────────────────────────
# Подробный разбор
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def detailed_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подробный разбор после завершения (пока заглушка)."""
    query = update.callback_query
    await query.answer("В разработке")
    return states.FULL_EXAM_RESULTS


# ──────────────────────────────────────────────────────────────
# Заглушка для нерабочих кнопок
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заглушка для кнопок-заголовков."""
    query = update.callback_query
    await query.answer()
    return None  # Не меняем состояние


# ──────────────────────────────────────────────────────────────
# Возврат в главное меню
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    query = update.callback_query
    await query.answer()

    kb = build_main_menu()
    await query.edit_message_text(
        "👋 Выберите раздел для подготовки к ЕГЭ:",
        reply_markup=kb,
    )
    return ConversationHandler.END


# ──────────────────────────────────────────────────────────────
# Учительский режим: создание ДЗ с полным вариантом
# ──────────────────────────────────────────────────────────────

@safe_handler()
async def teacher_generate_variant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Учитель генерирует вариант для ДЗ."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("⏳ Генерирую вариант для домашнего задания...")

    variant = generate_variant()
    context.user_data["fe_hw_variant"] = variant.to_dict()

    return await _show_teacher_preview(query.message, context, variant, edit=True)


async def _show_teacher_preview(message, context, variant: ExamVariant, edit: bool = True):
    """Показ предпросмотра варианта для учителя."""
    text = f"📋 <b>Предпросмотр варианта {variant.variant_id}</b>\n\n"

    text += "<b>Часть 1 (тестовая):</b>\n"
    for num in range(1, 17):
        task = variant.get_task(num)
        if task:
            topic = task.task_data.get("topic", "")
            text += f"  №{num}: {topic}\n"

    text += "\n<b>Часть 2 (развёрнутая):</b>\n"
    for num in range(17, 26):
        task = variant.get_task(num)
        if task:
            name = TASK_NAMES.get(num, "")
            title = task.title or ""
            block = f" [{task.block}]" if task.block else ""
            text += f"  №{num} {name}: {title}{block}\n"

    # Проверяем связь 24-25
    t24 = variant.get_task(24)
    t25 = variant.get_task(25)
    if t24 and t25 and t24.block == t25.block:
        text += f"\n🔗 Задания 24-25 связаны (блок: {t24.block})"

    kb = keyboards.get_teacher_preview_keyboard(variant.variant_id)
    if edit:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@safe_handler()
async def teacher_replace_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Учитель заменяет задание в варианте."""
    query = update.callback_query
    await query.answer()

    data = query.data  # fe_hw_replace_N
    try:
        exam_num = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    variant_data = context.user_data.get("fe_hw_variant")
    if not variant_data:
        await query.edit_message_text("⚠️ Вариант не найден.")
        return

    variant = ExamVariant.from_dict(variant_data)
    success = replace_task_in_variant(variant, exam_num)

    if success:
        context.user_data["fe_hw_variant"] = variant.to_dict()
        await query.answer(f"✅ Задание №{exam_num} заменено")
    else:
        await query.answer(f"⚠️ Не удалось заменить задание №{exam_num}", show_alert=True)

    return await _show_teacher_preview(query.message, context, variant, edit=True)


@safe_handler()
async def teacher_regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Учитель перегенерирует вариант."""
    return await teacher_generate_variant(update, context)
