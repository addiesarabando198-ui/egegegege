# Начало файла task20/handlers.py
import asyncio
import logging
import os
import csv
import io
import json
import random
import re
from typing import Optional, Dict, List, Any
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from core import states, db
from core.states import ANSWERING_T20, SEARCHING, VIEWING_EXAMPLE, CONFIRMING_RESET
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from core.ui_helpers import (
    show_thinking_animation,
    show_streak_notification,
    show_extended_thinking_animation,
    show_ai_evaluation_animation,
    get_personalized_greeting,
    get_motivational_message,
    create_visual_progress
)
from core.error_handler import safe_handler, auto_answer_callback
from core.plugin_loader import build_main_menu
from core.state_validator import validate_state_transition, state_validator
from core.utils import safe_edit_message
from core.menu_handlers import handle_to_main_menu
from core.freemium_manager import get_freemium_manager
from telegram.error import BadRequest
from core.document_processor import DocumentHandlerMixin
from core.migration import ensure_module_migration
from core.vision_service import process_photo_message

logger = logging.getLogger(__name__)

# Глобальные переменные для данных
task20_data = {}
topic_selector = None
evaluator = None

# Импорты внутренних модулей ПОСЛЕ определения переменных
try:
    from .evaluator import Task20AIEvaluator, EvaluationResult, AI_EVALUATOR_AVAILABLE
except ImportError as e:
    logger.error(f"Failed to import evaluator: {e}")
    AI_EVALUATOR_AVAILABLE = False

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

try:
    from .user_experience import UserProgress, SmartRecommendations
except ImportError as e:
    logger.error(f"Failed to import user_experience: {e}")
    UserProgress = None
    SmartRecommendations = None

async def clear_task20_cache():
    """Очистка кэша данных task20."""
    if cache:
        try:
            await cache.delete('task20_data')
            logger.info("Task20 cache cleared successfully")
        except Exception as e:
            logger.error(f"Failed to clear task20 cache: {e}")

async def delete_previous_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_message_id: Optional[int] = None):
    """Удаляет предыдущие сообщения диалога task20."""
    if not hasattr(context, 'bot') or not context.bot:
        logger.warning("Bot instance not available for message deletion")
        return

    # Список ключей с ID сообщений для удаления
    message_keys = [
        'task20_question_msg_id',   # Сообщение с вопросом
        'task20_answer_msg_id',     # Сообщение с ответом пользователя
        'task20_result_msg_id',     # Сообщение с результатом проверки
        'task20_thinking_msg_id',   # Сообщение "Анализирую..."
        'task20_example_msg_id'     # Сообщение с примером
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

    logger.info(f"Task20: Deleted {deleted_count}/{len(messages_to_delete)} messages")

@safe_handler()
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки Главное меню - вызывает глобальный обработчик."""
    return await handle_to_main_menu(update, context)

async def init_task20_data(force_reload=False):
    """Инициализация данных с кэшированием."""
    global task20_data, evaluator, topic_selector
    
    # Если требуется принудительная перезагрузка, очищаем кэш
    if force_reload and cache:
        await clear_task20_cache()
    
    # Проверяем кэш
    if cache and not force_reload:
        cached_data = await cache.get('task20_data')
        if cached_data and cached_data.get('topics'):
            task20_data = cached_data
            if TopicSelector:
                topic_selector = TopicSelector(task20_data['topics'])
            logger.info(f"Loaded task20 data from cache: {len(task20_data['topics'])} topics")
            return
    
    # Загружаем из файла
    data_file = os.path.join(os.path.dirname(__file__), "task20_topics.json")
    
    if not os.path.exists(data_file):
        logger.error(f"Topics file not found: {data_file}")
        task20_data = {
            "topics": [],
            "topic_by_id": {},
            "topics_by_block": {},
            "blocks": {}
        }
        topic_selector = None
        return
    
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            topics_list = json.load(f)
        
        if not isinstance(topics_list, list):
            logger.error(f"Invalid topics file format: expected list, got {type(topics_list)}")
            topics_list = []
        
        # Преобразуем список тем в нужную структуру
        all_topics = []
        topic_by_id = {}
        topics_by_block = {}
        blocks = {}
        
        for topic in topics_list:
            if not isinstance(topic, dict):
                logger.warning(f"Skipping invalid topic: {topic}")
                continue
            
            if 'id' not in topic or 'title' not in topic:
                logger.warning(f"Skipping topic without id or title: {topic}")
                continue
            
            # Проверяем наличие примеров
            if 'example_arguments' not in topic or not topic['example_arguments']:
                logger.warning(f"Topic {topic['id']} has no example_arguments")
            
            # Добавляем тему в общий список
            all_topics.append(topic)
            
            # Индексируем по ID
            topic_by_id[str(topic["id"])] = topic
            
            # Группируем по блокам
            block_name = topic.get("block", "Без категории")
            if block_name not in topics_by_block:
                topics_by_block[block_name] = []
                blocks[block_name] = {"topics": []}
            
            topics_by_block[block_name].append(topic)
            blocks[block_name]["topics"].append(topic)
        
        # Формируем итоговую структуру данных
        task20_data = {
            "topics": all_topics,
            "topic_by_id": topic_by_id,
            "topics_by_block": topics_by_block,
            "blocks": blocks
        }
        
        logger.info(f"Loaded {len(all_topics)} topics for task20")
        logger.info(f"Blocks: {list(blocks.keys())}")
        
        # Проверяем, что данные действительно загружены
        if not all_topics:
            logger.warning("No topics loaded from file - check file structure")
        
        # Сохраняем в кэш только если есть данные
        if cache and all_topics:
            await cache.set('task20_data', task20_data)
            logger.info("Task20 data cached successfully")
        
        # Создаём селектор
        if TopicSelector and all_topics:
            topic_selector = TopicSelector(all_topics)
        else:
            topic_selector = None
            
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse task20 topics JSON: {e}")
        task20_data = {"topics": [], "topic_by_id": {}, "topics_by_block": {}, "blocks": {}}
        topic_selector = None
    except Exception as e:
        logger.error(f"Failed to load task20 data: {e}")
        task20_data = {"topics": [], "topic_by_id": {}, "topics_by_block": {}, "blocks": {}}
        topic_selector = None
    
    # Инициализируем AI evaluator
    logger.info(f"AI_EVALUATOR_AVAILABLE = {AI_EVALUATOR_AVAILABLE}")
    
    if AI_EVALUATOR_AVAILABLE:
        try:
            evaluator = Task20AIEvaluator()
            logger.info("Task20 AI evaluator initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize AI evaluator: {e}", exc_info=True)
            evaluator = None
    else:
        logger.warning("AI evaluator not available for task20 - check imports")
        evaluator = None
        
    logger.info(f"Final evaluator status: {'initialized' if evaluator else 'not initialized'}")

@safe_handler()
@validate_state_transition({ConversationHandler.END, None})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 20 из главного меню."""
    query = update.callback_query
    
    # Очищаем контекст от данных других модулей
    keys_to_remove = [
        'current_topic',
        'task19_current_topic', 
        'task24_current_topic',
        'task25_current_topic',
        'answer_processing',
        'current_block',
        'waiting_for_bank_search'
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # ВАЖНО: Устанавливаем активный модуль
    context.user_data['active_module'] = 't20'
    context.user_data['current_module'] = 't20'
    
    # Получаем статистику пользователя
    results = context.user_data.get('task20_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r['topic_id'] for r in results)) / 50 * 100) if results else 0
    }
    
    # Персонализированное приветствие
    greeting = get_personalized_greeting(user_stats)
    
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 20",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    # Адаптивная клавиатура
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t20")
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def cmd_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task20."""
    # Автоматическая миграция при входе
    ensure_module_migration(context, 'task20', task20_data)
    
    # Очищаем контекст
    keys_to_remove = [
        'current_topic',
        'task19_current_topic', 
        'task24_current_topic',
        'task25_current_topic',
        'answer_processing',
        'current_block',
        'waiting_for_bank_search'
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # Устанавливаем активный модуль
    context.user_data['active_module'] = 't20'
    context.user_data['current_module'] = 't20'
    
    # Получаем статистику
    results = context.user_data.get('task20_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': 0
    }
    
    text = MessageFormatter.format_welcome_message(
        "задание 20",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t20")
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def show_achievement_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, achievement: Dict):
    """Показать уведомление о достижении."""
    text = f"""
🎉 <b>Новое достижение!</b>

{achievement.get('icon', '🏆')} <b>{achievement.get('name', 'Достижение')}</b>
<i>{achievement.get('description', '')}</i>

{achievement.get('reward_text', '')}
"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Отлично!", callback_data="t20_achievement_ok")
    ]])
    
    # Отправляем как отдельное сообщение
    try:
        msg = await update.effective_message.reply_text(
            text, 
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        # Удаляем через 10 секунд
        context.job_queue.run_once(
            lambda ctx: msg.delete(),
            when=10,
            name=f"delete_achievement_{msg.message_id}"
        )
    except Exception as e:
        logger.error(f"Error showing achievement notification: {e}")


@safe_handler()
async def handle_achievement_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки OK в уведомлении о достижении."""
    query = update.callback_query
    
    try:
        await query.message.delete()
    except Exception:
        pass
    
    # Не меняем состояние conversation handler
    return None

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима практики."""
    query = update.callback_query
    
    # Проверяем загрузку данных
    if not task20_data or not task20_data.get('topics'):
        logger.warning("Task20 data not loaded when accessing practice mode")
        
        # Пытаемся перезагрузить данные
        await query.answer("⏳ Загружаю данные...", show_alert=False)
        await init_task20_data()
        
        # Проверяем еще раз после попытки загрузки
        if not task20_data or not task20_data.get('topics'):
            text = """💪 <b>Режим практики</b>

❌ <b>Данные заданий не загружены</b>

<b>Проблема:</b>
Не удалось загрузить темы для практики.

<b>Возможные причины:</b>
• Отсутствует файл task20/task20_topics.json
• Файл содержит ошибки или пустой
• Проблемы с доступом к файлу

<b>Что делать:</b>
1. Убедитесь, что файл существует и доступен
2. Проверьте корректность JSON-структуры
3. Перезапустите бота

Обратитесь к администратору для решения проблемы."""
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t20_practice")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
            ])
            
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return states.CHOOSING_MODE
    
    # Если данные загружены, показываем меню практики
    results = context.user_data.get('task20_results', [])
    topics_done = len(set(r['topic_id'] for r in results))
    total_topics = len(task20_data.get('topics', []))
    
    text = f"""💪 <b>Режим практики</b>

📊 Прогресс: {topics_done}/{total_topics} тем изучено

Выберите способ тренировки:"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t20_random_all")],
        [InlineKeyboardButton("📚 Выбрать блок", callback_data="t20_select_block")],
        [InlineKeyboardButton("📋 Список всех тем", callback_data="t20_list_topics")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим теории и советов."""
    query = update.callback_query
    
    text = """📚 <b>Теория по заданию 20</b>

<b>Что требуется в задании 20?</b>
Сформулировать суждения (аргументы) абстрактного характера с элементами обобщения.

<b>Ключевые отличия от задания 19:</b>
• Задание 19 - конкретные примеры
• Задание 20 - абстрактные суждения

<b>Критерии оценивания:</b>
• 3 балла - приведены 3 суждения правильного типа
• 2 балла - приведено 2 суждения
• 1 балл - приведено 1 суждение
• 0 баллов - суждения неверного типа или отсутствуют

<b>Важно:</b> Если наряду с требуемыми суждениями приведено 2 или более дополнительных суждения с ошибками, ответ оценивается в 0 баллов!

<b>Новые возможности:</b>
🔧 <b>Работа над ошибками</b> - повторите темы с низкими баллами
📈 <b>Детальная статистика</b> - графики вашего прогресса
🏅 <b>Достижения</b> - мотивация для улучшения результатов
⚙️ <b>Уровни строгости</b> - от мягкого до экспертного

Выберите раздел для изучения:"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Как писать суждения", callback_data="t20_how_to_write")],
        [InlineKeyboardButton("✅ Правильные примеры", callback_data="t20_good_examples")],
        [InlineKeyboardButton("❌ Типичные ошибки", callback_data="t20_common_mistakes")],
        [InlineKeyboardButton("🔤 Полезные конструкции", callback_data="t20_useful_phrases")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def how_to_write(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Как писать суждения."""
    query = update.callback_query
    
    text = """📝 <b>Как писать суждения для задания 20</b>

<b>1. Структура суждения:</b>
• Начните с обобщающего тезиса
• Раскройте причинно-следственную связь
• Завершите выводом или следствием

<b>2. Используйте абстрактные понятия:</b>
• "Экономические субъекты" вместо "компания Apple"
• "Развитые страны" вместо "США и Германия"
• "Современные технологии" вместо "iPhone 15"

<b>3. Применяйте обобщающие слова:</b>
• Процессы: способствует, приводит к, порождает
• Влияние: определяет, формирует, трансформирует
• Связи: обусловливает, детерминирует, коррелирует

<b>4. Избегайте:</b>
• Конкретных дат и чисел
• Названий организаций и стран
• Имён конкретных людей
• Описания единичных событий

<b>Пример правильного суждения:</b>
<i>"Развитие информационных технологий способствует глобализации экономических процессов, позволяя хозяйствующим субъектам осуществлять деятельность вне зависимости от географических границ."</i>"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE
    
# Добавьте эти функции в файл task20/handlers.py

@safe_handler()
async def search_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инициализация поиска в банке суждений."""
    query = update.callback_query
    
    await query.edit_message_text(
        "🔍 <b>Поиск в банке суждений</b>\n\n"
        "Отправьте название темы или ключевые слова для поиска:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="t20_examples")
        ]]),
        parse_mode=ParseMode.HTML
    )
    
    context.user_data['waiting_for_bank_search'] = True
    return states.SEARCHING

@safe_handler()
async def view_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ конкретного примера из банка суждений."""
    query = update.callback_query
    
    # Извлекаем индекс из callback_data
    try:
        topic_idx = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Ошибка: неверный формат данных", show_alert=True)
        return states.CHOOSING_MODE
    
    topics = task20_data.get('topics', [])
    if not topics or topic_idx >= len(topics):
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    topic = topics[topic_idx]
    context.user_data['bank_current_idx'] = topic_idx
    context.user_data['viewing_mode'] = 'example'
    
    # Формируем текст с примерами
    text = f"🏦 <b>Банк суждений</b>\n\n"
    text += f"📚 <b>Тема {topic_idx + 1}/{len(topics)}</b>\n"
    text += f"{topic['title']}\n\n"
    
    if 'task_text' in topic:
        text += f"<b>Задание:</b>\n{topic['task_text']}\n\n"
    
    text += "<b>Эталонные суждения:</b>\n\n"
    
    # ИСПРАВЛЕНО: используем правильное имя поля - example_arguments вместо examples
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"{i}. <b>{example['type']}</b>\n"
        text += f"└ <i>{example['argument']}</i>\n"
        if 'explanation' in example:
            text += f"   💡 <code>{example['explanation']}</code>\n\n"
        else:
            text += "\n"
    
    # Кнопки навигации
    kb_buttons = []
    
    # Навигация между примерами
    nav_row = []
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Пред.", callback_data=f"t20_prev_example"))
    nav_row.append(InlineKeyboardButton(f"{topic_idx + 1}/{len(topics)}", callback_data="noop"))
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("След. ➡️", callback_data=f"t20_next_example"))
    kb_buttons.append(nav_row)
    
    # Кнопка "Отработать тему"
    kb_buttons.append([InlineKeyboardButton("🎯 Отработать эту тему", callback_data=f"t20_topic:{topic['id']}")])
    
    # Дополнительные действия
    kb_buttons.extend([
        [InlineKeyboardButton("📋 Все темы", callback_data="t20_view_all_examples")],
        [InlineKeyboardButton("⬅️ К банку суждений", callback_data="t20_back_examples")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.VIEWING_EXAMPLE

@safe_handler()
async def view_all_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ всех примеров по блокам."""
    query = update.callback_query
    
    # Если callback_data содержит блок (t20_all_examples:block_name)
    if ":" in query.data:
        block_name = query.data.split(":", 1)[1]
        return await show_block_examples(update, context, block_name)
    
    # Иначе показываем список блоков
    blocks = {}
    for topic in task20_data.get('topics', []):
        block = topic.get('block', 'Другое')
        if block not in blocks:
            blocks[block] = []
        blocks[block].append(topic)
    
    text = "🏦 <b>Банк суждений по блокам</b>\n\n"
    text += "Выберите блок для просмотра:\n\n"
    
    kb_buttons = []
    for block_name, topics in sorted(blocks.items()):
        kb_buttons.append([InlineKeyboardButton(
            f"📚 {block_name} ({len(topics)} тем)",
            callback_data=f"t20_all_examples:{block_name}"
        )])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_examples")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def show_block_examples(update: Update, context: ContextTypes.DEFAULT_TYPE, block_name: str):
    """Показ примеров из конкретного блока."""
    query = update.callback_query
    
    # Находим все темы блока
    block_topics = []
    for idx, topic in enumerate(task20_data.get('topics', [])):
        if topic.get('block') == block_name:
            block_topics.append((idx, topic))
    
    if not block_topics:
        await query.answer("Темы не найдены", show_alert=True)
        return states.CHOOSING_MODE
    
    text = f"📚 <b>Блок: {block_name}</b>\n\n"
    text += f"Найдено тем: {len(block_topics)}\n\n"
    
    kb_buttons = []
    for idx, topic in block_topics[:15]:  # Максимум 15 тем
        kb_buttons.append([InlineKeyboardButton(
            f"📖 {topic['title'][:50]}...",
            callback_data=f"t20_bank_nav:{idx}"
        )])
    
    if len(block_topics) > 15:
        text += f"\n<i>Показаны первые 15 из {len(block_topics)} тем</i>"
    
    kb_buttons.append([InlineKeyboardButton("⬅️ К блокам", callback_data="t20_view_all_examples")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def next_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующему примеру."""
    query = update.callback_query
    
    current_idx = context.user_data.get('bank_current_idx', 0)
    topics = task20_data.get('topics', [])
    
    # Увеличиваем индекс
    new_idx = min(current_idx + 1, len(topics) - 1)
    
    if new_idx == current_idx:
        await query.answer("Это последняя тема", show_alert=True)
        return states.VIEWING_EXAMPLE
    
    # Обновляем данные и показываем новый пример
    query.data = f"t20_view_example:{new_idx}"
    return await view_example(update, context)

@safe_handler()
async def prev_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к предыдущему примеру."""
    query = update.callback_query
    
    current_idx = context.user_data.get('bank_current_idx', 0)
    
    # Уменьшаем индекс
    new_idx = max(current_idx - 1, 0)
    
    if new_idx == current_idx:
        await query.answer("Это первая тема", show_alert=True)
        return states.VIEWING_EXAMPLE
    
    # Обновляем данные и показываем новый пример
    query.data = f"t20_view_example:{new_idx}"
    return await view_example(update, context)

@safe_handler()
async def back_to_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к банку примеров."""
    query = update.callback_query
    
    # Очищаем временные данные
    context.user_data.pop('viewing_mode', None)
    context.user_data.pop('bank_current_idx', None)
    
    # Возвращаемся к главному меню банка
    return await examples_bank(update, context)

@safe_handler()
async def cancel_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сброса прогресса."""
    query = update.callback_query
    
    await query.answer("✅ Сброс отменён")
    
    # Возвращаемся в настройки
    return await settings_mode(update, context)

@safe_handler()
async def handle_unexpected_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка неожиданных текстовых сообщений."""
    
    # Проверяем, не ждем ли мы поискового запроса
    if context.user_data.get('waiting_for_bank_search'):
        return await handle_bank_search(update, context)
    
    # Определяем текущее состояние
    current_state = context.user_data.get('current_state', states.CHOOSING_MODE)
    
    # Формируем сообщение в зависимости от состояния
    if current_state == states.ANSWERING_T20:
        text = ("⚠️ Похоже, вы отправили сообщение не в том формате.\n\n"
                "Для ответа на задание 20 отправьте все три суждения одним сообщением.")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отменить", callback_data="t20_menu")
        ]])
    else:
        text = "ℹ️ Пожалуйста, используйте кнопки меню для навигации."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 В меню задания 20", callback_data="t20_menu"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
        ]])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return current_state

@safe_handler()
async def skip_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск текущего вопроса."""
    query = update.callback_query
    
    topic = context.user_data.get('current_topic')
    
    if not topic:
        await query.answer("Нет активного задания", show_alert=True)
        return states.CHOOSING_MODE
    
    # Сохраняем пропуск в статистику
    result = {
        'topic': topic['title'],
        'topic_id': topic['id'],
        'block': topic['block'],
        'score': 0,
        'max_score': 3,
        'skipped': True,
        'timestamp': datetime.now().isoformat()
    }
    
    if 'task20_results' not in context.user_data:
        context.user_data['task20_results'] = []
    context.user_data['task20_results'].append(result)
    
    # Показываем сообщение о пропуске
    text = (
        "⏭️ <b>Задание пропущено</b>\n\n"
        f"Тема: {topic['title']}\n\n"
        "Пропущенные задания можно выполнить позже в режиме "
        "«Работа над ошибками»."
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Новая тема", callback_data="t20_new"),
            InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")
        ],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def safe_handle_answer_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасная обработка ответа на задание 20."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")
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
    context.user_data['task20_answer_msg_id'] = update.message.message_id

    # Проверяем минимальную длину
    if len(user_answer) < 50:
        await update.message.reply_text(
            "❌ Ответ слишком короткий. Приведите три развернутых суждения.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отменить", callback_data="t20_menu")
            ]])
        )
        return states.ANSWERING_T20

    # FREEMIUM: Проверяем лимит AI-проверок
    user_id = update.effective_user.id

    # ========== ОБНОВЛЕНИЕ ДНЕВНОГО СТРИКА ==========
    # Обновляем дневной стрик (если еще не обновлен сегодня)
    current_date = date.today().isoformat()
    last_activity_date = context.user_data.get('last_activity_date')

    if last_activity_date != current_date:
        daily_current, daily_max = await db.update_daily_streak(user_id)
        context.user_data['last_activity_date'] = current_date
        logger.info(f"[Task20] Daily streak updated for user {user_id}: {daily_current}/{daily_max}")

    module_code = 'task20'
    freemium_manager = get_freemium_manager(
        context.application.bot_data.get('subscription_manager')
    )

    can_use, remaining, limit_msg = await freemium_manager.check_ai_limit(user_id, module_code)

    if not can_use:
        # Пользователь исчерпал лимит
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
        return states.CHOOSING_MODE

    # Получаем информацию о подписке для дифференциации фидбека
    limit_info = await freemium_manager.get_limit_info(user_id, module_code)
    is_premium = limit_info.get('is_premium', False)

    # Показываем анимацию обработки
    thinking_msg = await show_ai_evaluation_animation(
        update.message,
        duration=40  # 40 секунд для task20
    )

    # Сохраняем ID сообщения "думаю"
    context.user_data['task20_thinking_msg_id'] = thinking_msg.message_id

    try:
        # Оцениваем ответ
        if evaluator and AI_EVALUATOR_AVAILABLE:
            try:
                result = await evaluator.evaluate(
                    answer=user_answer,
                    topic=topic['title'],
                    task_text=topic.get('task_text', ''),
                    user_id=update.effective_user.id
                )
                score = result.total_score

                # Формируем фидбек с учетом подписки
                if is_premium:
                    feedback_text = _format_evaluation_result(result, topic, user_answer)
                else:
                    # Упрощенный фидбек для freemium пользователей
                    detailed_feedback = _format_evaluation_result(result, topic, user_answer)
                    feedback_text = freemium_manager.simplify_feedback_for_freemium(
                        detailed_feedback,
                        score,
                        result.max_score
                    )
                
            except Exception as e:
                logger.error(f"Evaluation error: {e}")
                # Fallback оценка
                lines = [l.strip() for l in user_answer.split('\n') if l.strip() and len(l.strip()) > 20]
                score = min(3, len(lines))
                feedback_text = _format_evaluation_result({
                    'total_score': score,
                    'max_score': 3,
                    'feedback': 'Ваш ответ принят.',
                    'suggestions': ['Изучите примеры в банке заданий']
                }, topic, user_answer)
        else:
            # Простая оценка без AI
            lines = [l.strip() for l in user_answer.split('\n') if l.strip() and len(l.strip()) > 20]
            score = min(3, len(lines))
            feedback_text = _format_evaluation_result({
                'total_score': score,
                'max_score': 3,
                'feedback': 'Ваш ответ принят.',
                'suggestions': ['Изучите примеры в банке заданий']
            }, topic, user_answer)
        
        # Удаляем анимацию
        await thinking_msg.delete()

        # FREEMIUM: Расходуем AI-проверку
        await freemium_manager.use_ai_check(user_id, module_code)

        # Сохраняем результат
        if 'task20_results' not in context.user_data:
            context.user_data['task20_results'] = []
        
        result_data = {
            'topic': topic['title'],
            'topic_id': topic['id'],
            'block': topic['block'],
            'score': score,
            'max_score': 3,
            'timestamp': datetime.now().isoformat()
        }
        
        context.user_data['task20_results'].append(result_data)
        
        # ИСПРАВЛЕНИЕ: Используем изолированное хранилище task20_practice_stats
        if 'task20_practice_stats' not in context.user_data:
            context.user_data['task20_practice_stats'] = {}
        
        topic_id_str = str(topic['id'])
        if topic_id_str not in context.user_data['task20_practice_stats']:
            context.user_data['task20_practice_stats'][topic_id_str] = {
                'attempts': 0,
                'scores': [],
                'last_attempt': None,
                'best_score': 0,
                'topic_title': topic['title'],
                'topic_id': topic['id'],
                'block': topic['block'],
                'module': 'task20'
            }
        
        # Обновляем статистику
        topic_stats = context.user_data['task20_practice_stats'][topic_id_str]
        topic_stats['attempts'] += 1
        topic_stats['scores'].append(score)
        topic_stats['last_attempt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        topic_stats['best_score'] = max(topic_stats.get('best_score', 0), score)
        
        # Обновляем серию правильных ответов
        if score >= 2:
            context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
        else:
            context.user_data['correct_streak'] = 0
        
        # КРИТИЧЕСКИ ВАЖНО: ОТПРАВЛЯЕМ РЕЗУЛЬТАТ ПОЛЬЗОВАТЕЛЮ!
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎲 Новая тема", callback_data="t20_new"),
                InlineKeyboardButton("🔄 Повторить", callback_data="t20_retry")
            ],
            [InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")]
        ])

        result_msg = await update.message.reply_text(
            feedback_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )

        # Обновляем ID - теперь это сообщение с результатом
        context.user_data.pop('task20_thinking_msg_id', None)
        context.user_data['task20_result_msg_id'] = result_msg.message_id

        context.user_data['t20_last_screen'] = 'feedback'
        context.user_data['t20_last_feedback'] = {
            'text': feedback_text,
            'score': score,
            'topic': topic,
            'user_answer': user_answer  # Сохраняем и ответ пользователя
        }
        return states.CHOOSING_MODE
        
    except Exception as e:
        logger.error(f"Error in safe_handle_answer_task20: {e}")
        
        # Пытаемся удалить анимацию
        try:
            await thinking_msg.delete()
        except:
            pass
        
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке ответа. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")
            ]])
        )
        
        return states.CHOOSING_MODE
    
@safe_handler()
async def good_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры правильных суждений."""
    query = update.callback_query
    
    text = """✅ <b>Примеры правильных суждений</b>

<b>Тема: Роль образования в обществе</b>

<u>Правильно:</u>
<i>"Образование как социальный институт формирует человеческий капитал, обеспечивая передачу накопленных знаний и культурных ценностей от поколения к поколению."</i>

<b>Почему правильно:</b>
• Абстрактные понятия (система, капитал, поколения)
• Причинно-следственная связь
• Обобщающие слова (формирует, обеспечивая)

<b>Тема: Влияние конкуренции</b>

<u>Правильно:</u>
<i>"Конкурентная среда стимулирует предпринимателей к постоянному совершенствованию производственных процессов, что способствует повышению эффективности экономики в целом."</i>

<b>Почему правильно:</b>
• Нет конкретных примеров
• Есть обобщение (экономика в целом)
• Логическая связь между частями

<b>Тема: СМИ и общество</b>

<u>Правильно:</u>
<i>"Средства массовой информации выполняют функцию социального контроля, привлекая внимание общественности к нарушениям норм и злоупотреблениям, что способствует поддержанию социального порядка."</i>

<b>Почему правильно:</b>
• Указана функция, а не конкретный случай
• Абстрактное описание механизма
• Вывод о влиянии на общество"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def common_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Типичные ошибки."""
    query = update.callback_query
    
    text = """❌ <b>Типичные ошибки в задании 20</b>

<b>Ошибка 1: Конкретные примеры вместо суждений</b>

<u>Неправильно:</u>
<i>"В 2020 году компания Tesla увеличила производство электромобилей на 50%, что показывает влияние инноваций на развитие промышленности."</i>

<b>Почему неправильно:</b>
• Конкретная дата (2020 год)
• Название компании (Tesla)
• Конкретные цифры (50%)

<u>Как исправить:</u>
<i>"Внедрение инновационных технологий способствует росту производительности в промышленном секторе и модернизации производственных процессов."</i>

<b>Ошибка 2: Простое перечисление фактов</b>

<u>Неправильно:</u>
<i>"Глобализация есть. Она влияет на культуру. Культуры меняются."</i>

<b>Почему неправильно:</b>
• Нет развёрнутого суждения
• Отсутствуют причинно-следственные связи
• Слишком простые предложения

<b>Ошибка 3: Бытовые рассуждения</b>

<u>Неправильно:</u>
<i>"Все знают, что образование важно для человека, потому что без него никуда."</i>

<b>Почему неправильно:</b>
• Разговорный стиль
• Нет теоретического обоснования
• Отсутствует научная терминология

<b>Помните:</b> Суждение должно звучать как фрагмент научной статьи, а не как пример из жизни!"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def useful_phrases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полезные конструкции."""
    query = update.callback_query
    
    text = """🔤 <b>Полезные конструкции для задания 20</b>

<b>Для выражения влияния:</b>
• способствует развитию...
• приводит к формированию...
• обусловливает появление...
• детерминирует процессы...
• оказывает воздействие на...

<b>Для обобщения:</b>
• в современном обществе...
• в условиях рыночной экономики...
• в процессе социализации...
• в системе общественных отношений...
• в структуре социальных институтов...

<b>Для причинно-следственных связей:</b>
• вследствие чего...
• что позволяет...
• благодаря чему...
• в результате чего...
• это обеспечивает...

<b>Для характеристики процессов:</b>
• трансформация... происходит...
• модернизация... выражается в...
• эволюция... проявляется через...
• динамика... определяется...

<b>Для указания функций:</b>
• выполняет функцию...
• реализует задачу...
• обеспечивает условия для...
• создаёт предпосылки...

<b>Шаблон суждения:</b>
[Субъект] + [действие с обобщающим словом] + [объект], + [связка] + [следствие/результат]

<b>Пример:</b>
<i>"Социальные институты</i> (субъект) <i>формируют</i> (действие) <i>нормативную основу общества</i> (объект), <i>что обеспечивает</i> (связка) <i>стабильность социальных взаимодействий</i> (результат)."
"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def handle_theory_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общий обработчик для разделов теории."""
    query = update.callback_query
    
    if query.data == "t20_how_to_write":
        return await how_to_write(update, context)
    elif query.data == "t20_good_examples":
        return await good_examples(update, context)
    elif query.data == "t20_common_mistakes":
        return await common_mistakes(update, context)
    elif query.data == "t20_useful_phrases":
        return await useful_phrases(update, context)
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ банка примеров с эталонными суждениями."""
    query = update.callback_query
    
    # Проверяем загрузку данных
    if not task20_data or not task20_data.get('topics'):
        logger.warning("Task20 data not loaded when accessing examples bank")
        
        # Пытаемся перезагрузить данные
        await query.answer("⏳ Загружаю данные...", show_alert=False)
        await init_task20_data()
    
    # Получаем все темы
    topics = task20_data.get('topics', [])
    
    if not topics:
        text = """📚 <b>Банк эталонных суждений</b>

❌ <b>Банк примеров пуст</b>

<b>Возможные причины:</b>
• Файл с данными (task20_topics.json) отсутствует
• Файл поврежден или имеет неверный формат
• Проблемы с правами доступа к файлу

<b>Решение:</b>
1. Проверьте наличие файла task20/task20_topics.json
2. Убедитесь, что файл содержит корректный JSON
3. Перезапустите бота после исправления

Обратитесь к администратору для помощи."""
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t20_examples")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
        ])
        
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Показываем первую тему
    topic = topics[0]
    context.user_data['bank_current_idx'] = 0
    
    text = f"📚 <b>Тема 1 из {len(topics)}</b>\n\n"
    text += f"<b>{topic['title']}</b>\n\n"
    text += f"📋 {topic['task_text']}\n\n"
    text += "<b>Эталонные суждения:</b>\n\n"
    
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"{i}. <b>{example['type']}</b>\n"
        text += f"└ <i>{example['argument']}</i>\n\n"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    nav_row.append(InlineKeyboardButton("⏮️", callback_data="noop"))
    nav_row.append(InlineKeyboardButton(
        create_visual_progress(1, len(topics)), 
        callback_data="noop"
    ))
    
    if len(topics) > 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data="t20_bank_nav:1"))
    else:
        nav_row.append(InlineKeyboardButton("⏭️", callback_data="noop"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("🎯 Отработать эту тему", callback_data=f"t20_topic:{topic['id']}")])
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")])
    kb_buttons.append([InlineKeyboardButton("📋 Все темы", callback_data="t20_view_all_examples")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def view_by_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать просмотр суждений по порядку."""
    query = update.callback_query
    
    topics = task20_data.get('topics', [])
    
    if not topics:
        await query.answer("Банк суждений пуст", show_alert=True)
        return states.CHOOSING_MODE
    
    # Сохраняем начальный индекс
    context.user_data['bank_current_idx'] = 0
    
    # Показываем первую тему
    topic = topics[0]
    
    text = f"""🏦 <b>Банк суждений</b>

<b>Тема 1/{len(topics)}:</b> {topic['title']}
<b>Блок:</b> {topic['block']}

<b>Задание:</b>
<i>{topic['task_text']}</i>

<b>📝 Эталонные суждения:</b>

"""
    
    # Показываем суждения
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"<b>{i}. {example['type']}</b>\n"
        text += f"└ <i>{example['argument']}</i>\n\n"
    
    text += "💡 <b>Обратите внимание:</b>\n"
    text += "• Суждения носят абстрактный характер\n"
    text += "• Используются обобщающие слова\n"
    text += "• Нет конкретных примеров и дат"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    # Первая тема - кнопка назад неактивна
    nav_row.append(InlineKeyboardButton("⏮️", callback_data="noop"))
    
    # Прогресс
    progress_display = create_visual_progress(1, len(topics))
    nav_row.append(InlineKeyboardButton(progress_display, callback_data="noop"))
    
    # Кнопка вперед
    if len(topics) > 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data="t20_bank_nav:1"))
    else:
        nav_row.append(InlineKeyboardButton("⏭️", callback_data="noop"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")])
    kb_buttons.append([InlineKeyboardButton("📋 Все темы", callback_data="t20_view_all_examples")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса task20."""
    query = update.callback_query
    
    # Убеждаемся, что данные мигрированы
    ensure_module_migration(context, 'task20', task20_data)
    
    # Используем изолированное хранилище task20_practice_stats
    results = context.user_data.get('task20_results', [])
    task20_stats = context.user_data.get('task20_practice_stats', {})
    
    if not results and not task20_stats:
        text = (
            "📊 <b>Ваш прогресс</b>\n\n"
            "У вас пока нет результатов.\n"
            "Начните практику, чтобы увидеть статистику!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💪 Начать практику", callback_data="t20_practice")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
        ])
    else:
        # Собираем полную статистику
        total_attempts = 0
        total_score = 0
        max_possible = 0
        block_stats = {}
        unique_topics = set()
        
        # Обрабатываем результаты из task20_results
        for result in results:
            total_attempts += 1
            total_score += result.get('score', 0)
            max_possible += result.get('max_score', 3)
            
            block = result.get('block', 'Без категории')
            if block not in block_stats:
                block_stats[block] = {'attempts': 0, 'total_score': 0}
            block_stats[block]['attempts'] += 1
            block_stats[block]['total_score'] += result.get('score', 0)
            
            topic_id = result.get('topic_id', result.get('topic'))
            if topic_id:
                unique_topics.add(str(topic_id))
        
        # Дополняем статистику из task20_practice_stats
        for topic_id_str, topic_data in task20_stats.items():
            if topic_data.get('attempts', 0) > 0 and topic_id_str not in unique_topics:
                attempts = topic_data['attempts']
                scores = topic_data.get('scores', [])
                
                total_attempts += attempts
                total_score += sum(scores)
                max_possible += attempts * 3
                
                block = topic_data.get('block', 'Без категории')
                if block not in block_stats:
                    block_stats[block] = {'attempts': 0, 'total_score': 0}
                block_stats[block]['attempts'] += attempts
                block_stats[block]['total_score'] += sum(scores)
                
                unique_topics.add(topic_id_str)
        
        # Вычисляем метрики
        avg_score = total_score / total_attempts if total_attempts > 0 else 0
        perfect_scores = sum(1 for r in results if r.get('score') == r.get('max_score', 3))
        
        # Добавляем счетчик идеальных из practice_stats
        for topic_data in task20_stats.values():
            perfect_scores += sum(1 for score in topic_data.get('scores', []) if score == 3)
        
        # Визуальный прогресс
        progress_visual = create_visual_progress(total_score, max_possible)
        
        # Формируем текст
        text = f"""📊 <b>Ваш прогресс</b>

<b>Общая статистика:</b>
📝 Выполнено заданий: {total_attempts}
📚 Изучено тем: {len(unique_topics)}
⭐ Средний балл: {avg_score:.1f}/3
🎯 Идеальных ответов: {perfect_scores} ({perfect_scores/total_attempts*100:.0f}% от всех)
📈 Общий прогресс: {progress_visual}

<b>По блокам:</b>"""
        
        # Статистика по блокам
        for block, stats in sorted(block_stats.items()):
            block_avg = stats['total_score'] / stats['attempts'] if stats['attempts'] > 0 else 0
            text += f"\n• {block}: {block_avg:.1f}/3 ({stats['attempts']} попыток)"
        
        # Серия правильных ответов
        streak = context.user_data.get('correct_streak', 0)
        if streak > 0:
            text += f"\n\n🔥 <b>Текущая серия идеальных ответов:</b> {streak}"
        
        # Достижения
        achievements = context.user_data.get('task20_achievements', set())
        if achievements:
            text += f"\n🏅 <b>Получено достижений:</b> {len(achievements)}/6"
        
        # Рекомендации
        if avg_score < 2:
            text += "\n\n💡 <i>Совет: изучите банк суждений для улучшения результатов</i>"
        elif avg_score >= 2.5:
            text += "\n\n🎉 <i>Отличные результаты! Продолжайте в том же духе!</i>"
        else:
            text += "\n\n📚 <i>Хороший прогресс! Практикуйтесь для достижения мастерства</i>"
        
        # Формируем клавиатуру
        kb_buttons = []
        
        kb_buttons.append([
            InlineKeyboardButton("📈 Детальная статистика", callback_data="t20_detailed_progress"),
            InlineKeyboardButton("📥 Экспорт", callback_data="t20_export")
        ])
        
        kb_buttons.append([
            InlineKeyboardButton("🏅 Достижения", callback_data="t20_achievements"),
            InlineKeyboardButton("💪 Продолжить", callback_data="t20_practice")
        ])
        
        # Работа над ошибками
        weak_topics_count = sum(1 for r in results if r.get('score', 0) < 2)
        if weak_topics_count > 0:
            kb_buttons.append([
                InlineKeyboardButton(f"🔧 Работа над ошибками ({weak_topics_count})", 
                                   callback_data="t20_mistakes")
            ])
        
        kb_buttons.append([
            InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="t20_reset_progress"),
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
        ])
        
        kb = InlineKeyboardMarkup(kb_buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

def _format_evaluation_result(result, topic: Dict, user_answer: str = None) -> str:
    """Форматирование результата оценки в стиле task19 с показом суждений пользователя."""
    
    # Безопасное получение значений
    if isinstance(result, dict):
        score = result.get('total_score', 0)
        max_score = result.get('max_score', 3)
        feedback_text = result.get('feedback', '')
        suggestions = result.get('suggestions', [])
        detailed = result.get('detailed_feedback', {})
    else:
        score = getattr(result, 'total_score', 0)
        max_score = getattr(result, 'max_score', 3)
        feedback_text = getattr(result, 'feedback', '')
        suggestions = getattr(result, 'suggestions', [])
        detailed = getattr(result, 'detailed_feedback', {})
    
    # Преобразуем в int
    score = int(score)
    max_score = int(max_score)
    
    # Динамический заголовок в зависимости от результата
    percentage = (score / max_score * 100) if max_score > 0 else 0
    
    if percentage >= 90:
        header = "🎉 <b>Отличный результат!</b>"
    elif percentage >= 60:
        header = "👍 <b>Хороший результат!</b>"
    elif percentage >= 30:
        header = "📝 <b>Неплохо, но есть над чем поработать</b>"
    else:
        header = "❌ <b>Нужно больше практики</b>"
    
    # Основная информация
    text = f"{header}\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Ваш балл:</b> {score} из {max_score}\n\n"
    
    # Парсим суждения пользователя
    user_arguments = []
    if user_answer:
        # Разбиваем на строки и фильтруем пустые
        lines = [line.strip() for line in user_answer.split('\n') if line.strip()]
        
        # Пытаемся найти суждения
        import re
        for i, line in enumerate(lines):
            # Убираем нумерацию если есть
            cleaned_line = re.sub(r'^\d+[\.\)]\s*', '', line)
            cleaned_line = re.sub(r'^[-•]\s*', '', cleaned_line)
            
            if len(cleaned_line) > 20:  # Минимальная длина для суждения
                # Обрезаем длинные суждения для отображения
                display_text = cleaned_line[:100] + "..." if len(cleaned_line) > 100 else cleaned_line
                user_arguments.append({
                    'number': i + 1,
                    'text': display_text,
                    'full_text': cleaned_line
                })
    
    # Детальный разбор суждений
    text += "<b>📊 Анализ ваших суждений:</b>\n\n"
    
    # Создаем словарь для отслеживания статуса каждого суждения
    argument_status = {}
    
    # Обрабатываем информацию из detailed_feedback
    if detailed and isinstance(detailed, dict):
        # Сначала обрабатываем засчитанные суждения
        if detailed.get('valid_arguments'):
            for arg in detailed['valid_arguments']:
                if isinstance(arg, dict):
                    arg_num = arg.get('number', len(argument_status) + 1)
                    if isinstance(arg_num, str):
                        arg_num = int(arg_num) if arg_num.isdigit() else len(argument_status) + 1
                    argument_status[arg_num] = {
                        'status': 'valid',
                        'comment': arg.get('comment', 'Суждение корректно')
                    }
        
        # Затем незасчитанные (они перезапишут статус, если есть конфликт)
        if detailed.get('invalid_arguments'):
            for arg in detailed['invalid_arguments']:
                if isinstance(arg, dict):
                    arg_num = arg.get('number', len(argument_status) + 1)
                    if isinstance(arg_num, str):
                        arg_num = int(arg_num) if arg_num.isdigit() else len(argument_status) + 1
                    argument_status[arg_num] = {
                        'status': 'invalid',
                        'reason': arg.get('reason', 'Не соответствует критериям'),
                        'improvement': arg.get('improvement', '')
                    }
    
    # Если нет детальной информации, создаем базовую оценку
    if not argument_status and user_arguments:
        # Распределяем баллы по суждениям
        for i in range(min(3, len(user_arguments))):
            if i < score:
                argument_status[i + 1] = {
                    'status': 'valid',
                    'comment': 'Суждение засчитано'
                }
            else:
                argument_status[i + 1] = {
                    'status': 'invalid',
                    'reason': 'Суждение не соответствует требованиям'
                }
    
    # Отображаем все суждения с их статусом
    if user_arguments:
        text += "<b>Ваши суждения:</b>\n\n"
        
        for i, arg in enumerate(user_arguments[:3], 1):  # Максимум 3 суждения
            text += f"{i}. <i>\"{arg['text']}\"</i>\n"
            
            # Получаем статус суждения
            status_info = argument_status.get(i, {'status': 'unknown'})
            
            if status_info['status'] == 'valid':
                text += f"   ✅ {status_info.get('comment', 'Суждение засчитано')}\n"
            elif status_info['status'] == 'invalid':
                text += f"   ❌ {status_info.get('reason', 'Не засчитано')}\n"
                if status_info.get('improvement'):
                    text += f"   💡 <i>Как улучшить: {status_info['improvement']}</i>\n"
            else:
                text += f"   ⚠️ Статус не определен\n"
            
            text += "\n"
        
        # Если суждений больше 3
        if len(user_arguments) > 3:
            text += f"⚠️ <b>Внимание:</b> Обнаружено {len(user_arguments)} суждений вместо 3 требуемых.\n"
            text += "Дополнительные суждения не учитываются при оценке.\n\n"
    
    # Если суждений меньше 3
    elif user_answer and len(user_arguments) < 3:
        text += f"⚠️ <b>Внимание:</b> Обнаружено только {len(user_arguments)} суждение(й) из 3 требуемых.\n"
        text += "Убедитесь, что каждое суждение написано с новой строки.\n\n"
    
    # Проверка на конкретные примеры
    if detailed and detailed.get('has_concrete_examples'):
        text += "⚠️ <b>Важное замечание:</b> В суждениях обнаружены конкретные примеры (даты, названия, имена). "
        text += "Помните, что суждения должны носить абстрактный, обобщающий характер!\n\n"
    
    # Рекомендации
    if suggestions and isinstance(suggestions, list):
        unique_suggestions = []
        seen = set()
        for s in suggestions:
            if s and s not in seen and len(s) > 10:
                unique_suggestions.append(s)
                seen.add(s)
        
        if unique_suggestions:
            text += "<b>💡 Рекомендации для улучшения:</b>\n"
            for suggestion in unique_suggestions[:3]:
                text += f"• {suggestion}\n"
            text += "\n"
    
    # Мотивационное сообщение
    if score == max_score:
        text += "🎉 Превосходно! Все три суждения сформулированы правильно!"
    elif score >= 2:
        text += "💪 Хорошая работа! Продолжайте практиковаться для достижения максимального балла!"
    elif score == 1:
        text += "📚 Неплохое начало! Изучите примеры эталонных суждений в банке заданий."
    else:
        text += "📖 Рекомендую изучить теорию и примеры правильных суждений, затем попробовать снова!"
    
    return text.strip()

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки проверки."""
    query = update.callback_query

    text = """⚙️ <b>Настройки задания 20</b>

<b>Проверка:</b> экспертный уровень (критерии ФИПИ)

Используйте кнопки ниже для управления прогрессом."""

    kb_buttons = [
        [InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="t20_reset_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def reset_progress_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный сброс прогресса task20."""
    query = update.callback_query
    
    # Сбрасываем ТОЛЬКО данные task20
    context.user_data.pop('task20_results', None)
    context.user_data.pop('task20_practice_stats', None)
    context.user_data.pop('task20_achievements', None)
    
    await query.answer("✅ Прогресс по заданию 20 сброшен!", show_alert=True)
    return await return_to_menu(update, context)

reset_progress = reset_progress_task20

async def show_streak_notification(message, streak: int):
    """Показать уведомление о серии идеальных ответов."""
    if streak == 5:
        emoji = "🔥"
        text = "Отличный старт!"
    elif streak == 10:
        emoji = "⚡"
        text = "Впечатляющая серия!"
    elif streak == 15:
        emoji = "🌟"
        text = "Невероятно!"
    elif streak == 20:
        emoji = "💎"
        text = "Мастерская работа!"
    else:
        emoji = "🏆"
        text = f"Фантастика! Серия из {streak}!"
    
    notification_text = f"""
{emoji} <b>Серия идеальных ответов: {streak}!</b>

{text} Продолжайте в том же духе!
"""
    
    try:
        # Отправляем уведомление
        msg = await message.reply_text(
            notification_text,
            parse_mode=ParseMode.HTML
        )
        
        # Удаляем через 5 секунд
        import asyncio
        await asyncio.sleep(5)
        try:
            await msg.delete()
        except:
            pass
    except Exception as e:
        logger.error(f"Error showing streak notification: {e}")

@safe_handler()
async def confirm_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    
    # Сбрасываем прогресс
    context.user_data.pop('task20_results', None)
    context.user_data.pop('task20_practice_stats', None)
    context.user_data.pop('task20_achievements', None)
    
    await query.answer("✅ Прогресс сброшен!", show_alert=True)
    
    # Возвращаемся в меню
    return await return_to_menu(update, context)


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню task20."""
    query = update.callback_query
    
    # Автоматическая миграция при возврате
    ensure_module_migration(context, 'task20', task20_data)  # Передаем context!
    
    # Очищаем контекст от данных других модулей
    keys_to_remove = [
        'current_topic',
        'task19_current_topic', 
        'task24_current_topic',
        'task25_current_topic',
        'answer_processing',
        'current_block',
        'waiting_for_bank_search'
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # ВАЖНО: Устанавливаем активный модуль
    context.user_data['active_module'] = 't20'
    context.user_data['current_module'] = 't20'
    
    # Получаем статистику пользователя
    if UserProgress:
        user_stats = UserProgress(context.user_data).get_stats()
    else:
        user_stats = {
            'total_attempts': 0,
            'streak': 0,
            'weak_topics_count': 0,
            'progress_percent': 0
        }

    greeting = get_personalized_greeting(user_stats)
    is_new_user = user_stats.get('total_attempts', 0) == 0
    text = greeting + MessageFormatter.format_welcome_message("задание 20", is_new_user)

    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t20")

    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

    return states.CHOOSING_MODE

@safe_handler()
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query
    
    # Получаем реальные блоки из загруженных данных
    blocks_data = task20_data.get("topics_by_block", {})
    
    if not blocks_data:
        await query.edit_message_text(
            "❌ Данные о темах не загружены.\n\n"
            "Попробуйте перезапустить бота или обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = "📚 <b>Выберите блок тем:</b>"
    
    # Маппинг блоков на эмодзи
    block_emojis = {
        "Человек и общество": "🧠",
        "Экономика": "💰",
        "Социальные отношения": "👥",
        "Политика": "🏛️",
        "Право": "⚖️"
    }
    
    # Порядок блоков
    block_order = ["Человек и общество", "Экономика", "Социальные отношения", "Политика", "Право"]
    
    kb_buttons = []
    for block_name in block_order:
        if block_name in blocks_data:
            topics = blocks_data[block_name]
            emoji = block_emojis.get(block_name, "📚")
            kb_buttons.append([
                InlineKeyboardButton(
                    f"{emoji} {block_name} ({len(topics)} тем)",
                    callback_data=f"t20_block:{block_name}"
                )
            ])
    
    # Добавляем блоки, которых нет в block_order (на всякий случай)
    for block_name, topics in blocks_data.items():
        if block_name not in block_order and topics:
            kb_buttons.append([
                InlineKeyboardButton(
                    f"📚 {block_name} ({len(topics)} тем)",
                    callback_data=f"t20_block:{block_name}"
                )
            ])
    
    if not kb_buttons:
        kb_buttons.append([InlineKeyboardButton("❌ Нет доступных тем", callback_data="noop")])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

def _build_topic_message(topic: Dict) -> str:
    """Формирует текст сообщения с заданием по теме."""
    return (
        "📝 <b>Задание 20</b>\n\n"
        f"<b>Тема:</b> {topic['title']}\n"
        f"<b>Блок:</b> {topic['block']}\n\n"
        f"<b>Задание:</b> {topic['task_text']}\n\n"
        "<b>Требования:</b>\n"
        "• Приведите три суждения\n"
        "• Каждое суждение должно быть абстрактным\n"
        "• НЕ используйте конкретные примеры\n"
        "• Используйте обобщающие конструкции\n\n"
        "💡 <i>Отправьте ваш ответ одним сообщением</i>"
    )

@safe_handler()
async def show_ideal_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает эталонный ответ для текущей темы."""
    query = update.callback_query
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    text = f"📚 <b>Эталонные суждения</b>\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n\n"
    
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"{i}. <b>{example['type']}</b>\n"
        text += f"└ <i>{example['argument']}</i>\n\n"
    
    text += "💡 <b>Обратите внимание:</b>\n"
    text += "• Суждения носят абстрактный характер\n"
    text += "• Используются обобщающие слова\n"
    text += "• Нет конкретных примеров и дат"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t20_retry")],
        [InlineKeyboardButton("🎲 Новая тема", callback_data="t20_new")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после результата."""
    query = update.callback_query
    
    # Отладочное логирование
    current_state = context.user_data.get('_state', 'unknown')
    logger.info(f"handle_result_action called with action: {query.data}, current state: {current_state}")
    
    # Отвечаем на callback, чтобы убрать "часики"
    await query.answer()
    
    action = query.data.replace("t20_", "")
    
    if action == 'retry':
        # Повторить ту же тему
        topic = context.user_data.get('current_topic')
        if topic:
            text = _build_topic_message(topic)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="t20_menu")]
            ])
            await query.edit_message_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return states.ANSWERING_T20
        else:
            await query.answer("Тема не найдена", show_alert=True)
            return states.CHOOSING_MODE
            
    elif action == 'new':
        # Новая тема
        return await handle_new_task(update, context)
        
    elif action == 'menu':
        # В главное меню
        return await return_to_menu(update, context)
        
    elif action == 'progress':
        # Показать прогресс
        return await my_progress(update, context)
    
    # По умолчанию возвращаемся в режим выбора
    return states.CHOOSING_MODE


@safe_handler()
async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбранного блока."""
    query = update.callback_query
    
    block_name = query.data.split(":", 1)[1]
    context.user_data['current_block'] = block_name  # Важно!
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    
    text = f"📚 <b>Блок: {block_name}</b>\n\n"
    text += f"Доступно тем: {len(topics)}\n\n"
    text += "Выберите действие:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Список тем", callback_data="t20_list_topics")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t20_random_block")],
        [InlineKeyboardButton("⬅️ К блокам", callback_data="t20_select_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
#@validate_state_transition({ANSWERING_T20})
async def handle_answer_document_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка суждений из документа для task20."""

    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE

    extracted_text = await DocumentHandlerMixin.handle_document_answer(
        update,
        context,
        task_name="суждения"
    )

    if not extracted_text:
        return ANSWERING_T20

    # Сохраняем текст в context вместо изменения message.text
    context.user_data['document_text'] = extracted_text

    # Вызываем handle_answer напрямую
    return await handle_answer(update, context)


@safe_handler()
async def handle_answer_photo_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка суждений с фотографии для task20."""

    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE

    # Формируем контекст для улучшения OCR-коррекции
    topic_title = topic.get('title', '') if isinstance(topic, dict) else str(topic)
    ocr_context = f"ЕГЭ обществознание, задание 20 (суждения по теме), тема: {topic_title}"

    # Обрабатываем фото через OCR
    extracted_text = await process_photo_message(
        update,
        context.application.bot,
        task_name="суждения",
        task_context=ocr_context
    )

    if not extracted_text:
        return ANSWERING_T20

    # Сохраняем текст в context
    context.user_data['document_text'] = extracted_text

    # Вызываем handle_answer напрямую
    return await handle_answer(update, context)


@safe_handler()
async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы по ID."""
    query = update.callback_query
    
    # Удаляем предыдущие сообщения перед показом нового вопроса
    await delete_previous_messages(context, query.message.chat_id)

    topic_id = query.data.split(":")[1]
    topic = task20_data["topic_by_id"].get(str(topic_id))

    if not topic:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE

    context.user_data['current_topic'] = topic

    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_list_topics")]
    ])

    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

    # Сохраняем ID сообщения с вопросом
    context.user_data['task20_question_msg_id'] = query.message.message_id

    # ДОБАВИТЬ: Явная установка состояния
    state_validator.set_state(query.from_user.id, ANSWERING_T20)

    return ANSWERING_T20


@safe_handler()
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем в блоке или всех тем с пагинацией."""
    query = update.callback_query
    
    # Извлекаем номер страницы из callback_data
    parts = query.data.split(":page:")
    page = int(parts[1]) if len(parts) > 1 else 0
    
    block_name = context.user_data.get('current_block')
    
    # Если блок не выбран, показываем все темы
    if not block_name:
        # Собираем все темы из всех блоков
        all_topics = []
        blocks_data = task20_data.get("topics_by_block", {})
        
        for block, topics in blocks_data.items():
            for topic in topics:
                # Добавляем информацию о блоке к каждой теме
                topic_with_block = topic.copy()
                topic_with_block['block_display'] = block
                all_topics.append(topic_with_block)
        
        if not all_topics:
            await query.edit_message_text(
                "❌ Темы не найдены",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
                ]])
            )
            return states.CHOOSING_MODE
        
        topics = all_topics
        header_text = "📚 <b>Все темы</b>\n"
    else:
        # Если блок выбран, показываем темы блока
        topics = task20_data["topics_by_block"].get(block_name, [])
        header_text = f"📚 <b>{block_name}</b>\n"
    
    # Пагинация: 5 тем на страницу
    topics_per_page = 5
    total_pages = (len(topics) + topics_per_page - 1) // topics_per_page
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(topics))
    
    text = header_text
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    kb_buttons = []
    
    # Кнопки с темами
    for topic in topics[start_idx:end_idx]:
        # Если показываем все темы, добавляем информацию о блоке
        if not block_name and 'block_display' in topic:
            button_text = f"{topic['id']}. {topic['title'][:30]}... [{topic['block_display']}]"
        else:
            button_text = f"{topic['id']}. {topic['title'][:40]}..."
            
        kb_buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"t20_topic:{topic['id']}"
            )
        ])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t20_list_topics:page:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t20_list_topics:page:{page+1}"))
    
    if nav_buttons:
        kb_buttons.append(nav_buttons)
    
    # Кнопка назад
    if block_name:
        kb_buttons.append([InlineKeyboardButton("⬅️ К блоку", callback_data=f"t20_block:{block_name}")])
    else:
        kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы из всей базы."""
    query = update.callback_query

    # Удаляем предыдущие сообщения перед показом нового вопроса
    await delete_previous_messages(context, query.message.chat_id)

    # Проверяем наличие данных
    if not task20_data.get("topics"):
        await query.edit_message_text(
            "❌ Данные не загружены. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Если есть topic_selector, используем его
    if topic_selector:
        done_topics = {r['topic_id'] for r in context.user_data.get('task20_results', [])}
        topic = topic_selector.get_random_topic(exclude_ids=done_topics)
    else:
        # Fallback - простой random.choice
        import random
        topics = task20_data.get("topics", [])
        topic = random.choice(topics) if topics else None
    
    if not topic:
        await query.edit_message_text(
            "🎉 Поздравляем! Вы изучили все темы!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic

    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_practice")]
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    # Сохраняем ID сообщения с вопросом
    context.user_data['task20_question_msg_id'] = query.message.message_id

    state_validator.set_state(query.from_user.id, ANSWERING_T20)

    return ANSWERING_T20

@safe_handler()
async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы из блока."""
    query = update.callback_query

    # Удаляем предыдущие сообщения перед показом нового вопроса
    await delete_previous_messages(context, query.message.chat_id)

    import random

    block_name = context.user_data.get('current_block')  # Используем current_block
    if not block_name:
        await query.answer("Блок не выбран", show_alert=True)
        return states.CHOOSING_MODE
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    if not topics:
        await query.answer("В блоке нет тем", show_alert=True)
        return states.CHOOSING_MODE
    
    topic = random.choice(topics)
    context.user_data['current_topic'] = topic

    text = _build_topic_message(topic)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=f"t20_block:{block_name}")]
    ])

    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

    # Сохраняем ID сообщения с вопросом
    context.user_data['task20_question_msg_id'] = query.message.message_id

    state_validator.set_state(query.from_user.id, states.ANSWERING_T20)

    return states.ANSWERING_T20


@safe_handler()
async def bank_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку примеров."""
    query = update.callback_query
    
    topic_idx = int(query.data.split(":")[1])
    topics = task20_data.get('topics', [])
    
    if topic_idx >= len(topics):
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    topic = topics[topic_idx]
    context.user_data['bank_current_idx'] = topic_idx
    
    # Текст темы
    text = f"📚 <b>Тема {topic_idx + 1} из {len(topics)}</b>\n\n"
    text += f"<b>{topic['title']}</b>\n\n"
    text += f"📋 {topic['task_text']}\n\n"
    text += "<b>Эталонные суждения:</b>\n\n"
    
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"{i}. <b>{example['type']}</b>\n"
        text += f"└ <i>{example['argument']}</i>\n\n"
    
    text += "💡 <b>Обратите внимание:</b>\n"
    text += "• Суждения носят абстрактный характер\n"
    text += "• Используются обобщающие слова\n"
    text += "• Нет конкретных примеров и дат"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    # Кнопка "Назад" - только если не первая тема
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t20_bank_nav:{topic_idx-1}"))
    else:
        nav_row.append(InlineKeyboardButton("⏮️", callback_data="noop"))
    
    # Прогресс
    progress_display = create_visual_progress(topic_idx + 1, len(topics))
    nav_row.append(InlineKeyboardButton(progress_display, callback_data="noop"))
    
    # Кнопка "Вперед" - только если не последняя тема  
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t20_bank_nav:{topic_idx+1}"))
    else:
        nav_row.append(InlineKeyboardButton("⏭️", callback_data="noop"))
    
    kb_buttons.append(nav_row)
    
    # ВАЖНО: ДОБАВЛЯЕМ КНОПКУ "ОТРАБОТАТЬ ТЕМУ"
    kb_buttons.append([InlineKeyboardButton("🎯 Отработать эту тему", callback_data=f"t20_topic:{topic['id']}")])
    
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")])
    kb_buttons.append([InlineKeyboardButton("📋 Все темы", callback_data="t20_view_all_examples")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")])
    
    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb_buttons),
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer()
        else:
            raise
    
    return states.CHOOSING_MODE

@safe_handler()
async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск темы в банке суждений."""
    query = update.callback_query
    
    await query.edit_message_text(
        "🔍 <b>Поиск в банке суждений</b>\n\n"
        "Отправьте название темы или ключевые слова для поиска:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="t20_examples")
        ]]),
        parse_mode=ParseMode.HTML
    )
    
    context.user_data['waiting_for_bank_search'] = True
    return states.SEARCHING



@safe_handler()
async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик действий в настройках."""
    query = update.callback_query
    
    if query.data == "t20_reset_progress":
        return await reset_progress(update, context)
    elif query.data == "t20_confirm_reset":
        return await confirm_reset(update, context)
    
    return states.CHOOSING_MODE

@safe_handler()
async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика по темам."""
    query = update.callback_query
    
    results = context.user_data.get('task20_results', [])
    
    if len(results) < 5:
        await query.edit_message_text(
            "📊 <b>Детальная статистика</b>\n\n"
            "Для отображения детальной статистики необходимо выполнить минимум 5 заданий.\n\n"
            f"Сейчас выполнено: {len(results)} из 5\n\n"
            "Продолжайте практику, чтобы увидеть подробный анализ!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💪 Продолжить практику", callback_data="t20_practice")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")]
            ]),
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    # Группируем результаты по темам
    topic_stats = {}
    for result in results:
        topic = result.get('topic', 'Неизвестная тема')
        if topic not in topic_stats:
            topic_stats[topic] = {
                'attempts': 0,
                'total_score': 0,
                'scores': []
            }
        topic_stats[topic]['attempts'] += 1
        topic_stats[topic]['total_score'] += result['score']
        topic_stats[topic]['scores'].append(result['score'])
    
    # Сортируем темы по среднему баллу (от худших к лучшим)
    sorted_topics = sorted(
        topic_stats.items(),
        key=lambda x: x[1]['total_score'] / x[1]['attempts']
    )
    
    text = "📈 <b>Детальная статистика по темам</b>\n\n"
    
    # Показываем топ-5 худших тем для работы
    text += "🔴 <b>Темы, требующие внимания:</b>\n"
    for i, (topic, stats) in enumerate(sorted_topics[:5], 1):
        avg_score = stats['total_score'] / stats['attempts']
        text += f"{i}. {topic}: {avg_score:.1f}/3 ({stats['attempts']} попыток)\n"
    
    # Показываем топ-5 лучших тем
    if len(sorted_topics) > 5:
        text += "\n🟢 <b>Ваши сильные темы:</b>\n"
        for i, (topic, stats) in enumerate(reversed(sorted_topics[-5:]), 1):
            avg_score = stats['total_score'] / stats['attempts']
            text += f"{i}. {topic}: {avg_score:.1f}/3 ({stats['attempts']} попыток)\n"
    
    # Общие рекомендации
    weak_topics = [t for t, s in sorted_topics if s['total_score']/s['attempts'] < 2]
    if weak_topics:
        text += f"\n💡 <i>Рекомендуем поработать над {len(weak_topics)} темами с низкими баллами</i>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="t20_mistakes")],
        [InlineKeyboardButton("📥 Экспорт в CSV", callback_data="t20_export")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def achievements_check(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> List[Dict]:
    """Проверка и выдача достижений."""
    results = context.user_data.get('task20_results', [])
    achievements = context.user_data.get('task20_achievements', set())
    new_achievements = []
    
    # Определяем достижения
    achievement_conditions = {
        'first_perfect': {
            'name': '🌟 Первый идеал',
            'description': 'Получить первый максимальный балл',
            'icon': '🌟',
            'check': lambda r: any(res.get('score', 0) == 3 for res in r) if r else False
        },
        'consistency_5': {
            'name': '🎯 Стабильность',
            'description': 'Получить 3 балла 5 раз подряд',
            'icon': '🎯',
            'check': lambda r: len(r) >= 5 and any(
                all(r[i+j].get('score', 0) == 3 for j in range(5))
                for i in range(len(r) - 4)
            )
        },
        'explorer_10': {
            'name': '🗺️ Исследователь',
            'description': 'Изучить 10 разных тем',
            'icon': '🗺️',
            'check': lambda r: len(set(
                res.get('topic_id', res.get('topic', f'unknown_{i}')) 
                for i, res in enumerate(r)
            )) >= 10
        },
        'persistent_20': {
            'name': '💪 Упорство',
            'description': 'Выполнить 20 заданий',
            'icon': '💪',
            'check': lambda r: len(r) >= 20
        },
        'master_50': {
            'name': '🏆 Мастер',
            'description': 'Выполнить 50 заданий со средним баллом выше 2.5',
            'icon': '🏆',
            'check': lambda r: len(r) >= 50 and sum(res.get('score', 0) for res in r) / len(r) >= 2.5 if r else False
        },
        'comeback': {
            'name': '🔥 Возвращение',
            'description': 'Получить 3 балла после 3+ неудачных попыток',
            'icon': '🔥',
            'check': lambda r: any(
                i >= 3 and
                r[i].get('score', 0) == 3 and 
                all(r[j].get('score', 0) < 2 for j in range(max(0, i-3), i))
                for i in range(len(r))
            ) if len(r) >= 4 else False
        }
    }
    
    # Проверяем каждое достижение
    for ach_id, ach_data in achievement_conditions.items():
        if ach_id not in achievements:
            try:
                if ach_data['check'](results):
                    achievements.add(ach_id)
                    new_achievements.append({
                        'id': ach_id,
                        'name': ach_data['name'],
                        'description': ach_data['description'],
                        'icon': ach_data['icon']
                    })
            except Exception as e:
                logger.error(f"Error checking achievement {ach_id}: {e}")
    
    # Сохраняем достижения
    context.user_data['task20_achievements'] = achievements
    
    return new_achievements

@safe_handler()
async def show_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все достижения."""
    query = update.callback_query
    
    achievements = context.user_data.get('task20_achievements', set())
    
    all_achievements = {
        'first_perfect': ('🌟 Первый идеал', 'Получить первый максимальный балл'),
        'consistency_5': ('🎯 Стабильность', 'Получить 3 балла 5 раз подряд'),
        'explorer_10': ('🗺️ Исследователь', 'Изучить 10 разных тем'),
        'persistent_20': ('💪 Упорство', 'Выполнить 20 заданий'),
        'master_50': ('🏆 Мастер', 'Выполнить 50 заданий со средним баллом выше 2.5'),
        'comeback': ('🔥 Возвращение', 'Получить 3 балла после 3+ неудачных попыток')
    }
    
    text = "🏅 <b>Ваши достижения</b>\n\n"
    
    # Полученные достижения
    if achievements:
        text += "<b>Получено:</b>\n"
        for ach_id in achievements:
            if ach_id in all_achievements:
                name, desc = all_achievements[ach_id]
                text += f"{name} - {desc}\n"
        text += "\n"
    
    # Доступные достижения
    not_achieved = set(all_achievements.keys()) - achievements
    if not_achieved:
        text += "<b>Доступно:</b>\n"
        for ach_id in not_achieved:
            name, desc = all_achievements[ach_id]
            text += f"❓ {name[2:]} - {desc}\n"
    
    # Прогресс
    progress_display = create_visual_progress(len(achievements), len(all_achievements))
    text += f"\n<b>Прогресс:</b> {progress_display}"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def mistakes_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим работы над ошибками с учетом practice_stats."""
    query = update.callback_query
    
    # Находим темы с низкими баллами из ОБОИХ источников
    results = context.user_data.get('task20_results', [])
    stats = context.user_data.get('practice_stats', {})
    weak_topics = {}
    
    # Из results
    for result in results:
        if result['score'] < 2:  # Меньше 2 баллов
            topic_id = str(result.get('topic_id', result.get('topic', 'unknown')))
            if topic_id not in weak_topics:
                weak_topics[topic_id] = {
                    'topic': result.get('topic', result.get('topic_title', 'Неизвестная тема')),
                    'attempts': 0,
                    'avg_score': 0,
                    'total_score': 0,
                    'block': result.get('block', 'Без категории')
                }
            weak_topics[topic_id]['attempts'] += 1
            weak_topics[topic_id]['total_score'] += result['score']
    
    # Дополняем из practice_stats
    for topic_id_str, topic_data in stats.items():
        scores = topic_data.get('scores', [])
        if scores:
            avg = sum(scores) / len(scores)
            if avg < 2:  # Средний балл меньше 2
                if topic_id_str not in weak_topics:
                    weak_topics[topic_id_str] = {
                        'topic': topic_data.get('topic_title', f'Тема {topic_id_str}'),
                        'attempts': topic_data.get('attempts', 0),
                        'avg_score': avg,
                        'total_score': sum(scores),
                        'block': topic_data.get('block', 'Без категории')
                    }
    
    # Вычисляем средние баллы
    for topic_id in weak_topics:
        topic_data = weak_topics[topic_id]
        if topic_data['attempts'] > 0:
            topic_data['avg_score'] = topic_data['total_score'] / topic_data['attempts']
    
    if not weak_topics:
        text = "🎉 Отлично! У вас нет тем, требующих дополнительной практики!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
        ]])
    else:
        text = "🔧 <b>Работа над ошибками</b>\n\n"
        text += f"Найдено тем для улучшения: {len(weak_topics)}\n\n"
        
        # Сортируем по среднему баллу (от худших к лучшим)
        sorted_topics = sorted(
            weak_topics.items(),
            key=lambda x: x[1]['avg_score']
        )
        
        # Показываем топ-5 худших тем
        text += "<b>Темы, требующие внимания:</b>\n"
        for i, (topic_id, data) in enumerate(sorted_topics[:5], 1):
            topic_name = data['topic'][:40]  # Ограничиваем длину
            avg = data['avg_score']
            attempts = data['attempts']
            text += f"{i}. {topic_name}\n"
            text += f"   📊 Средний балл: {avg:.1f}/3 ({attempts} попыток)\n"
        
        if len(weak_topics) > 5:
            text += f"\n<i>...и ещё {len(weak_topics) - 5} тем</i>\n"
        
        text += "\n💡 <i>Повторите эти темы в банке суждений перед практикой</i>"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Банк суждений", callback_data="t20_examples")],
            [InlineKeyboardButton("💪 Начать практику", callback_data="t20_practice")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")]
        ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def handle_topic_choice_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обертка для обработки выбора темы."""
    return await choose_topic(update, context)

@safe_handler()
async def handle_new_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора новой темы."""
    # Используем случайную тему
    return await random_topic_all(update, context)

@safe_handler()
async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт результатов в CSV."""
    query = update.callback_query
    user_id = query.from_user.id
    
    results = context.user_data.get('task20_results', [])
    
    if not results:
        await query.answer("Нет результатов для экспорта", show_alert=True)
        return states.CHOOSING_MODE
    
    # Создаем CSV
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')  # Используем ; для лучшей совместимости с Excel
    
    # Добавляем заголовок с BOM для корректного отображения в Excel
    writer.writerow(["Дата", "Тема", "Блок", "Балл", "Макс.балл", "Процент"])
    
    for result in results:
        timestamp = result.get('timestamp', '')
        topic = result.get('topic', '')
        block = result.get('block', '')
        score = result.get('score', 0)
        max_score = result.get('max_score', 3)
        percentage = f"{(score/max_score*100):.0f}%" if max_score > 0 else "0%"
        
        writer.writerow([timestamp, topic, block, score, max_score, percentage])
    
    # Добавляем итоговую строку
    total_score = sum(r.get('score', 0) for r in results)
    total_max = sum(r.get('max_score', 3) for r in results)
    avg_percentage = f"{(total_score/total_max*100):.0f}%" if total_max > 0 else "0%"
    
    writer.writerow([])
    writer.writerow(["ИТОГО", "", "", total_score, total_max, avg_percentage])
    
    # Отправляем файл с правильной кодировкой
    output.seek(0)
    # Используем utf-8-sig для добавления BOM, чтобы Excel корректно определил кодировку
    await query.message.reply_document(
        document=io.BytesIO(output.getvalue().encode('utf-8-sig')),
        filename=f"task20_results_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        caption="📊 Ваши результаты по заданию 20\n\nФайл можно открыть в Excel или Google Sheets"
    )
    
    await query.answer("✅ Файл успешно создан!")
    
    return states.CHOOSING_MODE

@safe_handler()
async def practice_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика практики."""
    query = update.callback_query
    
    results = context.user_data.get('task20_results', [])
    
    if not results:
        text = "📊 У вас пока нет статистики практики"
    else:
        total = len(results)
        avg_score = sum(r['score'] for r in results) / total
        perfect = sum(1 for r in results if r['score'] == 3)
        
        text = f"""📊 <b>Статистика практики</b>

📝 Всего попыток: {total}
⭐ Средний балл: {avg_score:.1f}/3
🎯 Идеальных ответов: {perfect} ({perfect/total*100:.0f}%)

💡 Совет: регулярная практика - ключ к успеху!"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def choose_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы из списка."""
    query = update.callback_query
    
    topic_id = query.data.split(":")[1]
    topic = task20_data["topic_by_id"].get(topic_id)
    
    if not topic:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_list_topics")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    state_validator.set_state(query.from_user.id, ANSWERING_T20)
    
    return ANSWERING_T20

@safe_handler()
#@validate_state_transition({ANSWERING_T20})
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await safe_handle_answer_task20(update, context)

@safe_handler()
async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстового поиска в банке суждений."""
    if not context.user_data.get('waiting_for_bank_search'):
        return states.CHOOSING_MODE
        
    search_query = update.message.text.lower()
    topics = task20_data.get('topics', [])
    
    # Ищем темы по вхождению текста
    found_topics = []
    for idx, topic in enumerate(topics):
        if (search_query in topic['title'].lower() or 
            search_query in topic.get('keywords', '').lower() or
            search_query in topic['task_text'].lower()):
            found_topics.append((idx, topic))
    
    if not found_topics:
        text = "❌ По вашему запросу ничего не найдено.\n\nПопробуйте другие ключевые слова."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Искать снова", callback_data="t20_bank_search")],
            [InlineKeyboardButton("⬅️ К банку", callback_data="t20_examples")]
        ])
    else:
        text = f"🔍 <b>Результаты поиска</b>\n\nНайдено тем: {len(found_topics)}\n\n"
        kb_buttons = []
        
        for idx, topic in found_topics[:10]:  # Показываем максимум 10
            kb_buttons.append([InlineKeyboardButton(
                f"📖 {topic['title'][:50]}...",
                callback_data=f"t20_bank_nav:{idx}"
            )])
        
        if len(found_topics) > 10:
            text += f"\n<i>Показаны первые 10 из {len(found_topics)} результатов</i>"
        
        kb_buttons.append([InlineKeyboardButton("⬅️ К банку", callback_data="t20_examples")])
        kb = InlineKeyboardMarkup(kb_buttons)
    
    # Очищаем флаг поиска
    context.user_data['waiting_for_bank_search'] = False
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 В меню задания 20", callback_data="t20_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])
    )
    return ConversationHandler.END