"""
Scheduler для автоматической отправки напоминаний о дедлайнах домашних заданий.

Запускается каждые несколько часов через Telegram Job Queue.
Проверяет приближающиеся дедлайны и отправляет уведомления ученикам.
"""

import logging
import aiosqlite
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)


class DeadlineScheduler:
    """Планировщик напоминаний о дедлайнах"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file

    async def get_upcoming_deadlines(self, hours_before: int) -> List[Dict[str, Any]]:
        """
        Получает домашние задания с приближающимися дедлайнами.

        Args:
            hours_before: За сколько часов до дедлайна искать задания

        Returns:
            Список словарей с информацией о заданиях и учениках
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                db.row_factory = aiosqlite.Row

                now = datetime.now(timezone.utc)
                deadline_start = now + timedelta(hours=hours_before - 1)
                deadline_end = now + timedelta(hours=hours_before + 1)

                # Получаем задания с дедлайнами в указанном диапазоне
                cursor = await db.execute("""
                    SELECT
                        ha.id as homework_id,
                        ha.title,
                        ha.deadline,
                        ha.assignment_data,
                        ha.teacher_id,
                        hsa.student_id
                    FROM homework_assignments ha
                    JOIN homework_student_assignments hsa ON ha.id = hsa.homework_id
                    WHERE ha.deadline IS NOT NULL
                      AND ha.deadline BETWEEN ? AND ?
                      AND ha.status = 'active'
                      AND hsa.status = 'assigned'
                    ORDER BY ha.deadline
                """, (deadline_start.isoformat(), deadline_end.isoformat()))

                assignments = await cursor.fetchall()

                result = []
                for row in assignments:
                    # Проверяем, завершил ли ученик задание
                    try:
                        assignment_data = json.loads(row['assignment_data'])
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        logger.warning(f"Ошибка парсинга assignment_data для homework {row['homework_id']}: {e}")
                        continue  # Пропускаем задание с некорректными данными

                    # Определяем количество вопросов
                    if assignment_data.get('is_mixed'):
                        total_questions = assignment_data.get('total_questions_count', 0)
                    elif assignment_data.get('is_custom'):
                        total_questions = len(assignment_data.get('custom_questions', []))
                    else:
                        total_questions = assignment_data.get('questions_count', 0)

                    # Получаем прогресс ученика
                    progress_cursor = await db.execute("""
                        SELECT COUNT(*) as completed
                        FROM homework_progress
                        WHERE homework_id = ? AND student_id = ?
                    """, (row['homework_id'], row['student_id']))

                    progress_row = await progress_cursor.fetchone()
                    completed_questions = progress_row['completed'] if progress_row else 0

                    # Если не завершено - добавляем в результат
                    if completed_questions < total_questions:
                        result.append({
                            'homework_id': row['homework_id'],
                            'title': row['title'],
                            'deadline': row['deadline'],
                            'teacher_id': row['teacher_id'],
                            'student_id': row['student_id'],
                            'total_questions': total_questions,
                            'completed_questions': completed_questions,
                            'progress_percent': round((completed_questions / total_questions * 100) if total_questions > 0 else 0, 1)
                        })

                return result

        except Exception as e:
            logger.error(f"Ошибка при получении дедлайнов: {e}")
            return []

    async def has_recent_reminder(self, student_id: int, homework_id: int, hours: int) -> bool:
        """
        Проверяет, отправлялось ли напоминание недавно.

        Args:
            student_id: ID ученика
            homework_id: ID домашнего задания
            hours: За сколько часов проверять

        Returns:
            True если напоминание уже отправлялось недавно
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                db.row_factory = aiosqlite.Row

                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

                cursor = await db.execute("""
                    SELECT id FROM deadline_reminders
                    WHERE student_id = ?
                      AND homework_id = ?
                      AND sent_at > ?
                """, (student_id, homework_id, cutoff.isoformat()))

                row = await cursor.fetchone()
                return row is not None

        except Exception as e:
            logger.error(f"Ошибка при проверке напоминания: {e}")
            return False

    async def log_reminder(self, student_id: int, homework_id: int, hours_before: int):
        """Логирует отправленное напоминание"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    INSERT OR IGNORE INTO deadline_reminders (
                        student_id, homework_id, hours_before, sent_at
                    ) VALUES (?, ?, ?, ?)
                """, (
                    student_id,
                    homework_id,
                    hours_before,
                    datetime.now(timezone.utc).isoformat()
                ))
                await db.commit()

        except Exception as e:
            logger.error(f"Ошибка при логировании напоминания: {e}")

    def format_time_remaining(self, deadline_str: str) -> str:
        """Форматирует оставшееся время до дедлайна"""
        try:
            # Парсим deadline и убеждаемся что он timezone-aware
            deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))

            # Если deadline naive (без timezone), добавляем UTC
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            delta = deadline - now

            hours = delta.total_seconds() / 3600

            if hours < 1:
                minutes = int(delta.total_seconds() / 60)
                return f"{minutes} минут"
            elif hours < 24:
                hours_int = int(hours)
                return f"{hours_int} час{'а' if hours_int in [2, 3, 4] else 'ов' if hours_int >= 5 else ''}"
            else:
                days = int(hours / 24)
                return f"{days} день{'ня' if days == 1 else 'дня' if days in [2, 3, 4] else 'дней'}"

        except Exception as e:
            logger.error(f"Ошибка форматирования времени: {e}")
            return "скоро"

    async def send_deadline_reminder(
        self,
        bot: Bot,
        student_id: int,
        homework_id: int,
        title: str,
        deadline_str: str,
        progress_percent: float,
        completed_questions: int,
        total_questions: int,
        hours_before: int
    ) -> bool:
        """
        Отправляет напоминание о дедлайне ученику.

        Returns:
            True если успешно отправлено
        """
        try:
            # Проверяем, не отправляли ли недавно
            if await self.has_recent_reminder(student_id, homework_id, hours_before):
                logger.debug(f"Reminder already sent for student {student_id}, homework {homework_id}")
                return False

            time_remaining = self.format_time_remaining(deadline_str)

            # Формируем текст уведомления
            text = f"⏰ <b>Напоминание о дедлайне!</b>\n\n"
            text += f"📝 <b>Задание:</b> {title}\n"
            text += f"⏳ <b>Осталось времени:</b> {time_remaining}\n\n"

            if progress_percent > 0:
                text += f"📊 <b>Ваш прогресс:</b> {completed_questions}/{total_questions} вопросов ({progress_percent}%)\n\n"

                if progress_percent >= 100:
                    text += "✅ Задание выполнено! Отличная работа!"
                elif progress_percent >= 50:
                    text += "👍 Вы уже больше половины! Завершите оставшиеся вопросы."
                else:
                    text += "📚 Ещё есть время завершить задание. Не откладывайте на последний момент!"
            else:
                text += "⚠️ <b>Вы ещё не начали выполнение!</b>\n\n"
                text += "Начните работу как можно скорее, чтобы успеть до дедлайна."

            # Кнопки
            keyboard = [
                [InlineKeyboardButton("📝 Начать выполнение", callback_data=f"start_homework_{homework_id}")],
                [InlineKeyboardButton("📋 Мои домашние задания", callback_data="student_homework_list")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправляем
            await bot.send_message(
                chat_id=student_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

            # Логируем
            await self.log_reminder(student_id, homework_id, hours_before)

            logger.info(f"Sent deadline reminder to student {student_id} for homework {homework_id}")
            return True

        except Forbidden:
            logger.warning(f"Student {student_id} blocked the bot")
            return False

        except BadRequest as e:
            logger.error(f"BadRequest sending to {student_id}: {e}")
            return False

        except Exception as e:
            logger.error(f"Error sending reminder to {student_id}: {e}")
            return False

    async def check_and_send_reminders(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Главная функция для проверки дедлайнов и отправки напоминаний.
        Вызывается Job Queue каждые несколько часов.
        """
        bot = context.bot

        logger.info("=== Starting deadline reminders check ===")

        total_sent = 0

        try:
            # Проверяем дедлайны за 24 часа
            logger.info("Checking deadlines in 24 hours...")
            deadlines_24h = await self.get_upcoming_deadlines(hours_before=24)

            for assignment in deadlines_24h:
                success = await self.send_deadline_reminder(
                    bot=bot,
                    student_id=assignment['student_id'],
                    homework_id=assignment['homework_id'],
                    title=assignment['title'],
                    deadline_str=assignment['deadline'],
                    progress_percent=assignment['progress_percent'],
                    completed_questions=assignment['completed_questions'],
                    total_questions=assignment['total_questions'],
                    hours_before=24
                )

                if success:
                    total_sent += 1

            # Проверяем дедлайны за 3 часа (более срочные)
            logger.info("Checking deadlines in 3 hours...")
            deadlines_3h = await self.get_upcoming_deadlines(hours_before=3)

            for assignment in deadlines_3h:
                success = await self.send_deadline_reminder(
                    bot=bot,
                    student_id=assignment['student_id'],
                    homework_id=assignment['homework_id'],
                    title=assignment['title'],
                    deadline_str=assignment['deadline'],
                    progress_percent=assignment['progress_percent'],
                    completed_questions=assignment['completed_questions'],
                    total_questions=assignment['total_questions'],
                    hours_before=3
                )

                if success:
                    total_sent += 1

        except Exception as e:
            logger.error(f"Error in deadline reminders: {e}", exc_info=True)

        logger.info(f"=== Deadline reminders complete: {total_sent} sent ===")


# Глобальный экземпляр
_scheduler_instance: Optional['DeadlineScheduler'] = None


def get_deadline_scheduler() -> DeadlineScheduler:
    """Возвращает глобальный экземпляр scheduler"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = DeadlineScheduler()
    return _scheduler_instance
