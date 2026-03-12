import math
import html
from typing import List, Tuple, Optional, Set, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.universal_ui import AdaptiveKeyboards

def build_main_menu_keyboard(user_stats: Optional[Dict[str, Any]] = None) -> InlineKeyboardMarkup:
    """Создает унифицированную клавиатуру главного меню task24."""
    
    # Если статистика не передана, создаем пустую
    if user_stats is None:
        user_stats = {
            'total_attempts': 0,
            'average_score': 0,
            'streak': 0,
            'weak_topics_count': 0,
            'progress_percent': 0
        }
    
    # Используем адаптивную клавиатуру из core
    base_kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="task24")
    
    # Создаем новую клавиатуру с правильными callback_data для task24
    new_buttons = []
    
    for row in base_kb.inline_keyboard:
        new_row = []
        for button in row:
            # Маппинг стандартных callback на специфичные для task24
            if button.callback_data == "task24_practice":
                new_row.append(InlineKeyboardButton("💪 Тренироваться", callback_data="t24_train"))
            elif button.callback_data == "task24_theory":
                new_row.append(InlineKeyboardButton("📋 Критерии оценки", callback_data="t24_criteria"))
            elif button.callback_data == "task24_examples":
                new_row.append(InlineKeyboardButton("👀 Посмотреть эталоны", callback_data="t24_show"))
            elif button.callback_data == "task24_progress":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_progress"))
            elif button.callback_data == "task24_settings":
                # Добавляем поиск темы вместо настроек
                new_row.append(InlineKeyboardButton("🔍 Поиск темы", callback_data="t24_search"))
            elif button.callback_data == "task24_mistakes":
                # Пропускаем работу над ошибками, так как она не реализована
                continue
            elif button.callback_data == "task24_achievements":
                # Пропускаем достижения
                continue
            elif button.callback_data == "to_main_menu":
                new_row.append(button)  # Оставляем как есть
            else:
                new_row.append(button)
        
        if new_row:
            new_buttons.append(new_row)
    
    # Добавляем дополнительные специфичные для task24 кнопки
    additional_row = [InlineKeyboardButton("📜 Список всех тем", callback_data="t24_show_list")]
    
    # Вставляем перед последней строкой (где кнопка главного меню)
    if new_buttons and "to_main_menu" in str(new_buttons[-1]):
        new_buttons.insert(-1, additional_row)
    else:
        new_buttons.append(additional_row)
    
    return InlineKeyboardMarkup(new_buttons)

def build_progress_keyboard(practiced_indices: Set[int], total: int) -> InlineKeyboardMarkup:
    """Создает унифицированную клавиатуру с детальной статистикой прогресса."""
    completed = len(practiced_indices)
    progress = int(completed / total * 100) if total > 0 else 0
    
    # Визуальная шкала прогресса
    filled = "█" * (progress // 10)
    empty = "░" * (10 - progress // 10)
    progress_bar = f"{filled}{empty}"
    
    # Создаем кастомные кнопки для task24
    custom_buttons = [
        [InlineKeyboardButton(
            f"📊 Прогресс: {progress_bar} {progress}%",
            callback_data="show_detailed_progress"
        )],
        [
            InlineKeyboardButton(
                f"✅ Пройдено: {completed}",
                callback_data="show_completed"
            ),
            InlineKeyboardButton(
                f"📝 Осталось: {total - completed}",
                callback_data="show_remaining"
            )
        ]
    ]
    
    # Получаем базовую клавиатуру
    base_kb = AdaptiveKeyboards.create_progress_keyboard(
        has_detailed_stats=True,
        can_export=True,
        module_code="task24"
    )
    
    # Перестраиваем клавиатуру с новыми callback_data
    new_buttons = []
    
    # Добавляем кастомные кнопки вначале
    new_buttons.extend(custom_buttons)
    
    # Обрабатываем кнопки из базовой клавиатуры
    for row in base_kb.inline_keyboard:
        new_row = []
        for button in row:
            # Создаем новую кнопку с правильным callback_data
            if button.callback_data == "task24_detailed_progress":
                # Пропускаем, так как у нас уже есть кастомная кнопка детального прогресса
                continue
            elif button.callback_data == "task24_export":
                new_row.append(InlineKeyboardButton(button.text, callback_data="export_progress"))
            elif button.callback_data == "task24_menu":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_menu"))
            elif button.callback_data == "task24_reset_confirm":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_reset_progress"))
            elif button.callback_data == "task24_practice":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_train"))
            else:
                # Оставляем как есть
                new_row.append(InlineKeyboardButton(button.text, callback_data=button.callback_data))
        
        if new_row:  # Добавляем только непустые строки
            new_buttons.append(new_row)
    
    return InlineKeyboardMarkup(new_buttons)

def build_initial_choice_keyboard(mode: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для начального выбора способа поиска темы."""
    buttons = []
    
    if mode == 'train':
        buttons = [
            [InlineKeyboardButton("🎲 Случайная тема", callback_data="t24_nav_rnd:train")],
            [InlineKeyboardButton("📚 Выбрать из списка", callback_data="t24_nav_cb:train")],
            [InlineKeyboardButton("🔙 Назад", callback_data="t24_menu")]
        ]
    else:  # show mode
        buttons = [
            [InlineKeyboardButton("📖 Все темы", callback_data="t24_nav_all:show:0")],
            [InlineKeyboardButton("📚 По блокам", callback_data="t24_nav_cb:show")],
            [InlineKeyboardButton("🎲 Случайная тема", callback_data="t24_nav_rnd:show")],
            [InlineKeyboardButton("🔙 Назад", callback_data="t24_menu")]
        ]
    
    return InlineKeyboardMarkup(buttons)

def build_block_selection_keyboard(mode: str, plan_bot_data=None) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора блока тем с короткими callback_data."""
    buttons = []
    
    if not plan_bot_data or not hasattr(plan_bot_data, 'topics_by_block'):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Данные не загружены", callback_data="noop")
        ]])
    
    # Создаем кнопки для каждого блока
    for block_name in plan_bot_data.topics_by_block.keys():
        # Сокращаем блок до первых 20 символов для callback_data
        short_block = block_name[:20] if len(block_name) > 20 else block_name
        buttons.append([InlineKeyboardButton(
            block_name, 
            callback_data=f"t24_blk:{mode}:{short_block}"
        )])
    
    # Кнопка назад
    buttons.append([InlineKeyboardButton(
        "🔙 Назад", 
        callback_data=f"t24_nav_bc:{mode}"  # back_to_choice -> bc
    )])
    
    return InlineKeyboardMarkup(buttons)

def build_topic_page_keyboard(
    mode: str,
    page: int,
    data_source,
    practiced_set: Set[int],
    block_name: Optional[str] = None
) -> Tuple[str, InlineKeyboardMarkup]:
    """Создает постраничную клавиатуру тем с короткими callback_data."""
    per_page = 8
    
    # Проверяем data_source
    if not data_source or not hasattr(data_source, 'topic_list_for_pagination'):
        return "❌ Данные не загружены", InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Назад", callback_data="t24_menu")
        ]])
    
    # Получаем список тем
    if block_name and hasattr(data_source, 'topics_by_block'):
        topics = data_source.topics_by_block.get(block_name, [])
        header = f"📚 <b>Блок: {block_name}</b>\n\n"
    else:
        topics = data_source.topic_list_for_pagination
        header = "📚 <b>Все темы для планов</b>\n\n"
    
    if not topics:
        return "❌ Темы не найдены", InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Назад", callback_data=f"t24_nav_bc:{mode}")
        ]])
    
    # Пагинация
    total_pages = math.ceil(len(topics) / per_page)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(topics))
    page_topics = topics[start_idx:end_idx]
    
    # Формируем текст
    text = header
    for i, (idx, topic_name) in enumerate(page_topics, 1):
        marker = "✅ " if idx in practiced_set else "▫️ "
        text += f"{marker}{start_idx + i}. {topic_name}\n"
    
    text += f"\n📄 Страница {page + 1} из {total_pages}"
    
    # Кнопки тем
    buttons = []
    for idx, topic_name in page_topics:
        # Обрезаем название темы для отображения
        display_name = topic_name[:40] + "..." if len(topic_name) > 40 else topic_name
        callback_data = f"t24_t:{mode}:{idx}"  # topic -> t
        buttons.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
    
    # Навигация по страницам
    nav_row = []
    if page > 0:
        # Сокращаем callback_data для навигации
        if block_name:
            # Сокращаем имя блока
            short_block = block_name[:20]
            cb = f"t24_pg:b:{mode}:{page-1}:{short_block}"  # page:block
        else:
            cb = f"t24_pg:a:{mode}:{page-1}"  # page:all
        nav_row.append(InlineKeyboardButton("◀️", callback_data=cb))
    
    nav_row.append(InlineKeyboardButton(
        f"{page + 1}/{total_pages}", 
        callback_data="noop"
    ))
    
    if page < total_pages - 1:
        if block_name:
            short_block = block_name[:20]
            cb = f"t24_pg:b:{mode}:{page+1}:{short_block}"
        else:
            cb = f"t24_pg:a:{mode}:{page+1}"
        nav_row.append(InlineKeyboardButton("▶️", callback_data=cb))
    
    if nav_row:
        buttons.append(nav_row)
    
    # Кнопка назад
    buttons.append([InlineKeyboardButton(
        "🔙 Назад", 
        callback_data=f"t24_nav_bc:{mode}"
    )])
    
    return text, InlineKeyboardMarkup(buttons)

def build_search_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для поиска."""
    keyboard = [
        [InlineKeyboardButton("❌ Отмена", callback_data="t24_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_feedback_keyboard(score: int = 0, max_score: int = 4) -> InlineKeyboardMarkup:
    """Создает клавиатуру после проверки плана."""
    # Использовать адаптивную клавиатуру
    base_kb = AdaptiveKeyboards.create_result_keyboard(
        score=score,
        max_score=max_score,
        module_code="task24"
    )
    
    # Адаптируем callback_data для task24
    new_buttons = []
    
    for row in base_kb.inline_keyboard:
        new_row = []
        for button in row:
            # Маппинг callback_data
            if button.callback_data == "task24_retry":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_retry"))
            elif button.callback_data == "task24_new":
                new_row.append(InlineKeyboardButton(button.text, callback_data="next_topic"))
            elif button.callback_data == "task24_show_ideal":
                # Пропускаем, так как эталон уже показан
                continue
            elif button.callback_data == "task24_progress":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_progress"))
            elif button.callback_data == "task24_menu":
                new_row.append(InlineKeyboardButton(button.text, callback_data="t24_menu"))
            elif button.callback_data == "task24_theory":
                new_row.append(InlineKeyboardButton("📋 Критерии", callback_data="t24_criteria"))
            elif button.callback_data == "task24_examples":
                new_row.append(InlineKeyboardButton("👀 Эталоны", callback_data="t24_show"))
            else:
                new_row.append(button)
        
        if new_row:
            new_buttons.append(new_row)

    # Добавляем кнопку "Оспорить оценку" если оценка низкая (менее 60%)
    threshold = max_score * 0.6
    if score < threshold:
        # Вставляем перед последней строкой (обычно там "Главное меню")
        complaint_button = [InlineKeyboardButton("⚠️ Оспорить оценку", callback_data="t24_complaint")]
        if len(new_buttons) > 0:
            new_buttons.insert(-1, complaint_button)
        else:
            new_buttons.append(complaint_button)

    return InlineKeyboardMarkup(new_buttons)