"""
Сервис для отправки уведомлений ученикам и учителям о домашних заданиях.

ИСПРАВЛЕНО:
- Добавлен retry механизм с экспоненциальным backoff
- Асинхронная отправка уведомлений параллельно
- Rate limiting для предотвращения flood
"""

import logging
import asyncio
from datetime import datetime
from typing import List, Optional
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter

logger = logging.getLogger(__name__)

# ИСПРАВЛЕНО: Константы для retry механизма
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # секунды
MAX_RETRY_DELAY = 10.0  # секунды
RATE_LIMIT_DELAY = 0.05  # задержка между отправками (50ms)


async def send_message_with_retry(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: str = 'HTML',
    reply_markup = None
) -> bool:
    """
    ИСПРАВЛЕНО: Отправляет сообщение с retry механизмом.

    Args:
        bot: Telegram Bot instance
        chat_id: ID чата
        text: Текст сообщения
        parse_mode: Режим парсинга (HTML, Markdown)
        reply_markup: Клавиатура (опционально)

    Returns:
        True если успешно отправлено, False иначе
    """
    retry_delay = INITIAL_RETRY_DELAY

    for attempt in range(MAX_RETRIES):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            return True

        except RetryAfter as e:
            # Telegram просит подождать
            wait_time = min(e.retry_after, MAX_RETRY_DELAY)
            logger.warning(f"Rate limited for {wait_time}s, attempt {attempt + 1}/{MAX_RETRIES}")
            await asyncio.sleep(wait_time)

        except TelegramError as e:
            # Постоянные ошибки (бот заблокирован, чат не найден)
            if "blocked" in str(e).lower() or "not found" in str(e).lower():
                logger.warning(f"Permanent error for chat {chat_id}: {e}")
                return False

            # Временные ошибки - retry
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Telegram error, retrying in {retry_delay}s (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)  # Экспоненциальный backoff
            else:
                logger.error(f"Failed after {MAX_RETRIES} attempts: {e}")
                return False

        except Exception as e:
            logger.error(f"Unexpected error sending message to {chat_id}: {e}")
            return False

    return False


async def notify_students_about_homework(
    bot: Bot,
    student_ids: List[int],
    homework_title: str,
    teacher_name: str,
    deadline: Optional[datetime] = None,
    questions_count: int = 0
) -> dict:
    """
    Отправляет уведомления ученикам о новом домашнем задании.

    ИСПРАВЛЕНО:
    - Использует retry механизм
    - Отправляет уведомления параллельно с rate limiting
    - Улучшена обработка ошибок

    Args:
        bot: Telegram Bot instance
        student_ids: Список ID учеников для уведомления
        homework_title: Название домашнего задания
        teacher_name: Имя учителя
        deadline: Дедлайн выполнения (опционально)
        questions_count: Количество заданий

    Returns:
        Dict с результатами отправки: {'success': int, 'failed': int, 'failed_ids': List[int]}
    """
    # Формируем текст уведомления
    text = (
        f"📝 <b>Новое домашнее задание!</b>\n\n"
        f"👨‍🏫 <b>Учитель:</b> {teacher_name}\n"
        f"📋 <b>Название:</b> {homework_title}\n"
    )

    if questions_count > 0:
        text += f"📊 <b>Заданий:</b> {questions_count}\n"

    if deadline:
        deadline_str = deadline.strftime("%d.%m.%Y %H:%M")
        text += f"⏰ <b>Срок сдачи:</b> {deadline_str}\n"

    text += (
        "\n"
        "💡 Приступайте к выполнению как можно скорее!\n"
        "Посмотреть задание можно в разделе 'Мои задания'."
    )

    # ИСПРАВЛЕНО: Вспомогательная функция для отправки одному ученику с задержкой
    async def send_to_student(student_id: int, index: int) -> tuple[int, bool]:
        """Отправляет уведомление одному ученику с rate limiting"""
        # Rate limiting: задержка пропорциональна индексу
        await asyncio.sleep(index * RATE_LIMIT_DELAY)

        success = await send_message_with_retry(bot, student_id, text)

        if success:
            logger.info(f"✅ Notification sent to student {student_id}")
        else:
            logger.warning(f"❌ Failed to send notification to student {student_id} after {MAX_RETRIES} attempts")

        return student_id, success

    # ИСПРАВЛЕНО: Отправляем параллельно всем ученикам
    tasks = [send_to_student(student_id, i) for i, student_id in enumerate(student_ids)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Подсчитываем результаты
    success_count = 0
    failed_count = 0
    failed_ids = []

    for result in results:
        if isinstance(result, Exception):
            failed_count += 1
            logger.error(f"Exception in notification task: {result}")
        else:
            student_id, success = result
            if success:
                success_count += 1
            else:
                failed_count += 1
                failed_ids.append(student_id)

    result_dict = {
        'success': success_count,
        'failed': failed_count,
        'failed_ids': failed_ids
    }

    logger.info(f"Notification results: {success_count} success, {failed_count} failed out of {len(student_ids)} total")

    return result_dict


async def send_deadline_reminder(
    bot: Bot,
    student_id: int,
    homework_title: str,
    deadline: datetime,
    hours_left: int
) -> bool:
    """
    Отправляет напоминание о приближающемся дедлайне.

    ИСПРАВЛЕНО: Использует retry механизм

    Args:
        bot: Telegram Bot instance
        student_id: ID ученика
        homework_title: Название задания
        deadline: Дедлайн
        hours_left: Сколько часов осталось

    Returns:
        True если отправлено успешно
    """
    deadline_str = deadline.strftime("%d.%m.%Y %H:%M")

    if hours_left <= 1:
        urgency = "🔴 СРОЧНО!"
        time_text = "менее часа"
    elif hours_left <= 24:
        urgency = "⚠️ Важно!"
        time_text = f"{hours_left} ч."
    else:
        urgency = "📌 Напоминание"
        days_left = hours_left // 24
        time_text = f"{days_left} дн."

    text = (
        f"{urgency}\n\n"
        f"⏰ <b>Приближается дедлайн!</b>\n\n"
        f"📋 <b>Задание:</b> {homework_title}\n"
        f"⏱ <b>Осталось:</b> {time_text}\n"
        f"📅 <b>Срок:</b> {deadline_str}\n\n"
        "💪 Поторопитесь завершить задание!"
    )

    # ИСПРАВЛЕНО: Используем retry механизм
    success = await send_message_with_retry(bot, student_id, text)

    if success:
        logger.info(f"✅ Deadline reminder sent to student {student_id}")
    else:
        logger.error(f"❌ Failed to send deadline reminder to student {student_id} after {MAX_RETRIES} attempts")

    return success


async def notify_teacher_about_completion(
    bot: Bot,
    teacher_id: int,
    student_id: int,
    student_name: str,
    homework_id: int,
    homework_title: str,
    correct_count: int,
    total_count: int
) -> bool:
    """
    Отправляет уведомление учителю о завершении задания учеником.

    ИСПРАВЛЕНО: Использует retry механизм

    Args:
        bot: Telegram Bot instance
        teacher_id: ID учителя
        student_id: ID ученика
        student_name: Имя ученика
        homework_id: ID домашнего задания
        homework_title: Название задания
        correct_count: Количество правильных ответов
        total_count: Общее количество вопросов

    Returns:
        True если отправлено успешно
    """
    # Вычисляем процент правильных ответов
    percentage = int((correct_count / total_count * 100)) if total_count > 0 else 0

    text = (
        f"✅ <b>Ученик завершил задание!</b>\n\n"
        f"👤 <b>Ученик:</b> {student_name}\n"
        f"📋 <b>Задание:</b> {homework_title}\n"
        f"📊 <b>Результат:</b> {correct_count}/{total_count} правильных ({percentage}%)\n"
    )

    # Добавляем кнопку "Посмотреть детали"
    keyboard = [
        [InlineKeyboardButton(
            "📝 Посмотреть детали",
            callback_data=f"view_student_progress:{homework_id}:{student_id}"
        )]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # ИСПРАВЛЕНО: Используем retry механизм
    success = await send_message_with_retry(bot, teacher_id, text, reply_markup=reply_markup)

    if success:
        logger.info(f"✅ Completion notification sent to teacher {teacher_id} about student {student_id}, homework {homework_id}")
    else:
        logger.error(f"❌ Failed to send completion notification to teacher {teacher_id} after {MAX_RETRIES} attempts")

    return success
