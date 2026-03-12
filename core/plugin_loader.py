"""Загрузчик плагинов для бота."""

import importlib
import pkgutil
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.plugin_base import BotPlugin

# Глобальный список плагинов
PLUGINS: List[BotPlugin] = []


def discover_plugins() -> None:
    """Ищем модули *.plugin.py в корне проекта."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("Starting plugin discovery...")
    
    for mod in pkgutil.iter_modules():
        # Добавляем все модули плагинов
        # teacher_mode АКТИВИРОВАН для production!
        if mod.name in ("test_part", "task17", "task18", "task24", "task19", "task20", "task21", "task22", "task23", "task25", "personal_cabinet", "teacher_mode", "full_exam", "flashcards"):
            try:
                logger.info(f"Loading plugin: {mod.name}")
                plugin_module = importlib.import_module(f"{mod.name}.plugin")
                PLUGINS.append(plugin_module.plugin)
                logger.info(f"Successfully loaded: {plugin_module.plugin.title}")
            except Exception as e:
                logger.error(f"Failed to load plugin {mod.name}: {e}")
    
    PLUGINS.sort(key=lambda p: p.menu_priority)
    logger.info(f"Loaded {len(PLUGINS)} plugins: {[p.title for p in PLUGINS]}")


def build_main_menu() -> InlineKeyboardMarkup:
    """Строит главное меню из всех загруженных плагинов."""
    import logging
    logger = logging.getLogger(__name__)
    
    if not PLUGINS:
        logger.warning("No plugins loaded for main menu!")
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Нет доступных модулей", callback_data="no_plugins")
        ]])
    
    buttons = []
    for p in PLUGINS:
        logger.debug(f"Adding menu button for plugin: {p.code} - {p.title}")
        buttons.append([InlineKeyboardButton(
            p.title,
            callback_data=f"choose_{p.code}"
        )])
    
    logger.info(f"Main menu built with {len(buttons)} buttons")
    return InlineKeyboardMarkup(buttons)
    
# Добавьте эту функцию в конец файла core/plugin_loader.py

def load_modules(application):
    """Загружает и регистрирует все плагины в приложении."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Сначала ищем все плагины
    discover_plugins()
    
    # Список для post_init функций
    post_init_tasks = []
    
    # Затем регистрируем каждый плагин
    for plugin in PLUGINS:
        try:
            logger.info(f"Registering plugin: {plugin.title}")
            plugin.register(application)
            
            # Если у плагина есть post_init, сохраняем его
            if hasattr(plugin, 'post_init'):
                post_init_tasks.append(plugin)
                logger.info(f"Post-init scheduled for {plugin.title}")
                
        except Exception as e:
            logger.error(f"Failed to register plugin {plugin.code}: {e}")
    
    # Сохраняем post_init задачи в bot_data для вызова из app.py
    if post_init_tasks:
        # Добавляем в bot_data для вызова при инициализации
        if 'plugin_post_init_tasks' not in application.bot_data:
            application.bot_data['plugin_post_init_tasks'] = []
        application.bot_data['plugin_post_init_tasks'].extend(post_init_tasks)
        logger.info(f"Registered post_init handler for {len(post_init_tasks)} plugins")
    
    logger.info(f"Successfully registered {len(PLUGINS)} plugins")
    
    # Регистрируем обработчик главного меню
    from telegram import Update
    from telegram.ext import CommandHandler, CallbackQueryHandler
    
    async def show_main_menu(update: Update, context):
        """Показывает главное меню."""
        menu = build_main_menu()
        text = "👋 Выберите раздел для подготовки к ЕГЭ:"
        
        if update.message:
            await update.message.reply_text(text, reply_markup=menu)
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=menu)
    
    # Добавляем команду /menu для показа главного меню
    application.add_handler(CommandHandler("menu", show_main_menu))
    
    # Добавляем обработчик для кнопки "Главное меню"
    application.add_handler(
        CallbackQueryHandler(show_main_menu, pattern="^main_menu$")
    )