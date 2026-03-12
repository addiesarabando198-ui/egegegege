"""
Клавиатуры для учителей.

ВАЖНО: Этот файл содержит вспомогательные функции для создания клавиатур.
Основное меню учителя строится inline в teacher_handlers.teacher_menu(),
так как требует динамической логики (проверка тарифа для показа кнопки "Подарить подписку").

Используйте эти функции для стандартных клавиатур, которые не требуют логики.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


def get_teacher_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Базовое главное меню учителя (без динамической логики).

    ВНИМАНИЕ: Рекомендуется использовать teacher_handlers.teacher_menu()
    для главного меню, так как там есть логика показа кнопки "Подарить подписку"
    в зависимости от тарифа учителя.

    Эта функция оставлена для обратной совместимости и простых случаев.
    """
    keyboard = [
        [InlineKeyboardButton("👥 Мои ученики", callback_data="teacher_students")],
        [InlineKeyboardButton("📋 Мои задания", callback_data="teacher_my_assignments")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="teacher_create_assignment")],
        [InlineKeyboardButton("📊 Статистика", callback_data="teacher_statistics")],
        [InlineKeyboardButton("🔍 Проверить работу", callback_data="quick_check_menu")],
        # Кнопка "Подарить подписку" НЕ включена, так как требует проверки тарифа
        # Используйте teacher_handlers.teacher_menu() для полного меню
        [InlineKeyboardButton("👤 Мой профиль", callback_data="teacher_profile")],
        [InlineKeyboardButton("◀️ Назад в главное меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_to_teacher_menu_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в меню учителя"""
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]]
    return InlineKeyboardMarkup(keyboard)
