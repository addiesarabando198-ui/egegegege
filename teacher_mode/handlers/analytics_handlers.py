"""
Обработчики для статистики и аналитики.
"""

import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from ..states import TeacherStates
from ..services.analytics_service import (
    get_teacher_statistics,
    analyze_student_performance,
    analyze_group_performance,
    identify_weak_topics
)
from ..services.teacher_service import get_teacher_students

logger = logging.getLogger(__name__)


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать общую статистику учителя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        # Получаем статистику учителя
        stats = await get_teacher_statistics(user_id)

        text = (
            "📊 <b>Общая статистика</b>\n\n"
            f"👥 <b>Всего учеников:</b> {stats['total_students']}\n"
            f"📝 <b>Всего заданий:</b> {stats['total_homeworks']}\n"
            f"🔥 <b>Активных заданий:</b> {stats['active_homeworks']}\n"
            f"✅ <b>Выполнено:</b> {stats['completed_assignments']}\n"
            f"⏰ <b>Просрочено:</b> {stats['overdue_assignments']}\n"
            f"📈 <b>Средний % выполнения:</b> {stats['average_completion_rate']}%\n"
        )

        # Добавляем топ учеников
        if stats['top_students']:
            text += "\n🏆 <b>Топ учеников:</b>\n"
            for i, student in enumerate(stats['top_students'][:3], 1):
                text += f"{i}. {student['name']} - {student['accuracy']}%\n"

        keyboard = [
            [InlineKeyboardButton("👥 Аналитика по ученикам", callback_data="analytics_students")],
            [InlineKeyboardButton("📊 Групповая аналитика", callback_data="analytics_group")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing statistics: {e}", exc_info=True)
        text = "❌ Ошибка при загрузке статистики. Попробуйте позже."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.VIEW_STATISTICS


async def show_students_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список учеников для выбора детальной аналитики"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        # Получаем список учеников
        students = await get_teacher_students(user_id)

        if not students:
            text = (
                "👥 <b>Аналитика по ученикам</b>\n\n"
                "У вас пока нет учеников.\n"
                "Отправьте им ваш код учителя для подключения."
            )
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_statistics")]]
        else:
            text = (
                "👥 <b>Выберите ученика для детальной аналитики:</b>\n\n"
                "Вы увидите:\n"
                "• Общую успеваемость\n"
                "• Слабые темы (< 60%)\n"
                "• Сильные темы (≥ 80%)\n"
                "• Примеры ошибок\n"
                "• Рекомендации"
            )

            keyboard = []
            for student in students:
                student_name = f"{student['first_name']} {student['last_name'] or ''}".strip()
                keyboard.append([
                    InlineKeyboardButton(
                        f"📊 {student_name}",
                        callback_data=f"analytics_student:{student['user_id']}"
                    )
                ])

            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="teacher_statistics")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing students analytics: {e}", exc_info=True)
        text = "❌ Ошибка при загрузке списка учеников."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_statistics")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.VIEW_STATISTICS


async def show_student_detailed_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать детальную аналитику по конкретному ученику"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Извлекаем student_id из callback_data
    callback_data = query.data
    student_id = int(callback_data.split(':')[1])

    try:
        # Получаем аналитику ученика
        analytics = await analyze_student_performance(student_id, user_id)

        # Получаем имя ученика
        students = await get_teacher_students(user_id)
        student_name = "Ученик"
        for s in students:
            if s['user_id'] == student_id:
                student_name = f"{s['first_name']} {s['last_name'] or ''}".strip()
                break

        text = f"📊 <b>Аналитика: {student_name}</b>\n\n"

        # Общая информация
        text += (
            f"📝 <b>Заданий:</b> {analytics['total_homeworks']} "
            f"(✅ {analytics['completed_homeworks']} | "
            f"⏳ {analytics['in_progress']} | "
            f"⏰ {analytics['overdue']})\n"
            f"📊 <b>Вопросов решено:</b> {analytics['correct_count']}/{analytics['total_questions']}\n"
            f"🎯 <b>Общая успеваемость:</b> {analytics['overall_accuracy']}%\n"
        )

        # Слабые темы
        if analytics['weak_topics']:
            text += "\n🔴 <b>Слабые темы (< 60%):</b>\n"
            for wt in analytics['weak_topics'][:5]:
                text += f"  • {wt['topic']}: {wt['accuracy']}%\n"

        # Сильные темы
        if analytics['strong_topics']:
            text += "\n🟢 <b>Сильные темы (≥ 80%):</b>\n"
            for st in analytics['strong_topics'][:3]:
                text += f"  • {st['topic']}: {st['accuracy']}%\n"

        # Рекомендации
        if analytics['recommendations']:
            text += "\n💡 <b>Рекомендации:</b>\n"
            for rec in analytics['recommendations'][:3]:
                text += f"  • {rec}\n"

        keyboard = [
            [InlineKeyboardButton("📋 Примеры ошибок", callback_data=f"analytics_errors:{student_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="analytics_students")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing student analytics: {e}", exc_info=True)
        text = "❌ Ошибка при загрузке аналитики ученика."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="analytics_students")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.VIEW_STATISTICS


async def show_group_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать групповую аналитику"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        # Получаем групповую аналитику
        analytics = await analyze_group_performance(user_id)

        text = "📊 <b>Групповая аналитика</b>\n\n"

        if analytics['total_students'] == 0:
            text += "У вас пока нет учеников с выполненными заданиями."
        else:
            text += (
                f"👥 <b>Учеников:</b> {analytics['total_students']}\n"
                f"📝 <b>Вопросов решено:</b> {analytics['total_correct']}/{analytics['total_questions']}\n"
                f"📈 <b>Общая успеваемость группы:</b> {analytics['group_accuracy']}%\n"
            )

            # Общие слабые темы группы
            if analytics['common_weak_topics']:
                text += "\n🔴 <b>Слабые темы группы (< 60%):</b>\n"
                for cwt in analytics['common_weak_topics'][:5]:
                    text += (
                        f"  • {cwt['topic']}: {cwt['accuracy']}% "
                        f"({cwt['students_affected']} уч.)\n"
                    )

            # Топ учеников
            if analytics['students_summary']:
                text += "\n🏆 <b>Рейтинг учеников:</b>\n"
                for i, student in enumerate(analytics['students_summary'][:5], 1):
                    emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
                    text += f"{emoji} {i}. {student['name']}: {student['accuracy']}%\n"

        keyboard = [
            [InlineKeyboardButton("👥 По ученикам", callback_data="analytics_students")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_statistics")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing group analytics: {e}", exc_info=True)
        text = "❌ Ошибка при загрузке групповой аналитики."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_statistics")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.VIEW_STATISTICS


async def show_student_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список учеников (legacy function)"""
    # Перенаправляем на новую функцию аналитики
    return await show_students_analytics(update, context)
