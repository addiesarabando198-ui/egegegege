# payment/auto_renewal_handlers.py - Новый файл с обработчиками автопродления

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from telegram.constants import ParseMode
from .subscription_manager import SubscriptionManager
try:
    from core.error_handler import safe_handler
except ImportError:
    # Fallback если модуль error_handler недоступен
    def safe_handler():
        def decorator(func):
            return func
        return decorator

logger = logging.getLogger(__name__)

@safe_handler()
async def cmd_auto_renewal_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки статуса автопродления."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    try:
        # Получаем статус автопродления
        auto_renewal = await subscription_manager.get_auto_renewal_status(user_id)
        
        if not auto_renewal:
            text = """🔄 <b>Автопродление подписки</b>

У вас не настроено автопродление подписки.

С автопродлением ваша подписка будет автоматически продлеваться каждый месяц, и вы не потеряете доступ к материалам."""
            
            keyboard = [[
                InlineKeyboardButton("✅ Включить автопродление", 
                                   callback_data="enable_auto_renewal")
            ]]
        else:
            if auto_renewal['enabled']:
                text = f"""✅ <b>Автопродление включено</b>

📅 Следующее списание: {auto_renewal['next_renewal_date'].strftime('%d.%m.%Y')}
💳 Способ оплаты: {'Сохраненная карта' if auto_renewal['payment_method'] == 'card' else 'Рекуррентный платеж'}

Подписка будет автоматически продлена в указанную дату."""
                
                keyboard = [[
                    InlineKeyboardButton("❌ Отключить автопродление", 
                                       callback_data="disable_auto_renewal")
                ]]
            else:
                text = """❌ <b>Автопродление отключено</b>

Автопродление было отключено. Вы можете включить его снова в любой момент."""
                
                keyboard = [[
                    InlineKeyboardButton("✅ Включить автопродление", 
                                       callback_data="enable_auto_renewal")
                ]]
        
        keyboard.append([
            InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")
        ])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error checking auto-renewal status: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке статуса автопродления."
        )

@safe_handler()
async def handle_enable_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка включения автопродления."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    try:
        # Проверяем наличие активной подписки
        subscription = await subscription_manager.check_active_subscription(user_id)
        
        if not subscription:
            await query.edit_message_text(
                "❌ У вас нет активной подписки для настройки автопродления.\n\n"
                "Сначала оформите подписку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 Оформить подписку", 
                                       callback_data="subscribe_start")
                ]])
            )
            return
        
        # Проверяем наличие сохраненной карты или рекуррентного токена
        payment_info = await subscription_manager.get_last_payment_info(user_id)
        
        if not payment_info or not payment_info.get('recurrent_id'):
            text = """💳 <b>Настройка автопродления</b>

Для включения автопродления необходимо привязать карту.

При следующей оплате выберите опцию "Сохранить карту для автопродления"."""
            
            keyboard = [[
                InlineKeyboardButton("💳 Привязать карту", 
                                   callback_data="renew_subscription")
            ]]
        else:
            # Включаем автопродление
            success = await subscription_manager.enable_auto_renewal(
                user_id,
                payment_method='recurrent',
                recurrent_token=payment_info['recurrent_id']
            )
            
            if success:
                text = f"""✅ <b>Автопродление успешно включено!</b>

📅 Следующее списание: {subscription['expires_at'].strftime('%d.%m.%Y')}
💰 Сумма: {subscription.get('amount', 0)} ₽

Вы получите уведомление за 3 дня до списания."""
                
                keyboard = [[
                    InlineKeyboardButton("✅ Отлично!", callback_data="close_message")
                ]]
            else:
                text = "❌ Не удалось включить автопродление. Попробуйте позже."
                keyboard = []
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
        
    except Exception as e:
        logger.error(f"Error enabling auto-renewal: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

@safe_handler()
async def handle_disable_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отключает автопродление с улучшенной навигацией."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager')
    
    if query.data == "disable_auto_renewal":
        # Показываем подтверждение
        text = """⚠️ <b>Отключение автопродления</b>

Вы уверены, что хотите отключить автопродление?

После отключения:
- Подписка НЕ будет продлеваться автоматически
- Доступ сохранится до конца оплаченного периода
- Вы сможете включить автопродление снова в любой момент"""
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, отключить", 
                                   callback_data="confirm_disable_auto_renewal"),
                InlineKeyboardButton("❌ Отмена", 
                                   callback_data="cancel_disable_auto_renewal")
            ]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif query.data == "cancel_disable_auto_renewal":
        # ИСПРАВЛЕНИЕ: Возвращаемся к полной информации о подписках
        try:
            # Получаем полную информацию о подписке
            subscription_info = await subscription_manager.get_subscription_info(user_id)
            auto_renewal = await subscription_manager.get_auto_renewal_status(user_id)
            
            if subscription_info:
                # Формируем полный текст с информацией о подписке
                text = "📋 <b>Ваши подписки</b>\n\n"
                
                # Информация о типе подписки
                if subscription_info.get('type') == 'modular':
                    text += "✅ <b>Активные модули:</b>\n"
                    for module in subscription_info.get('modules', []):
                        text += f"   • {module}\n"
                else:
                    plan_name = subscription_info.get('plan_name', 'Подписка')
                    text += f"✅ <b>Активный план:</b> {plan_name}\n"
                
                # Дата истечения
                expires_at = subscription_info.get('expires_at')
                if expires_at:
                    text += f"\n📅 <b>Действует до:</b> {expires_at.strftime('%d.%m.%Y')}\n"
                
                # Информация об автопродлении
                if auto_renewal and auto_renewal.get('enabled'):
                    text += f"\n🔄 <b>Автопродление:</b> Включено\n"
                    text += f"📅 Следующее списание: {auto_renewal['next_renewal_date'].strftime('%d.%m.%Y')}\n"
                    text += f"💰 Сумма: {auto_renewal.get('amount', 0)} ₽"
                else:
                    text += f"\n🔄 <b>Автопродление:</b> Отключено"
                
                # Формируем клавиатуру
                keyboard = []
                
                # Кнопка управления автопродлением
                if auto_renewal and auto_renewal.get('enabled'):
                    keyboard.append([
                        InlineKeyboardButton("❌ Отключить автопродление", 
                                           callback_data="disable_auto_renewal")
                    ])
                else:
                    keyboard.append([
                        InlineKeyboardButton("✅ Включить автопродление", 
                                           callback_data="enable_auto_renewal")
                    ])
                
                # Дополнительные кнопки
                keyboard.append([
                    InlineKeyboardButton("➕ Добавить модули", 
                                       callback_data="subscribe_start")
                ])
                keyboard.append([
                    InlineKeyboardButton("🏠 Главное меню", 
                                       callback_data="to_main_menu")
                ])
                
            else:
                # Если подписки нет
                text = """📋 <b>Ваши подписки</b>

У вас нет активной подписки.

Оформите подписку для доступа к материалам."""
                
                keyboard = [
                    [InlineKeyboardButton("💳 Оформить подписку", 
                                        callback_data="subscribe_start")],
                    [InlineKeyboardButton("🏠 Главное меню", 
                                        callback_data="to_main_menu")]
                ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error showing subscriptions after cancel: {e}")
            # При ошибке показываем упрощенное меню
            try:
                text = "📋 Возвращаемся к управлению подписками..."
                keyboard = [[
                    InlineKeyboardButton("📋 Мои подписки", 
                                       callback_data="my_subscriptions"),
                    InlineKeyboardButton("🏠 Главное меню", 
                                       callback_data="to_main_menu")
                ]]
                
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                # Если и это не работает, вызываем handle_my_subscriptions напрямую
                from .handlers import handle_my_subscriptions
                return await handle_my_subscriptions(update, context)
        
    elif query.data == "confirm_disable_auto_renewal":
        # Подтверждено - отключаем
        try:
            if not subscription_manager:
                await query.edit_message_text("❌ Сервис временно недоступен")
                return
                
            success = await subscription_manager.disable_auto_renewal(user_id)
            
            if success:
                text = """✅ <b>Автопродление отключено</b>

Автоматическое продление подписки отключено.

Ваша текущая подписка будет действовать до конца оплаченного периода.

Вы можете включить автопродление снова в любой момент."""
                
                keyboard = [[
                    InlineKeyboardButton("📋 Мои подписки", 
                                       callback_data="my_subscriptions")
                ]]
            else:
                text = "❌ Не удалось отключить автопродление. Попробуйте позже."
                keyboard = [[
                    InlineKeyboardButton("🔄 Попробовать снова", 
                                       callback_data="disable_auto_renewal"),
                    InlineKeyboardButton("📋 Мои подписки", 
                                       callback_data="my_subscriptions")
                ]]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error disabling auto-renewal: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 Мои подписки", 
                                       callback_data="my_subscriptions")
                ]])
            )

@safe_handler()
async def handle_renew_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка продления подписки."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    try:
        # Получаем информацию о последней подписке
        last_subscription = await subscription_manager.get_last_subscription_info(user_id)
        
        if last_subscription:
            # Предлагаем продлить с тем же планом
            text = f"""💳 <b>Продление подписки</b>

Продлить подписку "{last_subscription['plan_name']}"?

💰 Стоимость: {last_subscription['amount']} ₽/мес"""
            
            keyboard = [
                [InlineKeyboardButton(f"✅ Продлить за {last_subscription['amount']} ₽", 
                                     callback_data=f"pay_plan_{last_subscription['plan_id']}")],
                [InlineKeyboardButton("🔄 Выбрать другой план", 
                                     callback_data="subscribe_start")],
                [InlineKeyboardButton("❌ Отмена", 
                                     callback_data="close_message")]
            ]
        else:
            # Перенаправляем на выбор плана
            text = "Выберите план подписки:"
            keyboard = [[
                InlineKeyboardButton("💳 Выбрать план", 
                                   callback_data="subscribe_start")
            ]]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error handling subscription renewal: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

@safe_handler()
async def manage_auto_renewal_from_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление автопродлением из меню подписок."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager')
    
    if not subscription_manager:
        await query.edit_message_text("❌ Сервис временно недоступен.")
        return
    
    try:
        auto_renewal = await subscription_manager.get_auto_renewal_status(user_id)
        
        if not auto_renewal or not auto_renewal.get('enabled'):
            # Предлагаем включить
            text = """🔄 <b>Управление автопродлением</b>

Автопродление отключено.

Включите автопродление, чтобы не беспокоиться о продлении подписки - она будет обновляться автоматически каждый месяц."""
            
            keyboard = [
                [InlineKeyboardButton("✅ Включить автопродление", 
                                    callback_data="enable_auto_renewal")],
                [InlineKeyboardButton("◀️ Назад", callback_data="my_subscriptions")]
            ]
        else:
            # Показываем информацию и опцию отключения
            text = f"""🔄 <b>Управление автопродлением</b>

✅ Автопродление включено

📅 Следующее списание: {auto_renewal['next_renewal_date'].strftime('%d.%m.%Y')}
💰 Сумма: {auto_renewal.get('amount', 0)} ₽

Подписка продлевается автоматически каждый месяц."""
            
            keyboard = [
                [InlineKeyboardButton("❌ Отключить автопродление", 
                                    callback_data="disable_auto_renewal")],
                [InlineKeyboardButton("◀️ Назад", callback_data="my_subscriptions")]
            ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error managing auto-renewal: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка. Попробуйте позже."
        )

def register_auto_renewal_handlers(app):
    """Регистрирует обработчики автопродления."""
    
    # Команды
    app.add_handler(CommandHandler("auto_renewal", cmd_auto_renewal_status))
    
    # Callback обработчики
    app.add_handler(CallbackQueryHandler(
        handle_enable_auto_renewal, 
        pattern="^enable_auto_renewal$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_disable_auto_renewal, 
        pattern="^(disable_auto_renewal|confirm_disable_auto_renewal|cancel_disable_auto_renewal)$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_renew_subscription, 
        pattern="^renew_subscription$"
    ))
    
    # Обработчик для управления автопродлением из my_subscriptions
    app.add_handler(CallbackQueryHandler(
        manage_auto_renewal_from_subscriptions,
        pattern="^manage_auto_renewal$"
    ))
    
    logger.info("Auto-renewal handlers registered")