"""
Админ-панель для управления системой жалоб и подсказок AI.

Этот модуль предоставляет администраторам инструменты для:
- Просмотра и обработки жалоб учеников
- Одобрения/отклонения жалоб
- Создания подсказок для AI на основе одобренных жалоб
- Управления существующими подсказками
- Просмотра аналитики по жалобам и подсказкам
"""

import logging
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode
from core.config import DATABASE_FILE
from core.hint_manager import HintManager
from core.admin_tools import admin_only

logger = logging.getLogger(__name__)

# Состояния conversation handler для создания подсказок
HINT_AWAITING_TEXT = "hint_awaiting_text"
HINT_AWAITING_CATEGORY = "hint_awaiting_category"
HINT_AWAITING_PRIORITY = "hint_awaiting_priority"


@admin_only
async def cmd_review_complaint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда для просмотра жалобы: /review_complaint <id>

    Отображает полную информацию о жалобе и кнопки для действий.
    """
    # Проверяем аргументы
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "❌ <b>Использование:</b> /review_complaint &lt;id&gt;\n\n"
            "Пример: <code>/review_complaint 123</code>\n\n"
            "Для просмотра списка жалоб используйте /pending_complaints",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        complaint_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный ID жалобы. Укажите числовой ID.",
            parse_mode=ParseMode.HTML
        )
        return

    # Загружаем жалобу из БД
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM user_feedback
                WHERE id = ? AND feedback_type = 'complaint'
                """,
                (complaint_id,)
            )
            complaint = await cursor.fetchone()

        if not complaint:
            await update.message.reply_text(
                f"❌ Жалоба #{complaint_id} не найдена.",
                parse_mode=ParseMode.HTML
            )
            return

        # Форматируем информацию о жалобе
        status_emoji = {
            'new': '🆕',
            'in_progress': '⏳',
            'resolved': '✅',
            'closed': '🔒'
        }

        user_answer_preview = complaint['user_answer'][:400] if complaint['user_answer'] else "Н/Д"
        ai_feedback_preview = complaint['ai_feedback'][:400] if complaint['ai_feedback'] else "Н/Д"

        text = f"""
{status_emoji.get(complaint['status'], '❓')} <b>Жалоба #{complaint_id}</b>

<b>Статус:</b> {complaint['status']}
<b>Пользователь:</b> <code>{complaint['user_id']}</code>
<b>Дата:</b> {complaint['created_at']}

📚 <b>Задание:</b> {complaint['task_type']}
📖 <b>Тема:</b> {complaint['topic_name']}
📊 <b>Оценка AI:</b> K1={complaint['k1_score']}, K2={complaint['k2_score']}

<b>Причина жалобы:</b>
{complaint['complaint_reason']}

<b>Описание от ученика:</b>
{complaint['message']}

━━━━━━━━━━━━━━━━━━━━

<b>План ученика:</b>
<code>{user_answer_preview}{'...' if len(user_answer_preview) >= 400 else ''}</code>

<b>Обратная связь AI:</b>
<code>{ai_feedback_preview}{'...' if len(ai_feedback_preview) >= 400 else ''}</code>
"""

        # Создаём клавиатуру с действиями
        keyboard = []

        if complaint['status'] == 'new':
            keyboard.append([
                InlineKeyboardButton("✅ Одобрить", callback_data=f"adm_approve:{complaint_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"adm_reject:{complaint_id}")
            ])

        if complaint['status'] in ['new', 'in_progress']:
            keyboard.append([
                InlineKeyboardButton("📝 Создать подсказку", callback_data=f"adm_create_hint:{complaint_id}")
            ])

        keyboard.append([
            InlineKeyboardButton("💬 Ответить ученику", callback_data=f"adm_respond:{complaint_id}")
        ])

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )

    except Exception as e:
        logger.error(f"Error reviewing complaint #{complaint_id}: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Произошла ошибка при загрузке жалобы #{complaint_id}.",
            parse_mode=ParseMode.HTML
        )


@admin_only
async def cmd_pending_complaints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда для просмотра списка ожидающих жалоб: /pending_complaints
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, user_id, task_type, topic_name, complaint_reason,
                       k1_score, k2_score, created_at
                FROM user_feedback
                WHERE feedback_type = 'complaint' AND status = 'new'
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
            complaints = await cursor.fetchall()

        if not complaints:
            await update.message.reply_text(
                "✅ Нет ожидающих жалоб!",
                parse_mode=ParseMode.HTML
            )
            return

        text = f"🆕 <b>Ожидающие жалобы ({len(complaints)}):</b>\n\n"

        for complaint in complaints:
            text += f"""
<b>#{complaint['id']}</b> | {complaint['task_type']} | {complaint['topic_name']}
👤 User: <code>{complaint['user_id']}</code> | 📊 K1={complaint['k1_score']}, K2={complaint['k2_score']}
📅 {complaint['created_at']}
💭 {complaint['complaint_reason']}

"""

        text += "\nИспользуйте /review_complaint &lt;id&gt; для просмотра."

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error fetching pending complaints: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при загрузке жалоб.",
            parse_mode=ParseMode.HTML
        )


async def handle_approve_complaint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик одобрения жалобы.
    """
    query = update.callback_query
    await query.answer()

    complaint_id = int(query.data.split(":")[1])

    try:
        # Обновляем статус жалобы
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                """
                UPDATE user_feedback
                SET status = 'resolved',
                    resolution_type = 'approved',
                    admin_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (update.effective_user.id, complaint_id)
            )
            await db.commit()

        logger.info(f"Complaint #{complaint_id} approved by admin {update.effective_user.id}")

        await query.edit_message_text(
            f"✅ <b>Жалоба #{complaint_id} одобрена!</b>\n\n"
            "Теперь вы можете создать подсказку для AI, чтобы предотвратить подобные ошибки в будущем.\n\n"
            f"Используйте команду:\n<code>/create_hint {complaint_id}</code>",
            parse_mode=ParseMode.HTML
        )

        # Уведомляем пользователя об одобрении
        await notify_user_about_resolution(context, complaint_id, approved=True)

    except Exception as e:
        logger.error(f"Error approving complaint #{complaint_id}: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при одобрении жалобы #{complaint_id}.",
            parse_mode=ParseMode.HTML
        )


async def handle_reject_complaint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик отклонения жалобы.
    """
    query = update.callback_query
    await query.answer()

    complaint_id = int(query.data.split(":")[1])

    try:
        # Обновляем статус жалобы
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                """
                UPDATE user_feedback
                SET status = 'resolved',
                    resolution_type = 'rejected',
                    admin_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (update.effective_user.id, complaint_id)
            )
            await db.commit()

        logger.info(f"Complaint #{complaint_id} rejected by admin {update.effective_user.id}")

        await query.edit_message_text(
            f"❌ <b>Жалоба #{complaint_id} отклонена.</b>\n\n"
            "Пользователь будет уведомлён.",
            parse_mode=ParseMode.HTML
        )

        # Уведомляем пользователя об отклонении
        await notify_user_about_resolution(context, complaint_id, approved=False)

    except Exception as e:
        logger.error(f"Error rejecting complaint #{complaint_id}: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при отклонении жалобы #{complaint_id}.",
            parse_mode=ParseMode.HTML
        )


async def handle_create_hint_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начало интерактивного создания подсказки из жалобы.
    """
    query = update.callback_query
    await query.answer()

    complaint_id = int(query.data.split(":")[1])

    # Сохраняем ID жалобы в контексте
    context.user_data['creating_hint_for_complaint'] = complaint_id

    await query.edit_message_text(
        f"📝 <b>Создание подсказки из жалобы #{complaint_id}</b>\n\n"
        "Введите текст подсказки для AI.\n\n"
        "<b>Формат:</b> \"Учитывай, что...\"\n\n"
        "<i>Пример:</i> <code>Учитывай, что в России разрешены многопартийность и плюрализм. "
        "Упоминание только одной партии в контексте примера НЕ является ошибкой, "
        "если контекст изложен правильно.</code>\n\n"
        "Отправьте текстовое сообщение с подсказкой.",
        parse_mode=ParseMode.HTML
    )

    return HINT_AWAITING_TEXT


@admin_only
async def cmd_create_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда для создания подсказки: /create_hint <complaint_id>
    """
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "❌ <b>Использование:</b> /create_hint &lt;complaint_id&gt;\n\n"
            "Пример: <code>/create_hint 123</code>",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        complaint_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный ID жалобы.",
            parse_mode=ParseMode.HTML
        )
        return

    # Проверяем существование жалобы
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, task_type, topic_name FROM user_feedback WHERE id = ?",
                (complaint_id,)
            )
            complaint = await cursor.fetchone()

        if not complaint:
            await update.message.reply_text(
                f"❌ Жалоба #{complaint_id} не найдена.",
                parse_mode=ParseMode.HTML
            )
            return

        # Сохраняем контекст
        context.user_data['creating_hint_for_complaint'] = complaint_id

        await update.message.reply_text(
            f"📝 <b>Создание подсказки из жалобы #{complaint_id}</b>\n\n"
            f"Задание: {complaint['task_type']}\n"
            f"Тема: {complaint['topic_name']}\n\n"
            "Введите текст подсказки для AI (начните с 'Учитывай, что...'):",
            parse_mode=ParseMode.HTML
        )

        return HINT_AWAITING_TEXT

    except Exception as e:
        logger.error(f"Error initiating hint creation: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка.",
            parse_mode=ParseMode.HTML
        )


async def handle_hint_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка ввода текста подсказки.
    """
    hint_text = update.message.text

    # Валидация
    if len(hint_text) < 20:
        await update.message.reply_text(
            "⚠️ Текст подсказки слишком короткий. Минимум 20 символов.\n\n"
            "Пожалуйста, введите более подробную подсказку:",
            parse_mode=ParseMode.HTML
        )
        return HINT_AWAITING_TEXT

    # Сохраняем текст
    context.user_data['hint_text'] = hint_text

    # Запрашиваем категорию
    keyboard = [
        [InlineKeyboardButton("📊 Критерии оценки", callback_data="hcat_criteria")],
        [InlineKeyboardButton("✅ Фактические аспекты", callback_data="hcat_factual")],
        [InlineKeyboardButton("📝 Структура ответа", callback_data="hcat_structural")],
        [InlineKeyboardButton("📖 Терминология", callback_data="hcat_terminology")],
        [InlineKeyboardButton("💭 Общие рекомендации", callback_data="hcat_general")],
    ]

    await update.message.reply_text(
        "✅ Текст подсказки сохранён.\n\n"
        "Теперь выберите категорию подсказки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    return HINT_AWAITING_CATEGORY


async def handle_hint_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка выбора категории подсказки.
    """
    query = update.callback_query
    await query.answer()

    category_map = {
        'hcat_criteria': 'criteria',
        'hcat_factual': 'factual',
        'hcat_structural': 'structural',
        'hcat_terminology': 'terminology',
        'hcat_general': 'general'
    }

    category = category_map.get(query.data, 'general')
    context.user_data['hint_category'] = category

    # Запрашиваем приоритет
    keyboard = [
        [InlineKeyboardButton("⭐️⭐️⭐️⭐️⭐️ Критичная (5)", callback_data="hprio_5")],
        [InlineKeyboardButton("⭐️⭐️⭐️⭐️ Высокая (4)", callback_data="hprio_4")],
        [InlineKeyboardButton("⭐️⭐️⭐️ Средняя (3)", callback_data="hprio_3")],
        [InlineKeyboardButton("⭐️⭐️ Низкая (2)", callback_data="hprio_2")],
        [InlineKeyboardButton("⭐️ Минимальная (1)", callback_data="hprio_1")],
    ]

    await query.edit_message_text(
        f"✅ Категория: <b>{category}</b>\n\n"
        "Теперь выберите приоритет подсказки:\n\n"
        "5 - Критичная (всегда применяется первой)\n"
        "4 - Высокая\n"
        "3 - Средняя (по умолчанию)\n"
        "2 - Низкая\n"
        "1 - Минимальная",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    return HINT_AWAITING_PRIORITY


async def handle_hint_priority_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Финальный шаг: сохранение подсказки в БД.
    """
    query = update.callback_query
    await query.answer()

    priority = int(query.data.split("_")[1])

    # Извлекаем все данные
    complaint_id = context.user_data.get('creating_hint_for_complaint')
    hint_text = context.user_data.get('hint_text')
    hint_category = context.user_data.get('hint_category', 'general')

    try:
        # Получаем информацию о жалобе
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT task_type, topic_name FROM user_feedback WHERE id = ?",
                (complaint_id,)
            )
            complaint = await cursor.fetchone()

        if not complaint:
            await query.edit_message_text(
                f"❌ Жалоба #{complaint_id} не найдена.",
                parse_mode=ParseMode.HTML
            )
            return ConversationHandler.END

        # Создаём подсказку через HintManager
        hint_manager = HintManager(DATABASE_FILE)
        hint_id = await hint_manager.create_hint_from_complaint(
            complaint_id=complaint_id,
            task_type=complaint['task_type'],
            topic_name=complaint['topic_name'],
            hint_text=hint_text,
            hint_category=hint_category,
            priority=priority,
            admin_id=update.effective_user.id
        )

        logger.info(
            f"Hint #{hint_id} created from complaint #{complaint_id} "
            f"by admin {update.effective_user.id}"
        )

        await query.edit_message_text(
            f"✅ <b>Подсказка #{hint_id} успешно создана!</b>\n\n"
            f"Задание: {complaint['task_type']}\n"
            f"Тема: {complaint['topic_name']}\n"
            f"Категория: {hint_category}\n"
            f"Приоритет: {priority}/5\n\n"
            f"<b>Текст подсказки:</b>\n<code>{hint_text}</code>\n\n"
            "Подсказка будет автоматически применяться при проверке этой темы.",
            parse_mode=ParseMode.HTML
        )

        # Очищаем контекст
        context.user_data.pop('creating_hint_for_complaint', None)
        context.user_data.pop('hint_text', None)
        context.user_data.pop('hint_category', None)

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error creating hint: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при создании подсказки.",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END


async def notify_user_about_resolution(
    context: ContextTypes.DEFAULT_TYPE,
    complaint_id: int,
    approved: bool
):
    """
    Отправляет уведомление пользователю о решении по его жалобе.
    """
    try:
        # Получаем информацию о жалобе
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT user_id, topic_name FROM user_feedback WHERE id = ?",
                (complaint_id,)
            )
            complaint = await cursor.fetchone()

        if not complaint:
            logger.warning(f"Cannot notify user: complaint #{complaint_id} not found")
            return

        user_id = complaint['user_id']
        topic = complaint['topic_name']

        if approved:
            message = f"""
✅ <b>Ваша жалоба #{complaint_id} одобрена!</b>

Тема: <i>{topic}</i>

Администратор рассмотрел вашу жалобу и согласился с вашими аргументами.
Спасибо за обратную связь! Мы используем её для улучшения качества проверки AI.

В будущем подобные ситуации будут учитываться при проверке.
"""
        else:
            message = f"""
❌ <b>Ваша жалоба #{complaint_id} отклонена</b>

Тема: <i>{topic}</i>

Администратор рассмотрел вашу жалобу. К сожалению, оценка AI признана корректной.

Если у вас остались вопросы, вы можете обратиться в поддержку.
"""

        await context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"User {user_id} notified about complaint #{complaint_id} resolution")

    except Exception as e:
        logger.error(f"Error notifying user about complaint resolution: {e}", exc_info=True)


@admin_only
async def cmd_hints_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда для просмотра списка всех подсказок: /hints_list [task_type] [topic]
    """
    task_type = context.args[0] if len(context.args) > 0 else None
    topic_name = ' '.join(context.args[1:]) if len(context.args) > 1 else None

    try:
        hint_manager = HintManager(DATABASE_FILE)

        if task_type and topic_name:
            hints = await hint_manager.get_hints_by_topic(task_type, topic_name)
            header = f"📋 <b>Подсказки для {task_type} / {topic_name}:</b>\n\n"
        elif task_type:
            hints = await hint_manager.get_active_hints(task_type, max_hints=20)
            header = f"📋 <b>Активные подсказки для {task_type}:</b>\n\n"
        else:
            # Получаем все активные подсказки
            async with aiosqlite.connect(DATABASE_FILE) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT id, task_type, topic_name, hint_category, priority,
                           is_active, usage_count
                    FROM task_specific_hints
                    WHERE is_active = 1
                    ORDER BY task_type, priority DESC, usage_count DESC
                    LIMIT 20
                    """
                )
                rows = await cursor.fetchall()
                hints = [dict(row) for row in rows]
            header = "📋 <b>Все активные подсказки (топ 20):</b>\n\n"

        if not hints:
            await update.message.reply_text(
                "Подсказок не найдено.",
                parse_mode=ParseMode.HTML
            )
            return

        text = header
        for hint in hints:
            status = "✅" if hint.get('is_active', 1) else "❌"
            text += f"""
{status} <b>#{hint.get('hint_id', hint.get('id'))}</b> | {hint.get('task_type', 'N/A')} | {hint.get('topic_name', 'Общая')}
📊 Приоритет: {hint.get('priority', 1)}/5 | 📈 Использований: {hint.get('usage_count', 0)}
📂 Категория: {hint.get('hint_category', 'N/A')}

"""

        text += "\nИспользуйте /hint_details &lt;id&gt; для просмотра полной информации."

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error fetching hints list: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при загрузке подсказок.",
            parse_mode=ParseMode.HTML
        )


def register_admin_complaint_handlers(app):
    """
    Регистрирует все обработчики админ-панели для жалоб.

    Args:
        app: Application instance
    """
    # Команды для работы с жалобами
    app.add_handler(CommandHandler("review_complaint", cmd_review_complaint))
    app.add_handler(CommandHandler("pending_complaints", cmd_pending_complaints))
    app.add_handler(CommandHandler("hints_list", cmd_hints_list))

    # Callback handlers для кнопок
    app.add_handler(CallbackQueryHandler(handle_approve_complaint, pattern=r"^adm_approve:"))
    app.add_handler(CallbackQueryHandler(handle_reject_complaint, pattern=r"^adm_reject:"))

    # Conversation handler для создания подсказок
    hint_creation_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_create_hint_button, pattern=r"^adm_create_hint:"),
            CommandHandler("create_hint", cmd_create_hint)
        ],
        states={
            HINT_AWAITING_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hint_text_input)
            ],
            HINT_AWAITING_CATEGORY: [
                CallbackQueryHandler(handle_hint_category_selection, pattern=r"^hcat_")
            ],
            HINT_AWAITING_PRIORITY: [
                CallbackQueryHandler(handle_hint_priority_selection, pattern=r"^hprio_")
            ],
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(hint_creation_conv)

    logger.info("Admin complaint handlers registered successfully")
