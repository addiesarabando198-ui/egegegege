"""
core/error_handler.py
Универсальная система обработки ошибок и callback_query для всего бота.
"""

import logging
import traceback
from functools import wraps
from typing import Callable, Optional, Any, Dict
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from core import states
from telegram.error import BadRequest, NetworkError, TimedOut

logger = logging.getLogger(__name__)


class ErrorTypes:
    """Типы ошибок для классификации."""
    NETWORK = "network"
    DATABASE = "database"
    VALIDATION = "validation"
    AI_SERVICE = "ai_service"
    PERMISSION = "permission"
    UNKNOWN = "unknown"


class BotError(Exception):
    """Базовый класс для ошибок бота."""
    def __init__(self, message: str, error_type: str = ErrorTypes.UNKNOWN, user_friendly_message: Optional[str] = None):
        super().__init__(message)
        self.error_type = error_type
        self.user_friendly_message = user_friendly_message or "Произошла ошибка. Попробуйте позже."


class ValidationError(BotError):
    """Ошибка валидации данных."""
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message, ErrorTypes.VALIDATION)
        self.field = field


class AIServiceError(BotError):
    """Ошибка AI сервиса."""
    def __init__(self, message: str, service: str = "YandexGPT"):
        super().__init__(
            message, 
            ErrorTypes.AI_SERVICE,
            "AI сервис временно недоступен. Попробуйте позже."
        )
        self.service = service


def safe_handler(
    return_on_error: Any = ConversationHandler.END,
    answer_callback: bool = True,
    log_errors: bool = True,
    notify_user: bool = True
):
    """
    Декоратор для безопасной обработки ошибок в handlers.
    
    Args:
        return_on_error: Что возвращать при ошибке
        answer_callback: Отвечать на callback_query
        log_errors: Логировать ошибки
        notify_user: Уведомлять пользователя об ошибке
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = None
            if getattr(update, "effective_user", None):
                user_id = update.effective_user.id
            elif getattr(update, "message", None) and getattr(update.message, "from_user", None):
                user_id = update.message.from_user.id
            elif getattr(update, "callback_query", None) and getattr(update.callback_query, "from_user", None):
                user_id = update.callback_query.from_user.id
            user_id = user_id or "Unknown"
            handler_name = func.__name__
            
            try:
                # Автоматически отвечаем на callback_query если есть
                if answer_callback and update.callback_query:
                    try:
                        await update.callback_query.answer()
                    except BadRequest as e:
                        if "query is too old" not in str(e):
                            logger.warning(f"Failed to answer callback query: {e}")
                
                # Вызываем оригинальную функцию
                return await func(update, context, *args, **kwargs)
                
            except BotError as e:
                # Обрабатываем известные ошибки бота
                if log_errors:
                    logger.error(
                        f"BotError in {handler_name} for user {user_id}: "
                        f"[{e.error_type}] {e}"
                    )
                
                if notify_user:
                    await _notify_user_about_error(update, e.user_friendly_message)
                
                return return_on_error
                
            except (NetworkError, TimedOut) as e:
                # Сетевые ошибки
                if log_errors:
                    logger.error(
                        f"Network error in {handler_name} for user {user_id}: {e}"
                    )
                
                if notify_user:
                    await _notify_user_about_error(
                        update, 
                        "⚠️ Проблемы с соединением. Попробуйте еще раз."
                    )
                
                return return_on_error

            except Exception as e:
                # Неизвестные ошибки
                if log_errors:
                    # logger.exception already logs the traceback
                    logger.exception(
                        f"Unexpected error in {handler_name} for user {user_id}: {e}"
                    )
                
                # Сохраняем информацию об ошибке для админов
                _save_error_info(context, user_id, handler_name, e)
                
                if notify_user:
                    await _notify_user_about_error(
                        update,
                        "❌ Произошла непредвиденная ошибка. Мы уже работаем над решением."
                    )
                
                return return_on_error
                
        return wrapper
    return decorator


async def _notify_user_about_error(update: Update, message: str):
    """Уведомление пользователя об ошибке."""
    error_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_last_action"),
        InlineKeyboardButton("📋 В меню", callback_data="to_main_menu")
    ]])
    
    try:
        if update.callback_query:
            # Если это callback, пробуем отредактировать сообщение
            try:
                await update.callback_query.edit_message_text(
                    message,
                    reply_markup=error_keyboard
                )
            except BadRequest:
                # Если не удалось отредактировать, отправляем новое
                await update.callback_query.message.reply_text(
                    message,
                    reply_markup=error_keyboard
                )
        else:
            # Для обычных сообщений
            await update.message.reply_text(
                message,
                reply_markup=error_keyboard
            )
    except Exception as e:
        logger.error(f"Failed to notify user about error: {e}")


def _save_error_info(context: ContextTypes.DEFAULT_TYPE, user_id: Any, handler: str, error: Exception):
    """Сохранение информации об ошибке для админов."""
    error_info = {
        'user_id': user_id,
        'handler': handler,
        'error_type': type(error).__name__,
        'error_message': str(error),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'traceback': traceback.format_exc()
    }
    
    # Сохраняем в bot_data для админ панели
    if not hasattr(context, 'bot_data') or context.bot_data is None:
        logger.warning("context.bot_data is not available, skipping error info save")
        return
        
    if 'recent_errors' not in context.bot_data:
        context.bot_data['recent_errors'] = []
    
    context.bot_data['recent_errors'].append(error_info)
    
    # Оставляем только последние 100 ошибок
    if len(context.bot_data['recent_errors']) > 100:
        context.bot_data['recent_errors'] = context.bot_data['recent_errors'][-100:]


class CallbackAnswerer:
    """Менеджер для гарантированного ответа на callback_query."""
    
    def __init__(self, query, default_text: str = "Обработка..."):
        self.query = query
        self.default_text = default_text
        self.answered = False
    
    async def __aenter__(self):
        """Отвечаем при входе в контекст."""
        if self.query:
            try:
                await self.query.answer(self.default_text)
                self.answered = True
            except BadRequest as e:
                if "query is too old" not in str(e):
                    logger.warning(f"Failed to answer callback query: {e}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Гарантируем ответ при выходе из контекста."""
        if self.query and not self.answered:
            try:
                if exc_type:
                    # Если была ошибка
                    await self.query.answer("❌ Произошла ошибка", show_alert=True)
                else:
                    await self.query.answer()
            except:
                pass
    
    async def answer(self, text: Optional[str] = None, show_alert: bool = False):
        """Ручной ответ с кастомным текстом."""
        if self.query and not self.answered:
            try:
                await self.query.answer(text, show_alert=show_alert)
                self.answered = True
            except BadRequest:
                pass


# Глобальный обработчик ошибок для приложения
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик всех необработанных ошибок."""
    
    # Логируем ошибку
    logger.error(f"Exception while handling an update: {context.error}")
    
    # Определяем user_id
    user_id = None
    if update and update.effective_user:
        user_id = update.effective_user.id
    
    # Сохраняем информацию об ошибке
    _save_error_info(
        context, 
        user_id, 
        "global_error_handler", 
        context.error
    )
    
    # Пробуем уведомить пользователя
    if update:
        # Сначала отвечаем на callback если есть
        if update.callback_query:
            try:
                await update.callback_query.answer(
                    "❌ Произошла ошибка. Попробуйте еще раз.",
                    show_alert=True
                )
            except:
                pass
        
        # Отправляем сообщение об ошибке
        message = (
            "❌ <b>Произошла ошибка</b>\n\n"
            "Приносим извинения за неудобства. "
            "Пожалуйста, попробуйте еще раз или обратитесь к администратору.\n\n"
            f"Код ошибки: <code>{type(context.error).__name__}</code>"
        )
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 В главное меню", callback_data="to_main_menu")
        ]])
        
        try:
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            elif update.message:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")
    
    # Уведомляем админов о критических ошибках
    if isinstance(context.error, (AIServiceError, AttributeError, KeyError)):
        await _notify_admins_about_critical_error(context, update)


async def _notify_admins_about_critical_error(context: ContextTypes.DEFAULT_TYPE, update: Update):
    """Уведомление админов о критических ошибках."""
    from core.admin_tools import admin_manager
    
    admin_ids = admin_manager.get_admin_list()
    if not admin_ids:
        return
    
    error_type = type(context.error).__name__
    user_info = "Unknown"
    if update and update.effective_user:
        user_info = f"@{update.effective_user.username or update.effective_user.id}"
    
    message = (
        f"🚨 <b>Критическая ошибка в боте</b>\n\n"
        f"<b>Тип:</b> <code>{error_type}</code>\n"
        f"<b>Пользователь:</b> {user_info}\n"
        f"<b>Время:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"<b>Описание:</b> <code>{str(context.error)[:200]}</code>\n\n"
        f"Проверьте логи для подробностей."
    )
    
    # Отправляем только первому админу чтобы не спамить
    try:
        await context.bot.send_message(
            chat_id=admin_ids[0],
            text=message,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Failed to notify admin about critical error: {e}")


# Функция для регистрации обработчика в приложении
def register_error_handler(app):
    """Регистрация глобального обработчика ошибок."""
    app.add_error_handler(global_error_handler)
    logger.info("Global error handler registered")


# Декоратор для автоматического ответа на callback_query
def auto_answer_callback(func: Callable) -> Callable:
    """Декоратор для автоматического ответа на callback_query."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        async with CallbackAnswerer(update.callback_query):
            return await func(update, context, *args, **kwargs)
    return wrapper