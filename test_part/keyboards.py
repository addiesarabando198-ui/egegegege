# test_part/keyboards.py
from typing import List, Optional
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.universal_ui import AdaptiveKeyboards, UniversalUIComponents

# Импортируем общие утилиты
from .utils import TestPartCallbackData as CallbackData

try:
    from .topic_data import TOPIC_NAMES
except ImportError:
    logging.error("Не найден файл topic_data.py или словарь TOPIC_NAMES в нём.")
    TOPIC_NAMES: dict = {}

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню плагинов."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Тестовая часть", callback_data=CallbackData.get_plugin_entry("test_part")),
            InlineKeyboardButton("Задание 24", callback_data=CallbackData.get_plugin_entry("task24")),
        ]
    ])

def get_initial_choice_keyboard() -> InlineKeyboardMarkup:
    """Основная клавиатура выбора режима."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Режим экзамена (1-16)", callback_data="initial:exam_mode")],  # НОВАЯ КНОПКА
        [InlineKeyboardButton("📝 По номеру задания", callback_data="initial:select_exam_num")],
        [InlineKeyboardButton("📚 По блокам тем", callback_data="initial:select_block")],
        [InlineKeyboardButton("🎲 Случайные вопросы", callback_data="initial:select_random_all")],
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="test_mistakes")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="test_part_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

def get_exam_results_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для результатов экзамена."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Подробный разбор", callback_data="exam_detailed_review")],
        [InlineKeyboardButton("🔄 Пройти экзамен снова", callback_data="initial:exam_mode")],
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="test_mistakes")],
        [InlineKeyboardButton("🔙 К выбору режима", callback_data="to_test_part_menu")]
    ])

def get_blocks_keyboard(blocks: List[str]) -> Optional[InlineKeyboardMarkup]:
    """Создает клавиатуру для выбора блока."""
    if not blocks:
        return None
    
    buttons = []
    row = []
    
    for i, block in enumerate(blocks, 1):
        button = InlineKeyboardButton(
            text=block, 
            callback_data=f"block:select:{block}"
        )
        row.append(button)
        
        if i % 2 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        "⬅️ Назад", 
        callback_data="block:back_to_initial"
    )])
    
    return InlineKeyboardMarkup(buttons) 

def get_mode_keyboard(block_name: str) -> InlineKeyboardMarkup:
    """Выбор режима *внутри* конкретного блока."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайные из блока", callback_data="mode:random")],
        [InlineKeyboardButton("📚 По теме блока", callback_data="mode:choose_topic")],
        [InlineKeyboardButton("⬅️ Назад к блокам", callback_data="to_blocks")],
        [InlineKeyboardButton("🔙 К выбору режима", callback_data="to_test_part_menu")]
    ])

def get_topics_keyboard(block_name: str, topics: List[str]) -> Optional[InlineKeyboardMarkup]:
    """Создает клавиатуру для выбора темы."""
    if not topics:
        return None
    
    buttons = []
    
    # Создаем кнопки для тем
    for topic in topics:
        topic_display = TOPIC_NAMES.get(topic, topic)
        # Ограничиваем длину текста кнопки
        if len(topic_display) > 35:
            topic_display = topic_display[:32] + "..."
        
        buttons.append([InlineKeyboardButton(
            topic_display, 
            callback_data=f"topic:{topic}"
        )])
    
    # Кнопки навигации
    buttons.append([InlineKeyboardButton("⬅️ Назад к режиму", callback_data="to_mode")])
    buttons.append([InlineKeyboardButton("🔙 К выбору режима", callback_data="to_test_part_menu")])
    
    return InlineKeyboardMarkup(buttons)

def get_exam_num_keyboard(numbers: List[int]) -> Optional[InlineKeyboardMarkup]:
    """Создает клавиатуру для выбора номера задания ЕГЭ."""
    if not numbers:
        return None
    
    # Фильтруем только корректные номера (1-27 для ЕГЭ по обществознанию)
    valid_numbers = [n for n in numbers if 1 <= n <= 27]
    
    if not valid_numbers:
        return None
    
    buttons = []
    row = []
    
    for i, number in enumerate(sorted(valid_numbers), 1):
        button = InlineKeyboardButton(
            text=str(number),
            callback_data=f"exam_number:select:{number}"
        )
        row.append(button)
        
        # По 6 кнопок в ряд
        if i % 6 == 0:
            buttons.append(row)
            row = []
    
    # Добавляем оставшиеся кнопки
    if row:
        buttons.append(row)
    
    # Кнопка назад
    buttons.append([InlineKeyboardButton(
        "⬅️ Назад",
        callback_data="exam_number:back_to_initial"
    )])
    
    return InlineKeyboardMarkup(buttons)

def get_after_answer_keyboard(last_mode: str = "random") -> InlineKeyboardMarkup:
    """Клавиатура после проверки ответа."""
    # Определяем текст для кнопки "следующий"
    if last_mode == "topic":
        main_button = InlineKeyboardButton("➡️ Ещё вопрос по теме", callback_data=CallbackData.TEST_NEXT_TOPIC)
    elif last_mode == "exam_num":
        main_button = InlineKeyboardButton("➡️ Следующий номер", callback_data=CallbackData.TEST_NEXT_RANDOM)
    else:  # random
        main_button = InlineKeyboardButton("➡️ Ещё случайный", callback_data=CallbackData.TEST_NEXT_RANDOM)

    return InlineKeyboardMarkup([
        [main_button],
        [InlineKeyboardButton("🔄 Сменить тему / режим", callback_data=CallbackData.TEST_CHANGE_TOPIC)],
        [InlineKeyboardButton("🏠 Главное меню", callback_data=CallbackData.TEST_TO_MAIN_MENU)],
    ])

def get_exam_question_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для вопроса в режиме экзамена."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏭️ Пропустить вопрос", callback_data="exam_skip_question"),
            InlineKeyboardButton("❌ Прервать экзамен", callback_data="exam_abort")
        ]
    ])

def get_mistakes_nav_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура навигации по ошибкам."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➡️ Следующая ошибка",
                callback_data="test_next_continue",
            )
        ],
        [
            InlineKeyboardButton(
                "⏩ Пропустить",
                callback_data="skip_mistake",
            )
        ],
        [
            InlineKeyboardButton(
                "🚪 Закончить разбор",
                callback_data="test_mistake_finish",
            )
        ],
        [
            InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
        ],
    ])

def get_question_keyboard(mode: str) -> InlineKeyboardMarkup:
    """Клавиатура для активного вопроса с кнопкой пропуска."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ Пропустить вопрос", callback_data=f"skip_question:{mode}")]
    ])

def get_next_action_keyboard(last_mode: str, has_explanation: bool = False, exam_number: int = None) -> InlineKeyboardMarkup:
    """Клавиатура действий после ответа (ОСНОВНАЯ ВЕРСИЯ)."""
    keyboard = []
    
    # Первый ряд - основные действия
    first_row = []
    
    # Кнопка "Следующий вопрос"
    if last_mode == "topic":
        next_text = "➡️ Следующий вопрос по теме"
    elif last_mode == "exam_num":
        # ИСПРАВЛЕНИЕ: Добавляем номер задания если он передан
        if exam_number:
            next_text = f"➡️ Следующий вопрос №{exam_number}"
        else:
            next_text = "➡️ Следующий вопрос"
    elif last_mode == "block":
        next_text = "➡️ Следующий из блока"
    elif last_mode == "mistakes":
        next_text = "➡️ Следующая ошибка"
    else:  # random_all
        next_text = "➡️ Следующий случайный"
    
    first_row.append(
        InlineKeyboardButton(
            next_text, callback_data=CallbackData.TEST_NEXT_CONTINUE
        )
    )
    
    # Добавляем кнопку пояснения если есть (во второй ряд для лучшего размещения)
    keyboard.append(first_row)
    
    # Второй ряд - пояснение (если есть)
    if has_explanation:
        keyboard.append([
            InlineKeyboardButton(
                "💡 Показать пояснение",
                callback_data=CallbackData.TEST_NEXT_SHOW_EXPLANATION,
            )
        ])
    
    # Третий ряд - навигация
    nav_row = []
    
    if last_mode in ["topic", "exam_num", "block"]:
        nav_row.append(
            InlineKeyboardButton(
                "🔄 Сменить тему", 
                callback_data=CallbackData.TEST_NEXT_CHANGE_TOPIC
            )
        )
    else:
        nav_row.append(
            InlineKeyboardButton(
                "🔄 Сменить режим", 
                callback_data=CallbackData.TEST_NEXT_CHANGE_TOPIC
            )
        )
    
    keyboard.append(nav_row)
    
    # Четвертый ряд - главное меню
    keyboard.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_subscription_keyboard(channel: str) -> InlineKeyboardMarkup:
    """Клавиатура для проверки подписки."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подписаться", url=f"https://t.me/{channel.lstrip('@')}")],
        [InlineKeyboardButton("🔄 Я подписался", callback_data="check_subscription")]
    ])

def get_error_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для ошибок."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Попробовать снова", callback_data="to_test_part_menu")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

def get_stats_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для команды статистики с универсальными компонентами."""
    return AdaptiveKeyboards.create_progress_keyboard(
        has_detailed_stats=True,
        can_export=True,
        module_code="test"
    )

def get_progress_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для экрана прогресса."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Подробнее", callback_data="test_detailed_analysis"),
            InlineKeyboardButton("📥 Экспорт", callback_data="test_export_csv")
        ],
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="test_work_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="to_test_part_menu")]
    ])

def get_mistakes_finish_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура завершения работы над ошибками."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data="test_part_progress")],
        [InlineKeyboardButton("🎲 Случайные вопросы", callback_data="initial:select_random_all")],
        [InlineKeyboardButton("🔙 К выбору режима", callback_data="to_test_part_menu")]
    ])

def get_adaptive_result_keyboard(is_correct: bool, has_explanation: bool = False) -> InlineKeyboardMarkup:
    """Адаптивная клавиатура после ответа с использованием универсальных компонентов."""
    # Базовая адаптивная клавиатура
    kb = AdaptiveKeyboards.create_result_keyboard(
        score=1 if is_correct else 0,
        max_score=1,
        module_code="test"
    )
    
    # Адаптируем callback_data под test_part
    kb_list = list(kb.inline_keyboard)
    
    for row in kb_list:
        for button in row:
            # Маппинг универсальных callback на специфичные
            if "новое задание" in button.text.lower():
                button.callback_data = CallbackData.TEST_NEXT_CONTINUE
            elif "попробовать снова" in button.text.lower():
                button.callback_data = "test_retry"
            elif "мой прогресс" in button.text.lower():
                button.callback_data = "test_progress"
            elif "в меню" in button.text.lower() and button.callback_data != "to_main_menu":
                button.callback_data = "to_test_part_menu"
    
    # Добавляем кнопку пояснения если нужно
    if has_explanation:
        kb_list.insert(1, [InlineKeyboardButton(
            "💡 Показать пояснение",
            callback_data=CallbackData.TEST_NEXT_SHOW_EXPLANATION
        )])
    
    return InlineKeyboardMarkup(kb_list)
