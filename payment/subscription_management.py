# payment/subscription_management.py - Управление подпиской и отмена

import logging
import aiosqlite
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from telegram.constants import ParseMode
from core.error_handler import safe_handler

logger = logging.getLogger(__name__)

# Состояния для обратной связи
FEEDBACK_REASON = 1
FEEDBACK_TEXT = 2

class SubscriptionManagementUI:
    """Интерфейс управления подпиской."""
    
    @staticmethod
    @safe_handler()
    async def cmd_manage_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /subscription - главное меню управления подпиской."""
        user_id = update.effective_user.id
        subscription_manager = context.bot_data.get('subscription_manager')
        
        # Получаем информацию о подписке
        subscription = await subscription_manager.get_active_subscription(user_id)
        auto_renewal = await subscription_manager.get_auto_renewal_status(user_id)
        
        if not subscription:
            text = """📋 <b>Управление подпиской</b>

У вас нет активной подписки.

Оформите подписку для доступа к материалам."""
            
            keyboard = [[
                InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")
            ]]
        else:
            # Форматируем информацию о подписке
            plan_name = subscription.get('plan_name', 'Подписка')
            expires_at = subscription['expires_at'].strftime('%d.%m.%Y')
            days_left = (subscription['expires_at'] - datetime.now()).days
            
            text = f"""📋 <b>Управление подпиской</b>

<b>Текущий план:</b> {plan_name}
<b>Действует до:</b> {expires_at} (осталось {days_left} дней)"""
            
            # Добавляем информацию об автопродлении
            if auto_renewal and auto_renewal['enabled']:
                next_payment = subscription.get('amount', 0)
                text += f"""

🔄 <b>Автопродление:</b> ✅ Включено
💰 <b>Следующее списание:</b> {next_payment} ₽
📅 <b>Дата списания:</b> {expires_at}"""
            else:
                text += "\n\n🔄 <b>Автопродление:</b> ❌ Выключено"
            
            # Создаем клавиатуру с опциями
            keyboard = []
            
            if auto_renewal and auto_renewal['enabled']:
                keyboard.append([
                    InlineKeyboardButton("❌ Отменить автопродление", 
                                       callback_data="cancel_auto_renewal")
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("✅ Включить автопродление", 
                                       callback_data="enable_auto_renewal")
                ])
            
            keyboard.extend([
                [InlineKeyboardButton("📊 История платежей", 
                                    callback_data="payment_history")],
                [InlineKeyboardButton("💳 Сменить карту", 
                                    callback_data="change_payment_method")],
                [InlineKeyboardButton("📞 Связаться с поддержкой", 
                                    callback_data="contact_support")],
                [InlineKeyboardButton("🚪 Отменить подписку", 
                                    callback_data="cancel_subscription")]
            ])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def check_module_access(self, user_id: int, module_code: str) -> bool:
        """
        Проверяет доступ пользователя к модулю.
        
        Args:
            user_id: ID пользователя
            module_code: Код модуля
            
        Returns:
            bool: True если есть доступ
        """
        try:
            # ИСПРАВЛЕНИЕ: test_part всегда доступен
            if module_code == 'test_part':
                return True
                
            # Проверяем админов
            admin_ids = self._get_admin_ids()
            if user_id in admin_ids:
                return True
            
            # Проверяем в кэше
            cache_key = f"access_{user_id}_{module_code}"
            if cache_key in self._cache:
                cached_result, cache_time = self._cache[cache_key]
                if (datetime.now() - cache_time).seconds < 300:  # 5 минут кэш
                    return cached_result
            
            # Проверяем в базе данных
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                
                if self.modular_mode:
                    # Модульная система - проверяем конкретный модуль
                    cursor = await db.execute("""
                        SELECT expires_at 
                        FROM user_subscriptions 
                        WHERE user_id = ? 
                            AND module_id = ?
                            AND expires_at > datetime('now')
                        ORDER BY expires_at DESC
                        LIMIT 1
                    """, (user_id, module_code))
                else:
                    # Единая подписка - проверяем план
                    cursor = await db.execute("""
                        SELECT plan_id, expires_at
                        FROM user_subscriptions 
                        WHERE user_id = ? 
                            AND is_active = 1
                            AND expires_at > datetime('now')
                        ORDER BY expires_at DESC
                        LIMIT 1
                    """, (user_id,))
                    
                    row = await cursor.fetchone()
                    if row:
                        plan = self.SUBSCRIPTION_PLANS.get(row['plan_id'], {})
                        modules = plan.get('modules', [])
                        has_access = module_code in modules
                        
                        # Кэшируем результат
                        self._cache[cache_key] = (has_access, datetime.now())
                        return has_access
                        
                    # Кэшируем отрицательный результат
                    self._cache[cache_key] = (False, datetime.now())
                    return False
                
                row = await cursor.fetchone()
                has_access = row is not None
                
                # Кэшируем результат
                self._cache[cache_key] = (has_access, datetime.now())
                return has_access
                
        except Exception as e:
            logger.error(f"Error checking module access: {e}")
            return False

    @staticmethod
    @safe_handler()
    async def cancel_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена автопродления."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        text = """⚠️ <b>Отмена автопродления</b>

Вы уверены, что хотите отключить автоматическое продление?

После отключения:
• Подписка НЕ будет продлеваться автоматически
• Доступ сохранится до конца оплаченного периода
• Вы сможете продлить подписку вручную

Отключить автопродление?"""
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, отключить", 
                                   callback_data="confirm_cancel_auto_renewal"),
                InlineKeyboardButton("❌ Нет, оставить", 
                                   callback_data="keep_auto_renewal")
            ]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    @staticmethod
    @safe_handler()
    async def confirm_cancel_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение отмены автопродления."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        subscription_manager = context.bot_data.get('subscription_manager')
        
        # Отключаем автопродление
        success = await subscription_manager.disable_auto_renewal(user_id)
        
        if success:
            # Логируем отмену
            await subscription_manager.log_cancellation(
                user_id, 
                reason="user_request",
                details="Отмена через меню управления"
            )
            
            text = """✅ <b>Автопродление отключено</b>

Автоматическое продление подписки отключено.

Ваша подписка останется активной до конца оплаченного периода.

Вы можете в любой момент:
• Включить автопродление снова
• Продлить подписку вручную

Хотите рассказать, почему решили отключить автопродление?"""
            
            keyboard = [
                [
                    InlineKeyboardButton("💬 Оставить отзыв", 
                                       callback_data="leave_cancellation_feedback"),
                    InlineKeyboardButton("⏭ Пропустить", 
                                       callback_data="skip_feedback")
                ]
            ]
        else:
            text = "❌ Произошла ошибка при отключении автопродления. Попробуйте позже."
            keyboard = []
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )

    @staticmethod
    @safe_handler()
    async def keep_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена отключения автопродления - возврат к управлению."""
        query = update.callback_query
        await query.answer("Автопродление остается включенным")

        # Возвращаемся к управлению подпиской
        return await SubscriptionManagementUI.cmd_manage_subscription(update, context)

    @staticmethod
    @safe_handler()
    async def cancellation_feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало сбора обратной связи об отмене."""
        query = update.callback_query
        await query.answer()
        
        text = """💬 <b>Обратная связь</b>

Почему вы решили отключить автопродление?

Выберите причину:"""
        
        keyboard = [
            [InlineKeyboardButton("💰 Слишком дорого", 
                                callback_data="feedback_expensive")],
            [InlineKeyboardButton("📚 Больше не нужно", 
                                callback_data="feedback_not_needed")],
            [InlineKeyboardButton("❌ Не устраивает качество", 
                                callback_data="feedback_quality")],
            [InlineKeyboardButton("💳 Проблемы с оплатой", 
                                callback_data="feedback_payment_issues")],
            [InlineKeyboardButton("🔄 Хочу платить вручную", 
                                callback_data="feedback_manual_payment")],
            [InlineKeyboardButton("💬 Другая причина", 
                                callback_data="feedback_other")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return FEEDBACK_REASON
    
    @staticmethod
    @safe_handler()
    async def handle_feedback_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбранной причины отмены."""
        query = update.callback_query
        await query.answer()
        
        # Сохраняем причину
        reason = query.data.replace('feedback_', '')
        context.user_data['cancellation_reason'] = reason
        
        text = """📝 <b>Дополнительный комментарий</b>

Расскажите подробнее о причине отмены (необязательно).

Ваш отзыв поможет нам стать лучше.

Отправьте текстовое сообщение или нажмите "Пропустить"."""
        
        keyboard = [[
            InlineKeyboardButton("⏭ Пропустить", callback_data="skip_detailed_feedback")
        ]]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return FEEDBACK_TEXT
    
    @staticmethod
    @safe_handler()
    async def handle_feedback_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстового отзыва."""
        user_id = update.effective_user.id
        feedback_text = update.message.text
        reason = context.user_data.get('cancellation_reason', 'unknown')
        
        # Сохраняем отзыв в базу
        subscription_manager = context.bot_data.get('subscription_manager')
        await subscription_manager.save_feedback(
            user_id=user_id,
            reason=reason,
            text=feedback_text,
            feedback_type='cancellation'
        )
        
        await update.message.reply_text(
            """✅ <b>Спасибо за отзыв!</b>

Мы обязательно учтем ваше мнение для улучшения сервиса.

Если передумаете, вы всегда можете:
• /subscription - управление подпиской
• /auto_renewal - включить автопродление""",
            parse_mode=ParseMode.HTML
        )
        
        return ConversationHandler.END
    
    @staticmethod
    @safe_handler()
    async def contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Контакт с поддержкой."""
        query = update.callback_query
        await query.answer()
        
        text = """📞 <b>Служба поддержки</b>

<b>Способы связи:</b>

💬 <b>Telegram:</b> @obshestvonapalcahsupport
⏰ <b>Время работы:</b> Пн-Пт 9:00-18:00 (МСК)

<b>Частые вопросы:</b>

<b>❓ Как отменить автопродление?</b>
Используйте команду /subscription и выберите "Отменить автопродление"

<b>❓ Как вернуть деньги?</b>
Напишите в поддержку с указанием номера заказа

<b>❓ Как сменить карту?</b>
В меню /subscription выберите "Сменить карту"

<b>❓ Когда произойдет списание?</b>
За 3 дня до списания вы получите уведомление

Выберите действие:"""
        
        keyboard = [
            [InlineKeyboardButton("💬 Написать в поддержку", 
                                url="https://t.me/obshestvonapalcahsupport")],
            [InlineKeyboardButton("⬅️ Назад", 
                                callback_data="back_to_subscription")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    @staticmethod
    @safe_handler()
    async def payment_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ истории платежей."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        subscription_manager = context.bot_data.get('subscription_manager')
        
        # Получаем историю платежей
        payments = await subscription_manager.get_payment_history(user_id, limit=10)
        
        if not payments:
            text = """📊 <b>История платежей</b>

У вас пока нет платежей."""
        else:
            text = """📊 <b>История платежей</b>

<b>Последние операции:</b>\n\n"""
            
            for payment in payments:
                date = payment['created_at'].strftime('%d.%m.%Y')
                amount = payment['amount'] / 100  # Из копеек в рубли
                status_emoji = "✅" if payment['status'] == 'completed' else "❌"
                
                text += f"{status_emoji} {date} - {amount} ₽ - {payment.get('plan_name', 'Подписка')}\n"
        
        keyboard = [[
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_subscription")
        ]]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


def get_subscription_management_handlers():
    """Возвращает обработчики для управления подпиской."""
    ui = SubscriptionManagementUI()
    
    # ConversationHandler для обратной связи
    feedback_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ui.cancellation_feedback_start, 
                                pattern="^leave_cancellation_feedback$")
        ],
        states={
            FEEDBACK_REASON: [
                CallbackQueryHandler(ui.handle_feedback_reason, 
                                   pattern="^feedback_")
            ],
            FEEDBACK_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ui.handle_feedback_text),
                CallbackQueryHandler(lambda u, c: ConversationHandler.END, 
                                   pattern="^skip_detailed_feedback$")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END)
        ],
        name="subscription_feedback_conversation",
        persistent=True
    )
    
    return [
        CommandHandler("subscription", ui.cmd_manage_subscription),
        CallbackQueryHandler(ui.cancel_auto_renewal, 
                           pattern="^cancel_auto_renewal$"),
        CallbackQueryHandler(ui.confirm_cancel_auto_renewal, 
                           pattern="^confirm_cancel_auto_renewal$"),
        CallbackQueryHandler(ui.contact_support, 
                           pattern="^contact_support$"),
        CallbackQueryHandler(ui.payment_history, 
                           pattern="^payment_history$"),
        feedback_conv
    ]