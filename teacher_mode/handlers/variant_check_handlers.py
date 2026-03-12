"""
Обработчики для проверки варианта целиком (Variant Check).

Позволяет учителю:
- Проверить вариант из бота (ключи загружаются автоматически)
- Проверить внешний вариант (учитель вводит условия и ключи)
- Выбрать задания для проверки (1-25, часть 2, или произвольный набор)
- Ввести ответы ученика (текст, пошагово или одним сообщением)
- Проверить ответы нескольких учеников (пакетный режим)
"""

import logging
import re
import json
from typing import Dict, List, Optional, Tuple, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from ..states import TeacherStates
from ..services import quick_check_service
from ..services.ai_homework_evaluator import evaluate_homework_answer
from full_exam.scoring import (
    PART2_MAX_SCORES, get_max_score_for_task,
    calculate_part1_score, calculate_part2_score,
    primary_to_secondary, get_grade_description,
    MIN_PASSING_SECONDARY, MAX_TOTAL_SCORE
)

logger = logging.getLogger(__name__)

# Максимальное число учеников в пакетном режиме
MAX_BATCH_STUDENTS = 30

# Названия заданий
TASK_NAMES = {
    1: "Тест 1", 2: "Тест 2", 3: "Тест 3", 4: "Тест 4",
    5: "Тест 5", 6: "Тест 6", 7: "Тест 7", 8: "Тест 8",
    9: "Тест 9", 10: "Тест 10", 11: "Тест 11", 12: "Тест 12",
    13: "Тест 13", 14: "Тест 14", 15: "Тест 15", 16: "Тест 16",
    17: "Анализ текста", 18: "Понятие из текста",
    19: "Примеры", 20: "Суждения", 21: "Графики",
    22: "Анализ ситуаций", 23: "Конституция",
    24: "Сложный план", 25: "Обоснование",
}

# Модули для каждого типа задания
TASK_MODULES = {
    17: "task17", 18: "task18", 19: "task19", 20: "task20",
    21: "task21", 22: "task22", 23: "task23", 24: "task24", 25: "task25",
}


def _clear_vc_data(context: ContextTypes.DEFAULT_TYPE):
    """Очищает данные проверки варианта из контекста."""
    keys_to_clear = [
        'vc_source', 'vc_variant_data', 'vc_selected_tasks',
        'vc_keys', 'vc_current_task_idx', 'vc_student_answers',
        'vc_results', 'vc_batch_results', 'vc_mode',
        'vc_entering_keys_idx', 'vc_student_name',
        'vc_part1_keys', 'vc_part1_answers',
    ]
    for key in keys_to_clear:
        context.user_data.pop(key, None)


# ============================================
# Меню проверки варианта
# ============================================

async def variant_check_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню проверки варианта."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем квоту
    quota = await quick_check_service.get_or_create_quota(user_id)
    if not quota:
        await query.message.edit_text(
            "❌ Ошибка получения квоты. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    _clear_vc_data(context)

    text = (
        "📋 <b>Проверка варианта</b>\n\n"
        "Проверьте целый вариант ЕГЭ одного или нескольких "
        "учеников за раз.\n\n"
        f"📊 Доступно проверок: <b>{quota.remaining_checks}</b>\n\n"
        "Выберите источник варианта:"
    )

    keyboard = [
        [InlineKeyboardButton("📄 Внешний вариант", callback_data="vc_source_external")],
        [InlineKeyboardButton("🤖 Вариант из бота", callback_data="vc_source_bot")],
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_SOURCE


# ============================================
# Выбор источника варианта
# ============================================

async def select_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора источника варианта."""
    query = update.callback_query
    await query.answer()

    source = query.data.replace("vc_source_", "")
    context.user_data['vc_source'] = source

    if source == 'bot':
        return await _show_bot_variant_info(update, context)
    else:
        return await _show_task_selection(update, context)


async def _show_bot_variant_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает информацию о проверке варианта из бота."""
    query = update.callback_query

    text = (
        "🤖 <b>Вариант из бота</b>\n\n"
        "Для проверки варианта, сгенерированного ботом, "
        "введите ID варианта.\n\n"
        "💡 <i>ID варианта отображается при генерации и в результатах.</i>\n\n"
        "Или выберите другой режим:"
    )

    keyboard = [
        [InlineKeyboardButton("📝 Ввести ID варианта", callback_data="vc_enter_variant_id")],
        [InlineKeyboardButton("📄 Внешний вариант", callback_data="vc_source_external")],
        [InlineKeyboardButton("◀️ Назад", callback_data="vc_menu")]
    ]

    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_SOURCE


async def enter_variant_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос ввода ID варианта из бота."""
    query = update.callback_query
    await query.answer()

    text = (
        "🔍 <b>Введите ID варианта</b>\n\n"
        "Введите ID варианта, сгенерированного ботом.\n"
        "Формат: <code>v-XXXXXXXX</code>"
    )

    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="vc_menu")]]

    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_SOURCE


async def process_variant_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введённого ID варианта."""
    variant_id = update.message.text.strip()

    # Пытаемся загрузить вариант из БД
    variant_data = await _load_variant_from_db(variant_id)

    if not variant_data:
        await update.message.reply_text(
            f"❌ Вариант <code>{variant_id}</code> не найден.\n\n"
            "Проверьте ID и попробуйте ещё раз.",
            parse_mode='HTML'
        )
        return TeacherStates.VARIANT_CHECK_SOURCE

    context.user_data['vc_variant_data'] = variant_data
    context.user_data['vc_source'] = 'bot'

    # Автоматически загружаем ключи из варианта
    keys = _extract_keys_from_variant(variant_data)
    context.user_data['vc_keys'] = keys

    # Определяем доступные задания
    available_tasks = sorted(keys.keys())
    context.user_data['vc_selected_tasks'] = available_tasks

    text = (
        f"✅ <b>Вариант загружен!</b>\n\n"
        f"ID: <code>{variant_id}</code>\n"
        f"Заданий: {len(available_tasks)}\n"
        f"Ключи загружены автоматически.\n\n"
        "Выберите задания для проверки или проверьте все:"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Проверить все задания", callback_data="vc_tasks_all")],
        [InlineKeyboardButton("📝 Только часть 2 (17-25)", callback_data="vc_tasks_part2")],
        [InlineKeyboardButton("⚙️ Выбрать задания", callback_data="vc_tasks_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="vc_menu")]
    ]

    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_SELECT_TASKS


async def _load_variant_from_db(variant_id: str) -> Optional[Dict]:
    """Загружает вариант из БД по ID."""
    try:
        import aiosqlite
        from core.db import DATABASE_FILE

        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT variant_data FROM full_exam_results WHERE variant_id = ? LIMIT 1",
                (variant_id,)
            )
            row = await cursor.fetchone()
            if row and row['variant_data']:
                return json.loads(row['variant_data'])
    except Exception as e:
        logger.error(f"Error loading variant {variant_id}: {e}", exc_info=True)
    return None


def _extract_keys_from_variant(variant_data: Dict) -> Dict[int, Dict]:
    """Извлекает ключи (правильные ответы) из данных варианта."""
    keys = {}
    tasks = variant_data.get('tasks', {})

    for task_num_str, task_info in tasks.items():
        task_num = int(task_num_str)
        task_data = task_info.get('task_data', {})

        if 1 <= task_num <= 16:
            # Часть 1: точный ответ
            keys[task_num] = {
                'type': 'exact',
                'answer': task_data.get('answer', ''),
                'question_type': task_data.get('type', 'text'),
            }
        elif 17 <= task_num <= 25:
            # Часть 2: данные для AI-проверки
            keys[task_num] = {
                'type': 'ai',
                'task_data': task_data,
                'module': TASK_MODULES.get(task_num, f'task{task_num}'),
            }

    return keys


# ============================================
# Выбор заданий (для внешнего варианта)
# ============================================

async def _show_task_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает экран выбора заданий для проверки."""
    query = update.callback_query

    text = (
        "📄 <b>Внешний вариант</b>\n\n"
        "Выберите, какие задания будете проверять:"
    )

    keyboard = [
        [InlineKeyboardButton("📝 Все задания (1-25)", callback_data="vc_tasks_all")],
        [InlineKeyboardButton("📝 Часть 2 (17-25)", callback_data="vc_tasks_part2")],
        [InlineKeyboardButton("⚙️ Выбрать задания", callback_data="vc_tasks_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="vc_menu")]
    ]

    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_SELECT_TASKS


async def select_tasks_preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора предустановленного набора заданий."""
    query = update.callback_query
    await query.answer()

    preset = query.data.replace("vc_tasks_", "")

    if preset == 'all':
        context.user_data['vc_selected_tasks'] = list(range(1, 26))
    elif preset == 'part2':
        context.user_data['vc_selected_tasks'] = list(range(17, 26))
    elif preset == 'custom':
        return await _show_custom_task_selection(update, context)

    source = context.user_data.get('vc_source', 'external')

    if source == 'bot':
        # Ключи уже загружены, переходим к вводу ответов
        return await _show_mode_selection(update, context)
    else:
        # Для внешнего варианта: переходим к вводу ключей
        return await _start_entering_keys(update, context)


async def _show_custom_task_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает интерфейс для выбора конкретных заданий."""
    query = update.callback_query

    selected = set(context.user_data.get('vc_selected_tasks', []))

    text = "⚙️ <b>Выберите задания для проверки:</b>\n\n"
    text += "Нажмите на кнопки для выбора/отмены заданий.\n"

    keyboard = []

    # Часть 1: задания 1-16 (по 4 в ряд)
    text += "\n<b>Часть 1:</b>"
    for row_start in range(1, 17, 4):
        row = []
        for num in range(row_start, min(row_start + 4, 17)):
            icon = "✅" if num in selected else "⬜"
            row.append(InlineKeyboardButton(
                f"{icon} {num}", callback_data=f"vc_toggle_{num}"
            ))
        keyboard.append(row)

    # Часть 2: задания 17-25 (по 3 в ряд)
    text += "\n<b>Часть 2:</b>"
    for row_start in range(17, 26, 3):
        row = []
        for num in range(row_start, min(row_start + 3, 26)):
            icon = "✅" if num in selected else "⬜"
            name = TASK_NAMES.get(num, str(num))
            row.append(InlineKeyboardButton(
                f"{icon} {num}", callback_data=f"vc_toggle_{num}"
            ))
        keyboard.append(row)

    # Кнопки быстрого выбора
    keyboard.append([
        InlineKeyboardButton("Все", callback_data="vc_select_all"),
        InlineKeyboardButton("Часть 1", callback_data="vc_select_part1"),
        InlineKeyboardButton("Часть 2", callback_data="vc_select_part2"),
        InlineKeyboardButton("Сбросить", callback_data="vc_select_none"),
    ])

    # Кнопка подтверждения
    if selected:
        keyboard.append([InlineKeyboardButton(
            f"✅ Подтвердить ({len(selected)} заданий)", callback_data="vc_confirm_tasks"
        )])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="vc_menu")])

    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_SELECT_TASKS


async def toggle_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переключает выбор задания."""
    query = update.callback_query
    await query.answer()

    task_num = int(query.data.replace("vc_toggle_", ""))
    selected = set(context.user_data.get('vc_selected_tasks', []))

    if task_num in selected:
        selected.discard(task_num)
    else:
        selected.add(task_num)

    context.user_data['vc_selected_tasks'] = sorted(selected)
    return await _show_custom_task_selection(update, context)


async def select_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбирает группу заданий."""
    query = update.callback_query
    await query.answer()

    group = query.data.replace("vc_select_", "")

    if group == 'all':
        context.user_data['vc_selected_tasks'] = list(range(1, 26))
    elif group == 'part1':
        selected = set(context.user_data.get('vc_selected_tasks', []))
        selected.update(range(1, 17))
        context.user_data['vc_selected_tasks'] = sorted(selected)
    elif group == 'part2':
        selected = set(context.user_data.get('vc_selected_tasks', []))
        selected.update(range(17, 26))
        context.user_data['vc_selected_tasks'] = sorted(selected)
    elif group == 'none':
        context.user_data['vc_selected_tasks'] = []

    return await _show_custom_task_selection(update, context)


async def confirm_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение выбранных заданий."""
    query = update.callback_query

    selected = context.user_data.get('vc_selected_tasks', [])
    if not selected:
        await query.answer("Выберите хотя бы одно задание", show_alert=True)
        return TeacherStates.VARIANT_CHECK_SELECT_TASKS

    await query.answer()

    source = context.user_data.get('vc_source', 'external')

    if source == 'bot':
        return await _show_mode_selection(update, context)
    else:
        return await _start_entering_keys(update, context)


# ============================================
# Ввод ключей (для внешнего варианта)
# ============================================

async def _start_entering_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс ввода ключей для внешнего варианта."""
    query = update.callback_query

    selected = context.user_data.get('vc_selected_tasks', [])
    part1_tasks = [t for t in selected if t <= 16]
    part2_tasks = [t for t in selected if t >= 17]

    context.user_data['vc_keys'] = {}
    context.user_data['vc_entering_keys_idx'] = 0

    lines = ["📝 <b>Ввод ключей (правильных ответов)</b>\n"]

    lines.append(
        "Отправьте <b>один файл</b> (TXT/PDF/DOCX), <b>текст</b> "
        "или <b>фото</b> с ключами ко всем заданиям сразу.\n"
    )

    # Формат ввода
    lines.append("<b>Формат:</b>\n")

    if part1_tasks and part2_tasks:
        lines.append(
            "<code>1: 24\n"
            "2: 135\n"
            "...\n"
            "17:\n"
            "[условие задания]\n"
            "---\n"
            "[ответ / критерии]\n"
            "18:\n"
            "[условие]\n"
            "---\n"
            "[ответ]</code>\n"
        )
    elif part1_tasks:
        lines.append(
            "<code>1: 24\n"
            "2: 135\n"
            "3: социализация\n"
            "...</code>\n"
        )
    elif part2_tasks:
        lines.append(
            "<code>17:\n"
            "[условие задания]\n"
            "---\n"
            "[ответ / критерии]\n"
            "18:\n"
            "[условие]\n"
            "---\n"
            "[ответ]</code>\n"
        )

    lines.append(
        "Номер задания в начале строки — граница блока.\n"
        "Для части 2: <code>---</code> отделяет условие от ответа.\n"
    )

    lines.append(
        "📄 <b>Файл</b> — TXT, PDF или DOCX\n"
        "📷 <b>Фото</b> — распознаем текст (OCR)\n"
    )

    lines.append("Отправьте ключи одним сообщением или файлом:")

    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="vc_menu")]]

    await query.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_ENTER_KEYS


async def process_keys_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода ключей от учителя (текстовое сообщение)."""
    text = update.message.text.strip()
    return await _process_keys_from_text(update, context, text, source="текста")


async def process_keys_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка файла (TXT/PDF/DOCX) с ключами."""
    from core.document_processor import DocumentProcessor

    if not update.message or not update.message.document:
        await update.message.reply_text("❌ Документ не найден.")
        return TeacherStates.VARIANT_CHECK_ENTER_KEYS

    document = update.message.document
    processing_msg = await update.message.reply_text("📄 Обрабатываю файл с ключами...")

    success, text, error = await DocumentProcessor.process_document(document, context)

    try:
        await processing_msg.delete()
    except Exception:
        pass

    if not success:
        import html as html_module
        await update.message.reply_text(
            f"❌ Ошибка обработки файла:\n{html_module.escape(str(error))}\n\n"
            "Поддерживаемые форматы: TXT, PDF, DOCX.",
            parse_mode='HTML'
        )
        return TeacherStates.VARIANT_CHECK_ENTER_KEYS

    # Парсим содержимое файла как ключи
    return await _process_keys_from_text(update, context, text, source="файла")


async def process_keys_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка фото с ключами (OCR)."""
    from core.vision_service import process_photo_message

    extracted_text = await process_photo_message(
        update,
        context.application.bot,
        task_name="ключи к заданиям",
        task_context="ЕГЭ обществознание, ключи (правильные ответы) к варианту"
    )

    if not extracted_text:
        await update.message.reply_text(
            "❌ Не удалось распознать текст с фото.\n\n"
            "Попробуйте ещё раз или введите ключи текстом / загрузите файл."
        )
        return TeacherStates.VARIANT_CHECK_ENTER_KEYS

    return await _process_keys_from_text(update, context, extracted_text, source="фото")


async def _process_keys_from_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    source: str = "текста"
) -> int:
    """Общая логика парсинга ключей из текста (из файла, фото или сообщения)."""
    selected = context.user_data.get('vc_selected_tasks', [])
    keys = context.user_data.get('vc_keys', {})

    part1_tasks = [t for t in selected if t <= 16]
    part2_tasks = [t for t in selected if t >= 17]

    # Пытаемся распарсить как комплексный файл со всеми ключами сразу
    parsed_all = _parse_bulk_keys(text, selected)
    if parsed_all:
        keys.update(parsed_all)
        context.user_data['vc_keys'] = keys

        # Считаем сколько ключей для каждой части
        p1_count = sum(1 for k in parsed_all if k <= 16)
        p2_count = sum(1 for k in parsed_all if k >= 17)
        parts_info = []
        if p1_count:
            parts_info.append(f"часть 1: {p1_count}")
        if p2_count:
            parts_info.append(f"часть 2: {p2_count}")

        # Проверяем, загружены ли ключи для всех выбранных заданий
        missing = [t for t in selected if t not in keys]

        if missing:
            missing_str = ", ".join(str(t) for t in sorted(missing))
            await update.message.reply_text(
                f"✅ Из {source} загружено <b>{len(parsed_all)}</b> ключей "
                f"({', '.join(parts_info)}).\n\n"
                f"⚠️ Не найдены ключи для заданий: <b>{missing_str}</b>\n"
                "Отправьте недостающие ключи или продолжите с имеющимися.",
                parse_mode='HTML'
            )
            # Обновляем индекс для пошагового ввода оставшихся заданий ч.2
            missing_p2 = [t for t in part2_tasks if t not in keys]
            if missing_p2:
                context.user_data['vc_entering_keys_idx'] = part2_tasks.index(missing_p2[0])
            return await _keys_complete(update, context)

        await update.message.reply_text(
            f"✅ Из {source} загружено <b>{len(parsed_all)}</b> ключей "
            f"({', '.join(parts_info)}).",
            parse_mode='HTML'
        )

        # Если задание 18 загружено, предлагаем добавить текст-источник
        if 18 in parsed_all:
            return await _ask_source_text_for_task18(update, context)

        return await _keys_complete(update, context)

    # Если комплексный парсинг не дал результатов, пробуем как для текущего шага
    part1_keys_entered = any(t in keys for t in range(1, 17))

    if part1_tasks and not part1_keys_entered:
        parsed = _parse_part1_keys(text, part1_tasks)
        if parsed:
            keys.update(parsed)
            context.user_data['vc_keys'] = keys

            if part2_tasks:
                context.user_data['vc_entering_keys_idx'] = 0
                task_num = part2_tasks[0]
                await update.message.reply_text(
                    f"✅ Из {source} загружены ответы части 1 ({len(parsed)} заданий).\n\n"
                    f"Теперь введите данные для <b>задания {task_num}</b> "
                    f"({TASK_NAMES.get(task_num, '')}):",
                    parse_mode='HTML'
                )
                return TeacherStates.VARIANT_CHECK_ENTER_KEYS
            else:
                return await _keys_complete(update, context)
        else:
            # Не удалось распознать ответы части 1
            await update.message.reply_text(
                f"❌ Не удалось распознать ответы из {source}.\n\n"
                "Используйте формат:\n"
                "<code>1: 24\n2: 135\n3: текст</code>\n\n"
                "Или загрузите файл / фото с ключами.",
                parse_mode='HTML'
            )
            return TeacherStates.VARIANT_CHECK_ENTER_KEYS

    # Для части 2: парсим как условие + ключ для текущего задания
    if part2_tasks:
        idx = context.user_data.get('vc_entering_keys_idx', 0)
        if idx < len(part2_tasks):
            task_num = part2_tasks[idx]
            parsed = _parse_part2_key(text, task_num)
            keys[task_num] = parsed
            context.user_data['vc_keys'] = keys

            idx += 1
            context.user_data['vc_entering_keys_idx'] = idx

            # Для задания 18: предлагаем загрузить текст-источник
            if task_num == 18:
                return await _ask_source_text_for_task18(update, context)

            if idx < len(part2_tasks):
                next_task = part2_tasks[idx]
                await update.message.reply_text(
                    f"✅ Ключ для задания {task_num} загружен из {source}.\n\n"
                    f"Введите данные для <b>задания {next_task}</b> "
                    f"({TASK_NAMES.get(next_task, '')}):",
                    parse_mode='HTML'
                )
                return TeacherStates.VARIANT_CHECK_ENTER_KEYS
            else:
                return await _keys_complete(update, context)

    await update.message.reply_text(
        f"❌ Не удалось распознать ключи из {source}.\n\n"
        "Проверьте формат и попробуйте ещё раз.",
        parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_ENTER_KEYS


def _parse_bulk_keys(text: str, selected: List[int]) -> Optional[Dict[int, Dict]]:
    """
    Парсит комплексный файл с ключами ко всем заданиям сразу.

    Поддерживаемые форматы:

    Формат 1 (с разделителями ===):
        17:
        [условие]
        ---
        [ответ]
        ===
        18:
        ...

    Формат 2 (простой — номера заданий как границы блоков):
        1: 24
        2: 135
        ...
        17:
        [условие]
        ---
        [ответ]
        18:
        [условие]
        ---
        [ответ]

    Для части 1: "N: ответ" на одной строке.
    Для части 2: номер задания, затем многострочный блок до следующего номера.
    Разделитель --- между условием и ответом/критериями (опционально).
    """
    keys = {}

    # Стратегия 1: если есть разделители ===, разбиваем по ним
    if re.search(r'\n\s*===\s*\n', text) or text.strip().endswith('==='):
        keys = _parse_bulk_keys_delimited(text, selected)

    # Стратегия 2: разбиваем по номерам заданий как границам блоков
    if not keys:
        keys = _parse_bulk_keys_by_task_numbers(text, selected)

    return keys if keys else None


def _parse_bulk_keys_delimited(text: str, selected: List[int]) -> Dict[int, Dict]:
    """Парсит ключи, разделённые === между блоками (старый формат)."""
    keys = {}
    blocks = re.split(r'\n\s*===\s*(?:\n|$)', text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        header_match = re.match(
            r'^(?:Задание\s*(?:№\s*)?|№\s*)?(\d+)\s*[:\.\)]\s*(.*)',
            block, re.DOTALL
        )

        if header_match:
            num = int(header_match.group(1))
            content = header_match.group(2).strip()

            if num in selected:
                if num <= 16:
                    answer = content.split('\n')[0].strip()
                    if answer:
                        keys[num] = {'type': 'exact', 'answer': answer}
                else:
                    keys[num] = _parse_part2_key(content, num)
        else:
            # Блок без номера — пробуем как набор коротких ответов
            for line in block.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                match = re.match(r'^(\d+)\s*[:\-\)\.]\s*(.+)$', line)
                if match:
                    num = int(match.group(1))
                    answer = match.group(2).strip()
                    if num in selected and 1 <= num <= 16:
                        keys[num] = {'type': 'exact', 'answer': answer}

    return keys


def _parse_bulk_keys_by_task_numbers(text: str, selected: List[int]) -> Dict[int, Dict]:
    """
    Парсит ключи, используя номера заданий как границы блоков.

    Ищет паттерны вида "N:", "N.", "Задание N", "№N" и разбивает текст
    на блоки по этим границам. Работает как с многострочным, так и
    с однострочным текстом (после _clean_text из PDF).

    Умеет отличать заголовки заданий от пронумерованных пунктов внутри
    критериев оценивания (например, "1) основные признаки..." не будет
    ошибочно принято за задание 1).
    """
    keys = {}

    # Паттерн заголовка задания (используется для split по всему тексту)
    # Поддерживает: "17:", "17.", "17)", "Задание 17:", "Задание 17.",
    # "Задание 17" (без разделителя), "Задание №17", "№17", "№ 17"
    task_header_pattern = (
        r'(?:^|\n)\s*'
        r'(?:Задание\s*(?:№\s*)?|№\s*)?'
        r'(\d{1,2})'
        r'\s*[:\.\)]\s*'
    )

    # Также поддерживаем "Задание 17" без разделителя (но только если после числа
    # идёт перенос строки или конец строки, чтобы не ловить числа внутри текста)
    task_header_pattern_no_sep = (
        r'(?:^|\n)\s*'
        r'(?:Задание\s*(?:№\s*)?|№\s*)'
        r'(\d{1,2})'
        r'\s*(?=[:\.\)\n]|\s*$|\s+[А-Яа-яA-Za-z(])'
    )

    # Контекстные слова-маркеры критериев оценивания ФИПИ.
    # Если совпадение находится рядом с этими маркерами,
    # скорее всего это пункт внутри критериев, а не заголовок задания.
    criteria_context_words = [
        'правильно приведен', 'правильно приведён',
        'сформулирован', 'результатом', 'могут быть',
        'максимальный балл', 'балла', 'баллов',
        'указания по оцениванию', 'засчитывается',
        'иные ситуации', 'рассуждения общего характера',
    ]

    def _is_likely_task_header(match_obj, num: int) -> bool:
        """Проверяет, является ли совпадение заголовком задания, а не пунктом критерия."""
        pos = match_obj.start()
        matched_text = match_obj.group(0).strip()

        # "Задание N" или "№N" — точно заголовок
        if re.match(r'(?:Задание|№)', matched_text, re.IGNORECASE):
            return True

        # Проверяем контекст вокруг совпадения (±200 символов)
        context_start = max(0, pos - 200)
        context_end = min(len(text), pos + 200)
        context = text[context_start:context_end].lower()

        # Если рядом есть маркеры критериев — это пункт внутри критерия
        for marker in criteria_context_words:
            if marker in context:
                # Но если номер >= 17, это скорее всего настоящий заголовок задания
                # (в критериях пункты обычно нумеруются 1-3)
                if num < 10:
                    return False

        return True

    # Собираем все позиции заголовков
    task_positions: List[Tuple[int, int, str]] = []  # (char_pos, task_num, content_start_pos)

    for m in re.finditer(task_header_pattern, text):
        num = int(m.group(1))
        if 1 <= num <= 25 and _is_likely_task_header(m, num):
            task_positions.append((m.start(), num, m.end()))

    # Дополнительно ищем "Задание N" без разделителя
    for m in re.finditer(task_header_pattern_no_sep, text):
        num = int(m.group(1))
        if 1 <= num <= 25:
            # Проверяем, что эта позиция ещё не найдена
            already_found = any(abs(pos - m.start()) < 5 for pos, _, _ in task_positions)
            if not already_found:
                task_positions.append((m.start(), num, m.end()))

    # Сортируем по позиции в тексте
    task_positions.sort(key=lambda x: x[0])

    if not task_positions:
        return keys

    # Проверяем, что номера заданий идут в возрастающем порядке
    # (помогает отсеять ложные срабатывания)
    filtered_positions = []
    prev_num = 0
    for pos in task_positions:
        num = pos[1]
        if num > prev_num:
            filtered_positions.append(pos)
            prev_num = num
        elif num in selected:
            # Если номер не в порядке, но в selected — всё равно берём
            filtered_positions.append(pos)
            prev_num = num
    task_positions = filtered_positions

    # Для каждого найденного задания извлекаем содержимое блока
    for pos_idx, (char_pos, num, content_start) in enumerate(task_positions):
        if num not in selected:
            continue

        # Конец блока — начало следующего задания или конец текста
        if pos_idx + 1 < len(task_positions):
            content_end = task_positions[pos_idx + 1][0]
        else:
            content_end = len(text)

        block_text = text[content_start:content_end].strip()

        if num <= 16:
            # Часть 1: берём первую строку / текст до переноса
            answer = block_text.split('\n')[0].strip()
            if answer:
                keys[num] = {'type': 'exact', 'answer': answer}
        else:
            # Часть 2: многострочный блок (условие + критерии)
            if block_text:
                keys[num] = _parse_part2_key(block_text, num)

    return keys


def _parse_part1_keys(text: str, expected_tasks: List[int]) -> Optional[Dict[int, Dict]]:
    """Парсит ответы части 1 из текста."""
    keys = {}
    lines = text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Формат: "1: ответ" или "1 - ответ" или "1) ответ"
        match = re.match(r'^(\d+)\s*[:\-\)\.]\s*(.+)$', line)
        if match:
            num = int(match.group(1))
            answer = match.group(2).strip()
            if 1 <= num <= 16:
                keys[num] = {
                    'type': 'exact',
                    'answer': answer,
                }

    return keys if keys else None


def _parse_part2_key(text: str, task_num: int) -> Dict:
    """Парсит условие и ключ для задания части 2.

    Поддерживает форматы:
    1. С разделителем --- между условием и ключом
    2. ФИПИ-формат: условие задания + таблица "Содержание верного ответа
       и указания по оцениванию" + баллы + "Максимальный балл"
    3. Без разделителя — весь текст как условие + ключ
    """
    condition = ""
    answer_key = ""

    # Стратегия 1: разделитель ---
    parts = re.split(r'\n\s*---\s*\n', text, maxsplit=1)
    if len(parts) == 2:
        condition = parts[0].strip()
        answer_key = parts[1].strip()
    else:
        # Стратегия 2: ФИПИ-формат — ищем маркер начала критериев
        fipi_markers = [
            r'Содержание\s+верного\s+ответа',
            r'Указания\s+по\s+оцениванию',
            r'В\s+правильном\s+ответе\s+(?:должны\s+быть|могут\s+быть)',
        ]
        fipi_split_pos = None
        for marker in fipi_markers:
            m = re.search(marker, text, re.IGNORECASE)
            if m:
                fipi_split_pos = m.start()
                break

        if fipi_split_pos is not None and fipi_split_pos > 10:
            condition = text[:fipi_split_pos].strip()
            answer_key = text[fipi_split_pos:].strip()
            # Убираем шапку таблицы и столбец "Баллы" из критериев
            answer_key = _clean_fipi_criteria(answer_key)
        else:
            # Стратегия 3: весь текст — условие + ключ
            condition = text.strip()
            answer_key = ""

    module = TASK_MODULES.get(task_num, f'task{task_num}')

    task_data = {
        'task_text': condition,
        'title': TASK_NAMES.get(task_num, f'Задание {task_num}'),
        'correct_answer_criteria': answer_key,
    }

    # Для задания 18: извлекаем ключевое понятие из условия
    if task_num == 18:
        from task18.evaluator import extract_concept_from_text
        concept = extract_concept_from_text(condition)
        if concept:
            task_data['concept'] = concept

    return {
        'type': 'ai',
        'task_data': task_data,
        'module': module,
        'condition_text': condition,
        'answer_key_text': answer_key,
    }


def _clean_fipi_criteria(text: str) -> str:
    """Очищает критерии оценивания ФИПИ от шапки таблицы и мусора.

    Убирает заголовки столбцов, колонки с баллами, копирайт и т.п.
    """
    # Убираем заголовок таблицы "Содержание верного ответа ... Баллы"
    text = re.sub(
        r'Содержание\s+верного\s+ответа\s+и\s+указания\s+по\s+оцениванию\s*'
        r'(?:\(допускаются[^)]*\))?\s*Баллы?\s*',
        '', text, flags=re.IGNORECASE
    )
    # Убираем строки "Максимальный балл N"
    text = re.sub(
        r'Максимальный\s+балл\s+\d+',
        '', text, flags=re.IGNORECASE
    )
    # Убираем копирайт ФИПИ
    text = re.sub(
        r'©\s*\d{4}\s*ФГ?БНУ.*?(?:не\s+допускается|$)',
        '', text, flags=re.IGNORECASE
    )
    # Убираем одиночные числа-баллы на отдельных строках (остатки столбца "Баллы")
    text = re.sub(r'(?m)^\s*\d\s*$', '', text)
    # Убираем множественные пустые строки
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


async def _ask_source_text_for_task18(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Предлагает загрузить текст-источник для задания 18."""
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить", callback_data="vc_skip_source_text")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="vc_menu")],
    ]

    text = (
        "✅ Ключ для задания 18 загружен.\n\n"
        "📄 <b>Текст-источник (из задания 17)</b>\n\n"
        "Для полной проверки задания 18 (Элемент 2 — объяснение связи с текстом) "
        "рекомендуется загрузить текст, на который опирается задание.\n\n"
        "Отправьте текст-источник или нажмите <b>«Пропустить»</b>, "
        "чтобы проверить только признаки понятия (Элемент 1)."
    )

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_ENTER_SOURCE_TEXT


async def process_source_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработка текста-источника для задания 18."""
    source_text = update.message.text.strip()

    if len(source_text) < 20:
        await update.message.reply_text(
            "❌ Текст слишком короткий. Минимум 20 символов.\n\n"
            "Отправьте текст-источник или нажмите «Пропустить».",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Пропустить", callback_data="vc_skip_source_text"),
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.VARIANT_CHECK_ENTER_SOURCE_TEXT

    # Сохраняем текст-источник в task_data задания 18
    keys = context.user_data.get('vc_keys', {})
    if 18 in keys:
        keys[18]['task_data']['source_text'] = source_text
        keys[18]['task_data']['text'] = source_text
        context.user_data['vc_keys'] = keys

    return await _continue_after_source_text(update, context, loaded=True)


async def skip_source_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Пропуск загрузки текста-источника для задания 18."""
    query = update.callback_query
    await query.answer()

    return await _continue_after_source_text(update, context, loaded=False)


async def _continue_after_source_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    loaded: bool
) -> int:
    """Продолжает ввод ключей после шага загрузки текста-источника."""
    selected = context.user_data.get('vc_selected_tasks', [])
    part2_tasks = [t for t in selected if t >= 17]
    idx = context.user_data.get('vc_entering_keys_idx', 0)

    status = "✅ Текст-источник загружен." if loaded else "⏭ Текст-источник пропущен (будет проверен только Элемент 1)."

    if idx < len(part2_tasks):
        next_task = part2_tasks[idx]
        text = (
            f"{status}\n\n"
            f"Введите данные для <b>задания {next_task}</b> "
            f"({TASK_NAMES.get(next_task, '')}):"
        )

        # Определяем, откуда отправить (callback_query или message)
        if update.callback_query:
            await update.callback_query.message.edit_text(
                text, parse_mode='HTML'
            )
        else:
            await update.message.reply_text(text, parse_mode='HTML')

        return TeacherStates.VARIANT_CHECK_ENTER_KEYS
    else:
        if update.callback_query:
            # Нужно создать "виртуальный" update для _keys_complete
            await update.callback_query.message.edit_text(
                f"{status}\n\nВсе ключи загружены!",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(status, parse_mode='HTML')

        return await _keys_complete(update, context)


async def _keys_complete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Все ключи введены, переходим к выбору режима проверки."""
    keys = context.user_data.get('vc_keys', {})
    selected = context.user_data.get('vc_selected_tasks', [])

    text = (
        f"✅ <b>Ключи готовы!</b>\n\n"
        f"Заданий для проверки: <b>{len(selected)}</b>\n"
        f"Ключей загружено: <b>{len(keys)}</b>\n\n"
        "Выберите режим проверки:"
    )

    keyboard = [
        [InlineKeyboardButton("👤 Один ученик", callback_data="vc_mode_single")],
        [InlineKeyboardButton("👥 Несколько учеников", callback_data="vc_mode_batch")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="vc_menu")]
    ]

    if update.message:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )
    return TeacherStates.VARIANT_CHECK_CONFIRM


async def _show_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает выбор режима проверки (один/несколько учеников)."""
    query = update.callback_query

    selected = context.user_data.get('vc_selected_tasks', [])
    keys = context.user_data.get('vc_keys', {})

    text = (
        f"✅ <b>Вариант готов к проверке!</b>\n\n"
        f"Заданий: <b>{len(selected)}</b>\n"
        f"Ключей: <b>{len(keys)}</b>\n\n"
        "Выберите режим проверки:"
    )

    keyboard = [
        [InlineKeyboardButton("👤 Один ученик", callback_data="vc_mode_single")],
        [InlineKeyboardButton("👥 Несколько учеников", callback_data="vc_mode_batch")],
        [InlineKeyboardButton("◀️ Назад", callback_data="vc_menu")]
    ]

    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_CONFIRM


async def select_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора режима (один/несколько учеников)."""
    query = update.callback_query
    await query.answer()

    mode = query.data.replace("vc_mode_", "")
    context.user_data['vc_mode'] = mode
    context.user_data['vc_batch_results'] = []
    context.user_data['vc_student_answers'] = {}
    context.user_data['vc_current_task_idx'] = 0

    return await _prompt_for_student_answers(update, context, is_query=True)


# ============================================
# Ввод ответов ученика
# ============================================

async def _prompt_for_student_answers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    is_query: bool = True
) -> int:
    """Запрашивает ответы ученика."""
    selected = context.user_data.get('vc_selected_tasks', [])
    idx = context.user_data.get('vc_current_task_idx', 0)
    mode = context.user_data.get('vc_mode', 'single')
    batch_results = context.user_data.get('vc_batch_results', [])

    student_num = len(batch_results) + 1 if mode == 'batch' else None

    if idx == 0:
        # Начало ввода ответов — предложить два способа
        part1_tasks = [t for t in selected if t <= 16]
        part2_tasks = [t for t in selected if t >= 17]

        lines = []
        if student_num:
            lines.append(f"👤 <b>Ученик #{student_num}</b>\n")

        lines.append("📝 <b>Введите ответы ученика</b>\n")
        lines.append(
            "Вы можете ввести все ответы <b>одним сообщением</b>, "
            "<b>по одному заданию</b>, загрузить <b>файлом</b> (TXT/PDF/DOCX) "
            "или отправить <b>фото</b>.\n"
        )

        lines.append("<b>Формат для всех ответов сразу:</b>\n")

        if part1_tasks:
            lines.append(
                "<code>1: ответ\n2: ответ\n...\n</code>"
            )

        if part2_tasks:
            lines.append(
                "<code>17:\nтекст ответа на задание 17\n===\n"
                "18:\nтекст ответа на задание 18\n===\n...</code>\n"
            )

        lines.append(
            "Или введите ответ на первое задание, "
            f"и мы пройдём по каждому:\n\n"
            f"<b>Задание {selected[0]}</b> ({TASK_NAMES.get(selected[0], '')}):"
        )

        text = "\n".join(lines)
    else:
        # Продолжение: следующее задание
        if idx >= len(selected):
            return await _run_evaluation(update, context)

        task_num = selected[idx]
        text = (
            f"📝 <b>Задание {task_num}</b> ({TASK_NAMES.get(task_num, '')})\n\n"
            f"Введите ответ ученика:"
        )

    keyboard = []
    if idx > 0:
        keyboard.append([InlineKeyboardButton(
            "⏭ Пропустить задание", callback_data="vc_skip_task"
        )])
    keyboard.append([InlineKeyboardButton(
        "✅ Завершить ввод и проверить", callback_data="vc_finish_input"
    )])
    keyboard.append([InlineKeyboardButton("◀️ Отмена", callback_data="vc_menu")])

    if is_query:
        query = update.callback_query
        await query.message.edit_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )

    return TeacherStates.VARIANT_CHECK_ENTER_ANSWER


async def process_student_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ответа ученика."""
    text = update.message.text.strip()
    selected = context.user_data.get('vc_selected_tasks', [])
    idx = context.user_data.get('vc_current_task_idx', 0)
    answers = context.user_data.get('vc_student_answers', {})

    # Пытаемся распознать формат "все ответы сразу"
    if idx == 0 and _looks_like_bulk_answers(text, selected):
        parsed = _parse_bulk_answers(text, selected)
        if parsed and len(parsed) > 1:
            answers.update(parsed)
            context.user_data['vc_student_answers'] = answers

            await update.message.reply_text(
                f"✅ Распознано ответов: <b>{len(parsed)}</b>\n\n"
                "Запускаю проверку...",
                parse_mode='HTML'
            )
            return await _run_evaluation(update, context)

    # Одиночный ответ на текущее задание
    if idx < len(selected):
        task_num = selected[idx]
        answers[task_num] = text
        context.user_data['vc_student_answers'] = answers

        idx += 1
        context.user_data['vc_current_task_idx'] = idx

        if idx >= len(selected):
            await update.message.reply_text(
                f"✅ Все ответы собраны ({len(answers)} заданий).\n\n"
                "Запускаю проверку...",
                parse_mode='HTML'
            )
            return await _run_evaluation(update, context)
        else:
            return await _prompt_for_student_answers(update, context, is_query=False)

    return await _run_evaluation(update, context)


async def process_answer_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка файла (TXT/PDF/DOCX) с ответами ученика."""
    from core.document_processor import DocumentProcessor

    if not update.message or not update.message.document:
        await update.message.reply_text("❌ Документ не найден.")
        return TeacherStates.VARIANT_CHECK_ENTER_ANSWER

    document = update.message.document
    processing_msg = await update.message.reply_text("📄 Обрабатываю файл с ответами...")

    success, text, error = await DocumentProcessor.process_document(document, context)

    try:
        await processing_msg.delete()
    except Exception:
        pass

    if not success:
        import html as html_module
        await update.message.reply_text(
            f"❌ Ошибка обработки файла:\n{html_module.escape(str(error))}\n\n"
            "Поддерживаемые форматы: TXT, PDF, DOCX.",
            parse_mode='HTML'
        )
        return TeacherStates.VARIANT_CHECK_ENTER_ANSWER

    return await _process_answers_from_text(update, context, text, source="файла")


async def process_answer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка фото с ответами ученика (OCR)."""
    from core.vision_service import process_photo_message

    extracted_text = await process_photo_message(
        update,
        context.application.bot,
        task_name="ответы ученика",
        task_context="ЕГЭ обществознание, ответы ученика на задания варианта"
    )

    if not extracted_text:
        await update.message.reply_text(
            "❌ Не удалось распознать текст с фото.\n\n"
            "Попробуйте ещё раз или введите ответы текстом / загрузите файл."
        )
        return TeacherStates.VARIANT_CHECK_ENTER_ANSWER

    return await _process_answers_from_text(update, context, extracted_text, source="фото")


async def _process_answers_from_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    source: str = "текста"
) -> int:
    """Общая логика парсинга ответов ученика из текста (файл, фото или сообщение)."""
    selected = context.user_data.get('vc_selected_tasks', [])
    idx = context.user_data.get('vc_current_task_idx', 0)
    answers = context.user_data.get('vc_student_answers', {})

    # Пытаемся распознать формат "все ответы сразу"
    if _looks_like_bulk_answers(text, selected):
        parsed = _parse_bulk_answers(text, selected)
        if parsed and len(parsed) > 1:
            answers.update(parsed)
            context.user_data['vc_student_answers'] = answers

            await update.message.reply_text(
                f"✅ Из {source} загружено ответов: <b>{len(parsed)}</b>\n\n"
                "Запускаю проверку...",
                parse_mode='HTML'
            )
            return await _run_evaluation(update, context)

    # Одиночный ответ на текущее задание
    if idx < len(selected):
        task_num = selected[idx]
        answers[task_num] = text
        context.user_data['vc_student_answers'] = answers

        idx += 1
        context.user_data['vc_current_task_idx'] = idx

        if idx >= len(selected):
            await update.message.reply_text(
                f"✅ Все ответы собраны ({len(answers)} заданий).\n\n"
                "Запускаю проверку...",
                parse_mode='HTML'
            )
            return await _run_evaluation(update, context)
        else:
            return await _prompt_for_student_answers(update, context, is_query=False)

    # Не удалось распознать
    await update.message.reply_text(
        f"❌ Не удалось распознать ответы из {source}.\n\n"
        "Проверьте формат и попробуйте ещё раз.",
        parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_ENTER_ANSWER


async def skip_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск текущего задания."""
    query = update.callback_query
    await query.answer()

    idx = context.user_data.get('vc_current_task_idx', 0)
    idx += 1
    context.user_data['vc_current_task_idx'] = idx

    selected = context.user_data.get('vc_selected_tasks', [])
    if idx >= len(selected):
        return await _finish_input(update, context)

    return await _prompt_for_student_answers(update, context, is_query=True)


async def _finish_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершение ввода и запуск проверки."""
    query = update.callback_query
    if query:
        await query.answer()

    answers = context.user_data.get('vc_student_answers', {})
    if not answers:
        msg = query.message if query else update.message
        await msg.reply_text(
            "❌ Нет ответов для проверки. Введите хотя бы один ответ.",
        )
        return TeacherStates.VARIANT_CHECK_ENTER_ANSWER

    return await _run_evaluation(update, context)


async def finish_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback для кнопки завершения ввода."""
    return await _finish_input(update, context)


def _looks_like_bulk_answers(text: str, selected: List[int]) -> bool:
    """Проверяет, похож ли текст на пакет ответов."""
    # Ищем паттерн "число: текст" или "число)\nтекст"
    lines = text.split('\n')
    numbered_count = 0
    for line in lines:
        if re.match(r'^\s*(\d+)\s*[:\-\)\.]', line.strip()):
            numbered_count += 1

    # Если есть разделители === или несколько пронумерованных строк
    has_separators = '===' in text
    return numbered_count >= 2 or has_separators


def _parse_bulk_answers(text: str, selected: List[int]) -> Dict[int, str]:
    """Парсит пакет ответов из одного сообщения."""
    answers = {}

    # Разделяем по === (для развёрнутых ответов)
    if '===' in text:
        blocks = re.split(r'\n\s*===\s*\n', text)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            match = re.match(r'^(\d+)\s*[:\-\)\.]\s*(.*)', block, re.DOTALL)
            if match:
                num = int(match.group(1))
                answer = match.group(2).strip()
                if num in selected:
                    answers[num] = answer
        return answers

    # Для коротких ответов (часть 1): построчно
    lines = text.strip().split('\n')

    # Собираем ответы, которые могут быть многострочными
    current_num = None
    current_lines = []

    for line in lines:
        match = re.match(r'^(\d+)\s*[:\-\)\.]\s*(.*)', line.strip())
        if match:
            # Сохраняем предыдущий ответ
            if current_num is not None:
                answers[current_num] = '\n'.join(current_lines).strip()
            current_num = int(match.group(1))
            current_lines = [match.group(2)]
        elif current_num is not None:
            current_lines.append(line)

    # Последний ответ
    if current_num is not None:
        answers[current_num] = '\n'.join(current_lines).strip()

    # Фильтруем по выбранным заданиям
    return {k: v for k, v in answers.items() if k in selected and v}


# ============================================
# Проверка ответов
# ============================================

async def _run_evaluation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запускает проверку всех ответов ученика."""
    user_id = update.effective_user.id
    answers = context.user_data.get('vc_student_answers', {})
    keys = context.user_data.get('vc_keys', {})
    selected = context.user_data.get('vc_selected_tasks', [])

    # Проверяем квоту
    tasks_to_check = [t for t in selected if t in answers]
    # Для AI-проверки считаем только часть 2
    ai_tasks = [t for t in tasks_to_check if t >= 17]
    quota_needed = len(ai_tasks)

    if quota_needed > 0:
        quota = await quick_check_service.get_or_create_quota(user_id)
        if not quota or quota.remaining_checks < quota_needed:
            remaining = quota.remaining_checks if quota else 0
            msg = update.callback_query.message if update.callback_query else update.message
            await msg.reply_text(
                f"❌ Недостаточно квоты.\n\n"
                f"Требуется: {quota_needed} проверок\n"
                f"Доступно: {remaining}\n\n"
                "Обновите подписку для увеличения лимита.",
                parse_mode='HTML'
            )
            return TeacherStates.VARIANT_CHECK_CONFIRM

    # Отправляем сообщение о начале проверки
    msg = update.callback_query.message if update.callback_query else update.message
    progress_msg = await msg.reply_text(
        f"⏳ <b>Проверяю вариант...</b>\n\n"
        f"Заданий: {len(tasks_to_check)}\n"
        f"AI-проверка: {len(ai_tasks)} заданий\n\n"
        "Это может занять некоторое время...",
        parse_mode='HTML'
    )

    # Проверяем каждое задание
    results = {}
    part1_correct = {}

    for task_num in tasks_to_check:
        answer = answers[task_num]
        key = keys.get(task_num, {})

        if task_num <= 16:
            # Часть 1: точное сравнение
            result = _check_part1_answer(task_num, answer, key)
            results[task_num] = result
            part1_correct[task_num] = result['is_correct']
        else:
            # Часть 2: AI-проверка
            try:
                result = await _check_part2_answer(task_num, answer, key, user_id)
                results[task_num] = result

                # Списываем квоту
                if quota_needed > 0:
                    await quick_check_service.check_and_use_quota(user_id, 1)

            except Exception as e:
                logger.error(f"Error checking task {task_num}: {e}", exc_info=True)
                results[task_num] = {
                    'score': 0,
                    'max_score': PART2_MAX_SCORES.get(task_num, 0),
                    'feedback': f"❌ Ошибка при проверке: {str(e)}",
                    'is_correct': False,
                }

    # Сохраняем результаты
    context.user_data['vc_results'] = results

    # В пакетном режиме: добавляем к списку результатов
    mode = context.user_data.get('vc_mode', 'single')
    if mode == 'batch':
        batch_results = context.user_data.get('vc_batch_results', [])
        batch_results.append({
            'student_num': len(batch_results) + 1,
            'student_name': context.user_data.get('vc_student_name', f'Ученик {len(batch_results) + 1}'),
            'answers': dict(answers),
            'results': dict(results),
        })
        context.user_data['vc_batch_results'] = batch_results

    # Удаляем сообщение о прогрессе
    try:
        await progress_msg.delete()
    except Exception:
        pass

    # Показываем результаты
    return await _show_results(update, context, results)


def _check_part1_answer(task_num: int, answer: str, key: Dict) -> Dict:
    """Проверка ответа части 1 (точное сравнение)."""
    correct_answer = str(key.get('answer', ''))
    max_score = get_max_score_for_task(task_num)

    # Нормализация ответов
    user_norm = answer.strip().lower().replace(' ', '').replace(',', '')
    correct_norm = correct_answer.strip().lower().replace(' ', '').replace(',', '')

    # Для множественного выбора: сортируем цифры
    question_type = key.get('question_type', '')
    if question_type == 'multiple_choice':
        user_norm = ''.join(sorted(set(user_norm)))
        correct_norm = ''.join(sorted(set(correct_norm)))

    is_correct = user_norm == correct_norm
    score = max_score if is_correct else 0

    return {
        'score': score,
        'max_score': max_score,
        'is_correct': is_correct,
        'feedback': (
            f"✅ Верно! Ответ: {correct_answer}" if is_correct
            else f"❌ Неверно. Ваш ответ: {answer}, правильный: {correct_answer}"
        ),
        'correct_answer': correct_answer,
    }


async def _check_part2_answer(
    task_num: int,
    answer: str,
    key: Dict,
    user_id: int
) -> Dict:
    """Проверка ответа части 2 через AI."""
    module = key.get('module', TASK_MODULES.get(task_num, f'task{task_num}'))
    task_data = dict(key.get('task_data', {}))  # копия, чтобы не мутировать оригинал
    max_score = PART2_MAX_SCORES.get(task_num, 0)

    # Для внешнего варианта: дополняем task_data данными из ключа
    # чтобы evaluator получил полный контекст
    criteria = task_data.get('correct_answer_criteria', '')
    if criteria and 'criteria' not in task_data:
        task_data['criteria'] = criteria

    # Для task17/task18: если condition_text и answer_key_text переданы из ключа,
    # убедимся что evaluator получит их в нужных полях
    condition_text = key.get('condition_text', '')
    answer_key_text = key.get('answer_key_text', '')

    if condition_text:
        if 'text' not in task_data or not task_data['text']:
            task_data['text'] = condition_text
        if 'question' not in task_data or not task_data['question']:
            task_data['question'] = condition_text
        if 'task_text' not in task_data or not task_data['task_text']:
            task_data['task_text'] = condition_text

    if answer_key_text:
        if 'correct_answer_criteria' not in task_data or not task_data['correct_answer_criteria']:
            task_data['correct_answer_criteria'] = answer_key_text
        if 'scoring_notes' not in task_data or not task_data['scoring_notes']:
            task_data['scoring_notes'] = answer_key_text

    is_correct, feedback = await evaluate_homework_answer(
        task_module=module,
        question_data=task_data,
        user_answer=answer,
        user_id=user_id
    )

    # Извлекаем баллы из feedback
    score = _extract_score_from_feedback(feedback, max_score)

    return {
        'score': score,
        'max_score': max_score,
        'is_correct': is_correct,
        'feedback': feedback,
    }


def _extract_score_from_feedback(feedback: str, max_score: int) -> int:
    """Извлекает баллы из текста обратной связи."""
    # Ищем паттерн "Баллы: X/Y"
    match = re.search(r'Баллы:\s*(\d+)\s*/\s*(\d+)', feedback)
    if match:
        return min(int(match.group(1)), max_score)

    # Ищем паттерн "X/Y" в начале
    match = re.search(r'(\d+)\s*/\s*(\d+)', feedback)
    if match:
        score = int(match.group(1))
        if score <= max_score:
            return score

    return 0


# ============================================
# Отображение результатов
# ============================================

async def _show_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    results: Dict[int, Dict]
) -> int:
    """Показывает результаты проверки варианта."""
    selected = context.user_data.get('vc_selected_tasks', [])
    mode = context.user_data.get('vc_mode', 'single')

    # Считаем баллы
    part1_scores = {}
    part2_scores = {}

    for task_num in sorted(results.keys()):
        r = results[task_num]
        if task_num <= 16:
            part1_scores[task_num] = r['is_correct']
        else:
            part2_scores[task_num] = r['score']

    # Формируем сводку
    lines = ["📊 <b>РЕЗУЛЬТАТЫ ПРОВЕРКИ ВАРИАНТА</b>\n"]

    # Часть 1
    part1_tasks_checked = [t for t in selected if t <= 16 and t in results]
    if part1_tasks_checked:
        p1_score = sum(
            get_max_score_for_task(t) for t in part1_tasks_checked
            if results[t]['is_correct']
        )
        p1_max = sum(get_max_score_for_task(t) for t in part1_tasks_checked)
        lines.append(f"<b>Часть 1:</b> {p1_score}/{p1_max}")

        for num in sorted(part1_tasks_checked):
            r = results[num]
            icon = "✅" if r['is_correct'] else "❌"
            max_s = get_max_score_for_task(num)
            score = max_s if r['is_correct'] else 0
            lines.append(f"  №{num}: {icon} {score}/{max_s}")

        lines.append("")

    # Часть 2
    part2_tasks_checked = [t for t in selected if t >= 17 and t in results]
    if part2_tasks_checked:
        p2_score = sum(results[t]['score'] for t in part2_tasks_checked)
        p2_max = sum(PART2_MAX_SCORES.get(t, 0) for t in part2_tasks_checked)
        lines.append(f"<b>Часть 2:</b> {p2_score}/{p2_max}")

        for num in sorted(part2_tasks_checked):
            r = results[num]
            max_s = PART2_MAX_SCORES.get(num, 0)
            name = TASK_NAMES.get(num, f"Задание {num}")
            bar = "█" * r['score'] + "░" * (max_s - r['score'])
            lines.append(f"  №{num} ({name}): {bar} {r['score']}/{max_s}")

        lines.append("")

    # Общий итог
    total_score = sum(r['score'] for r in results.values())
    total_max = sum(r['max_score'] for r in results.values())

    # Если проверяли все 25 заданий — считаем вторичный балл
    all_tasks_checked = set(results.keys()) == set(range(1, 26))
    if all_tasks_checked:
        p1_correct = {t: results[t]['is_correct'] for t in range(1, 17)}
        p2_earned = {t: results[t]['score'] for t in range(17, 26)}

        p1, _ = calculate_part1_score(p1_correct)
        p2, _ = calculate_part2_score(p2_earned)
        total_primary = p1 + p2
        secondary = primary_to_secondary(total_primary)
        emoji, description = get_grade_description(secondary)

        lines.append(
            f"<b>Первичный балл:</b> {total_primary}/{MAX_TOTAL_SCORE}\n"
            f"<b>Вторичный балл:</b> {secondary}/100\n"
        )
        lines.append(description)

        if secondary >= MIN_PASSING_SECONDARY:
            lines.append(f"\n✅ Порог сдачи ({MIN_PASSING_SECONDARY} б.) пройден")
        else:
            lines.append(
                f"\n⚠️ Порог сдачи ({MIN_PASSING_SECONDARY} б.) не пройден "
                f"(не хватает {MIN_PASSING_SECONDARY - secondary} б.)"
            )
    else:
        lines.append(f"<b>Итого:</b> {total_score}/{total_max}")
        if total_max > 0:
            pct = round(total_score / total_max * 100)
            lines.append(f"Процент: {pct}%")

    text = "\n".join(lines)

    # Кнопки
    keyboard = []

    # Подробные результаты по каждому заданию части 2
    if part2_tasks_checked:
        keyboard.append([InlineKeyboardButton(
            "📝 Подробные результаты", callback_data="vc_detailed_results"
        )])

    # Пакетный режим: следующий ученик
    if mode == 'batch':
        batch_results = context.user_data.get('vc_batch_results', [])
        if len(batch_results) < MAX_BATCH_STUDENTS:
            keyboard.append([InlineKeyboardButton(
                f"👤 Следующий ученик (#{len(batch_results) + 1})",
                callback_data="vc_next_student"
            )])

        if len(batch_results) >= 2:
            keyboard.append([InlineKeyboardButton(
                "📊 Сводка по классу", callback_data="vc_batch_summary"
            )])

    keyboard.append([InlineKeyboardButton("🔄 Новая проверка", callback_data="vc_menu")])
    keyboard.append([InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")])

    msg = update.callback_query.message if update.callback_query else update.message
    await msg.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )

    return TeacherStates.VARIANT_CHECK_RESULTS


async def show_detailed_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает подробные результаты по каждому заданию части 2."""
    query = update.callback_query
    await query.answer()

    results = context.user_data.get('vc_results', {})
    selected = context.user_data.get('vc_selected_tasks', [])

    part2_tasks = [t for t in selected if t >= 17 and t in results]

    for task_num in sorted(part2_tasks):
        r = results[task_num]
        name = TASK_NAMES.get(task_num, f"Задание {task_num}")

        text = (
            f"📝 <b>Задание {task_num} ({name})</b>\n"
            f"Баллы: {r['score']}/{r['max_score']}\n\n"
            f"{r.get('feedback', 'Нет обратной связи')}"
        )

        # Обрезаем длинные сообщения
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>... (сокращено)</i>"

        try:
            await query.message.reply_text(text, parse_mode='HTML')
        except Exception as e:
            # Если HTML невалидный — отправляем без форматирования
            await query.message.reply_text(
                f"📝 Задание {task_num} ({name})\n"
                f"Баллы: {r['score']}/{r['max_score']}\n\n"
                f"{r.get('feedback', 'Нет обратной связи')}"
            )

    keyboard = [
        [InlineKeyboardButton("◀️ К сводке", callback_data="vc_back_to_results")],
        [InlineKeyboardButton("🔄 Новая проверка", callback_data="vc_menu")],
    ]

    await query.message.reply_text(
        "☝️ Подробные результаты по каждому заданию отправлены выше.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return TeacherStates.VARIANT_CHECK_RESULTS


async def back_to_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат к сводке результатов."""
    results = context.user_data.get('vc_results', {})
    if results:
        return await _show_results(update, context, results)

    # Если результатов нет — в меню
    return await variant_check_menu(update, context)


# ============================================
# Пакетный режим
# ============================================

async def next_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переход к проверке следующего ученика."""
    query = update.callback_query
    await query.answer()

    # Сбрасываем ответы текущего ученика
    context.user_data['vc_student_answers'] = {}
    context.user_data['vc_current_task_idx'] = 0
    context.user_data['vc_results'] = {}

    return await _prompt_for_student_answers(update, context, is_query=True)


async def show_batch_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает сводку по всем проверенным ученикам."""
    query = update.callback_query
    await query.answer()

    batch_results = context.user_data.get('vc_batch_results', [])
    selected = context.user_data.get('vc_selected_tasks', [])

    if not batch_results:
        await query.message.edit_text(
            "❌ Нет результатов для сводки.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="vc_menu")
            ]])
        )
        return TeacherStates.VARIANT_CHECK_RESULTS

    lines = [f"📊 <b>СВОДКА ПО КЛАССУ</b>\n"]
    lines.append(f"Учеников: {len(batch_results)}")
    lines.append(f"Заданий: {len(selected)}\n")

    # Таблица результатов
    total_scores = []
    max_possible = 0

    for student in batch_results:
        results = student['results']
        total = sum(r['score'] for r in results.values())
        max_s = sum(r['max_score'] for r in results.values())
        max_possible = max_s
        total_scores.append(total)

        name = student.get('student_name', f"Ученик {student['student_num']}")
        pct = round(total / max_s * 100) if max_s > 0 else 0
        lines.append(f"  {name}: <b>{total}/{max_s}</b> ({pct}%)")

    lines.append("")

    # Статистика
    if total_scores:
        avg = sum(total_scores) / len(total_scores)
        lines.append(f"<b>Средний балл:</b> {avg:.1f}/{max_possible}")
        lines.append(f"<b>Максимум:</b> {max(total_scores)}/{max_possible}")
        lines.append(f"<b>Минимум:</b> {min(total_scores)}/{max_possible}")

        if max_possible > 0:
            avg_pct = round(avg / max_possible * 100)
            lines.append(f"<b>Средний %:</b> {avg_pct}%")

    # Статистика по заданиям
    lines.append("\n<b>Успеваемость по заданиям:</b>")
    for task_num in sorted(selected):
        task_scores = []
        for student in batch_results:
            r = student['results'].get(task_num)
            if r:
                task_scores.append(r['score'])

        if task_scores:
            task_avg = sum(task_scores) / len(task_scores)
            task_max = PART2_MAX_SCORES.get(task_num, get_max_score_for_task(task_num))
            name = TASK_NAMES.get(task_num, str(task_num))
            pct = round(task_avg / task_max * 100) if task_max > 0 else 0
            lines.append(f"  №{task_num} ({name}): {task_avg:.1f}/{task_max} ({pct}%)")

    text = "\n".join(lines)

    keyboard = [
        [InlineKeyboardButton("🔄 Новая проверка", callback_data="vc_menu")],
        [InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")]
    ]

    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )
    return TeacherStates.VARIANT_CHECK_RESULTS
