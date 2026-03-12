"""
Обработчики жалоб учеников на оценки AI для Task24.

Этот модуль реализует workflow подачи жалоб:
1. Ученик нажимает "Оспорить оценку"
2. Выбирает причину жалобы
3. Описывает проблему подробно
4. Жалоба сохраняется в БД и отправляется администратору
"""

import logging
import aiosqlite
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)

# Состояния conversation handler для жалоб
COMPLAINT_CHOOSING_REASON = "complaint_choosing_reason"
COMPLAINT_AWAITING_DETAILS = "complaint_awaiting_details"


async def initiate_complaint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начало процесса подачи жалобы.

    Вызывается при нажатии на кнопку "Оспорить оценку".
    """
    query = update.callback_query
    await query.answer()

    # Проверяем, есть ли сохранённый результат проверки
    last_result = context.user_data.get('last_plan_result')
    if not last_result:
        await query.edit_message_text(
            "❌ Данные последней проверки не найдены.\n\n"
            "Пожалуйста, попробуйте решить задачу ещё раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Назад к меню", callback_data="t24_menu")
            ]])
        )
        return ConversationHandler.END

    # Проверяем лимит жалоб (не более 3 в день)
    user_id = update.effective_user.id
    if not await check_complaint_limit(user_id):
        await query.edit_message_text(
            "⚠️ <b>Лимит жалоб исчерпан</b>\n\n"
            "Вы можете отправить не более 3 жалоб в день.\n"
            "Пожалуйста, попробуйте завтра или обратитесь напрямую в поддержку.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Назад", callback_data="t24_menu")
            ]]),
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    # Сохраняем контекст жалобы
    topic_name = last_result.get('topic')
    context.user_data['complaint_context'] = {
        'topic': topic_name,
        'task_type': 'task24',
        'user_answer': last_result.get('user_answer'),
        'ai_feedback': last_result.get('ai_feedback'),
        'k1_score': last_result.get('k1'),
        'k2_score': last_result.get('k2'),
        'timestamp': datetime.now().isoformat()
    }

    # Клавиатура с причинами жалобы
    keyboard = [
        [InlineKeyboardButton("❌ Фактическая ошибка засчитана неверно", callback_data="cr_factual")],
        [InlineKeyboardButton("📝 Структура плана оценена неправильно", callback_data="cr_structure")],
        [InlineKeyboardButton("📊 Критерии применены некорректно", callback_data="cr_criteria")],
        [InlineKeyboardButton("💭 Другая причина", callback_data="cr_other")],
        [InlineKeyboardButton("« Отмена", callback_data="t24_cancel_complaint")]
    ]

    await query.edit_message_text(
        f"⚠️ <b>Оспаривание оценки</b>\n\n"
        f"Тема: <i>{topic_name}</i>\n"
        f"Ваша оценка: {last_result.get('k1')} + {last_result.get('k2')} = {last_result.get('total')}/4\n\n"
        f"Выберите причину вашей жалобы:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    return COMPLAINT_CHOOSING_REASON


async def handle_complaint_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка выбора причины жалобы.
    """
    query = update.callback_query
    await query.answer()

    # Отмена жалобы
    if query.data == "t24_cancel_complaint":
        await query.edit_message_text(
            "❌ Жалоба отменена.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Назад к меню", callback_data="t24_menu")
            ]])
        )
        # Очищаем контекст
        context.user_data.pop('complaint_context', None)
        return ConversationHandler.END

    # Маппинг причин
    reason_map = {
        "cr_factual": "Фактическая ошибка засчитана неверно",
        "cr_structure": "Структура плана оценена неправильно",
        "cr_criteria": "Критерии применены некорректно",
        "cr_other": "Другая причина"
    }

    complaint_reason = reason_map.get(query.data, "Не указана")
    context.user_data['complaint_reason'] = complaint_reason

    await query.edit_message_text(
        "📝 <b>Опишите проблему подробнее</b>\n\n"
        f"Причина: <i>{complaint_reason}</i>\n\n"
        "Пожалуйста, объясните, почему вы считаете оценку несправедливой. "
        "Будьте максимально конкретны:\n"
        "• Укажите, какой именно пункт или ошибку вы оспариваете\n"
        "• Объясните, почему считаете оценку AI некорректной\n"
        "• Приведите аргументы из курса обществознания\n\n"
        "<i>Отправьте текстовое сообщение с описанием проблемы.</i>",
        parse_mode=ParseMode.HTML
    )

    return COMPLAINT_AWAITING_DETAILS


async def handle_complaint_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Сохранение детальной жалобы в БД.
    """
    user_id = update.effective_user.id
    complaint_details = update.message.text

    # Валидация длины
    if len(complaint_details) < 20:
        await update.message.reply_text(
            "⚠️ Описание слишком короткое.\n\n"
            "Пожалуйста, опишите проблему подробнее (минимум 20 символов).",
            parse_mode=ParseMode.HTML
        )
        return COMPLAINT_AWAITING_DETAILS

    complaint_ctx = context.user_data.get('complaint_context', {})
    complaint_reason = context.user_data.get('complaint_reason', 'Не указана')

    try:
        # Сохраняем жалобу в БД
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                """
                INSERT INTO user_feedback
                (user_id, feedback_type, category, message,
                 task_type, topic_name, user_answer, ai_feedback,
                 k1_score, k2_score, complaint_reason, status)
                VALUES (?, 'complaint', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
                """,
                (
                    user_id,
                    complaint_reason,
                    complaint_details,
                    complaint_ctx.get('task_type'),
                    complaint_ctx.get('topic'),
                    complaint_ctx.get('user_answer'),
                    complaint_ctx.get('ai_feedback'),
                    complaint_ctx.get('k1_score'),
                    complaint_ctx.get('k2_score'),
                    complaint_reason
                )
            )
            complaint_id = cursor.lastrowid
            await db.commit()

        logger.info(f"Complaint #{complaint_id} created by user {user_id} for topic '{complaint_ctx.get('topic')}'")

        # Уведомляем администратора (если есть ID в конфиге)
        await notify_admin_about_complaint(context, complaint_id, user_id, complaint_ctx, complaint_details)

        # Отправляем подтверждение пользователю
        await update.message.reply_text(
            "✅ <b>Жалоба успешно отправлена!</b>\n\n"
            f"Номер обращения: <code>#{complaint_id}</code>\n"
            f"Тема: <i>{complaint_ctx.get('topic')}</i>\n\n"
            "Мы рассмотрим вашу жалобу в течение 24 часов.\n"
            "Вы получите уведомление, когда администратор ответит.\n\n"
            "Спасибо за обратную связь! Это помогает нам улучшить качество проверки.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Вернуться к меню", callback_data="t24_menu")
            ]])
        )

    except Exception as e:
        logger.error(f"Failed to save complaint: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при сохранении жалобы.\n\n"
            "Пожалуйста, попробуйте позже или обратитесь напрямую в поддержку.",
            parse_mode=ParseMode.HTML
        )

    # Очищаем контекст
    context.user_data.pop('complaint_context', None)
    context.user_data.pop('complaint_reason', None)

    return ConversationHandler.END


async def check_complaint_limit(user_id: int) -> bool:
    """
    Проверяет, не превышен ли дневной лимит жалоб для пользователя.

    Args:
        user_id: ID пользователя

    Returns:
        bool: True если можно подать жалобу, False если лимит исчерпан
    """
    COMPLAINT_DAILY_LIMIT = 3

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM user_feedback
                WHERE user_id = ?
                  AND feedback_type = 'complaint'
                  AND DATE(created_at) = DATE('now')
                """,
                (user_id,)
            )
            count = (await cursor.fetchone())[0]
            return count < COMPLAINT_DAILY_LIMIT
    except Exception as e:
        logger.error(f"Error checking complaint limit: {e}")
        return True  # В случае ошибки разрешаем подать жалобу


async def notify_admin_about_complaint(
    context: ContextTypes.DEFAULT_TYPE,
    complaint_id: int,
    user_id: int,
    complaint_ctx: dict,
    complaint_details: str
):
    """
    Отправляет уведомление администратору о новой жалобе.

    Args:
        context: Контекст бота
        complaint_id: ID жалобы
        user_id: ID пользователя
        complaint_ctx: Контекст проверки
        complaint_details: Детали жалобы
    """
    # Получаем ID администратора из конфига (если есть)
    try:
        # TODO: Добавить admin_id в конфиг
        # admin_id = context.bot_data.get('admin_id')
        # Временно используем захардкоженный ID или пропускаем
        admin_id = None

        if not admin_id:
            logger.info("Admin ID not configured, skipping notification")
            return

        # Форматируем уведомление
        topic = complaint_ctx.get('topic', 'Не указана')
        k1 = complaint_ctx.get('k1_score', '?')
        k2 = complaint_ctx.get('k2_score', '?')

        notification_text = f"""
🆕 <b>Новая жалоба #{complaint_id}</b>

👤 <b>Пользователь:</b> {user_id}
📚 <b>Задание:</b> Task24 (План)
📖 <b>Тема:</b> {topic}
📊 <b>Оценка:</b> K1={k1}, K2={k2}

<b>Описание:</b>
{complaint_details[:300]}{'...' if len(complaint_details) > 300 else ''}

Используйте /review_complaint {complaint_id} для просмотра полной информации.
"""

        await context.bot.send_message(
            chat_id=admin_id,
            text=notification_text,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Admin notification sent for complaint #{complaint_id}")

    except Exception as e:
        logger.error(f"Failed to notify admin about complaint #{complaint_id}: {e}")
        # Не прерываем процесс, даже если уведомление не отправлено
