import logging
import os
import io
import csv
import json
import random
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date
from core.document_processor import DocumentHandlerMixin
from core.vision_service import process_photo_message, process_photo_by_file_id, get_vision_service
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from core.admin_tools import admin_manager
from core import states, db
from core.plugin_loader import build_main_menu
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from core.states import (
    CHOOSING_MODE, 
    CHOOSING_BLOCK_T25,
    ANSWERING,
    ANSWERING_PARTS,
    SEARCHING,
    AWAITING_FEEDBACK,
    TASK25_WAITING
)
from .data_loader import get_data
from core.ui_helpers import (
    show_thinking_animation,
    show_extended_thinking_animation,
    show_ai_evaluation_animation,
    show_streak_notification,
    get_personalized_greeting,
    get_motivational_message,
    create_visual_progress
)
from core.error_handler import safe_handler, auto_answer_callback
from core.state_validator import validate_state_transition, state_validator
from core.migration import ensure_module_migration
from core.utils import safe_menu_transition

logger = logging.getLogger(__name__)

# Глобальные переменные
task25_data = get_data()
topic_selector = None
evaluator = None


if task25_data and task25_data.get('topics'):
    logger.info(f"✅ task25_data initialized with {len(task25_data['topics'])} topics")
else:
    logger.error("❌ task25_data is empty after import!")
# Импорты внутренних модулей ПОСЛЕ определения переменных
try:
    from .evaluator import Task25AIEvaluator, StrictnessLevel, EvaluationResult, AI_EVALUATOR_AVAILABLE
except ImportError as e:
    logger.error(f"Failed to import evaluator: {e}")
    AI_EVALUATOR_AVAILABLE = False
    StrictnessLevel = None
    EvaluationResult = None

try:
    from .cache import cache
except ImportError as e:
    logger.error(f"Failed to import cache: {e}")
    cache = None

try:
    from .utils import TopicSelector
except ImportError as e:
    logger.error(f"Failed to import utils: {e}")
    TopicSelector = None

async def delete_previous_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_message_id: Optional[int] = None):
    """Удаляет предыдущие сообщения диалога task25."""
    if not hasattr(context, 'bot') or not context.bot:
        logger.warning("Bot instance not available for message deletion")
        return

    # Список ключей с ID сообщений для удаления
    message_keys = [
        'task25_question_msg_id',   # Сообщение с вопросом
        'task25_answer_msg_id',     # Сообщение с ответом пользователя
        'task25_result_msg_id',     # Сообщение с результатом проверки
        'task25_thinking_msg_id'    # Сообщение "Анализирую..."
    ]

    messages_to_delete = []
    deleted_count = 0

    for key in message_keys:
        msg_id = context.user_data.get(key)
        if msg_id and msg_id != keep_message_id:
            messages_to_delete.append((key, msg_id))

    # Удаляем сообщения
    for key, msg_id in messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted_count += 1
            logger.debug(f"Deleted {key}: {msg_id}")
        except Exception as e:
            logger.debug(f"Failed to delete {key} {msg_id}: {e}")

    # Очищаем контекст
    for key in message_keys:
        context.user_data.pop(key, None)

    logger.info(f"Task25: Deleted {deleted_count}/{len(messages_to_delete)} messages")

def check_data_loaded():
    """Проверяет загрузку данных."""
    global task25_data
    if not task25_data or not task25_data.get('topics'):
        logger.error("task25_data is empty or not loaded!")
        return False
    return True

async def init_task25_data():
    """Инициализация данных для задания 25."""
    global task25_data, evaluator, topic_selector
    
    logger.info("Starting init_task25_data...")
    
    # Если данные уже загружены из data_loader, просто инициализируем дополнительные компоненты
    if task25_data and task25_data.get('topics'):
        logger.info(f"Data already loaded: {len(task25_data['topics'])} topics")
        
        # Инициализируем селектор
        if TopicSelector and task25_data['topics']:
            try:
                topic_selector = TopicSelector(task25_data['topics'])
                logger.info("TopicSelector initialized")
            except Exception as e:
                logger.warning(f"Failed to init TopicSelector: {e}")
        
        # Инициализируем evaluator
        _init_evaluator()
        
        return True
    
    # Если данных нет, пытаемся загрузить заново
    logger.warning("Data not pre-loaded, attempting to load...")
    from .data_loader import load_data_sync
    
    task25_data = load_data_sync()
    
    if task25_data and task25_data.get('topics'):
        logger.info(f"✅ Loaded {len(task25_data['topics'])} topics")
        
        # Инициализируем компоненты
        if TopicSelector:
            try:
                topic_selector = TopicSelector(task25_data['topics'])
            except Exception as e:
                logger.warning(f"Failed to init TopicSelector: {e}")
        
        _init_evaluator()
        return True
    else:
        logger.error("❌ Failed to load data")
        return False

def _init_evaluator():
    """Инициализация AI evaluator."""
    global evaluator
    
    if AI_EVALUATOR_AVAILABLE:
        try:
            strictness_level = StrictnessLevel[os.getenv('TASK25_STRICTNESS', 'STANDARD').upper()]
            logger.info(f"Using strictness level: {strictness_level.value}")
        except (KeyError, AttributeError):
            strictness_level = StrictnessLevel.STANDARD if StrictnessLevel else None
            logger.info("Using default strictness level: STANDARD")
        
        if strictness_level:
            try:
                evaluator = Task25AIEvaluator(strictness=strictness_level)
                logger.info(f"Task25 AI evaluator initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize AI evaluator: {e}", exc_info=True)
                evaluator = None
    else:
        logger.warning("AI evaluator not available for task25")
        evaluator = None

def _determine_block(title: str) -> str:
    """Определяет блок темы по названию."""
    if not title:
        return "Общие темы"
    
    title_lower = title.lower()
    
    # Ключевые слова для определения блоков
    if any(w in title_lower for w in ['человек', 'личность', 'общество', 'культур', 'мораль', 'познани']):
        return "Человек и общество"
    elif any(w in title_lower for w in ['экономик', 'рынок', 'деньг', 'предпринимат', 'бизнес', 'налог']):
        return "Экономика"
    elif any(w in title_lower for w in ['социальн', 'семь', 'группа', 'страт', 'класс', 'молодеж']):
        return "Социальная сфера"
    elif any(w in title_lower for w in ['политик', 'власть', 'государств', 'демократ', 'выбор', 'партии']):
        return "Политика"
    elif any(w in title_lower for w in ['прав', 'закон', 'юрид', 'суд', 'преступ', 'конституц']):
        return "Право"
    
    return "Общие темы"

async def cmd_t25status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса модуля task25."""
    global task25_data, topic_selector, evaluator
    
    text = "📊 <b>Статус модуля Task25:</b>\n\n"
    
    # Проверка данных
    if task25_data:
        text += "✅ <b>Данные загружены:</b>\n"
        text += f"• Всего тем: {len(task25_data.get('topics', []))}\n"
        text += f"• Блоков: {len(task25_data.get('blocks', {}))}\n"
        text += f"• По ID: {len(task25_data.get('topic_by_id', {}))}\n"
        
        # Примеры тем
        if task25_data.get('topics'):
            text += f"\n<b>Примеры тем:</b>\n"
            for topic in task25_data['topics'][:3]:
                text += f"• {topic.get('title', 'Без названия')}\n"
    else:
        text += "❌ <b>Данные НЕ загружены!</b>\n"
    
    # Проверка компонентов
    text += f"\n<b>Компоненты:</b>\n"
    text += f"• TopicSelector: {'✅' if topic_selector else '❌'}\n"
    text += f"• Evaluator: {'✅' if evaluator else '❌'}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_debug_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки загрузки данных (только для админов)."""
    global task25_data

    user_id = update.effective_user.id
    # Проверка на админа
    if not admin_manager.is_admin(user_id):
        await update.message.reply_text("❌ Недостаточно прав")
        return
    
    text = "🔍 <b>Диагностика task25_data:</b>\n\n"
    
    if task25_data:
        text += f"✅ Данные загружены\n"
        text += f"• Всего тем: {len(task25_data.get('topics', []))}\n"
        text += f"• Блоков: {len(task25_data.get('blocks', {}))}\n"
        text += f"• По ID: {len(task25_data.get('topic_by_id', {}))}\n"
        text += f"• Ключи: {list(task25_data.keys())}\n"
        
        if task25_data.get('blocks'):
            text += f"\n<b>Блоки:</b>\n"
            for block_name in list(task25_data['blocks'].keys())[:5]:
                count = len(task25_data['blocks'][block_name]['topics'])
                text += f"• {block_name}: {count} тем\n"
    else:
        text += "❌ Данные НЕ загружены\n"
        text += "task25_data is None или пустой dict\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

@safe_handler()
@validate_state_transition({ConversationHandler.END, None})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 25 из главного меню."""
    query = update.callback_query

    results = context.user_data.get('task25_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r.get('topic_id') for r in results)) / 100 * 100) if results else 0
    }

    greeting = get_personalized_greeting(user_stats)
    text = greeting + (
        "📝 <b>Задание 25 - Развёрнутый ответ</b>\n\n"
        "Задание проверяет умение:\n"
        "• Обосновывать теоретические положения\n"
        "• Отвечать на конкретные вопросы\n"
        "• Приводить развёрнутые примеры\n\n"
        "Максимальный балл: <b>6</b>\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t25_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t25_theory")],
        [InlineKeyboardButton("🏦 Банк ответов", callback_data="t25_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t25_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t25_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def cmd_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task25 - вход в задание 25."""
    
    # Автоматическая миграция данных при необходимости
    ensure_module_migration(context, 'task25', task25_data)
    
    text = (
        "📝 <b>Задание 25</b>\n\n"
        "Развёрнутый ответ с обоснованием и примерами.\n"
        "Максимальный балл: 6\n\n"
        "Выберите режим работы:"
    )
    
    # Получаем статистику пользователя
    results = context.user_data.get('task25_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r.get('topic_id') for r in results)) / 100 * 100) if results else 0
    }
    
    # Используем адаптивную клавиатуру
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t25")
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def list_by_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ тем по уровню сложности с пагинацией."""
    query = update.callback_query
    
    # Парсим callback_data: t25_list_by_diff:easy
    parts = query.data.split(':')
    difficulty = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0
    
    # Фильтруем темы по сложности
    all_topics = task25_data.get('topics', [])
    topics = [t for t in all_topics if t.get('difficulty', 'medium') == difficulty]
    
    if not topics:
        return states.CHOOSING_MODE
    
    # Пагинация - 10 тем на страницу
    items_per_page = 10
    total_pages = (len(topics) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(topics))
    
    # Названия уровней
    difficulty_names = {
        'easy': '🟢 Легкие темы',
        'medium': '🟡 Средние темы',
        'hard': '🔴 Сложные темы'
    }
    
    # Формируем текст
    text = f"<b>{difficulty_names.get(difficulty, 'Темы')}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    # Получаем прогресс пользователя
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = set(user_stats.get('topics_completed', []))
    
    # Список тем на текущей странице
    buttons = []
    for i in range(start_idx, end_idx):
        topic = topics[i]
        topic_id = topic.get('id')
        
        # Определяем эмодзи статуса
        if topic_id in completed_topics:
            status = "✅"
        else:
            status = "📝"
        
        # Блок темы
        block = topic.get('block', 'Общие')
        
        # Сокращаем название если слишком длинное
        title = topic.get('title', 'Без названия')
        if len(title) > 30:
            title = title[:27] + "..."
        
        button_text = f"{status} {title}"
        buttons.append([InlineKeyboardButton(
            button_text,
            callback_data=f"t25_topic:{topic_id}"
        )])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t25_list_by_diff:{difficulty}:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t25_list_by_diff:{difficulty}:{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("⬅️ К уровням", callback_data="t25_all_topics_list")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики."""
    query = update.callback_query
    
    # Проверяем загрузку данных
    if not task25_data or not task25_data.get('topics'):
        logger.warning("Task25 data not loaded when accessing practice mode")
        
        # Пытаемся перезагрузить данные
        await query.answer("⏳ Загружаю данные...", show_alert=False)
        await init_task25_data()
        
        # Проверяем еще раз после попытки загрузки
        if not task25_data or not task25_data.get('topics'):
            text = """💪 <b>Режим практики</b>

❌ <b>Данные заданий не загружены</b>

<b>Проблема:</b>
Не удалось загрузить темы для практики.

<b>Возможные причины:</b>
• Отсутствует файл task25/task25_topics.json
• Файл содержит ошибки или пустой
• Проблемы с доступом к файлу

<b>Что делать:</b>
1. Убедитесь, что файл существует и доступен
2. Проверьте корректность JSON-структуры
3. Перезапустите бота

Обратитесь к администратору для решения проблемы."""
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t25_practice")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
            ])
            
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return states.CHOOSING_MODE
    
    # Если данные загружены, продолжаем
    return await choose_practice_mode(update, context)


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим теории и советов."""
    query = update.callback_query
    
    text = (
        "📚 <b>Теория по заданию 25</b>\n\n"
        "<b>Структура ответа:</b>\n"
        "1️⃣ <b>Обоснование (К1)</b> - 2 балла\n"
        "• Несколько предложений с теоретической аргументацией\n"
        "• Объяснение причинно-следственных связей\n"
        "• Опора на обществоведческие знания\n\n"
        
        "2️⃣ <b>Ответ на вопрос (К2)</b> - 1 балл\n"
        "• Чёткий и конкретный ответ\n"
        "• Полное соответствие поставленному вопросу\n\n"
        
        "3️⃣ <b>Примеры (К3)</b> - 3 балла\n"
        "• Три развёрнутых примера (по 1 баллу)\n"
        "• Конкретные ситуации из жизни РФ\n"
        "• Детали: имена, даты, места\n\n"
        
        "<b>💡 Советы:</b>\n"
        "• Внимательно читайте все части задания\n"
        "• Следите за логикой изложения\n"
        "• Используйте термины корректно\n"
        "• Проверяйте фактическую точность"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Примеры ответов", callback_data="t25_example_answers")],
        [InlineKeyboardButton("⚠️ Типичные ошибки", callback_data="t25_common_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})  # Изменено с CHOOSING_BLOCK
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем с улучшенным отображением."""
    query = update.callback_query
    
    # Проверяем загрузку данных
    if not task25_data or not task25_data.get('topics_by_block'):
        logger.warning("No blocks data available")
        await query.answer("❌ Данные не загружены", show_alert=True)
        return await practice_mode(update, context)
    
    blocks_data = task25_data.get('topics_by_block', {})
    
    if not blocks_data:
        text = "📚 <b>Выбор блока</b>\n\n❌ Блоки тем не найдены."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")]
        ])
    else:
        text = "📚 <b>Выбор блока</b>\n\nВыберите блок для практики:"
        
        buttons = []
        
        # Создаем кнопки для каждого блока
        for block_name, topics in blocks_data.items():
            # Получаем статистику по блоку
            user_stats = context.user_data.get('task25_stats', {})
            completed_topics = set(user_stats.get('topics_completed', []))
            completed_in_block = len([t for t in topics if t.get('id') in completed_topics])
            
            button_text = f"{block_name} ({completed_in_block}/{len(topics)})"
            buttons.append([InlineKeyboardButton(
                button_text,
                callback_data=f"t25_block:{block_name}"
            )])
        
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
        kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK_T25

@safe_handler()
async def by_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Алиас для select_block."""
    return await select_block(update, context)

@safe_handler()
async def another_topic_from_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Другая тема из текущего контекста (блок, сложность или все)."""
    query = update.callback_query
    
    # Проверяем, откуда пришел пользователь
    selected_block = context.user_data.get("selected_block")
    selected_difficulty = context.user_data.get("selected_difficulty")
    
    if selected_block:
        # Если был выбран блок, показываем случайную из блока
        return await random_topic_block(update, context)
    elif selected_difficulty:
        # Если была выбрана сложность, выбираем новую тему той же сложности
        if topic_selector:
            user_id = update.effective_user.id
            topic = topic_selector.get_topic_by_difficulty(user_id, selected_difficulty)
        else:
            topics = [t for t in task25_data.get('topics', []) 
                     if t.get('difficulty', 'medium') == selected_difficulty]
            topic = random.choice(topics) if topics else None
        
        if not topic:
            return states.CHOOSING_MODE
        
        # Сохраняем тему
        context.user_data['current_topic'] = topic
        
        # Показываем тему
        from .utils import format_topic_for_display
        topic_text = format_topic_for_display(topic)
        
        # Добавляем кнопки навигации
        kb = InlineKeyboardMarkup(_get_navigation_buttons(context))
        
        await query.edit_message_text(
            f"{topic_text}\n\n"
            "📝 <b>Напишите развёрнутый ответ:</b>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.ANSWERING
    else:
        # Иначе случайную из всех
        return await random_topic_all(update, context)

def _get_navigation_buttons(context: ContextTypes.DEFAULT_TYPE) -> List[List[InlineKeyboardButton]]:
    """Определяет кнопки навигации в зависимости от контекста."""
    buttons = []
    
    # Кнопка "Другая тема" всегда присутствует
    buttons.append([InlineKeyboardButton("🎲 Другая тема", callback_data="t25_another_topic")])
    
    # Определяем кнопку "Назад" в зависимости от контекста
    selected_block = context.user_data.get("selected_block")
    selected_difficulty = context.user_data.get("selected_difficulty")
    
    if selected_block:
        # Если выбран блок
        buttons.append([InlineKeyboardButton("⬅️ К блоку", callback_data=f"t25_block:{selected_block}")])
    elif selected_difficulty:
        # Если выбрана сложность
        buttons.append([InlineKeyboardButton("⬅️ К сложности", callback_data="t25_by_difficulty")])
    else:
        # По умолчанию - к практике
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
    
    return buttons



@safe_handler()
async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню конкретного блока."""
    query = update.callback_query
    
    block_name = query.data.split(":", 1)[1]
    context.user_data["selected_block"] = block_name
    
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    # Статистика по блоку
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = set(user_stats.get('topics_completed', []))
    completed_in_block = len([t for t in topics if t.get('id') in completed_topics])
    
    text = f"📚 <b>Блок: {block_name}</b>\n"
    text += f"✅ Выполнено: {completed_in_block}/{len(topics)} тем\n\n"
    text += "Выберите действие:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список тем", callback_data=f"t25_list_topics:page:0")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_block")],
        [InlineKeyboardButton("⬅️ К блокам", callback_data="t25_select_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK_T25


def _build_topic_message(topic: Dict) -> str:
    """Формирует текст сообщения с заданием по теме."""
    text = "📝 <b>Задание 25</b>\n\n"
    
    # Информация о теме
    text += f"<b>Тема:</b> {topic.get('title', 'Не указана')}\n"
    text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n"
    
    # Сложность
    if 'difficulty' in topic:
        diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(topic['difficulty'], "⚪")
        diff_text = {"easy": "Лёгкая", "medium": "Средняя", "hard": "Сложная"}.get(topic['difficulty'], topic['difficulty'])
        text += f"<b>Сложность:</b> {diff_emoji} {diff_text}\n"
    
    text += "\n"
    
    # Текст задания
    if 'parts' in topic:
        parts = topic['parts']
        text += "<b>Ваше задание:</b>\n\n"
        
        if 'part1' in parts:
            text += f"<b>1.</b> {parts['part1']}\n\n"
        
        if 'part2' in parts:
            text += f"<b>2.</b> {parts['part2']}\n\n"
        
        if 'part3' in parts:
            text += f"<b>3.</b> {parts['part3']}\n\n"
    else:
        text += f"<b>Задание:</b>\n{topic.get('task_text', 'Текст задания не указан')}\n\n"
    
    # Требования
    text += "📋 <b>Требования к ответу:</b>\n"
    text += "1️⃣ Развёрнутое обоснование (2 балла)\n"
    text += "2️⃣ Точный ответ на вопрос (1 балл)\n"
    text += "3️⃣ Три конкретных примера (3 балла)\n\n"
    
    text += "💡 <i>Отправьте развёрнутый ответ одним сообщением</i>"
    
    return text


@safe_handler()
async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из всех с правильными кнопками."""
    query = update.callback_query

    # Удаляем предыдущие сообщения перед показом нового вопроса
    await delete_previous_messages(context, query.message.chat_id)

    topics = task25_data.get("topics", [])
    if not topics:
        return states.CHOOSING_MODE
    
    # Приоритет непройденным темам
    user_stats = context.user_data.get('task25_stats', {})
    completed = set(user_stats.get('topics_completed', []))
    
    uncompleted = [t for t in topics if t.get('id') not in completed]
    topic_pool = uncompleted if uncompleted else topics
    
    topic = random.choice(topic_pool)
    context.user_data['current_topic'] = topic
    
    # Очищаем выбранный блок, так как выбрана случайная тема из всех
    context.user_data.pop('selected_block', None)
    
    text = _build_topic_message(topic)
    
    # Проверяем режим ответа
    settings = context.user_data.get('task25_settings', {})
    
    if settings.get('answer_mode') == 'parts':
        # Начинаем режим по частям
        context.user_data['current_part'] = 1
        context.user_data['part_answers'] = {}
        
        parts = topic.get('parts', {})
        part1_text = parts.get('part1', '')
        
        text = (
            f"📝 <b>Режим ответа по частям</b>\n\n"
            f"<b>Тема:</b> {topic['title']}\n\n"
            f"<b>Часть 1: Обоснование (2 балла)</b>\n\n"
            f"{part1_text}\n\n"
            f"💡 <i>Отправьте ваше обоснование</i>"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="t25_practice")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )

        # Сохраняем ID сообщения с вопросом
        context.user_data['task25_question_msg_id'] = query.message.message_id

        return ANSWERING_PARTS
    else:
        # Стандартный режим
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Другая тема", callback_data="t25_another_topic")],
            [InlineKeyboardButton("⬅️ К выбору", callback_data="t25_practice")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )

        # Сохраняем ID сообщения с вопросом
        context.user_data['task25_question_msg_id'] = query.message.message_id

        return states.ANSWERING

def _get_fallback_feedback(user_answer: str, topic: Dict) -> str:
    """Формирует базовую обратную связь без AI."""
    score = _estimate_score(user_answer)
    
    text = f"📊 <b>Результаты проверки</b>\n\n"
    text += f"<b>Тема:</b> {topic.get('title', 'Не указана')}\n"
    text += f"{'─' * 30}\n\n"
    
    # Примерная оценка
    text += f"<b>Предварительная оценка:</b> {score}/6 баллов\n\n"
    
    if score >= 5:
        text += "✅ Ваш ответ выглядит полным и развёрнутым.\n"
    elif score >= 3:
        text += "⚡ Ответ содержит основные элементы, но может быть улучшен.\n"
    else:
        text += "📝 Рекомендуется дополнить ответ.\n"
    
    text += "\n<b>Общие рекомендации:</b>\n"
    text += "• Убедитесь, что есть теоретическое обоснование\n"
    text += "• Проверьте наличие ответа на поставленный вопрос\n"
    text += "• Приведите 3 примера из разных источников\n"
    text += "\n⚠️ <i>Это предварительная оценка. Для точной проверки обратитесь к преподавателю.</i>"
    
    return text

async def safe_handle_answer_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасная обработка ответа на задание 25."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Проверяем наличие текста из документа
    if 'document_text' in context.user_data:
        user_answer = context.user_data.pop('document_text')
        logger.info("Using text from document")
    else:
        user_answer = update.message.text.strip()
        logger.info("Using text from message")

    # Сохраняем ID сообщения с ответом пользователя
    context.user_data['task25_answer_msg_id'] = update.message.message_id

    # Проверяем минимальную длину
    if len(user_answer) < 100:
        await update.message.reply_text(
            "❌ Ответ слишком короткий. Задание 25 требует развёрнутого ответа с обоснованием и примерами.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отменить", callback_data="t25_menu")
            ]])
        )
        return states.ANSWERING

    # Проверка лимитов AI-проверок
    freemium_manager = context.bot_data.get('freemium_manager')
    user_id = update.effective_user.id

    # ========== ОБНОВЛЕНИЕ ДНЕВНОГО СТРИКА ==========
    # Обновляем дневной стрик (если еще не обновлен сегодня)
    current_date = date.today().isoformat()
    last_activity_date = context.user_data.get('last_activity_date')

    if last_activity_date != current_date:
        daily_current, daily_max = await db.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date
        logger.info(f"[Task25] Daily streak updated for user {user_id}: {daily_current}/{daily_max}")

    is_premium = False

    if freemium_manager:
        can_use, remaining, limit_msg = await freemium_manager.check_ai_limit(user_id, 'task25')

        if not can_use:
            # Показываем улучшенный paywall с CTA
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Попробовать за 1₽", callback_data="subscribe_start")],
                [InlineKeyboardButton("💎 Оформить подписку", callback_data="subscribe_start")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ])

            await update.message.reply_text(
                limit_msg,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return states.ANSWERING

        # Получаем информацию о подписке для дифференциации фидбека
        limit_info = await freemium_manager.get_limit_info(user_id, 'task25')
        is_premium = limit_info.get('is_premium', False)

    # Показываем анимацию обработки
    thinking_msg = await show_ai_evaluation_animation(
        update.message,
        duration=45  # 45 секунд для task25 (сложнее)
    )

    # Сохраняем ID сообщения "думаю"
    context.user_data['task25_thinking_msg_id'] = thinking_msg.message_id

    try:    
        # Инициализируем evaluator если нужно
        global evaluator
        if evaluator is None and AI_EVALUATOR_AVAILABLE:
            try:
                strictness = StrictnessLevel.STANDARD
                evaluator = Task25AIEvaluator(strictness=strictness)
                logger.info("Task25 evaluator initialized")
            except Exception as e:
                logger.error(f"Failed to initialize evaluator: {e}")
                evaluator = None
        
        # Оцениваем ответ
        if evaluator and AI_EVALUATOR_AVAILABLE:
            try:
                result = await evaluator.evaluate(
                    answer=user_answer,
                    topic=topic,
                    user_id=update.effective_user.id
                )

                # Форматируем результат с учетом подписки
                if hasattr(result, 'format_feedback'):
                    detailed_feedback = result.format_feedback()
                else:
                    detailed_feedback = _format_evaluation_result(result, topic)

                score = result.total_score

                # Дифференцируем фидбек для freemium vs premium
                if is_premium:
                    feedback_text = detailed_feedback
                else:
                    # Упрощенный фидбек для freemium пользователей
                    if freemium_manager:
                        feedback_text = freemium_manager.simplify_feedback_for_freemium(
                            detailed_feedback,
                            score,
                            6  # max_score для task25
                        )
                    else:
                        feedback_text = detailed_feedback
                
            except Exception as e:
                logger.error(f"Evaluation error: {e}")
                # Fallback оценка
                feedback_text = _get_fallback_feedback(user_answer, topic)
                score = _estimate_score(user_answer)
        else:
            # Простая оценка без AI
            feedback_text = _get_fallback_feedback(user_answer, topic)
            score = _estimate_score(user_answer)
        
        # Удаляем анимацию
        await thinking_msg.delete()

        # Регистрируем использование AI-проверки
        if freemium_manager:
            # ИСПРАВЛЕНО: Используем прямой вызов БД вместо use_ai_check
            # чтобы избежать двойной проверки лимита
            from core import db
            await db.increment_ai_check_usage(user_id)

            # Получаем информацию об остатке
            limit_info = await freemium_manager.get_limit_info(user_id, 'task25')
            remaining_checks = limit_info.get('checks_remaining', 0)

            # Добавляем информацию о лимите к feedback
            if not limit_info.get('is_premium') and remaining_checks <= 3:
                if remaining_checks > 0:
                    feedback_text += f"\n\n📊 Осталось проверок сегодня: <b>{remaining_checks}</b>"
                else:
                    feedback_text += f"\n\n⏳ Бесплатные проверки на сегодня исчерпаны. Лимит обновится завтра."

        # Сохраняем результат
        result_data = {
            'topic_title': topic.get('title', 'Неизвестная тема'),  # Изменить ключ
            'topic_id': topic.get('id'),
            'block': topic.get('block', 'Общие темы'),  # Исправить значение по умолчанию
            'score': score,
            'max_score': 6,
            'timestamp': datetime.now().isoformat()
        }
        
        if 'task25_results' not in context.user_data:
            context.user_data['task25_results'] = []
        context.user_data['task25_results'].append(result_data)
        
        # Обновляем серию правильных ответов
        if score >= 5:  # Считаем хорошим результатом 5+ баллов
            context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
            
            # Показываем уведомление о серии
            if context.user_data['correct_streak'] % 3 == 0:
                await show_streak_notification(
                    update.message,
                    context.user_data['correct_streak']
                )
        else:
            context.user_data['correct_streak'] = 0
        
        # Кнопки действий
        kb = AdaptiveKeyboards.create_result_keyboard(
            score=score,
            max_score=6,
            module_code="t25"
        )

        # Отправляем результат
        result_msg = await update.message.reply_text(
            feedback_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )

        # Обновляем ID - теперь это сообщение с результатом
        context.user_data.pop('task25_thinking_msg_id', None)
        context.user_data['task25_result_msg_id'] = result_msg.message_id

        # Меняем состояние на AWAITING_FEEDBACK для обработки дальнейших действий
        return states.AWAITING_FEEDBACK
        
    except Exception as e:
        logger.error(f"Error in handle_answer: {e}")
        await thinking_msg.delete()
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t25_retry"),
                InlineKeyboardButton("📝 В меню", callback_data="t25_menu")
            ]])
        )
        return states.CHOOSING_MODE


def _estimate_score(user_answer: str) -> int:
    """Примерная оценка без AI."""
    parts = user_answer.split('\n\n')
    if len(parts) >= 3:
        return 3  # Средний балл
    elif len(parts) >= 2:
        return 2
    else:
        return 1
        
@safe_handler()
@validate_state_transition({ANSWERING_PARTS})
async def handle_answer_parts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа по частям."""
    
    # Получаем текст из документа или сообщения
    if 'document_text' in context.user_data:
        user_answer = context.user_data.pop('document_text')
    else:
        user_answer = update.message.text
    
    topic = context.user_data.get('current_topic')
    current_part = context.user_data.get('current_part', 1)
    answers = context.user_data.get('part_answers', {})
    
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE
    
    # Сохраняем ответ на текущую часть
    answers[f'part{current_part}'] = user_answer
    context.user_data['part_answers'] = answers
    
    # Переходим к следующей части или завершаем
    if current_part < 3:
        current_part += 1
        context.user_data['current_part'] = current_part
        
        # Показываем следующую часть
        parts = topic.get('parts', {})
        part_text = parts.get(f'part{current_part}', '')
        
        part_names = {
            2: "Ответ на вопрос",
            3: "Примеры"
        }
        
        text = (
            f"✅ Часть {current_part - 1} получена!\n\n"
            f"<b>Часть {current_part}: {part_names.get(current_part, '')}</b>\n\n"
            f"{part_text}\n\n"
            f"💡 <i>Отправьте ваш ответ</i>"
        )
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML
        )
        
        return ANSWERING_PARTS  # Используем константу из states
    
    else:
        # Все части собраны, объединяем и проверяем
        full_answer = "\n\n".join([
            f"Часть 1 (Обоснование):\n{answers.get('part1', '')}",
            f"Часть 2 (Ответ):\n{answers.get('part2', '')}",
            f"Часть 3 (Примеры):\n{answers.get('part3', '')}"
        ])
        
        # Очищаем временные данные
        context.user_data.pop('part_answers', None)
        context.user_data.pop('current_part', None)
        
        # Сохраняем полный ответ в context вместо изменения message.text
        context.user_data['document_text'] = full_answer
        
        # Вызываем стандартную функцию проверки
        return await safe_handle_answer_task25(update, context)


def _format_evaluation_result(result: EvaluationResult, topic: Dict) -> str:
    """Форматирует результат AI-оценки для отображения."""
    score = result.total_score
    max_score = result.max_score
    
    # Заголовок в зависимости от результата
    if score >= 5:
        header = "🎉 <b>Отличный результат!</b>"
    elif score >= 3:
        header = "👍 <b>Хороший ответ!</b>"
    else:
        header = "📝 <b>Нужно доработать</b>"
    
    text = f"{header}\n\n"
    text += f"<b>Ваш балл:</b> {score} из {max_score}\n\n"
    
    # Детальная разбивка по критериям
    if hasattr(result, 'criteria_scores') and result.criteria_scores:
        text += "<b>📊 Детальная оценка:</b>\n"
        text += f"• К1 (Обоснование): {result.criteria_scores.get('k1_score', 0)}/2\n"
        text += f"• К2 (Ответ на вопрос): {result.criteria_scores.get('k2_score', 0)}/1\n"
        text += f"• К3 (Примеры): {result.criteria_scores.get('k3_score', 0)}/3\n\n"
    
    # Обратная связь
    if result.feedback:
        text += f"<b>💭 Комментарий:</b>\n{result.feedback}\n\n"
    
    # ИСПРАВЛЕНО: используем правильное имя атрибута detailed_feedback
    if hasattr(result, 'detailed_feedback') and result.detailed_feedback:
        detail = result.detailed_feedback
        if isinstance(detail, dict):
            if detail.get('k1_comment'):
                text += f"<b>📌 Обоснование:</b> {detail['k1_comment']}\n"
            if detail.get('k2_comment'):
                text += f"<b>📌 Ответ:</b> {detail['k2_comment']}\n"
            if detail.get('k3_comment'):
                text += f"<b>📌 Примеры:</b> {detail['k3_comment']}\n"
            
            # Найденные примеры
            if detail.get('k3_examples_found'):
                examples = detail['k3_examples_found']
                if examples and isinstance(examples, list):
                    text += "\n<b>Найденные примеры:</b>\n"
                    for i, ex in enumerate(examples[:3], 1):
                        text += f"{i}. {ex}\n"
    
    # Рекомендации
    if hasattr(result, 'suggestions') and result.suggestions:
        text += "\n<b>💡 Рекомендации:</b>\n"
        for suggestion in result.suggestions[:3]:
            text += f"• {suggestion}\n"
    
    # Фактические ошибки
    if hasattr(result, 'factual_errors') and result.factual_errors:
        text += "\n<b>⚠️ Фактические ошибки:</b>\n"
        for error in result.factual_errors[:3]:
            text += f"• {error}\n"
    
    return text.strip()


@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после получения результата."""
    query = update.callback_query
    
    action = query.data.split('_')[-1]
    
    # Используем универсальные callback_data
    if action == 'retry':
        return await handle_retry(update, context)
    elif action == 'new':
        return await random_topic_all(update, context)
    elif action == 'theory':
        return await theory_mode(update, context)
    elif action == 'examples':
        # Функция bank_examples пока не реализована, используем search_examples
        return await search_examples(update, context)
    elif action == 'menu':
        return await return_to_menu(update, context)
    
    return states.CHOOSING_MODE


@safe_handler()
async def search_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска примеров."""
    query = update.callback_query
    
    text = (
        "🔍 <b>Поиск примеров</b>\n\n"
        "Отправьте ключевые слова для поиска.\n"
        "Например: <i>семья, экономика, право</i>\n\n"
        "Для отмены нажмите кнопку ниже:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t25_examples")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Устанавливаем флаг ожидания поиска
    context.user_data['waiting_for_search'] = True
    
    return states.SEARCHING

@safe_handler()
async def examples_by_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры по блокам."""
    query = update.callback_query
    
    if not check_data_loaded():
        await query.answer("❌ Данные не загружены", show_alert=True)
        await query.edit_message_text(
            "❌ <b>Ошибка загрузки данных</b>\n\n"
            "Попробуйте позже или обратитесь к администратору.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")
            ]])
        )
        return states.CHOOSING_MODE
    
    blocks = task25_data.get("topics_by_block", {})
    
    # Фильтруем блоки с примерами
    blocks_with_examples = {}
    for block_name, topics in blocks.items():
        topics_with_ex = [t for t in topics if 'example_answers' in t]
        if topics_with_ex:
            blocks_with_examples[block_name] = topics_with_ex
    
    if not blocks_with_examples:
        text = "📚 <b>Примеры по блокам</b>\n\n"
        text += "❌ В базе нет тем с примерами ответов.\n\n"
        text += "<i>Администратор уведомлен о проблеме.</i>"
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")
        ]])
    else:
        text = "📚 <b>Примеры по блокам</b>\n\n"
        text += f"Найдено блоков: {len(blocks_with_examples)}\n\n"
        text += "Выберите блок:"
        
        buttons = []
        for block_name, topics in blocks_with_examples.items():
            buttons.append([InlineKeyboardButton(
                f"{block_name} ({len(topics)} тем)",
                callback_data=f"t25_examples_block:{block_name}"
            )])
        
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")])
        kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE


@safe_handler()
async def best_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ лучших примеров."""
    query = update.callback_query
    
    if not check_data_loaded():
        await query.answer("❌ Данные не загружены", show_alert=True)
        await query.edit_message_text(
            "❌ <b>Ошибка загрузки данных</b>\n\n"
            "Попробуйте позже или обратитесь к администратору.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Фильтруем темы с примерами
    import random
    topics_with_examples = [
        t for t in task25_data.get('topics', [])
        if 'example_answers' in t
    ]
    
    if not topics_with_examples:
        text = "⭐ <b>Лучшие примеры ответов</b>\n\n"
        text += "❌ В базе пока нет тем с примерами.\n\n"
        text += "<i>Администратор уведомлен о проблеме.</i>"
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")
        ]])
    else:
        sample_topics = random.sample(
            topics_with_examples,
            min(5, len(topics_with_examples))
        )
        
        text = "⭐ <b>Лучшие примеры ответов</b>\n\n"
        text += f"Показано {len(sample_topics)} из {len(topics_with_examples)}:\n\n"
        
        buttons = []
        for i, topic in enumerate(sample_topics, 1):
            text += f"{i}. {topic.get('title', 'Без названия')[:50]}\n"
            buttons.append([InlineKeyboardButton(
                f"👁 Пример {i}",
                callback_data=f"t25_show_example:{topic['id']}"
            )])
        
        buttons.append([InlineKeyboardButton("🔄 Другие", callback_data="t25_best_examples")])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")])
        
        kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE

@safe_handler()
async def show_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ примера ответа с навигацией."""
    query = update.callback_query
    
    # Извлекаем ID темы
    topic_id = query.data.split(':')[1]
    
    # Находим тему по ID
    topic = None
    for t in task25_data.get('topics', []):
        if str(t.get('id')) == str(topic_id):
            topic = t
            break
    
    if not topic or 'example_answers' not in topic:
        await query.answer("Пример не найден", show_alert=True)
        return states.CHOOSING_MODE
    
    # Форматируем текст примера
    text = f"📝 <b>Пример эталонного ответа</b>\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n\n"
    
    # Показываем задание
    if 'task_text' in topic:
        text += f"<b>Задание:</b>\n{topic['task_text']}\n\n"
    elif 'parts' in topic:
        text += "<b>Задание:</b>\n"
        parts = topic['parts']
        if parts.get('part1'):
            text += f"1) {parts['part1']}\n"
        if parts.get('part2'):
            text += f"2) {parts['part2']}\n"
        if parts.get('part3'):
            text += f"3) {parts['part3']}\n"
        text += "\n"
    
    # Показываем эталонный ответ
    example = topic['example_answers']
    text += "<b>Эталонный ответ:</b>\n\n"
    
    # Обработка разных форматов ответов
    if isinstance(example, dict):
        if 'part1' in example:
            if isinstance(example['part1'], dict):
                text += f"<b>1. Обоснование (2 балла):</b>\n{example['part1'].get('answer', example['part1'])}\n\n"
            else:
                text += f"<b>1. Обоснование (2 балла):</b>\n{example['part1']}\n\n"
        
        if 'part2' in example:
            if isinstance(example['part2'], dict):
                text += f"<b>2. Ответ на вопрос (1 балл):</b>\n{example['part2'].get('answer', example['part2'])}\n\n"
            else:
                text += f"<b>2. Ответ на вопрос (1 балл):</b>\n{example['part2']}\n\n"
        
        if 'part3' in example:
            text += "<b>3. Примеры (3 балла):</b>\n"
            if isinstance(example['part3'], list):
                for i, ex in enumerate(example['part3'], 1):
                    if isinstance(ex, dict):
                        text += f"\n{i}) <b>{ex.get('type', 'Пример')}:</b>\n{ex.get('example', ex)}\n"
                    else:
                        text += f"\n{i}) {ex}\n"
            else:
                text += f"{example['part3']}\n"
    
    # Кнопки действий
    buttons = []
    
    # Кнопка "Попробовать эту тему"
    buttons.append([InlineKeyboardButton(
        "📝 Попробовать эту тему",
        callback_data=f"t25_topic:{topic['id']}"
    )])
    
    # Навигация по блоку
    block_name = topic.get('block')
    if block_name:
        buttons.append([InlineKeyboardButton(
            f"📚 Другие темы из блока «{block_name}»",
            callback_data=f"t25_examples_block:{block_name}"
        )])
    
    # Возврат в меню
    buttons.extend([
        [InlineKeyboardButton("🔍 Поиск примеров", callback_data="t25_search_examples")],
        [InlineKeyboardButton("⬅️ К банку примеров", callback_data="t25_examples")]
    ])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def example_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры ответов в теории - вызывается из состояния CHOOSING_MODE."""
    query = update.callback_query
    
    # Вызываем функцию best_examples для показа примеров
    return await best_examples(update, context)


@safe_handler()
async def common_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Типичные ошибки."""
    query = update.callback_query
    
    text = """⚠️ <b>Типичные ошибки в задании 25</b>

<b>1. Обоснование (К1)</b>
❌ Отсутствие теоретических понятий
❌ Несоответствие обоснования вопросу
❌ Использование бытовых рассуждений

<b>2. Ответ на вопрос (К2)</b>
❌ Неоднозначная формулировка
❌ Противоречие с обоснованием
❌ Отсутствие прямого ответа

<b>3. Примеры (К3)</b>
❌ Примеры из одной сферы жизни
❌ Абстрактные примеры без деталей
❌ Несоответствие примеров тезису

<b>Как избежать ошибок:</b>
✅ Внимательно читайте вопрос
✅ Используйте обществоведческие термины
✅ Приводите конкретные примеры с деталями
✅ Проверяйте логическую связность"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Примеры ответов", callback_data="t25_best_examples")],
        [InlineKeyboardButton("⬅️ К теории", callback_data="t25_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика."""
    query = update.callback_query
    
    # Здесь можно добавить более подробную статистику
    return states.CHOOSING_MODE


@safe_handler()
async def recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рекомендации по улучшению."""
    query = update.callback_query
    
    stats = context.user_data.get('task25_stats', {})
    
    text = "🎯 <b>Персональные рекомендации</b>\n\n"
    
    # Анализируем статистику и даем советы
    if not stats.get('total_attempts'):
        text += "📝 Начните с изучения теории и примеров\n"
        text += "💡 Попробуйте режим ответов по частям\n"
        text += "🟢 Начните с тем легкого уровня\n"
    else:
        avg_score = sum(stats.get('scores', [0])) / max(len(stats.get('scores', [1])), 1)
        
        if avg_score < 3:
            text += "📚 Изучите типичные ошибки\n"
            text += "💡 Используйте режим по частям\n"
            text += "🔍 Анализируйте эталонные ответы\n"
        elif avg_score < 5:
            text += "✏️ Работайте над развёрнутостью примеров\n"
            text += "🎯 Тренируйтесь на сложных темах\n"
        else:
            text += "⭐ Отличные результаты!\n"
            text += "🔴 Попробуйте экспертный уровень проверки\n"
    
    # Рекомендуем непройденные блоки
    blocks_progress = stats.get('blocks_progress', {})
    weak_blocks = [b for b, p in blocks_progress.items() if p < 50]
    
    if weak_blocks:
        text += f"\n<b>Обратите внимание на блоки:</b>\n"
        for block in weak_blocks[:3]:
            text += f"• {block}\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 К статистике", callback_data="t25_progress")],
        [InlineKeyboardButton("💪 Начать практику", callback_data="t25_practice")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

# Остальные обработчики...
@safe_handler()
async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банк примеров."""
    query = update.callback_query
    
    text = (
        "🏦 <b>Банк примеров</b>\n\n"
        "Здесь собраны эталонные примеры ответов.\n"
        "Выберите способ поиска:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Поиск по ключевым словам", callback_data="t25_search_examples")],
        [InlineKeyboardButton("📚 По блокам", callback_data="t25_examples_by_block")],
        [InlineKeyboardButton("⭐ Лучшие примеры", callback_data="t25_best_examples")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def show_example_topic(query, context: ContextTypes.DEFAULT_TYPE, topic_idx: int):
    """Показывает эталонный ответ для темы по индексу."""
    topics_with_examples = [t for t in task25_data.get('topics', []) 
                           if 'example_answers' in t]
    
    if topic_idx >= len(topics_with_examples) or topic_idx < 0:
        topic_idx = 0
    
    topic = topics_with_examples[topic_idx]
    total = len(topics_with_examples)
    
    # Форматируем текст
    text = f"📚 <b>Банк эталонных ответов</b>\n"
    text += f"Пример {topic_idx + 1} из {total}\n"
    text += "━" * 35 + "\n\n"
    
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n\n"
    
    # Текст задания
    if 'task_text' in topic:
        text += f"<b>Задание:</b>\n{topic['task_text']}\n\n"
    elif 'parts' in topic:
        text += "<b>Задание:</b>\n"
        parts = topic['parts']
        if 'part1' in parts:
            text += f"1. {parts['part1']}\n"
        if 'part2' in parts:
            text += f"2. {parts['part2']}\n"
        if 'part3' in parts:
            text += f"3. {parts['part3']}\n"
        text += "\n"
    
    # Эталонный ответ
    text += _format_example_answer(topic)
    
    # Кнопки навигации
    kb_buttons = []
    
    # Навигация между примерами
    nav_row = []
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t25_example_nav:{topic_idx-1}"))
    nav_row.append(InlineKeyboardButton(f"{topic_idx+1}/{total}", callback_data="t25_noop"))
    if topic_idx < total - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t25_example_nav:{topic_idx+1}"))
    
    kb_buttons.append(nav_row)
    
    # Действия
    kb_buttons.extend([
        [InlineKeyboardButton("📝 Попробовать эту тему", callback_data=f"t25_try_topic:{topic['id']}")],
        [InlineKeyboardButton("🔍 Поиск по темам", callback_data="t25_bank_search")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )

@safe_handler()
async def handle_example_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по примерам ответов."""
    query = update.callback_query
    
    # Извлекаем действие из callback_data
    action = query.data.split(':')[1]
    
    # Получаем текущий индекс примера
    current_idx = context.user_data.get('example_index', 0)
    topics_with_examples = [
        t for t in task25_data.get('topics', [])
        if 'example_answers' in t
    ]
    
    if not topics_with_examples:
        await query.answer("Нет доступных примеров", show_alert=True)
        return states.CHOOSING_MODE
    
    # Обработка действий навигации
    if action == 'next':
        current_idx = (current_idx + 1) % len(topics_with_examples)
    elif action == 'prev':
        current_idx = (current_idx - 1) % len(topics_with_examples)
    elif action == 'random':
        current_idx = random.randint(0, len(topics_with_examples) - 1)
    
    # Сохраняем индекс
    context.user_data['example_index'] = current_idx
    
    # Показываем пример
    topic = topics_with_examples[current_idx]
    
    text = f"📚 <b>Пример {current_idx + 1} из {len(topics_with_examples)}</b>\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n"
    text += f"{'─' * 30}\n\n"
    
    # Форматируем пример
    if 'example_answers' in topic:
        example = topic['example_answers']
        
        if 'part1' in example:
            text += "<b>1. Обоснование:</b>\n"
            text += f"{example['part1']}\n\n"
        
        if 'part2' in example:
            text += "<b>2. Ответ на вопрос:</b>\n"
            text += f"{example['part2']}\n\n"
        
        if 'part3' in example:
            text += "<b>3. Примеры:</b>\n"
            if isinstance(example['part3'], list):
                for i, ex in enumerate(example['part3'], 1):
                    if isinstance(ex, dict):
                        text += f"{i}) {ex.get('type', 'Пример')}: {ex.get('example', ex)}\n"
                    else:
                        text += f"{i}) {ex}\n"
            else:
                text += f"{example['part3']}\n"
    
    # Кнопки навигации
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️", callback_data="t25_example_nav:prev"),
            InlineKeyboardButton(f"{current_idx + 1}/{len(topics_with_examples)}", callback_data="t25_noop"),
            InlineKeyboardButton("➡️", callback_data="t25_example_nav:next")
        ],
        [InlineKeyboardButton("🎲 Случайный", callback_data="t25_example_nav:random")],
        [InlineKeyboardButton("📝 Попробовать эту тему", callback_data=f"t25_topic:{topic['id']}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку примеров."""
    query = update.callback_query
    
    topic_idx = int(query.data.split(":")[1])
    await show_example_topic(query, context, topic_idx)
    return states.CHOOSING_MODE


@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя."""
    query = update.callback_query
    
    # Используем task25_practice_stats
    results = context.user_data.get('task25_results', [])
    task25_stats = context.user_data.get('task25_practice_stats', {})
    
    if not task25_stats and not results:
        text = (
            "📊 <b>Ваш прогресс</b>\n\n"
            "Вы ещё не решали задания. Начните практику!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💪 Начать практику", callback_data="t25_practice")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
        ])
    else:
        text = "📊 <b>Ваш прогресс</b>\n\n"
        
        # Собираем статистику из ОБОИХ источников
        total_attempts = 0
        total_score = 0
        topics_tried = 0
        
        # Обрабатываем данные из task25_practice_stats (ИСПРАВЛЕНО!)
        for topic_id, topic_stats in task25_stats.items():  # Было: stats.items()
            if topic_stats.get('attempts', 0) > 0:
                topics_tried += 1
                total_attempts += topic_stats['attempts']
                if topic_stats.get('scores'):
                    # Берём лучший результат по теме
                    best_score = max(topic_stats['scores'])
                    total_score += best_score
        
        # Если task25_stats пустой, но есть results - используем их (ИСПРАВЛЕНО!)
        if not task25_stats and results:  # Было: if not stats and results
            total_attempts = len(results)
            total_score = sum(r['score'] for r in results)
            topics_tried = len(set(r.get('topic_id') for r in results if r.get('topic_id')))
        
        # Если есть и task25_stats и results - синхронизируем (ИСПРАВЛЕНО!)
        elif task25_stats and results:  # Было: elif stats and results
            # Проверяем, есть ли в results темы, которых нет в task25_stats
            for result in results:
                topic_id_str = str(result.get('topic_id', 0))
                if topic_id_str not in task25_stats:
                    # Добавляем тему из results
                    if 'task25_practice_stats' not in context.user_data:
                        context.user_data['task25_practice_stats'] = {}
                    
                    context.user_data['task25_practice_stats'][topic_id_str] = {
                        'attempts': 1,
                        'scores': [result['score']],
                        'topic_title': result.get('topic_title', 'Неизвестная тема'),
                        'topic_id': result.get('topic_id'),
                        'module': 'task25'
                    }
                    
                    # Обновляем локальную переменную
                    task25_stats = context.user_data['task25_practice_stats']
        
        # Формируем отображение
        if topics_tried > 0:
            avg_score = total_score / topics_tried
            text += f"<b>Тем изучено:</b> {topics_tried}\n"
            text += f"<b>Всего попыток:</b> {total_attempts}\n"
            text += f"<b>Средний балл:</b> {avg_score:.1f}/6\n\n"
            
            # Детализация по темам (только если есть данные)
            if task25_stats:
                text += "<b>Последние темы:</b>\n"
                # Сортируем по последней попытке (если есть timestamp)
                sorted_topics = sorted(
                    task25_stats.items(),
                    key=lambda x: x[1].get('last_attempt', ''),
                    reverse=True
                )[:5]  # Показываем последние 5 тем
                
                for topic_id_str, topic_data in sorted_topics:
                    topic_title = topic_data.get('topic_title', 'Неизвестная тема')[:30]
                    if topic_data.get('scores'):
                        best = max(topic_data['scores'])
                        attempts = topic_data.get('attempts', 0)
                        text += f"• {topic_title}: {best}/6 (попыток: {attempts})\n"
        else:
            text += "Начните практику для отслеживания прогресса!"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Подробнее", callback_data="t25_detailed_progress")],
            [InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="t25_reset_confirm")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
        ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

def save_result(context: ContextTypes.DEFAULT_TYPE, topic: Dict, score: int):
    """Сохраняет результат проверки."""
    from datetime import datetime
    
    # Инициализируем структуру результатов если нужно
    if 'task25_results' not in context.user_data:
        context.user_data['task25_results'] = []
    
    # Сохраняем результат с правильными ключами
    result = {
        'topic_id': topic.get('id'),
        'topic_title': topic.get('title', 'Неизвестная тема'),
        'block': topic.get('block', 'Общие темы'),
        'score': score,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    context.user_data['task25_results'].append(result)
    
    # Обновляем также practice_stats для обратной совместимости
    if 'practice_stats' not in context.user_data:
        context.user_data['practice_stats'] = {}

    topic_id_str = str(topic.get('id', 0))

    # Инициализируем статистику по теме если её нет
    if 'task25_practice_stats' not in context.user_data:
        context.user_data['task25_practice_stats'] = {}
    if topic_id_str not in context.user_data['task25_practice_stats']:
        context.user_data['task25_practice_stats'][topic_id_str] = {
            'attempts': 0,
            'scores': [],
            'last_attempt': None,
            'best_score': 0,
            'topic_title': topic.get('title', 'Неизвестная тема'),
            'topic_id': topic.get('id')
        }
    
    # Обновляем статистику
    topic_stats = context.user_data['task25_practice_stats'][topic_id_str]
    topic_stats['attempts'] += 1
    topic_stats['scores'].append(score)
    topic_stats['last_attempt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    topic_stats['best_score'] = max(topic_stats.get('best_score', 0), score)
    
    # Обновляем серию правильных ответов
    if score >= 5:  # Для task25 хорошим считается 5+ баллов из 6
        context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
    else:
        context.user_data['correct_streak'] = 0
    
    return result

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки задания 25."""
    query = update.callback_query
    
    # Получаем текущие настройки - ИСПРАВЛЕНО
    settings = context.user_data.get('task25_settings', {
        'answer_mode': 'full',  # full или parts
        'show_examples': True,
        'strictness': 'standard'
    })
    
    # Убедимся, что settings это словарь
    if not isinstance(settings, dict):
        settings = {
            'answer_mode': 'full',
            'show_examples': True,
            'strictness': 'standard'
        }
        context.user_data['task25_settings'] = settings
    
    text = "⚙️ <b>Настройки задания 25</b>\n\n"
    
    # Режим ответа
    answer_mode_text = "целиком" if settings.get('answer_mode', 'full') == 'full' else "по частям"
    text += f"📝 Режим ответа: <b>{answer_mode_text}</b>\n"
    
    # Показ примеров
    examples_text = "да" if settings.get('show_examples', True) else "нет"
    text += f"📚 Показывать примеры: <b>{examples_text}</b>\n"
    
    # Строгость проверки
    strictness_map = {
        'lenient': 'мягкая',
        'standard': 'стандартная',
        'strict': 'строгая',
        'expert': 'экспертная'
    }
    text += f"🎯 Строгость проверки: <b>{strictness_map.get(settings.get('strictness', 'standard'), 'стандартная')}</b>\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'✅' if settings.get('answer_mode', 'full') == 'full' else '⚪'} Отвечать целиком",
            callback_data="t25_set_mode:full"
        )],
        [InlineKeyboardButton(
            f"{'✅' if settings.get('answer_mode', 'full') == 'parts' else '⚪'} Отвечать по частям",
            callback_data="t25_set_mode:parts"
        )],
        [InlineKeyboardButton(
            f"{'✅' if settings.get('show_examples', True) else '❌'} Показ примеров",
            callback_data="t25_toggle_examples"
        )],
        [InlineKeyboardButton("🎯 Строгость проверки", callback_data="t25_strictness_menu")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню task25."""
    query = update.callback_query
    
    if query:
        await query.answer()
    
    # Автоматическая миграция при возврате
    ensure_module_migration(context, 'task25', task25_data)
    
    results = context.user_data.get('task25_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r.get('topic_id') for r in results)) / 100 * 100) if results else 0
    }

    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 25",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t25")
    
    # Используем безопасную функцию перехода
    await safe_menu_transition(query, text, kb)
    
    return states.CHOOSING_MODE


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text(
        "❌ Действие отменено.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 К заданиям", callback_data="t25_menu")
        ]])
    )

    return states.CHOOSING_MODE


@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    from core.menu_handlers import handle_to_main_menu
    return await handle_to_main_menu(update, context)


@safe_handler()
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()  # Просто подтверждаем нажатие без действий
    return None  # Не меняем состояние

@safe_handler()
async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для информационных кнопок."""
    query = update.callback_query
    return None

# Дополнительные обработчики...
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем с пагинацией."""
    query = update.callback_query
    
    # Извлекаем номер страницы
    parts = query.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0
    
    # Получаем темы блока
    block_name = context.user_data.get("selected_block", "")
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    if not topics:
        await query.edit_message_text(
            "❌ Темы не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=f"t25_block:{block_name}")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Пагинация
    topics_per_page = 5
    total_pages = (len(topics) + topics_per_page - 1) // topics_per_page
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(topics))
    
    text = f"📚 <b>Темы блока: {block_name}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    kb_buttons = []
    
    # Добавляем темы текущей страницы
    for i in range(start_idx, end_idx):
        topic = topics[i]
        difficulty = topic.get('difficulty', 'medium')
        diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(difficulty, "⚪")
        
        kb_buttons.append([InlineKeyboardButton(
            f"{diff_emoji} {topic['title'][:40]}...",
            callback_data=f"t25_select_topic:{topic['id']}"
        )])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t25_list_topics:page:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t25_list_topics:page:{page+1}"))
    
    if nav_buttons:
        kb_buttons.append(nav_buttons)
    
    kb_buttons.append([InlineKeyboardButton("⬅️ К блоку", callback_data=f"t25_block:{block_name}")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK_T25

@safe_handler()
async def show_topic_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ темы по ID - используется для показа примеров и выбора темы для практики."""
    query = update.callback_query
    
    # Определяем действие по callback_data
    action_type = "show_example"  # по умолчанию показываем пример
    if "try_topic" in query.data:
        action_type = "practice"
    
    # Извлекаем ID темы
    topic_id = query.data.split(':')[1]
    
    # Находим тему по ID
    topic = None
    for t in task25_data.get('topics', []):
        if str(t.get('id')) == str(topic_id):
            topic = t
            break
    
    if not topic:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    # Если это режим практики (нажали "Попробовать эту тему")
    if action_type == "practice":
        context.user_data['current_topic'] = topic
        context.user_data['mode'] = 'practice'
        
        # Показываем задание для решения
        text = "📝 <b>Задание 25</b>\n\n"
        text += f"<b>Тема:</b> {topic['title']}\n"
        text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n\n"
        
        text += "<b>Ваше задание:</b>\n"
        if 'parts' in topic:
            parts = topic['parts']
            if parts.get('part1'):
                text += f"1. {parts['part1']}\n"
            if parts.get('part2'):
                text += f"2. {parts['part2']}\n"
            if parts.get('part3'):
                text += f"3. {parts['part3']}\n"
        else:
            text += f"{topic.get('task_text', '')}\n"
        
        text += "\n📌 <b>Требования к ответу:</b>\n"
        text += "1️⃣ Развёрнутое обоснование (2 балла)\n"
        text += "2️⃣ Точный ответ на вопрос (1 балл)\n"
        text += "3️⃣ Три конкретных примера (3 балла)\n\n"
        text += "💬 <i>Отправьте развёрнутый ответ одним сообщением</i>"
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="t25_menu")
        ]])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.TASK25_WAITING
    
    # Иначе показываем пример (нажали "Пример 1-5")
    else:
        # Проверяем наличие эталонного ответа
        if 'example_answers' not in topic:
            await query.answer("Эталонный ответ для этой темы пока не добавлен", show_alert=True)
            return states.CHOOSING_MODE
        
        # Форматируем текст примера
        text = f"📝 <b>Пример эталонного ответа</b>\n"
        text += "━" * 35 + "\n\n"
        text += f"<b>Тема:</b> {topic['title']}\n"
        text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n"
        text += f"<b>Сложность:</b> "
        
        difficulty = topic.get('difficulty', 'medium')
        diff_map = {
            'easy': '🟢 Лёгкая',
            'medium': '🟡 Средняя', 
            'hard': '🔴 Сложная'
        }
        text += f"{diff_map.get(difficulty, difficulty)}\n\n"
        
        # Показываем задание
        text += "<b>📋 Задание:</b>\n"
        if 'task_text' in topic:
            text += f"{topic['task_text']}\n\n"
        elif 'parts' in topic:
            parts = topic['parts']
            if parts.get('part1'):
                text += f"1. {parts['part1']}\n"
            if parts.get('part2'):
                text += f"2. {parts['part2']}\n"
            if parts.get('part3'):
                text += f"3. {parts['part3']}\n"
            text += "\n"
        
        # Используем функцию форматирования эталонного ответа
        text += _format_example_answer(topic)
        
        # Кнопки действий
        buttons = []
        
        # Основная кнопка - попробовать решить
        buttons.append([InlineKeyboardButton(
            "📝 Попробовать эту тему",
            callback_data=f"t25_try_topic:{topic['id']}"
        )])
        
        # Навигация по блоку (если есть)
        block_name = topic.get('block')
        if block_name:
            buttons.append([InlineKeyboardButton(
                f"📚 Другие темы из блока «{block_name}»",
                callback_data=f"t25_examples_block:{block_name}"
            )])
        
        # Кнопки навигации
        buttons.extend([
            [InlineKeyboardButton("🔍 Другие примеры", callback_data="t25_best_examples")],
            [InlineKeyboardButton("⬅️ К банку примеров", callback_data="t25_examples")]
        ])
        
        kb = InlineKeyboardMarkup(buttons)
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.CHOOSING_MODE

@safe_handler()
async def show_topic_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем с пагинацией."""
    query = update.callback_query
    
    # Парсим callback_data: t25_list_topics:page:0
    parts = query.data.split(':')
    page = int(parts[2]) if len(parts) > 2 else 0
    
    block_name = context.user_data.get("selected_block")
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    # Пагинация - 10 тем на страницу
    items_per_page = 10
    total_pages = (len(topics) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(topics))
    
    # Формируем текст
    text = f"📚 <b>{block_name}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    # Получаем прогресс пользователя
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = user_stats.get('topics_completed', set())
    
    # Список тем на текущей странице
    buttons = []
    for i in range(start_idx, end_idx):
        topic = topics[i]
        topic_id = topic.get('id')
        
        # Определяем эмодзи статуса
        if topic_id in completed_topics:
            status = "✅"
        else:
            status = "📝"
        
        # Сокращаем название если слишком длинное
        title = topic.get('title', 'Без названия')
        if len(title) > 40:
            title = title[:37] + "..."
        
        button_text = f"{status} {title}"
        buttons.append([InlineKeyboardButton(
            button_text,
            callback_data=f"t25_topic:{topic_id}"
        )])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t25_list_topics:page:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t25_list_topics:page:{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("⬅️ К блокам", callback_data="t25_select_block")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из выбранного блока с правильными кнопками."""
    query = update.callback_query
    
    block_name = context.user_data.get("selected_block")
    if not block_name:
        return states.CHOOSING_MODE
    
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    if not topics:
        return states.CHOOSING_MODE
    
    # Приоритет непройденным темам
    user_stats = context.user_data.get('task25_stats', {})
    completed = set(user_stats.get('topics_completed', []))
    
    uncompleted = [t for t in topics if t.get('id') not in completed]
    topic_pool = uncompleted if uncompleted else topics
    
    topic = random.choice(topic_pool)
    context.user_data['current_topic'] = topic
    
    # Проверяем режим ответа
    settings = context.user_data.get('task25_settings', {})
    
    text = _build_topic_message(topic)
    
    if settings.get('answer_mode') == 'parts':
        # Начинаем режим по частям
        context.user_data['current_part'] = 1
        context.user_data['part_answers'] = {}
        
        parts = topic.get('parts', {})
        part1_text = parts.get('part1', '')
        
        text = (
            f"📝 <b>Режим ответа по частям</b>\n\n"
            f"<b>Тема:</b> {topic['title']}\n\n"
            f"<b>Часть 1: Обоснование (2 балла)</b>\n\n"
            f"{part1_text}\n\n"
            f"💡 <i>Отправьте ваше обоснование</i>"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data=f"t25_block:{block_name}")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return ANSWERING_PARTS
    else:
        # Стандартный режим
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Другая тема", callback_data="t25_random_block")],
            [InlineKeyboardButton("⬅️ К блоку", callback_data=f"t25_block:{block_name}")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.ANSWERING


@safe_handler()
async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск в банке ответов."""
    query = update.callback_query
    
    text = (
        "🔍 <b>Поиск в банке ответов</b>\n\n"
        "Отправьте ключевые слова для поиска.\n"
        "Например: <i>демократия</i>, <i>рыночная экономика</i>\n\n"
        "Или выберите действие:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все примеры", callback_data="t25_all_examples")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.SEARCHING

@safe_handler()
async def list_all_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка всех тем без разделения по блокам."""
    query = update.callback_query
    
    # Собираем все темы
    all_topics = task25_data.get('topics', [])
    
    if not all_topics:
        return states.CHOOSING_MODE
    
    # Сортируем по сложности для удобства
    topics_by_difficulty = {
        'easy': [],
        'medium': [],
        'hard': []
    }
    
    for topic in all_topics:
        difficulty = topic.get('difficulty', 'medium')
        topics_by_difficulty[difficulty].append(topic)
    
    # Формируем текст
    text = "📚 <b>Все темы задания 25</b>\n\n"
    
    # Статистика
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = set(user_stats.get('topics_completed', []))
    
    text += f"✅ Изучено: {len(completed_topics)}/{len(all_topics)}\n\n"
    
    # Группируем по сложности
    difficulty_names = {
        'easy': '🟢 Легкие темы',
        'medium': '🟡 Средние темы',
        'hard': '🔴 Сложные темы'
    }
    
    buttons = []
    
    for difficulty in ['easy', 'medium', 'hard']:
        topics = topics_by_difficulty[difficulty]
        if topics:
            completed_in_level = len([t for t in topics if t.get('id') in completed_topics])
            buttons.append([InlineKeyboardButton(
                f"{difficulty_names[difficulty]} ({completed_in_level}/{len(topics)})",
                callback_data=f"t25_list_by_diff:{difficulty}"
            )])
    
    buttons.append([InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_all")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка изменения настроек."""
    query = update.callback_query
    
    # Парсим режим из callback_data: t25_set_mode:full
    mode = query.data.split(':')[1]
    
    # Получаем текущие настройки
    settings = context.user_data.get('task25_settings', {})
    
    # Убедимся, что это словарь
    if not isinstance(settings, dict):
        settings = {}
    
    # Обновляем настройки
    settings['answer_mode'] = mode
    context.user_data['task25_settings'] = settings
    
    # Обновляем отображение
    return await settings_mode(update, context)


@safe_handler()
async def toggle_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение показа примеров."""
    query = update.callback_query
    
    settings = context.user_data.get('task25_settings', {})
    settings['show_examples'] = not settings.get('show_examples', True)
    context.user_data['task25_settings'] = settings
    
    return await settings_mode(update, context)


@safe_handler()
async def strictness_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора строгости проверки."""
    query = update.callback_query
    
    current_strictness = context.user_data.get('task25_settings', {}).get('strictness', 'standard')
    
    text = (
        "🎯 <b>Выберите уровень строгости проверки:</b>\n\n"
        "🟢 <b>Мягкая</b> - засчитываются частично правильные ответы\n"
        "🟡 <b>Стандартная</b> - обычные критерии ЕГЭ\n"
        "🔴 <b>Строгая</b> - требуется полное соответствие критериям\n"
        "⚫ <b>Экспертная</b> - максимальная строгость\n"
    )
    
    buttons = []
    strictness_levels = [
        ('lenient', '🟢 Мягкая'),
        ('standard', '🟡 Стандартная'),
        ('strict', '🔴 Строгая'),
        ('expert', '⚫ Экспертная')
    ]
    
    for level, name in strictness_levels:
        check = '✅ ' if level == current_strictness else ''
        buttons.append([InlineKeyboardButton(
            f"{check}{name}",
            callback_data=f"t25_strictness:{level}"
        )])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_settings")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поискового запроса."""
    # Проверяем, ожидаем ли мы поисковый запрос
    if not context.user_data.get('waiting_for_search'):
        return states.CHOOSING_MODE
    
    # Сбрасываем флаг
    context.user_data['waiting_for_search'] = False
    
    search_query = update.message.text.lower()
    
    # Ищем темы с примерами
    found_topics = []
    for topic in task25_data.get('topics', []):
        if 'example_answers' not in topic:
            continue
            
        if (search_query in topic.get('title', '').lower() or
            search_query in topic.get('task_text', '').lower() or
            search_query in topic.get('block', '').lower() or
            any(search_query in str(part).lower() for part in topic.get('parts', {}).values())):
            found_topics.append(topic)
    
    if not found_topics:
        text = "🔍 <b>Результаты поиска</b>\n\n"
        text += f"По запросу «{update.message.text}» примеры не найдены.\n"
        text += "Попробуйте другие ключевые слова."
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Новый поиск", callback_data="t25_search_examples")],
            [InlineKeyboardButton("⬅️ К банку примеров", callback_data="t25_examples")]
        ])
    else:
        text = f"🔍 <b>Найдено примеров: {len(found_topics)}</b>\n\n"
        
        # Показываем первые 7 результатов
        buttons = []
        for i, topic in enumerate(found_topics[:7]):
            text += f"{i+1}. {topic['title']}\n"
            buttons.append([InlineKeyboardButton(
                f"👁 Пример {i+1}",
                callback_data=f"t25_show_example:{topic['id']}"
            )])
        
        if len(found_topics) > 7:
            text += f"\n<i>Показаны первые 7 из {len(found_topics)} тем</i>"
        
        buttons.extend([
            [InlineKeyboardButton("🔍 Новый поиск", callback_data="t25_search_examples")],
            [InlineKeyboardButton("⬅️ К банку примеров", callback_data="t25_examples")]
        ])
        
        kb = InlineKeyboardMarkup(buttons)
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена поиска и возврат к банку примеров."""
    query = update.callback_query
    
    # Сбрасываем флаг поиска
    context.user_data['waiting_for_search'] = False
    
    # Возвращаемся к банку примеров
    return await examples_bank(update, context)

@safe_handler()
async def show_examples_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ примеров ответов по выбранному блоку."""
    query = update.callback_query
    
    # Извлекаем название блока из callback_data
    block_name = query.data.split(':', 1)[1]
    
    # Фильтруем темы по блоку с примерами
    topics_in_block = [
        t for t in task25_data.get('topics', [])
        if t.get('block') == block_name and 'example_answers' in t
    ]
    
    if not topics_in_block:
        await query.answer("В этом блоке пока нет примеров", show_alert=True)
        return states.CHOOSING_MODE
    
    text = f"📚 <b>{block_name}</b>\n"
    text += f"Доступно примеров: {len(topics_in_block)}\n\n"
    text += "Выберите тему:\n\n"
    
    buttons = []
    for i, topic in enumerate(topics_in_block[:10], 1):  # Ограничиваем 10 темами
        buttons.append([InlineKeyboardButton(
            f"{i}. {topic['title'][:45]}...",
            callback_data=f"t25_show_example:{topic['id']}"
        )])
    
    if len(topics_in_block) > 10:
        text += f"\n<i>Показаны первые 10 из {len(topics_in_block)} тем</i>"
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples_by_block")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий в настройках."""
    # Реализация...
    pass


@safe_handler()
async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка уровня строгости."""
    query = update.callback_query
    
    level = query.data.split(':')[1]
    
    settings = context.user_data.get('task25_settings', {})
    settings['strictness'] = level
    context.user_data['task25_settings'] = settings
    
    return await settings_mode(update, context)


@safe_handler()
async def show_block_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика по блокам тем."""
    query = update.callback_query

    task25_stats = context.user_data.get('task25_practice_stats', {})
    stats = task25_stats

    if not stats:
        text = "📊 <b>Статистика по блокам</b>\n\n"
        text += "Вы ещё не решали задания.\n"
        text += "Начните практику для сбора статистики!"
    else:
        # Собираем статистику по блокам
        block_data = {}
        
        for topic_id, topic_stats in stats.items():
            topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
            if topic:
                block = topic.get('block', 'Другое')
                if block not in block_data:
                    block_data[block] = {
                        'topics_tried': 0,
                        'total_attempts': 0,
                        'scores': []
                    }
                
                block_data[block]['topics_tried'] += 1
                block_data[block]['total_attempts'] += topic_stats.get('attempts', 0)
                block_data[block]['scores'].extend(topic_stats.get('scores', []))
        
        text = "📊 <b>Статистика по блокам</b>\n\n"
        
        for block, data in sorted(block_data.items()):
            total_topics = len(task25_data.get('topics_by_block', {}).get(block, []))
            coverage = (data['topics_tried'] / total_topics * 100) if total_topics > 0 else 0
            
            text += f"<b>{block}</b>\n"
            text += f"• Изучено тем: {data['topics_tried']}/{total_topics} ({coverage:.0f}%)\n"
            text += f"• Всего попыток: {data['total_attempts']}\n"
            
            if data['scores']:
                avg_score = sum(data['scores']) / len(data['scores'])
                max_score = max(data['scores'])
                text += f"• Средний балл: {avg_score:.1f}/6\n"
                text += f"• Лучший результат: {max_score}/6\n"
            
            text += "\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Общий прогресс", callback_data="t25_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный прогресс по темам."""
    query = update.callback_query
    
    # ИЗМЕНЕНИЕ: Используем task25_practice_stats
    task25_stats = context.user_data.get('task25_practice_stats', {})
    
    if not task25_stats:
        return states.CHOOSING_MODE
    
    sorted_topics = sorted(
        task25_stats.items(),
        key=lambda x: x[1].get('attempts', 0),
        reverse=True
    )
    
    text = "📈 <b>Детальный прогресс</b>\n\n"
    
    for topic_id, topic_stats in sorted_topics[:10]:  # Показываем топ-10
        topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
        if topic:
            topic_name = topic.get('title', 'Неизвестная тема')[:40]
            attempts = topic_stats.get('attempts', 0)
            scores = topic_stats.get('scores', [])
            
            text += f"<b>{topic_name}</b>\n"
            text += f"• Попыток: {attempts}\n"
            
            if scores:
                avg_score = sum(scores) / len(scores)
                last_score = scores[-1]
                best_score = max(scores)
                
                text += f"• Последний результат: {last_score}/6\n"
                text += f"• Лучший результат: {best_score}/6\n"
                text += f"• Средний балл: {avg_score:.1f}/6\n"
                
                # Тренд
                if len(scores) > 1:
                    if scores[-1] > scores[-2]:
                        text += "• Тренд: 📈 Улучшение\n"
                    elif scores[-1] < scores[-2]:
                        text += "• Тренд: 📉 Снижение\n"
                    else:
                        text += "• Тренд: ➡️ Стабильно\n"
            
            text += "\n"
    
    if len(sorted_topics) > 10:
        text += f"<i>Показаны 10 из {len(sorted_topics)} изученных тем</i>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 По блокам", callback_data="t25_block_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def _save_user_stats(context: ContextTypes.DEFAULT_TYPE, topic: Dict, score: int):
    """Сохраняет статистику пользователя с изолированным хранилищем."""
    from datetime import datetime
    
    if 'task25_results' not in context.user_data:
        context.user_data['task25_results'] = []
    
    result = {
        'topic_id': topic.get('id'),
        'topic_title': topic.get('title', 'Неизвестная тема'),
        'block': topic.get('block', 'Общие темы'),
        'score': score,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    context.user_data['task25_results'].append(result)
    
    # ИЗМЕНЕНИЕ: Используем task25_practice_stats вместо practice_stats
    if 'task25_practice_stats' not in context.user_data:
        context.user_data['task25_practice_stats'] = {}
    
    topic_id_str = str(topic.get('id', 0))
    
    if topic_id_str not in context.user_data['task25_practice_stats']:
        context.user_data['task25_practice_stats'][topic_id_str] = {
            'attempts': 0,
            'scores': [],
            'last_attempt': None,
            'best_score': 0,
            'topic_title': topic.get('title', 'Неизвестная тема'),
            'topic_id': topic.get('id'),
            'module': 'task25'
        }
    
    topic_stats = context.user_data['task25_practice_stats'][topic_id_str]
    topic_stats['attempts'] += 1
    topic_stats['scores'].append(score)
    topic_stats['last_attempt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if score > topic_stats.get('best_score', 0):
        topic_stats['best_score'] = score
    
    if topic.get('title'):
        topic_stats['topic_title'] = topic.get('title')
    
    if score >= 5:
        context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
    else:
        context.user_data['correct_streak'] = 0
    
    return result


def _format_example_answer(topic: Dict) -> str:
    """Форматирует эталонный ответ для отображения."""
    example = topic.get('example_answers', {})
    if not example:
        return "\n⚠️ <i>Эталонный ответ не найден</i>"
    
    text = "\n" + "━" * 35 + "\n"
    text += "✨ <b>ЭТАЛОННЫЙ ОТВЕТ:</b>\n\n"
    
    # Часть 1 - Обоснование
    if 'part1' in example:
        text += "1️⃣ <b>Обоснование (2 балла):</b>\n"
        if isinstance(example['part1'], dict):
            content = example['part1'].get('answer', example['part1'].get('text', str(example['part1'])))
        else:
            content = str(example['part1'])
        text += f"<i>{content}</i>\n\n"
    
    # Часть 2 - Ответ на вопрос
    if 'part2' in example:
        text += "2️⃣ <b>Ответ на вопрос (1 балл):</b>\n"
        if isinstance(example['part2'], dict):
            content = example['part2'].get('answer', example['part2'].get('text', str(example['part2'])))
        else:
            content = str(example['part2'])
        text += f"<i>{content}</i>\n\n"
    
    # Часть 3 - Примеры
    if 'part3' in example:
        text += "3️⃣ <b>Примеры (3 балла):</b>\n\n"
        
        if isinstance(example['part3'], list):
            # Если примеры в виде списка
            for i, ex in enumerate(example['part3'], 1):
                text += f"📌 <b>Пример {i}:</b>\n"
                if isinstance(ex, dict):
                    # Если пример - словарь с типом и текстом
                    if 'type' in ex:
                        text += f"<b>{ex['type']}</b>\n"
                    example_text = ex.get('example', ex.get('text', str(ex)))
                    text += f"<i>{example_text}</i>\n\n"
                else:
                    # Если пример - просто текст
                    text += f"<i>{ex}</i>\n\n"
        elif isinstance(example['part3'], str):
            # Если примеры - просто текст
            text += f"<i>{example['part3']}</i>\n"
    
    # Финальный разделитель и подсказка
    text += "━" * 35 + "\n"
    text += "💡 <i>Обратите внимание на:</i>\n"
    text += "• Структуру и логику изложения\n"
    text += "• Использование терминов\n"
    text += "• Конкретность примеров\n"
    text += "• Детализацию ответов"
    
    return text

@safe_handler()
async def handle_strictness_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик изменения уровня строгости."""
    query = update.callback_query
    
    # Парсим уровень из callback_data
    _, level_str = query.data.split(':')
    
    global evaluator
    
    try:
        # Определяем новый уровень
        new_level = StrictnessLevel[level_str.upper()]
        
        # Пересоздаём evaluator с новым уровнем
        if AI_EVALUATOR_AVAILABLE:
            evaluator = Task25AIEvaluator(strictness=new_level)
            
            logger.info(f"Changed strictness level to {new_level.value}")
            
    except Exception as e:
        logger.error(f"Error changing strictness: {e}")
    # Возвращаемся в меню настроек
    return await show_settings(update, context)


@safe_handler()
async def handle_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает прогресс пользователя."""
    query = update.callback_query

    task25_stats = context.user_data.get('task25_practice_stats', {})
    stats = task25_stats

    if not stats:
        text = "📊 <b>Ваш прогресс</b>\n\n"
        text += "Вы ещё не решали задания. Начните практику!"
    else:
        text = "📊 <b>Ваш прогресс</b>\n\n"
        
        total_attempts = 0
        total_score = 0
        topics_tried = 0
        
        for topic_id, topic_stats in stats.items():
            if topic_stats['attempts'] > 0:
                topics_tried += 1
                total_attempts += topic_stats['attempts']
                if topic_stats['scores']:
                    # Берём лучший результат по теме
                    best_score = max(topic_stats['scores'])
                    total_score += best_score
        
        if topics_tried > 0:
            avg_score = total_score / topics_tried
            text += f"<b>Тем изучено:</b> {topics_tried}\n"
            text += f"<b>Всего попыток:</b> {total_attempts}\n"
            text += f"<b>Средний балл:</b> {avg_score:.1f}/6\n\n"
            
            # Детализация по темам
            text += "<b>По темам:</b>\n"
            for topic_id, topic_stats in stats.items():
                if topic_stats['attempts'] > 0:
                    topic = task25_data.get('topic_by_id', {}).get(topic_id, {})
                    topic_title = topic.get('title', 'Неизвестная тема')[:30]
                    
                    if topic_stats['scores']:
                        best = max(topic_stats['scores'])
                        last = topic_stats['scores'][-1]
                        text += f"• {topic_title}: {best}/6 (попыток: {topic_stats['attempts']})\n"
        else:
            text += "Начните практику для отслеживания прогресса!"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def handle_reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный сброс прогресса task25."""
    query = update.callback_query
    
    # Сбрасываем ТОЛЬКО данные task25
    context.user_data.pop('task25_results', None)
    context.user_data.pop('task25_practice_stats', None)
    context.user_data.pop('task25_achievements', None)
    
    await query.answer("✅ Прогресс по заданию 25 сброшен!", show_alert=True)
    return await settings_mode(update, context)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def choose_practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима практики."""
    query = update.callback_query
    
    text = "💪 <b>Режим практики</b>\n\nВыберите способ выбора темы:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_all")],  # Изменено с t25_random на t25_random_all
        [InlineKeyboardButton("📚 По блокам", callback_data="t25_by_block")],
        [InlineKeyboardButton("📈 По сложности", callback_data="t25_by_difficulty")],
        [InlineKeyboardButton("🎯 Рекомендованная", callback_data="t25_recommended")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def handle_random_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы."""
    query = update.callback_query
    
    if topic_selector:
        user_id = update.effective_user.id
        topic = topic_selector.get_random_topic(user_id)
    else:
        # Fallback - простой случайный выбор
        if task25_data.get('topics'):
            topic = random.choice(task25_data['topics'])
        else:
            topic = None
    
    if not topic:
        return states.CHOOSING_MODE
    
    # Сохраняем тему
    context.user_data['current_topic'] = topic
    
    # Форматируем и показываем
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING


@safe_handler()
async def choose_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока для практики."""
    query = update.callback_query
    
    blocks = list(task25_data.get("blocks", {}).keys())
    
    if not blocks:
        await query.edit_message_text(
            "❌ Блоки тем не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = "📚 <b>Выберите блок тем:</b>"
    
    kb_buttons = []
    for block in blocks:
        topics_count = len(task25_data["topics_by_block"].get(block, []))
        kb_buttons.append([
            InlineKeyboardButton(
                f"{block} ({topics_count} тем)",
                callback_data=f"t25_block:{block}"
            )
        ])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def by_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор темы по сложности."""
    query = update.callback_query
    
    text = "📈 <b>Выбор по сложности</b>\n\nВыберите уровень:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Легкие", callback_data="t25_diff:easy")],
        [InlineKeyboardButton("🟡 Средние", callback_data="t25_diff:medium")],
        [InlineKeyboardButton("🔴 Сложные", callback_data="t25_diff:hard")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def handle_difficulty_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбранной сложности."""
    query = update.callback_query
    
    # Извлекаем уровень сложности
    _, difficulty = query.data.split(':')
    
    # Сохраняем выбранную сложность для навигации
    context.user_data['selected_difficulty'] = difficulty
    
    if topic_selector:
        user_id = update.effective_user.id
        topic = topic_selector.get_topic_by_difficulty(user_id, difficulty)
    else:
        # Fallback
        topics = [t for t in task25_data.get('topics', []) 
                 if t.get('difficulty', 'medium') == difficulty]
        topic = random.choice(topics) if topics else None
    
    if not topic:
        return states.CHOOSING_MODE
    
    # Сохраняем тему
    context.user_data['current_topic'] = topic
    
    # Показываем тему
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    # Добавляем кнопки навигации
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Другая тема", callback_data="t25_another_topic")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_by_difficulty")]
    ])
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

@safe_handler()
async def recommended_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рекомендованная тема на основе прогресса."""
    query = update.callback_query
    
    # Временно используем случайную тему
    await query.answer("🎯 Подбираю рекомендацию...", show_alert=False)
    return await random_topic_all(update, context)

@safe_handler()
async def handle_recommended(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор рекомендованной темы."""
    query = update.callback_query
    
    # ИЗМЕНЕНИЕ: Используем task25_practice_stats вместо practice_stats
    user_stats = context.user_data.get('task25_practice_stats', {})
    
    if topic_selector and user_stats:
        user_id = update.effective_user.id
        topic = topic_selector.get_recommended_topic(user_id, user_stats)
    else:
        # Если нет статистики - даём случайную тему средней сложности
        topics = [t for t in task25_data.get('topics', []) 
                 if t.get('difficulty', 'medium') == 'medium']
        topic = random.choice(topics) if topics else None
    
    if not topic:
        await query.answer("❌ Не удалось подобрать тему", show_alert=True)
        return states.CHOOSING_MODE
    
    # Сохраняем тему
    context.user_data['current_topic'] = topic
    
    # Показываем с пояснением
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    recommendation_text = "🎯 <b>Рекомендованная тема</b>\n"
    if user_stats:
        # Добавим больше информации о том, почему выбрана эта тема
        topics_tried = len(user_stats)
        if topics_tried > 0:
            recommendation_text += f"<i>Выбрана на основе {topics_tried} изученных тем</i>\n\n"
        else:
            recommendation_text += "<i>Начните с темы средней сложности</i>\n\n"
    else:
        recommendation_text += "<i>Начните с темы средней сложности</i>\n\n"
    
    await query.edit_message_text(
        recommendation_text + topic_text + "\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

@safe_handler()
async def handle_topic_by_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора темы из блока."""
    query = update.callback_query
    
    block_name = query.data.split(":", 1)[1]
    context.user_data["selected_block"] = block_name
    
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    text = f"📚 <b>Блок: {block_name}</b>\n"
    text += f"Доступно тем: {len(topics)}\n\n"
    text += "Выберите действие:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список тем", callback_data=f"t25_list_topics:page:0")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_block")],
        [InlineKeyboardButton("⬅️ К блокам", callback_data="t25_by_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK_T25


@safe_handler()
async def handle_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторить то же задание."""
    query = update.callback_query
    
    topic = context.user_data.get('current_topic')
    if not topic:
        return await choose_practice_mode(update, context)
    
    # Показываем то же задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Попробуйте ещё раз:</b>\n\n"
        "<i>💡 Подсказка: обратите внимание на все три части задания</i>",
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

@safe_handler()
async def handle_new_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Новая случайная тема."""
    query = update.callback_query
    
    # Выбираем новую тему
    if topic_selector:
        user_id = update.effective_user.id
        topic = topic_selector.get_random_topic(user_id)
    else:
        topics = task25_data.get('topics', [])
        topic = random.choice(topics) if topics else None
    
    if not topic:
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    # Показываем новое задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню настроек."""
    query = update.callback_query
    
    current_strictness = "Не установлен"
    if evaluator and hasattr(evaluator, 'strictness'):
        current_strictness = evaluator.strictness.value
    
    text = f"""⚙️ <b>Настройки задания 25</b>

<b>Текущие настройки:</b>
• Уровень проверки: {current_strictness}
• AI-проверка: {'✅ Включена' if AI_EVALUATOR_AVAILABLE else '❌ Выключена'}

<b>Уровни проверки:</b>
🟢 <b>Мягкий</b> - для начального обучения
🟡 <b>Стандартный</b> - оптимальный баланс
🔴 <b>Строгий</b> - как на реальном ЕГЭ
🟣 <b>Экспертный</b> - максимальная строгость"""
    
    kb_buttons = []
    
    if AI_EVALUATOR_AVAILABLE and StrictnessLevel:
        kb_buttons.extend([
            [InlineKeyboardButton("🟢 Мягкий", callback_data="t25_strictness:lenient")],
            [InlineKeyboardButton("🟡 Стандартный", callback_data="t25_strictness:standard")],
            [InlineKeyboardButton("🔴 Строгий", callback_data="t25_strictness:strict")],
            [InlineKeyboardButton("🟣 Экспертный", callback_data="t25_strictness:expert")]
        ])
    
    kb_buttons.extend([
        [InlineKeyboardButton("🗑 Сбросить прогресс", callback_data="t25_reset_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE
    

@safe_handler()
async def confirm_reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    
    # Сбрасываем статистику
    context.user_data['practice_stats'] = {}
    
    
    # Возвращаемся в настройки
    return await show_settings(update, context)


@safe_handler()
async def show_example_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает эталонный ответ для выбранной темы."""
    query = update.callback_query
    
    # Извлекаем ID темы
    _, topic_id = query.data.split(':')
    topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
    
    if not topic:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    # Форматируем эталонный ответ
    text = f"📚 <b>Эталонный ответ</b>\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"{'─' * 30}\n\n"
    
    if 'example_answers' in topic:
        example = topic['example_answers']
        
        # Часть 1 - Обоснование
        if 'part1' in example:
            text += "<b>1. Обоснование (2 балла):</b>\n"
            if isinstance(example['part1'], dict):
                text += f"{example['part1'].get('answer', example['part1'])}\n\n"
            else:
                text += f"{example['part1']}\n\n"
        
        # Часть 2 - Ответ
        if 'part2' in example:
            text += "<b>2. Ответ на вопрос (1 балл):</b>\n"
            if isinstance(example['part2'], dict):
                text += f"{example['part2'].get('answer', example['part2'])}\n\n"
            else:
                text += f"{example['part2']}\n\n"
        
        # Часть 3 - Примеры
        if 'part3' in example:
            text += "<b>3. Примеры (3 балла):</b>\n"
            if isinstance(example['part3'], list):
                for i, ex in enumerate(example['part3'], 1):
                    if isinstance(ex, dict):
                        text += f"\n{i}) <b>{ex.get('type', 'Пример')}:</b>\n"
                        text += f"{ex.get('example', ex)}\n"
                    else:
                        text += f"\n{i}) {ex}\n"
            else:
                text += f"{example['part3']}\n"
    else:
        text += "<i>Эталонный ответ для этой темы пока не добавлен</i>"
    
    # Кнопки действий
    buttons = []
    
    # Кнопка "Попробовать эту тему"
    buttons.append([InlineKeyboardButton(
        "📝 Попробовать эту тему",
        callback_data=f"t25_topic:{topic['id']}"
    )])
    
    # Навигация по блоку
    block_name = topic.get('block')
    if block_name:
        buttons.append([InlineKeyboardButton(
            f"📚 Другие темы из блока «{block_name}»",
            callback_data=f"t25_examples_block:{block_name}"
        )])
    
    # Возврат в меню
    buttons.extend([
        [InlineKeyboardButton("🔍 Поиск примеров", callback_data="t25_search_examples")],
        [InlineKeyboardButton("⬅️ К банку примеров", callback_data="t25_examples")]
    ])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def handle_select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы из списка."""
    query = update.callback_query

    # Удаляем предыдущие сообщения перед показом нового вопроса
    await delete_previous_messages(context, query.message.chat_id)

    # Извлекаем ID темы
    _, topic_id = query.data.split(':')
    topic = task25_data.get('topic_by_id', {}).get(int(topic_id))

    if not topic:
        return states.CHOOSING_MODE

    context.user_data['current_topic'] = topic

    # Показываем задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)

    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )

    # Сохраняем ID сообщения с вопросом
    context.user_data['task25_question_msg_id'] = query.message.message_id

    return states.ANSWERING


@safe_handler()
async def handle_try_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Попробовать решить выбранную тему после просмотра примера."""
    query = update.callback_query
    
    # Извлекаем ID темы
    _, topic_id = query.data.split(':')
    topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
    
    if not topic:
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    # Показываем задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>\n\n"
        "<i>💡 Подсказка: вы только что просмотрели эталонный ответ для этой темы</i>",
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

@safe_handler()
async def handle_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт результатов в CSV."""
    query = update.callback_query
    user_id = query.from_user.id
    
    results = context.user_data.get('task25_results', [])
    
    if not results:
        await query.answer("Нет результатов для экспорта", show_alert=True)
        return states.CHOOSING_MODE
    
    # Создаем CSV
    import io
    import csv
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    # Заголовок
    writer.writerow(["Дата", "Тема", "Блок", "Балл", "Макс.балл", "Процент"])
    
    for result in results:
        timestamp = result.get('timestamp', '')
        topic_title = result.get('topic_title', 'Неизвестная тема')
        block = result.get('block', 'Общие темы')
        score = result.get('score', 0)
        max_score = 6
        percentage = f"{(score/max_score*100):.0f}%"
        
        writer.writerow([timestamp, topic_title, block, score, max_score, percentage])
    
    # Итоговая строка
    total_score = sum(r.get('score', 0) for r in results)
    total_max = len(results) * 6
    avg_percentage = f"{(total_score/total_max*100):.0f}%" if total_max > 0 else "0%"
    
    writer.writerow([])
    writer.writerow(["ИТОГО", "", "", total_score, total_max, avg_percentage])
    
    # Отправляем файл
    output.seek(0)
    await query.message.reply_document(
        document=io.BytesIO(output.getvalue().encode('utf-8-sig')),
        filename=f"task25_results_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        caption="📊 Ваши результаты по заданию 25\n\nФайл можно открыть в Excel или Google Sheets"
    )
    
    await query.answer("✅ Файл успешно создан!")
    
    return states.CHOOSING_MODE
    
@safe_handler()
async def handle_detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика по темам."""
    query = update.callback_query
    
    results = context.user_data.get('task25_results', [])
    
    if not results:
        text = "📊 <b>Детальная статистика</b>\n\n"
        text += "У вас пока нет результатов для анализа."
    else:
        # Группируем результаты по темам
        topic_stats = {}
        for result in results:
            topic_id = result.get('topic_id')
            topic_title = result.get('topic_title', 'Неизвестная тема')
            
            if topic_id not in topic_stats:
                topic_stats[topic_id] = {
                    'title': topic_title,
                    'scores': [],
                    'block': result.get('block', 'Общие темы')
                }
            
            topic_stats[topic_id]['scores'].append(result.get('score', 0))
        
        # Сортируем по среднему баллу
        sorted_topics = sorted(
            topic_stats.items(),
            key=lambda x: sum(x[1]['scores']) / len(x[1]['scores']),
            reverse=True
        )
        
        text = "📊 <b>Детальная статистика по темам</b>\n\n"
        
        for topic_id, data in sorted_topics[:10]:  # Топ-10 тем
            avg_score = sum(data['scores']) / len(data['scores'])
            max_score = max(data['scores'])
            attempts = len(data['scores'])
            
            text += f"<b>{data['title']}</b>\n"
            text += f"Блок: {data['block']}\n"
            text += f"Средний балл: {avg_score:.1f}/6\n"
            text += f"Лучший результат: {max_score}/6\n"
            text += f"Попыток: {attempts}\n\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 К прогрессу", callback_data="t25_progress")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def handle_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    
    text = (
        "⚠️ <b>Сброс прогресса</b>\n\n"
        "Вы уверены, что хотите сбросить весь прогресс по заданию 25?\n"
        "Это действие нельзя отменить!"
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data="t25_do_reset"),
            InlineKeyboardButton("❌ Отмена", callback_data="t25_progress")
        ]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def handle_do_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполнение сброса прогресса."""
    query = update.callback_query
    
    # Сбрасываем все данные
    context.user_data['task25_results'] = []
    context.user_data['task25_stats'] = {
        'total_attempts': 0,
        'topics_completed': [],
        'scores': [],
        'blocks_progress': {}
    }
    context.user_data['practice_stats'] = {}
    context.user_data.pop('correct_streak', None)
    
    await query.answer("✅ Прогресс сброшен!", show_alert=True)
    
    # Возвращаемся в меню
    return await return_to_menu(update, context)

@safe_handler()
@validate_state_transition({states.ANSWERING})
async def handle_answer_document_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка развернутого ответа из документа для task25."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE
    
    extracted_text = await DocumentHandlerMixin.handle_document_answer(
        update, 
        context,
        task_name="развернутый ответ"
    )
    
    if not extracted_text:
        return states.ANSWERING
    
    # Для task25 может быть разбивка на части
    current_part = context.user_data.get('current_part', 0)
    
    if current_part > 0:
        # Если отвечаем по частям - сохраняем текст в context
        context.user_data['document_text'] = extracted_text
        return await handle_answer_parts(update, context)
    else:
        # Если полный ответ - сохраняем текст в context
        context.user_data['document_text'] = extracted_text
        return await safe_handle_answer_task25(update, context)


@safe_handler()
async def handle_answer_photo_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка развернутого ответа с фотографии для task25.

    Поддерживает как одиночные фото, так и альбомы (media group).
    При получении альбома фотографии буферизуются и обрабатываются
    вместе после небольшой задержки.
    """

    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE

    media_group_id = update.message.media_group_id

    if media_group_id:
        # Это часть альбома — буферизуем и обрабатываем позже
        return await _buffer_media_group_photo(update, context, topic, media_group_id)

    # Одиночное фото — обрабатываем как раньше
    topic_title = topic.get('title', '') if isinstance(topic, dict) else str(topic)
    ocr_context = f"ЕГЭ обществознание, задание 25 (развернутый ответ), тема: {topic_title}"

    extracted_text = await process_photo_message(
        update,
        context.application.bot,
        task_name="развернутый ответ",
        task_context=ocr_context
    )

    if not extracted_text:
        return states.ANSWERING

    # Для task25 может быть разбивка на части
    current_part = context.user_data.get('current_part', 0)

    if current_part > 0:
        context.user_data['document_text'] = extracted_text
        return await handle_answer_parts(update, context)
    else:
        context.user_data['document_text'] = extracted_text
        return await safe_handle_answer_task25(update, context)


async def _buffer_media_group_photo(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                     topic: dict, media_group_id: str):
    """Буферизация фото из альбома для последующей пакетной обработки."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Инициализируем буфер
    if 'pending_media_group' not in context.user_data:
        context.user_data['pending_media_group'] = {}

    group_data = context.user_data['pending_media_group']

    is_first = media_group_id not in group_data
    if is_first:
        group_data[media_group_id] = {
            'photo_file_ids': [],
            'topic': topic,
            'current_part': context.user_data.get('current_part', 0),
        }
        # Показываем сообщение при первом фото в альбоме
        msg = await update.message.reply_text("📸 Получаю фотографии из альбома...")
        group_data[media_group_id]['status_msg_id'] = msg.message_id

    # Сохраняем file_id самого большого фото (лучшее качество)
    group_data[media_group_id]['photo_file_ids'].append(update.message.photo[-1].file_id)

    # Перепланируем задачу обработки (сбрасываем таймер при каждом новом фото)
    job_name = f"t25_media_group_{user_id}_{media_group_id}"

    if context.job_queue:
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()

        context.job_queue.run_once(
            _process_media_group_task25_job,
            when=2.0,
            name=job_name,
            data={
                'user_id': user_id,
                'chat_id': chat_id,
                'media_group_id': media_group_id,
            }
        )

    # Остаёмся в текущем состоянии, чтобы принять оставшиеся фото из альбома
    current_part = context.user_data.get('current_part', 0)
    return ANSWERING_PARTS if current_part > 0 else states.ANSWERING


async def _process_media_group_task25_job(context):
    """Job callback: обработка всех фотографий из альбома после задержки."""
    job_data = context.job.data
    user_id = job_data['user_id']
    chat_id = job_data['chat_id']
    media_group_id = job_data['media_group_id']

    user_data = context.application.user_data.get(user_id, {})
    group_info = user_data.get('pending_media_group', {}).get(media_group_id)
    if not group_info:
        return

    photo_file_ids = group_info['photo_file_ids']
    topic = group_info['topic']
    current_part = group_info.get('current_part', 0)
    status_msg_id = group_info.get('status_msg_id')

    # Очищаем буфер
    user_data.get('pending_media_group', {}).pop(media_group_id, None)
    if not user_data.get('pending_media_group'):
        user_data.pop('pending_media_group', None)

    # Удаляем статусное сообщение
    if status_msg_id:
        try:
            await context.bot.delete_message(chat_id, status_msg_id)
        except Exception:
            pass

    # Проверяем доступность OCR
    vision_service = get_vision_service()
    if not vision_service.is_available:
        await context.bot.send_message(
            chat_id,
            "❌ Функция распознавания текста с фото недоступна.\n"
            "Пожалуйста, введите ответ текстом или загрузите документ."
        )
        return

    # Обрабатываем все фотографии
    topic_title = topic.get('title', '') if isinstance(topic, dict) else str(topic)
    ocr_context = f"ЕГЭ обществознание, задание 25 (развернутый ответ), тема: {topic_title}"

    processing_msg = await context.bot.send_message(
        chat_id,
        f"📸 Распознаю текст с {len(photo_file_ids)} фотографий...\n"
        "Это может занять немного больше времени."
    )

    all_texts = []
    for i, file_id in enumerate(photo_file_ids, 1):
        try:
            text = await process_photo_by_file_id(file_id, context.bot, task_context=ocr_context)
            if text:
                all_texts.append(text)
        except Exception as e:
            logger.error(f"Error processing photo {i}/{len(photo_file_ids)} in media group: {e}")

    # Удаляем сообщение о обработке
    try:
        await processing_msg.delete()
    except Exception:
        pass

    if not all_texts:
        await context.bot.send_message(
            chat_id,
            "❌ Не удалось распознать текст ни с одной фотографии.\n\n"
            "Попробуйте:\n• Сделать фото при лучшем освещении\n"
            "• Убедиться, что текст чёткий\n• Ввести ответ текстом"
        )
        return

    # Объединяем текст со всех фотографий
    if len(all_texts) == 1:
        combined_text = all_texts[0]
    else:
        combined_text = "\n\n".join(all_texts)

    # Сообщаем об успешном распознавании
    preview = combined_text[:500] + "..." if len(combined_text) > 500 else combined_text
    import html as html_module
    preview_escaped = html_module.escape(preview)
    await context.bot.send_message(
        chat_id,
        f"✅ Текст распознан с {len(all_texts)} фото!\n\n"
        f"📝 <b>Предпросмотр:</b>\n"
        f"<code>{preview_escaped}</code>\n\n"
        f"🔍 Проверяю развернутый ответ...",
        parse_mode='HTML'
    )

    # Сохраняем текст и запускаем оценку
    if current_part > 0:
        # Режим ответа по частям
        user_data['document_text'] = combined_text
        await _evaluate_media_group_parts(context, chat_id, user_id, user_data, topic, current_part, combined_text)
    else:
        # Полный ответ — запускаем полную оценку
        user_data['document_text'] = combined_text
        await _evaluate_media_group_answer(context, chat_id, user_id, user_data, topic, combined_text)


async def _evaluate_media_group_parts(context, chat_id, user_id, user_data, topic, current_part, text):
    """Обработка ответа по частям для альбома (аналог handle_answer_parts)."""
    answers = user_data.get('part_answers', {})
    answers[f'part{current_part}'] = text
    user_data['part_answers'] = answers

    if current_part < 3:
        current_part += 1
        user_data['current_part'] = current_part

        parts = topic.get('parts', {})
        part_text = parts.get(f'part{current_part}', '')
        part_names = {2: "Ответ на вопрос", 3: "Примеры"}

        msg_text = (
            f"✅ Часть {current_part - 1} получена!\n\n"
            f"<b>Часть {current_part}: {part_names.get(current_part, '')}</b>\n\n"
            f"{part_text}\n\n"
            f"💡 <i>Отправьте ваш ответ</i>"
        )

        await context.bot.send_message(chat_id, msg_text, parse_mode='HTML')

        # Обновляем состояние ConversationHandler
        _update_conversation_state(context, chat_id, user_id, ANSWERING_PARTS)
    else:
        # Все части собраны — объединяем и проверяем
        full_answer = "\n\n".join([
            f"Часть 1 (Обоснование):\n{answers.get('part1', '')}",
            f"Часть 2 (Ответ):\n{answers.get('part2', '')}",
            f"Часть 3 (Примеры):\n{answers.get('part3', '')}"
        ])
        user_data.pop('part_answers', None)
        user_data.pop('current_part', None)
        user_data['document_text'] = full_answer
        await _evaluate_media_group_answer(context, chat_id, user_id, user_data, topic, full_answer)


async def _evaluate_media_group_answer(context, chat_id, user_id, user_data, topic, user_answer):
    """Полная оценка ответа из альбома (аналог safe_handle_answer_task25 для job)."""
    bot_data = context.application.bot_data

    # Проверяем минимальную длину
    if len(user_answer) < 100:
        await context.bot.send_message(
            chat_id,
            "❌ Ответ слишком короткий. Задание 25 требует развёрнутого ответа с обоснованием и примерами.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отменить", callback_data="t25_menu")
            ]])
        )
        _update_conversation_state(context, chat_id, user_id, states.ANSWERING)
        return

    # Проверка лимитов AI-проверок
    freemium_manager = bot_data.get('freemium_manager')
    is_premium = False

    if freemium_manager:
        can_use, remaining, limit_msg = await freemium_manager.check_ai_limit(user_id, 'task25')
        if not can_use:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Попробовать за 1₽", callback_data="subscribe_start")],
                [InlineKeyboardButton("💎 Оформить подписку", callback_data="subscribe_start")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ])
            await context.bot.send_message(chat_id, limit_msg, reply_markup=kb, parse_mode=ParseMode.HTML)
            _update_conversation_state(context, chat_id, user_id, states.ANSWERING)
            return

        limit_info = await freemium_manager.get_limit_info(user_id, 'task25')
        is_premium = limit_info.get('is_premium', False)

    # Обновляем дневной стрик
    current_date = date.today().isoformat()
    last_activity_date = user_data.get('last_activity_date')
    if last_activity_date != current_date:
        await db.update_daily_streak(user_id)
        user_data['last_activity_date'] = current_date

    # Показываем сообщение о проверке
    thinking_msg = await context.bot.send_message(
        chat_id, "🔍 Анализирую ваш ответ..."
    )

    try:
        global evaluator
        if evaluator is None and AI_EVALUATOR_AVAILABLE:
            try:
                strictness = StrictnessLevel.STANDARD
                evaluator = Task25AIEvaluator(strictness=strictness)
            except Exception as e:
                logger.error(f"Failed to initialize evaluator: {e}")
                evaluator = None

        if evaluator and AI_EVALUATOR_AVAILABLE:
            try:
                result = await evaluator.evaluate(
                    answer=user_answer,
                    topic=topic,
                    user_id=user_id
                )

                if hasattr(result, 'format_feedback'):
                    detailed_feedback = result.format_feedback()
                else:
                    detailed_feedback = _format_evaluation_result(result, topic)

                score = result.total_score

                if is_premium:
                    feedback_text = detailed_feedback
                else:
                    if freemium_manager:
                        feedback_text = freemium_manager.simplify_feedback_for_freemium(
                            detailed_feedback, score, 6
                        )
                    else:
                        feedback_text = detailed_feedback

            except Exception as e:
                logger.error(f"Evaluation error in media group job: {e}")
                feedback_text = _get_fallback_feedback(user_answer, topic)
                score = _estimate_score(user_answer)
        else:
            feedback_text = _get_fallback_feedback(user_answer, topic)
            score = _estimate_score(user_answer)

        # Удаляем сообщение "Анализирую"
        try:
            await thinking_msg.delete()
        except Exception:
            pass

        # Регистрируем использование AI-проверки
        if freemium_manager:
            await db.increment_ai_check_usage(user_id)
            limit_info = await freemium_manager.get_limit_info(user_id, 'task25')
            remaining_checks = limit_info.get('checks_remaining', 0)
            if not limit_info.get('is_premium') and remaining_checks <= 3:
                if remaining_checks > 0:
                    feedback_text += f"\n\n📊 Осталось проверок сегодня: <b>{remaining_checks}</b>"
                else:
                    feedback_text += f"\n\n⏳ Бесплатные проверки на сегодня исчерпаны. Лимит обновится завтра."

        # Сохраняем результат
        result_data = {
            'topic_title': topic.get('title', 'Неизвестная тема'),
            'topic_id': topic.get('id'),
            'block': topic.get('block', 'Общие темы'),
            'score': score,
            'max_score': 6,
            'timestamp': datetime.now().isoformat()
        }

        if 'task25_results' not in user_data:
            user_data['task25_results'] = []
        user_data['task25_results'].append(result_data)

        # Обновляем серию правильных ответов
        if score >= 5:
            user_data['correct_streak'] = user_data.get('correct_streak', 0) + 1
        else:
            user_data['correct_streak'] = 0

        # Кнопки действий
        kb = AdaptiveKeyboards.create_result_keyboard(
            score=score, max_score=6, module_code="t25"
        )

        await context.bot.send_message(
            chat_id, feedback_text, reply_markup=kb, parse_mode=ParseMode.HTML
        )

        # Обновляем состояние ConversationHandler на AWAITING_FEEDBACK
        _update_conversation_state(context, chat_id, user_id, states.AWAITING_FEEDBACK)

    except Exception as e:
        logger.error(f"Error in media group evaluation: {e}")
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id,
            "❌ Произошла ошибка при проверке. Попробуйте ещё раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t25_retry"),
                InlineKeyboardButton("📝 В меню", callback_data="t25_menu")
            ]])
        )
        _update_conversation_state(context, chat_id, user_id, states.CHOOSING_MODE)


def _update_conversation_state(context, chat_id, user_id, new_state):
    """Обновляет состояние ConversationHandler для task25 из job callback."""
    try:
        for handler_group in context.application.handlers.values():
            for handler in handler_group:
                if isinstance(handler, ConversationHandler) and handler.name == "task25_conversation":
                    key = (chat_id, user_id)
                    handler._conversations[key] = new_state
                    return
    except Exception as e:
        logger.error(f"Failed to update conversation state: {e}")


@safe_handler()
async def handle_all_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все доступные примеры."""
    query = update.callback_query
    
    # Фильтруем темы с примерами
    topics_with_examples = [t for t in task25_data.get('topics', []) 
                           if 'example_answers' in t]
    
    if not topics_with_examples:
        await query.edit_message_text(
            "❌ Примеры ответов пока не добавлены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t25_bank_search")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = f"📚 <b>Банк эталонных ответов</b>\n"
    text += f"Доступно примеров: {len(topics_with_examples)}\n\n"
    
    # Группируем по блокам
    by_block = {}
    for topic in topics_with_examples:
        block = topic.get('block', 'Другое')
        if block not in by_block:
            by_block[block] = []
        by_block[block].append(topic)
    
    kb_buttons = []
    for block, topics in sorted(by_block.items()):
        kb_buttons.append([InlineKeyboardButton(
            f"{block} ({len(topics)} тем)",
            callback_data=f"t25_examples_block:{block}"
        )])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_bank_search")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def show_theory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории по заданию 25."""
    query = update.callback_query
    
    text = """📚 <b>Теория по заданию 25</b>

<b>Структура развернутого ответа:</b>

1️⃣ <b>Обоснование (К1 - 2 балла)</b>
• Теоретическое обоснование тезиса
• Опора на обществоведческие понятия
• Логическая связь с вопросом

2️⃣ <b>Ответ на вопрос (К2 - 1 балл)</b>
• Четкий и однозначный ответ
• Соответствие заданному вопросу

3️⃣ <b>Примеры (К3 - 3 балла)</b>
• Три развернутых примера
• Из разных сфер общественной жизни
• Конкретные, с деталями

<b>Типичные ошибки:</b>
❌ Отсутствие теоретического обоснования
❌ Примеры из одной сферы
❌ Абстрактные примеры без конкретики
❌ Несоответствие примеров тезису"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎯 Попробовать", callback_data="t25_practice"),
        InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE