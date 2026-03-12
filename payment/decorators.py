# payment/decorators.py
"""Декораторы для проверки подписки и доступа к модулям."""
import functools
import logging
from typing import Callable, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .subscription_manager import SubscriptionManager
from .config import SUBSCRIPTION_MODE, SUBSCRIPTION_PLANS

logger = logging.getLogger(__name__)


def requires_subscription(
    plan_level: Optional[str] = None,
    send_message: bool = True,
    check_channel: bool = False
) -> Callable:
    """
    Декоратор для проверки подписки (старая система).
    
    Args:
        plan_level: Минимальный уровень подписки (basic_month, pro_month, pro_ege)
        send_message: Отправлять ли сообщение о необходимости подписки
        check_channel: Проверять ли также подписку на канал
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not update.effective_user:
                return await func(update, context, *args, **kwargs)
            
            user_id = update.effective_user.id
            
            # Проверяем админов
            from core import config
            admin_ids = []
            if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
                if isinstance(config.ADMIN_IDS, str):
                    admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
                elif isinstance(config.ADMIN_IDS, list):
                    admin_ids = config.ADMIN_IDS
            
            if user_id in admin_ids:
                return await func(update, context, *args, **kwargs)
            
            # Получаем менеджер из контекста
            subscription_manager = context.bot_data.get('subscription_manager')
            if not subscription_manager:
                subscription_manager = SubscriptionManager()
            
            # Проверяем активную подписку
            subscription = await subscription_manager.check_active_subscription(user_id)
            
            if subscription:
                # Проверяем уровень подписки если указан
                if plan_level:
                    plan_hierarchy = {
                        'basic_month': 1,
                        'pro_month': 2,
                        'pro_ege': 3
                    }
                    
                    user_level = plan_hierarchy.get(subscription['plan_id'], 0)
                    required_level = plan_hierarchy.get(plan_level, 0)
                    
                    if user_level >= required_level:
                        return await func(update, context, *args, **kwargs)
                else:
                    return await func(update, context, *args, **kwargs)
            
            # Проверяем подписку на канал как альтернативу
            if check_channel:
                from core import config, utils
                if hasattr(config, 'REQUIRED_CHANNEL'):
                    is_member = await utils.check_subscription(
                        context.bot, 
                        user_id, 
                        config.REQUIRED_CHANNEL
                    )
                    if is_member:
                        return await func(update, context, *args, **kwargs)
            
            # Нет подписки - отправляем сообщение
            if send_message:
                text = """❌ <b>Требуется подписка!</b>

Для доступа к этой функции необходима активная подписка.

Используйте /subscribe для выбора подходящего плана."""
                
                keyboard = [[
                    InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                    await update.callback_query.answer("Требуется подписка!", show_alert=True)
                    try:
                        await update.callback_query.edit_message_text(
                            text, 
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    except:
                        await update.callback_query.message.reply_text(
                            text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                elif update.message:
                    await update.message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
            
            return None
        
        return wrapper
    return decorator


def requires_module(module_code: str, send_message: bool = True) -> Callable:
    """
    Декоратор для проверки доступа к модулю (модульная система).

    Args:
        module_code: Код модуля ('test_part', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25')
        send_message: Отправлять ли сообщение о необходимости подписки
    
    Использование:
        @requires_module('task24')
        async def premium_function(update, context):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not update.effective_user:
                return await func(update, context, *args, **kwargs)
            
            user_id = update.effective_user.id
            
            # Проверяем админов
            from core import config
            admin_ids = []
            if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
                if isinstance(config.ADMIN_IDS, str):
                    admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
                elif isinstance(config.ADMIN_IDS, list):
                    admin_ids = config.ADMIN_IDS
            
            if user_id in admin_ids:
                logger.info(f"Admin {user_id} bypassing module check for {module_code}")
                return await func(update, context, *args, **kwargs)
            
            # Получаем менеджер из контекста
            subscription_manager = context.bot_data.get('subscription_manager')
            if not subscription_manager:
                subscription_manager = SubscriptionManager()
            
            # Проверяем доступ к модулю
            has_access = await subscription_manager.check_module_access(user_id, module_code)
            
            if has_access:
                logger.info(f"User {user_id} has access to module {module_code}")
                return await func(update, context, *args, **kwargs)
            
            # Нет доступа - показываем сообщение
            if send_message:
                module_names = {
                    'test_part': '📝 Тестовая часть',
                    'task19': '🎯 Задание 19',
                    'task20': '📖 Задание 20',
                    'task22': '📝 Задание 22',
                    'task23': '📜 Задание 23 (Конституция РФ)',
                    'task24': '💎 Задание 24 (Премиум)',
                    'task25': '✍️ Задание 25'
                }
                module_name = module_names.get(module_code, module_code)
                
                # Находим минимальную цену для этого модуля
                min_price = None
                for plan_id, plan in SUBSCRIPTION_PLANS.items():
                    if module_code in plan.get('modules', []):
                        price = plan.get('price_rub', 0)
                        if min_price is None or price < min_price:
                            min_price = price
                
                text = f"🔒 <b>Доступ к модулю '{module_name}' ограничен</b>\n\n"
                
                if min_price:
                    text += f"💰 Доступ от {min_price}₽/месяц\n\n"
                
                text += "Для доступа необходима подписка.\n"
                text += "Выберите подходящий план:"
                
                keyboard = [[
                    InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")
                ]]
                
                # Добавляем кнопку "Мои подписки" если есть другие активные модули
                user_modules = await subscription_manager.get_user_modules(user_id)
                if user_modules:
                    keyboard.append([
                        InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")
                    ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                    await update.callback_query.answer(
                        f"Требуется подписка на {module_name}!", 
                        show_alert=True
                    )
                    try:
                        await update.callback_query.edit_message_text(
                            text, 
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Error editing message: {e}")
                        await update.callback_query.message.reply_text(
                            text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                elif update.message:
                    await update.message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
            
            return None
        
        return wrapper
    return decorator



def requires_any_subscription(send_message: bool = True) -> Callable:
    """
    Универсальный декоратор, работающий в обоих режимах.
    Проверяет наличие любой активной подписки.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not update.effective_user:
                return await func(update, context, *args, **kwargs)
            
            user_id = update.effective_user.id
            
            # Проверяем админов
            from core import config
            admin_ids = []
            if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
                if isinstance(config.ADMIN_IDS, str):
                    admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
                elif isinstance(config.ADMIN_IDS, list):
                    admin_ids = config.ADMIN_IDS
            
            if user_id in admin_ids:
                return await func(update, context, *args, **kwargs)
            
            # Получаем менеджер из контекста
            subscription_manager = context.bot_data.get('subscription_manager')
            if not subscription_manager:
                subscription_manager = SubscriptionManager()
            
            # Проверяем любую активную подписку
            if SUBSCRIPTION_MODE == 'modular':
                user_modules = await subscription_manager.get_user_modules(user_id)
                has_subscription = len(user_modules) > 0
            else:
                subscription = await subscription_manager.check_active_subscription(user_id)
                has_subscription = subscription is not None
            
            if has_subscription:
                return await func(update, context, *args, **kwargs)
            
            # Нет подписки - показываем сообщение
            if send_message:
                text = """❌ <b>Требуется подписка!</b>

Для использования бота необходима активная подписка.

Выберите подходящий план:"""
                
                keyboard = [[
                    InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                    await update.callback_query.answer("Требуется подписка!", show_alert=True)
                    try:
                        await update.callback_query.edit_message_text(
                            text, 
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    except:
                        await update.callback_query.message.reply_text(
                            text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                elif update.message:
                    await update.message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
            
            return None
        
        return wrapper
    return decorator