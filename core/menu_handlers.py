# core/menu_handlers.py
"""Глобальные обработчики меню."""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
import logging
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

async def handle_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки 'Главное меню'."""
    query = update.callback_query
    
    if query:
        await query.answer()
        
        user_id = query.from_user.id
        
        welcome_text = """
🎓 <b>Подготовка к ЕГЭ по обществознанию</b>

Используйте кнопки ниже для навигации:
"""
        
        # Получаем клавиатуру меню
        try:
            from core.app import show_main_menu_with_access
            kb = await show_main_menu_with_access(context, user_id)
        except ImportError:
            try:
                from core.plugin_loader import build_main_menu
                kb = build_main_menu()
            except ImportError as e:
                logger.error(f"Could not import menu builder: {e}")
                kb = None
        
        # Пытаемся отредактировать сообщение
        try:
            if kb:
                await query.edit_message_text(
                    welcome_text, 
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            else:
                await query.edit_message_text(
                    welcome_text,
                    parse_mode="HTML"
                )
        except BadRequest as e:
            # Проверяем тип ошибки
            error_message = str(e).lower()
            
            # Если сообщение не изменилось - просто игнорируем
            if "message is not modified" in error_message:
                logger.debug("Message is not modified, skipping update")
                pass
            # Если сообщение слишком старое для редактирования
            elif "message to edit not found" in error_message or "message can't be edited" in error_message:
                logger.debug("Message too old or can't be edited, sending new one")
                # Только в этом случае удаляем и отправляем новое
                try:
                    await query.message.delete()
                except:
                    pass
                
                if kb:
                    await query.message.chat.send_message(
                        welcome_text, 
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                else:
                    await query.message.chat.send_message(
                        welcome_text,
                        parse_mode="HTML"
                    )
            else:
                # Неизвестная ошибка - логируем
                logger.error(f"Unknown BadRequest error: {e}")
        except Exception as e:
            # Другие ошибки
            logger.error(f"Unexpected error in handle_to_main_menu: {e}")

    return ConversationHandler.END


async def handle_plugin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора плагина из главного меню."""
    query = update.callback_query
    
    # === ИСПРАВЛЕНИЕ: НЕ ДЕЛАЕМ context.user_data.clear()! ===
    # Очищаем только временное состояние предыдущего модуля
    temp_keys = [
        'current_topic',
        'active_module',
        'current_module',
        'answer_processing',
        'current_block',
        'viewing_mode',
        '_state',
        'conversation_state'
    ]
    
    for key in temp_keys:
        context.user_data.pop(key, None)
    
    # Логируем для отладки
    logger.info(f"Plugin choice: {query.data}, preserved data keys: {len(context.user_data)}")
    
    # Отвечаем на callback
    if query:
        await query.answer()
    
    # ConversationHandler плагина сам обработает вход
    return None


def register_global_handlers(app):
    """Регистрирует глобальные обработчики, работающие во всех плагинах."""
    
    # Универсальный возврат в главное меню с высоким приоритетом
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern="^to_main_menu$"
        ),
        group=-1  # Высокий приоритет - срабатывает раньше других
    )
    
    # Для обратной совместимости со старым паттерном
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern="^main_menu$"
        ),
        group=-1
    )