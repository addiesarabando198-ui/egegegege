"""
Обработчики для быстрой проверки работ (Quick Check).

Функционал для онлайн-школ: проверка работ, не назначенных через бота.
"""

import re
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..states import TeacherStates
from ..models import QuickCheckTaskType
from ..services import quick_check_service
from ..utils.rate_limiter import check_operation_limit

logger = logging.getLogger(__name__)


def _safe_html_truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, ensuring valid HTML for Telegram."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    # Remove any partially-cut tag at the end (e.g. "<b" or "</b")
    last_open = truncated.rfind('<')
    if last_open != -1 and '>' not in truncated[last_open:]:
        truncated = truncated[:last_open]
    truncated += "…"
    # Properly track open/close tags with a stack
    stack = []
    for m in re.finditer(r'<(/?)(\w+)[^>]*>', truncated):
        is_close = m.group(1) == '/'
        tag = m.group(2).lower()
        if is_close:
            # Remove the matching open tag from stack (search from end)
            for j in range(len(stack) - 1, -1, -1):
                if stack[j] == tag:
                    stack.pop(j)
                    break
        else:
            stack.append(tag)
    # Close remaining open tags in reverse order
    for tag in reversed(stack):
        truncated += f"</{tag}>"
    return truncated


def _strip_html(text: str) -> str:
    """Strip HTML tags from text."""
    return re.sub(r'<[^>]+>', '', text)


# ============================================
# Главное меню быстрой проверки
# ============================================

async def quick_check_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню быстрой проверки"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем квоту учителя
    quota = await quick_check_service.get_or_create_quota(user_id)

    if not quota:
        await query.message.edit_text(
            "❌ Ошибка получения квоты. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    # Получаем краткую статистику
    stats = await quick_check_service.get_quick_check_stats(user_id, days=30)

    text = (
        "🔍 <b>Быстрая проверка работ</b>\n\n"
        "Проверяйте работы учеников с помощью AI, даже если задание "
        "не было создано в боте.\n\n"
        f"📊 <b>Ваша квота:</b>\n"
        f"├ Доступно: <b>{quota.remaining_checks}</b> проверок\n"
        f"├ Использовано: {quota.used_this_month}/{quota.monthly_limit}\n"
    )

    if quota.bonus_checks > 0:
        text += f"└ Бонусных: {quota.bonus_checks}\n"
    else:
        text += "└ До конца периода: " + quota.current_period_end.strftime("%d.%m.%Y") + "\n"

    text += f"\n📈 <b>За последние 30 дней:</b>\n"
    text += f"└ Проверено: {stats['total_checks']} работ\n"

    keyboard = [
        [InlineKeyboardButton("✅ Проверить одну работу", callback_data="qc_check_single")],
        [InlineKeyboardButton("📚 Массовая проверка", callback_data="qc_check_bulk")],
        [InlineKeyboardButton("📋 Проверка варианта", callback_data="vc_menu")],
        [InlineKeyboardButton("📜 История проверок", callback_data="qc_history")],
        [InlineKeyboardButton("📊 Статистика", callback_data="qc_stats")],
        [InlineKeyboardButton("◀️ В меню учителя", callback_data="teacher_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_MENU


# ============================================
# Одиночная проверка
# ============================================

async def start_single_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало одиночной проверки - выбор типа задания"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем квоту
    quota = await quick_check_service.get_or_create_quota(user_id)
    if not quota or not quota.can_check:
        await query.message.edit_text(
            "❌ <b>Квота исчерпана</b>\n\n"
            f"Вы использовали все доступные проверки ({quota.monthly_limit if quota else 0}).\n\n"
            "💡 Обновите подписку или дождитесь начала нового периода.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    text = (
        "🔍 <b>Проверка одной работы</b>\n\n"
        "Выберите тип задания для проверки:"
    )

    keyboard = [
        [InlineKeyboardButton("📖 Задание 17", callback_data="qc_type_task17")],
        [InlineKeyboardButton("📝 Задание 18", callback_data="qc_type_task18")],
        [InlineKeyboardButton("💡 Задание 19", callback_data="qc_type_task19")],
        [InlineKeyboardButton("⚙️ Задание 20", callback_data="qc_type_task20")],
        [InlineKeyboardButton("📊 Задание 21", callback_data="qc_type_task21")],
        [InlineKeyboardButton("📝 Задание 22", callback_data="qc_type_task22")],
        [InlineKeyboardButton("📜 Задание 23", callback_data="qc_type_task23")],
        [InlineKeyboardButton("📄 Задание 24", callback_data="qc_type_task24")],
        [InlineKeyboardButton("💻 Задание 25", callback_data="qc_type_task25")],
        [InlineKeyboardButton("📝 Произвольное задание", callback_data="qc_type_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_SELECT_TYPE


async def select_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора типа задания"""
    query = update.callback_query
    await query.answer()

    # Извлекаем тип из callback_data
    task_type_str = query.data.replace("qc_type_", "")
    task_type = QuickCheckTaskType(task_type_str)

    # Сохраняем в контекст
    context.user_data['qc_task_type'] = task_type
    context.user_data['qc_mode'] = 'single'  # одиночная проверка

    task_names = {
        QuickCheckTaskType.TASK17: "📖 Задание 17 (Анализ текста)",
        QuickCheckTaskType.TASK18: "📝 Задание 18 (Понятие из текста)",
        QuickCheckTaskType.TASK19: "💡 Задание 19 (Примеры)",
        QuickCheckTaskType.TASK20: "⚙️ Задание 20 (Слова)",
        QuickCheckTaskType.TASK21: "📊 Задание 21 (Графики)",
        QuickCheckTaskType.TASK22: "📝 Задание 22 (Анализ ситуаций)",
        QuickCheckTaskType.TASK23: "📜 Задание 23 (Конституция РФ)",
        QuickCheckTaskType.TASK24: "📄 Задание 24 (Планы)",
        QuickCheckTaskType.TASK25: "💻 Задание 25 (Сочинение)",
        QuickCheckTaskType.CUSTOM: "📝 Произвольное задание"
    }

    # Для задания 21 подсказываем про фото графика
    if task_type == QuickCheckTaskType.TASK21:
        text = (
            f"✏️ <b>{task_names[task_type]}</b>\n\n"
            "Отправьте условие задания:\n\n"
            "📷 <b>Фото графика</b> — отправьте изображение графика "
            "спроса/предложения (можно с подписью-условием)\n"
            "📝 <b>Текст</b> — введите условие текстом\n\n"
            "💡 Для объективной оценки рекомендуется прикрепить "
            "фото графика из условия задания."
        )
    else:
        text = (
            f"✏️ <b>{task_names[task_type]}</b>\n\n"
            "Введите условие задания текстом.\n\n"
            "Например:\n"
            "<i>«Дан файл с числами. Найдите количество пар чисел, "
            "сумма которых делится на 7»</i>\n\n"
            "💡 Можно скопировать текст задания откуда угодно."
        )

    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_ENTER_CONDITION


async def process_task_condition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введенного условия задания (текст)"""
    user_id = update.effective_user.id
    condition = update.message.text.strip()

    # Валидация
    if len(condition) < 10:
        await update.message.reply_text(
            "❌ Условие задания слишком короткое. Минимум 10 символов.\n\n"
            "Попробуйте еще раз или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_CONDITION

    if len(condition) > 5000:
        await update.message.reply_text(
            "❌ Условие задания слишком длинное. Максимум 5000 символов.\n\n"
            "Попробуйте сократить или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_CONDITION

    # Сохраняем условие
    context.user_data['qc_condition'] = condition

    task_type = context.user_data.get('qc_task_type')

    # Для задания 18: предлагаем загрузить текст-источник
    if task_type == QuickCheckTaskType.TASK18:
        return await _ask_qc_source_text(update, context)

    return await _proceed_to_answer_input(update, context)


async def _ask_qc_source_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Предлагает загрузить текст-источник для задания 18 (быстрая проверка)."""
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить", callback_data="qc_skip_source_text")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")],
    ]

    text = (
        "✅ Условие сохранено!\n\n"
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
    return TeacherStates.QUICK_CHECK_ENTER_SOURCE_TEXT


async def process_qc_source_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обработка текста-источника для задания 18 (быстрая проверка)."""
    source_text = update.message.text.strip()

    if len(source_text) < 20:
        await update.message.reply_text(
            "❌ Текст слишком короткий. Минимум 20 символов.\n\n"
            "Отправьте текст-источник или нажмите «Пропустить».",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Пропустить", callback_data="qc_skip_source_text"),
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_ENTER_SOURCE_TEXT

    context.user_data['qc_source_text'] = source_text
    return await _proceed_to_answer_input(update, context)


async def skip_qc_source_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Пропуск загрузки текста-источника для задания 18 (быстрая проверка)."""
    query = update.callback_query
    await query.answer()

    # Переходим к вводу ответа
    return await _proceed_to_answer_input_from_callback(update, context)


async def _proceed_to_answer_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Переход к вводу ответа ученика (из текстового сообщения)."""
    mode = context.user_data.get('qc_mode', 'single')

    if mode == 'single':
        text = (
            "✅ Условие сохранено!\n\n"
            "Теперь введите <b>ответ ученика</b> на это задание.\n\n"
            "💡 Можно вставить ответ текстом или отправить <b>фото рукописного ответа</b>."
        )

        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    else:
        context.user_data['qc_bulk_answers'] = []

        text = (
            "✅ Условие сохранено!\n\n"
            "Теперь отправляйте <b>ответы учеников</b>. Доступные способы:\n\n"
            "📝 <b>Текст</b> — каждая строка = ответ одного ученика\n"
            "📷 <b>Фото</b> — фото рукописного ответа (одно фото = один ответ)\n"
            "📄 <b>Файл</b> — TXT/PDF/DOCX с ответами (каждый абзац = ответ)\n\n"
            "Можно отправлять несколько сообщений подряд.\n"
            "Когда все ответы добавлены, нажмите <b>«Начать проверку»</b>.\n\n"
            "Максимум 50 ответов."
        )

        keyboard = [
            [InlineKeyboardButton("🚀 Начать проверку", callback_data="qc_run_bulk_check")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK


async def _proceed_to_answer_input_from_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Переход к вводу ответа ученика (из callback query)."""
    mode = context.user_data.get('qc_mode', 'single')
    query = update.callback_query

    if mode == 'single':
        text = (
            "Теперь введите <b>ответ ученика</b> на это задание.\n\n"
            "💡 Можно вставить ответ текстом или отправить <b>фото рукописного ответа</b>."
        )

        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    else:
        context.user_data['qc_bulk_answers'] = []

        text = (
            "Теперь отправляйте <b>ответы учеников</b>. Доступные способы:\n\n"
            "📝 <b>Текст</b> — каждая строка = ответ одного ученика\n"
            "📷 <b>Фото</b> — фото рукописного ответа (одно фото = один ответ)\n"
            "📄 <b>Файл</b> — TXT/PDF/DOCX с ответами (каждый абзац = ответ)\n\n"
            "Можно отправлять несколько сообщений подряд.\n"
            "Когда все ответы добавлены, нажмите <b>«Начать проверку»</b>.\n\n"
            "Максимум 50 ответов."
        )

        keyboard = [
            [InlineKeyboardButton("🚀 Начать проверку", callback_data="qc_run_bulk_check")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK


async def process_task_condition_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка фото условия задания (например, график для задания 21).

    Сохраняет изображение в base64 для передачи в AI evaluator вместе с текстом условия.
    Подпись к фото (caption) используется как текстовое условие.
    """
    import base64
    from core.image_preprocessor import compress_for_claude

    if not update.message.photo:
        await update.message.reply_text(
            "❌ Фото не найдено. Отправьте изображение или введите условие текстом."
        )
        return TeacherStates.QUICK_CHECK_ENTER_CONDITION

    # Скачиваем фото (самый большой вариант)
    photo = update.message.photo[-1]
    try:
        file = await photo.get_file()
        file_bytes = await file.download_as_bytearray()
    except Exception as e:
        logger.error(f"Failed to download condition photo: {e}")
        await update.message.reply_text(
            "❌ Не удалось загрузить фото. Попробуйте ещё раз."
        )
        return TeacherStates.QUICK_CHECK_ENTER_CONDITION

    # Сжимаем и кодируем в base64
    try:
        compressed = compress_for_claude(bytes(file_bytes))
    except Exception:
        compressed = bytes(file_bytes)

    image_base64 = base64.b64encode(compressed).decode('utf-8')

    # Определяем media_type
    media_type = "image/jpeg"
    if compressed[:8] == b'\x89PNG\r\n\x1a\n':
        media_type = "image/png"
    elif compressed[:4] == b'RIFF' and compressed[8:12] == b'WEBP':
        media_type = "image/webp"

    # Сохраняем изображение условия в контексте
    context.user_data['qc_condition_image'] = {
        'base64': image_base64,
        'media_type': media_type,
    }

    # Текст условия из подписи к фото (caption), если есть
    caption = (update.message.caption or '').strip()
    if caption:
        context.user_data['qc_condition'] = caption
    else:
        context.user_data['qc_condition'] = '(условие задания на изображении)'

    task_type = context.user_data.get('qc_task_type')
    mode = context.user_data.get('qc_mode', 'single')

    await update.message.reply_text(
        "✅ Изображение условия сохранено!\n"
        + (f"📝 Подпись: <i>{caption[:100]}</i>\n\n" if caption else "\n")
        + "AI будет анализировать график при проверке ответов.",
        parse_mode='HTML'
    )

    if mode == 'single':
        text = (
            "Теперь введите <b>ответ ученика</b> на это задание.\n\n"
            "💡 Можно вставить ответ текстом или отправить <b>фото рукописного ответа</b>."
        )
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return TeacherStates.QUICK_CHECK_ENTER_ANSWER
    else:
        context.user_data['qc_bulk_answers'] = []
        text = (
            "Теперь отправляйте <b>ответы учеников</b>:\n\n"
            "📝 <b>Текст</b> — каждая строка = ответ одного ученика\n"
            "📷 <b>Фото</b> — фото рукописного ответа\n"
            "📄 <b>Файл</b> — TXT/PDF/DOCX с ответами\n\n"
            "Когда все ответы добавлены, нажмите <b>«Начать проверку»</b>."
        )
        keyboard = [
            [InlineKeyboardButton("🚀 Начать проверку", callback_data="qc_run_bulk_check")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK


async def process_single_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка текстового ответа ученика и запуск проверки"""
    answer = update.message.text.strip()

    # Валидация
    if len(answer) < 1:
        await update.message.reply_text(
            "❌ Ответ не может быть пустым.\n\n"
            "Попробуйте еще раз или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    if len(answer) > 5000:
        await update.message.reply_text(
            "❌ Ответ слишком длинный. Максимум 5000 символов.\n\n"
            "Попробуйте сократить или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    return await _run_single_check(update, context, answer)


async def process_single_answer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка фото с рукописным ответом ученика для быстрой проверки"""
    from core.vision_service import process_photo_message

    user_id = update.effective_user.id

    # Формируем контекст для улучшения OCR-коррекции
    task_type = context.user_data.get('qc_task_type', '')
    condition = context.user_data.get('qc_condition', '')
    ocr_context = f"ЕГЭ обществознание, {task_type}, условие задания: {condition}" if condition else None

    # Распознаём текст с фотографии
    extracted_text = await process_photo_message(
        update,
        context.application.bot,
        task_name="ответ ученика",
        task_context=ocr_context
    )

    if not extracted_text:
        await update.message.reply_text(
            "Попробуйте отправить фото ещё раз или введите ответ текстом."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    # Сохраняем распознанный текст как ответ и запускаем проверку
    # Имитируем текстовый ввод — переиспользуем логику process_single_answer
    context.user_data['_ocr_answer'] = extracted_text
    return await _run_single_check(update, context, extracted_text)


async def _run_single_check(update: Update, context: ContextTypes.DEFAULT_TYPE, answer: str) -> int:
    """Общая логика проверки одиночного ответа (текст или OCR)"""
    user_id = update.effective_user.id

    # Извлекаем данные из контекста
    task_type = context.user_data.get('qc_task_type')
    condition = context.user_data.get('qc_condition')

    # Отправляем сообщение о начале проверки
    checking_msg = await update.message.reply_text(
        "⏳ Проверяю ответ с помощью AI...\n\n"
        "Это может занять несколько секунд."
    )

    # Проверяем и списываем квоту
    success, quota = await quick_check_service.check_and_use_quota(user_id, count=1)
    if not success:
        await checking_msg.edit_text(
            "❌ <b>Квота исчерпана</b>\n\n"
            "Не удалось выполнить проверку.",
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    try:
        # Вызываем AI для проверки
        from teacher_mode.services.ai_homework_evaluator import evaluate_homework_answer

        # Создаем минимальный question_data для evaluator
        question_data = {
            'title': f'{task_type.value} - быстрая проверка',
            'task_text': condition
        }

        # Прикрепляем изображение условия (например, график для task21)
        condition_image = context.user_data.get('qc_condition_image')
        if condition_image:
            question_data['condition_image'] = condition_image

        # Для задания 18: добавляем текст-источник, если он был загружен
        qc_source_text = context.user_data.get('qc_source_text')
        if qc_source_text:
            question_data['source_text'] = qc_source_text
            question_data['text'] = qc_source_text

        is_correct, ai_feedback = await evaluate_homework_answer(
            task_module=task_type.value,
            question_data=question_data,
            user_answer=answer,
            user_id=user_id
        )

        # Сохраняем проверку в БД
        quick_check = await quick_check_service.create_quick_check(
            teacher_id=user_id,
            task_type=task_type,
            task_condition=condition,
            student_answer=answer,
            ai_feedback=ai_feedback,
            is_correct=is_correct
        )

        # Формируем результат
        import html as html_module
        answer_escaped = html_module.escape(answer[:200])
        condition_escaped = html_module.escape(condition[:200])

        header = (
            f"<b>🔍 Быстрая проверка</b>\n\n"
            f"<b>Тип задания:</b> {task_type.value}\n\n"
            f"<b>Условие:</b>\n{condition_escaped}{'...' if len(condition) > 200 else ''}\n\n"
            f"<b>Ответ ученика:</b>\n<code>{answer_escaped}</code>\n\n"
        )
        footer = f"\n\n💡 Осталось проверок: {quota.remaining_checks}"

        # Telegram limit is 4096 chars; trim ai_feedback if needed
        max_feedback_len = 4096 - len(header) - len(footer) - 100
        if len(ai_feedback) > max_feedback_len:
            ai_feedback = _safe_html_truncate(ai_feedback, max_feedback_len)

        text = header + ai_feedback + footer

        keyboard = [
            [InlineKeyboardButton("✅ Проверить еще", callback_data="qc_check_single")],
            [InlineKeyboardButton("📊 Статистика", callback_data="qc_stats")],
            [InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await checking_msg.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        except Exception as html_err:
            # Fallback: strip HTML if Telegram can't parse it
            logger.warning(f"HTML parse failed, falling back to plain text: {html_err}")
            plain = _strip_html(text)[:4096]
            await checking_msg.edit_text(plain, reply_markup=reply_markup)

        # Очищаем контекст
        context.user_data.pop('qc_task_type', None)
        context.user_data.pop('qc_condition', None)
        context.user_data.pop('qc_mode', None)
        context.user_data.pop('_ocr_answer', None)
        context.user_data.pop('qc_condition_image', None)
        context.user_data.pop('qc_source_text', None)

        return TeacherStates.QUICK_CHECK_MENU

    except Exception as e:
        logger.error(f"Error checking answer: {e}")

        await checking_msg.edit_text(
            "❌ <b>Ошибка при проверке</b>\n\n"
            "Произошла ошибка при обработке ответа. Попробуйте позже.\n\n"
            "Квота не была списана.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )

        # Возвращаем квоту (уменьшаем used_this_month, а не добавляем бонус)
        await quick_check_service.refund_quota(user_id, 1)

        return TeacherStates.QUICK_CHECK_MENU


# ============================================
# Массовая проверка
# ============================================

async def start_bulk_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало массовой проверки"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем квоту (минимум 2 проверки для массовой)
    quota = await quick_check_service.get_or_create_quota(user_id)
    if not quota or quota.remaining_checks < 2:
        await query.message.edit_text(
            "❌ <b>Недостаточно квоты</b>\n\n"
            f"Для массовой проверки нужно минимум 2 проверки.\n"
            f"Доступно: {quota.remaining_checks if quota else 0}\n\n"
            "💡 Используйте одиночную проверку или обновите подписку.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    text = (
        "📚 <b>Массовая проверка</b>\n\n"
        "Проверка нескольких ответов на одно задание.\n\n"
        "Выберите тип задания:"
    )

    keyboard = [
        [InlineKeyboardButton("📖 Задание 17", callback_data="qc_bulk_task17")],
        [InlineKeyboardButton("📝 Задание 18", callback_data="qc_bulk_task18")],
        [InlineKeyboardButton("💡 Задание 19", callback_data="qc_bulk_task19")],
        [InlineKeyboardButton("⚙️ Задание 20", callback_data="qc_bulk_task20")],
        [InlineKeyboardButton("📊 Задание 21", callback_data="qc_bulk_task21")],
        [InlineKeyboardButton("📝 Задание 22", callback_data="qc_bulk_task22")],
        [InlineKeyboardButton("📜 Задание 23", callback_data="qc_bulk_task23")],
        [InlineKeyboardButton("📄 Задание 24", callback_data="qc_bulk_task24")],
        [InlineKeyboardButton("💻 Задание 25", callback_data="qc_bulk_task25")],
        [InlineKeyboardButton("📝 Произвольное", callback_data="qc_bulk_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_SELECT_TYPE


async def select_bulk_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора типа для массовой проверки"""
    query = update.callback_query
    await query.answer()

    task_type_str = query.data.replace("qc_bulk_", "")
    task_type = QuickCheckTaskType(task_type_str)

    context.user_data['qc_task_type'] = task_type
    context.user_data['qc_mode'] = 'bulk'

    task_names = {
        QuickCheckTaskType.TASK17: "📖 Задание 17",
        QuickCheckTaskType.TASK18: "📝 Задание 18",
        QuickCheckTaskType.TASK19: "💡 Задание 19",
        QuickCheckTaskType.TASK20: "⚙️ Задание 20",
        QuickCheckTaskType.TASK21: "📊 Задание 21",
        QuickCheckTaskType.TASK22: "📝 Задание 22",
        QuickCheckTaskType.TASK23: "📜 Задание 23",
        QuickCheckTaskType.TASK24: "📄 Задание 24",
        QuickCheckTaskType.TASK25: "💻 Задание 25",
        QuickCheckTaskType.CUSTOM: "📝 Произвольное"
    }

    if task_type == QuickCheckTaskType.TASK21:
        text = (
            f"✏️ <b>{task_names[task_type]}</b>\n\n"
            "Отправьте условие задания (общее для всех ответов):\n\n"
            "📷 <b>Фото графика</b> — изображение графика спроса/предложения "
            "(можно с подписью-условием)\n"
            "📝 <b>Текст</b> — условие текстом\n\n"
            "💡 Для объективной оценки рекомендуется прикрепить фото графика."
        )
    else:
        text = (
            f"✏️ <b>{task_names[task_type]}</b>\n\n"
            "Введите условие задания текстом.\n\n"
            "Это условие будет общим для всех ответов."
        )

    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_ENTER_CONDITION


async def process_bulk_answers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка текстового ввода ответов в массовой проверке (добавление в коллекцию)"""
    answers_text = update.message.text.strip()

    # Разбиваем на строки
    new_lines = [line.strip() for line in answers_text.split('\n') if line.strip()]

    if len(new_lines) == 0:
        await update.message.reply_text(
            "❌ Не найдено ни одного ответа.\n\n"
            "Введите ответы построчно, отправьте фото или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    # Получаем текущий список ответов
    collected = context.user_data.get('qc_bulk_answers', [])

    if len(collected) + len(new_lines) > 50:
        await update.message.reply_text(
            f"❌ Слишком много ответов (уже {len(collected)} + {len(new_lines)} новых = {len(collected) + len(new_lines)}).\n\n"
            "Максимум 50 ответов за раз. Нажмите «Начать проверку» или сократите список."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    # Добавляем новые ответы как dict-записи
    for line in new_lines:
        collected.append({'text': line, 'photo_file_id': None, 'source': 'text'})
    context.user_data['qc_bulk_answers'] = collected

    return await _show_bulk_collection_status(update, context, collected)


async def process_bulk_answer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка фото рукописного ответа в массовой проверке"""
    from core.vision_service import process_photo_message

    # Сохраняем file_id самого крупного варианта фото
    photo_file_id = update.message.photo[-1].file_id if update.message.photo else None

    # Формируем контекст для улучшения OCR
    task_type = context.user_data.get('qc_task_type', '')
    condition = context.user_data.get('qc_condition', '')
    ocr_context = f"ЕГЭ обществознание, {task_type}, условие задания: {condition}" if condition else None

    # Распознаём текст с фотографии
    extracted_text = await process_photo_message(
        update,
        context.application.bot,
        task_name="ответ ученика",
        task_context=ocr_context
    )

    if not extracted_text:
        await update.message.reply_text(
            "❌ Не удалось распознать текст с фото.\n\n"
            "Попробуйте отправить фото ещё раз или введите ответ текстом."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    # Добавляем распознанный ответ в коллекцию вместе с file_id фото
    collected = context.user_data.get('qc_bulk_answers', [])

    if len(collected) >= 50:
        await update.message.reply_text(
            "❌ Достигнут лимит (50 ответов). Нажмите «Начать проверку»."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    collected.append({
        'text': extracted_text,
        'photo_file_id': photo_file_id,
        'source': 'photo'
    })
    context.user_data['qc_bulk_answers'] = collected

    return await _show_bulk_collection_status(update, context, collected, last_ocr=extracted_text)


async def process_bulk_answer_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка документа (TXT/PDF/DOCX) с ответами в массовой проверке"""
    from core.document_processor import DocumentProcessor

    if not update.message or not update.message.document:
        await update.message.reply_text("❌ Документ не найден.")
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    document = update.message.document

    processing_msg = await update.message.reply_text("📄 Обрабатываю документ...")

    success, text, error = await DocumentProcessor.process_document(document, context)

    try:
        await processing_msg.delete()
    except Exception:
        pass

    if not success:
        await update.message.reply_text(
            f"❌ Ошибка обработки документа:\n{error}\n\n"
            "Поддерживаемые форматы: TXT, PDF, DOCX.\n"
            "Попробуйте другой файл или отправьте ответы текстом."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    # Разбиваем текст документа на отдельные ответы (по абзацам / строкам)
    new_answers = [line.strip() for line in text.split('\n') if line.strip()]

    if not new_answers:
        await update.message.reply_text(
            "❌ Не удалось извлечь ответы из документа.\n"
            "Убедитесь, что каждый ответ на отдельной строке."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    collected = context.user_data.get('qc_bulk_answers', [])

    if len(collected) + len(new_answers) > 50:
        # Берём столько, сколько помещается
        available = 50 - len(collected)
        new_answers = new_answers[:available]
        await update.message.reply_text(
            f"⚠️ Из документа добавлено только {available} ответов (достигнут лимит 50)."
        )

    for ans in new_answers:
        collected.append({'text': ans, 'photo_file_id': None, 'source': 'document'})
    context.user_data['qc_bulk_answers'] = collected

    return await _show_bulk_collection_status(
        update, context, collected,
        extra_info=f"📄 Из документа добавлено: {len(new_answers)} ответов"
    )


async def _show_bulk_collection_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    collected: list,
    last_ocr: str = None,
    extra_info: str = None
) -> int:
    """Показывает текущий статус сбора ответов в массовой проверке"""
    text = f"✅ <b>Ответов собрано: {len(collected)}</b>\n\n"

    if extra_info:
        text += f"{extra_info}\n\n"

    if last_ocr:
        preview = last_ocr[:100] + ("..." if len(last_ocr) > 100 else "")
        text += f"📷 Распознано с фото:\n<code>{preview}</code>\n\n"

    # Показываем последние 5 собранных ответов
    if collected:
        source_icons = {'text': '📝', 'photo': '📷', 'document': '📄'}
        text += "<b>Последние ответы:</b>\n"
        start = max(0, len(collected) - 5)
        for i, entry in enumerate(collected[start:], start + 1):
            answer_text = entry['text'] if isinstance(entry, dict) else entry
            source = entry.get('source', 'text') if isinstance(entry, dict) else 'text'
            icon = source_icons.get(source, '📝')
            preview = answer_text[:40] + ("..." if len(answer_text) > 40 else "")
            text += f"  {i}. {icon} <code>{preview}</code>\n"

    text += (
        "\n📝 Отправьте ещё ответы (текст / фото / файл)\n"
        "или нажмите <b>«Начать проверку»</b>."
    )

    keyboard = [
        [InlineKeyboardButton(f"🚀 Начать проверку ({len(collected)})", callback_data="qc_run_bulk_check")],
        [InlineKeyboardButton("🗑 Очистить список", callback_data="qc_clear_bulk_answers")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK


async def clear_bulk_answers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Очистка собранных ответов массовой проверки"""
    query = update.callback_query
    await query.answer()

    context.user_data['qc_bulk_answers'] = []

    text = (
        "🗑 <b>Список ответов очищен.</b>\n\n"
        "Отправьте ответы учеников:\n"
        "📝 Текст (каждая строка = один ответ)\n"
        "📷 Фото рукописного ответа\n"
        "📄 Файл (TXT/PDF/DOCX)\n\n"
        "Когда все ответы добавлены, нажмите <b>«Начать проверку»</b>."
    )

    keyboard = [
        [InlineKeyboardButton("🚀 Начать проверку", callback_data="qc_run_bulk_check")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK


async def run_bulk_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запуск массовой проверки собранных ответов.

    Для каждой работы отправляет отдельное сообщение с полным AI-фидбэком.
    Если ответ был загружен с фото — прикрепляет фото к сообщению с обратной связью.
    В конце отправляет итоговую сводку.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    bot = context.application.bot

    # Получаем собранные ответы (список dict: {text, photo_file_id, source})
    entries = context.user_data.get('qc_bulk_answers', [])

    if not entries:
        await query.message.edit_text(
            "❌ Нет собранных ответов для проверки.\n\n"
            "Сначала отправьте ответы учеников (текст, фото или файл).",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    # Проверяем квоту
    quota = await quick_check_service.get_or_create_quota(user_id)
    if not quota or quota.remaining_checks < len(entries):
        await query.message.edit_text(
            f"❌ <b>Недостаточно квоты</b>\n\n"
            f"Нужно: {len(entries)} проверок\n"
            f"Доступно: {quota.remaining_checks if quota else 0}\n\n"
            "Сократите количество ответов или обновите подписку.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    # Извлекаем данные
    task_type = context.user_data.get('qc_task_type')
    condition = context.user_data.get('qc_condition')

    await query.message.edit_text(
        f"⏳ Проверяю {len(entries)} ответов...\n\n"
        "Результаты будут отправлены отдельным сообщением по каждой работе."
    )
    checking_msg = query.message

    try:
        import html as html_module
        from teacher_mode.services.ai_homework_evaluator import evaluate_homework_answer

        correct_count = 0
        checked_count = 0

        for i, entry in enumerate(entries):
            answer_text = entry['text'] if isinstance(entry, dict) else entry
            photo_file_id = entry.get('photo_file_id') if isinstance(entry, dict) else None
            source = entry.get('source', 'text') if isinstance(entry, dict) else 'text'

            # Списываем квоту
            success, _ = await quick_check_service.check_and_use_quota(user_id, count=1)
            if not success:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Квота исчерпана, оставшиеся работы не проверены.",
                    parse_mode='HTML'
                )
                break

            # Проверяем ответ через AI
            question_data = {
                'title': f'{task_type.value} - массовая проверка',
                'task_text': condition
            }

            # Прикрепляем изображение условия (например, график для task21)
            condition_image = context.user_data.get('qc_condition_image')
            if condition_image:
                question_data['condition_image'] = condition_image

            # Для задания 18: добавляем текст-источник
            qc_source_text = context.user_data.get('qc_source_text')
            if qc_source_text:
                question_data['source_text'] = qc_source_text
                question_data['text'] = qc_source_text

            is_correct, ai_feedback = await evaluate_homework_answer(
                task_module=task_type.value,
                question_data=question_data,
                user_answer=answer_text,
                user_id=user_id
            )

            # Сохраняем в БД
            await quick_check_service.create_quick_check(
                teacher_id=user_id,
                task_type=task_type,
                task_condition=condition,
                student_answer=answer_text,
                ai_feedback=ai_feedback,
                is_correct=is_correct
            )

            checked_count += 1
            if is_correct:
                correct_count += 1

            # Формируем полный фидбэк для этой работы (как в одиночной проверке)
            answer_escaped = html_module.escape(answer_text[:300])
            feedback_header = (
                f"<b>🔍 Работа {i + 1}/{len(entries)}</b>\n\n"
                f"<b>Тип задания:</b> {task_type.value}\n\n"
                f"<b>Ответ ученика:</b>\n<code>{answer_escaped}</code>"
                f"{'...' if len(answer_text) > 300 else ''}\n\n"
            )
            # Telegram limit is 4096 chars; trim ai_feedback if needed
            max_fb_len = 4096 - len(feedback_header) - 50
            trimmed_feedback = _safe_html_truncate(ai_feedback, max_fb_len) if len(ai_feedback) > max_fb_len else ai_feedback
            feedback_text = feedback_header + trimmed_feedback

            # Отправляем фидбэк: с фото если есть, иначе текстом
            try:
                if photo_file_id:
                    # Если фидбэк помещается в caption (лимит 1024 символа) — шлём как caption
                    if len(feedback_text) <= 1024:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=photo_file_id,
                            caption=feedback_text,
                            parse_mode='HTML'
                        )
                    else:
                        # Фото со коротким caption + полный фидбэк reply-сообщением
                        photo_msg = await bot.send_photo(
                            chat_id=chat_id,
                            photo=photo_file_id,
                            caption=f"<b>🔍 Работа {i + 1}/{len(entries)}</b> — ответ ученика",
                            parse_mode='HTML'
                        )
                        await bot.send_message(
                            chat_id=chat_id,
                            text=feedback_text,
                            reply_to_message_id=photo_msg.message_id,
                            parse_mode='HTML'
                        )
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=feedback_text,
                        parse_mode='HTML'
                    )
            except Exception as e:
                logger.warning(f"HTML send failed for work {i + 1}, falling back to plain text: {e}")
                # Фолбэк: отправляем без форматирования, strip HTML
                try:
                    fallback_text = f"Работа {i + 1}/{len(entries)}\n\n{_strip_html(trimmed_feedback)}"
                    await bot.send_message(
                        chat_id=chat_id,
                        text=fallback_text[:4096]
                    )
                except Exception:
                    pass

            # Обновляем прогресс в исходном сообщении
            if (i + 1) % 3 == 0 and (i + 1) < len(entries):
                try:
                    await checking_msg.edit_text(
                        f"⏳ Проверено {i + 1}/{len(entries)}..."
                    )
                except Exception:
                    pass

        # Итоговая сводка
        accuracy = (correct_count / checked_count * 100) if checked_count else 0

        summary = (
            f"📊 <b>Массовая проверка завершена!</b>\n\n"
            f"Проверено: {checked_count} из {len(entries)} работ\n"
            f"✅ Правильных: {correct_count}\n"
            f"❌ Неправильных: {checked_count - correct_count}\n"
            f"📈 Точность: {accuracy:.1f}%\n\n"
            f"Подробный фидбэк по каждой работе отправлен выше ⬆️"
        )

        keyboard = [
            [InlineKeyboardButton("📜 Посмотреть историю", callback_data="qc_history")],
            [InlineKeyboardButton("📚 Ещё массовая", callback_data="qc_check_bulk")],
            [InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await bot.send_message(
            chat_id=chat_id,
            text=summary,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        # Очищаем контекст
        context.user_data.pop('qc_task_type', None)
        context.user_data.pop('qc_condition', None)
        context.user_data.pop('qc_mode', None)
        context.user_data.pop('qc_bulk_answers', None)
        context.user_data.pop('qc_condition_image', None)
        context.user_data.pop('qc_source_text', None)

        return TeacherStates.QUICK_CHECK_MENU

    except Exception as e:
        logger.error(f"Error in bulk check: {e}")

        await bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ Ошибка при массовой проверке.\n\n"
                "Частично проверенные ответы сохранены."
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )

        return TeacherStates.QUICK_CHECK_MENU


# ============================================
# История и статистика
# ============================================

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показ истории проверок"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем последние 10 проверок
    checks = await quick_check_service.get_teacher_quick_checks(
        teacher_id=user_id,
        limit=10,
        offset=0
    )

    if not checks:
        text = (
            "📜 <b>История проверок</b>\n\n"
            "У вас пока нет проверенных работ.\n\n"
            "Начните с кнопки «Проверить работу» в главном меню."
        )
    else:
        text = "📜 <b>История проверок (последние 10)</b>\n\n"

        for i, check in enumerate(checks):
            emoji = "✅" if check.is_correct is True else ("❌" if check.is_correct is False else "⚠️")
            condition_preview = check.task_condition[:40]
            answer_preview = check.student_answer[:30]
            date = check.created_at.strftime("%d.%m %H:%M")

            text += (
                f"{i+1}. {emoji} {check.task_type.value}\n"
                f"   ├ {condition_preview}...\n"
                f"   ├ Ответ: <code>{answer_preview}</code>\n"
                f"   └ {date}\n\n"
            )

    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_MENU


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показ статистики проверок"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем статистику
    stats = await quick_check_service.get_quick_check_stats(user_id, days=30)
    quota = stats.get('quota')

    text = (
        "📊 <b>Статистика проверок</b>\n\n"
        f"<b>За последние 30 дней:</b>\n"
        f"├ Всего проверок: {stats['total_checks']}\n"
        f"├ Правильных: {stats['correct_count']}\n"
        f"└ Точность: {stats['accuracy_rate']:.1f}%\n\n"
    )

    if quota:
        text += (
            f"<b>Квота:</b>\n"
            f"├ Месячный лимит: {quota['monthly_limit']}\n"
            f"├ Использовано: {quota['used_this_month']}\n"
            f"├ Осталось: {quota['remaining']}\n"
        )

        if quota['bonus_checks'] > 0:
            text += f"└ Бонусных: {quota['bonus_checks']}\n"

    if stats['task_distribution']:
        text += "\n<b>Распределение по типам:</b>\n"
        for task_type, count in stats['task_distribution'].items():
            text += f"├ {task_type}: {count}\n"

    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_MENU

