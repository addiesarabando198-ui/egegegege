"""Middleware для автоматического обновления данных пользователей."""
import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from core import db

logger = logging.getLogger(__name__)

async def update_user_data_on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет данные пользователя при каждом текстовом сообщении."""
    if update.effective_user and update.message:
        user = update.effective_user
        try:
            await db.update_user_info(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
        except Exception as e:
            logger.error(f"Error updating user info in middleware: {e}")

async def update_user_data_on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет данные пользователя при callback запросах."""
    if update.effective_user and update.callback_query:
        user = update.effective_user
        try:
            await db.update_user_info(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
        except Exception as e:
            logger.error(f"Error updating user info in callback middleware: {e}")

def register_user_middleware(app):
    """Регистрирует middleware для обновления данных пользователей."""
    # Обновляем данные при текстовых сообщениях
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            update_user_data_on_message
        ),
        group=-1  # Выполняется первым
    )
    
    # Для callback queries используем CallbackQueryHandler
    from telegram.ext import CallbackQueryHandler
    app.add_handler(
        CallbackQueryHandler(
            update_user_data_on_callback,
            pattern=".*"  # Для всех callback
        ),
        group=-1  # Выполняется первым
    )
    
    logger.info("User data middleware registered")