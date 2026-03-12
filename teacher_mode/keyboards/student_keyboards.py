"""
Клавиатуры для учеников.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_homework_list_keyboard(homeworks: list) -> InlineKeyboardMarkup:
    """Клавиатура со списком домашних заданий"""
    keyboard = []

    for hw in homeworks:
        keyboard.append([
            InlineKeyboardButton(
                f"📝 {hw['title']} ({hw['status']})",
                callback_data=f"homework_{hw['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")])

    return InlineKeyboardMarkup(keyboard)


def get_back_to_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню"""
    keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
    return InlineKeyboardMarkup(keyboard)
