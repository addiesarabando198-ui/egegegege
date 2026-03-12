# payment/consent_handler.py - Новый модуль для обработки согласия на автопродление

import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler
from telegram.constants import ParseMode
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
CONSENT_WAITING = 1
CONSENT_CONFIRMED = 2

class AutoRenewalConsent:
    """Класс для управления согласием на автопродление."""
    
    def __init__(self):
        self.user_consents: Dict[int, Dict] = {}
    
    async def show_auto_renewal_consent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает форму согласия на автопродление."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        plan_data = context.user_data.get('selected_plan_data', {})
        plan_name = plan_data.get('name', 'Подписка')
        price = plan_data.get('price_rub', 0)
        
        # Сохраняем временное состояние
        self.user_consents[user_id] = {
            'checkbox_state': False,
            'timestamp': datetime.now()
        }
        
        text = f"""🔄 <b>Оформление автоматического продления</b>

📋 <b>Условия автопродления:</b>

💰 <b>Сумма списания:</b> {price} ₽
📅 <b>Периодичность:</b> Ежемесячно (каждые 30 дней)
⏰ <b>Дата первого продления:</b> {(datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y')}

<b>Что включает автопродление:</b>
✅ Автоматическое списание средств каждый месяц
✅ Непрерывный доступ к материалам
✅ Уведомление за 3 дня до списания
✅ Возможность отмены в любой момент

⚠️ <b>Важно:</b>
• Списания происходят без дополнительного подтверждения
• Вы можете отменить автопродление в любое время через /auto_renewal
• При недостатке средств подписка будет приостановлена
• После 3 неудачных попыток автопродление отключается

📞 <b>Поддержка и отмена:</b>
• Команда /auto_renewal - управление автопродлением
• Команда /support - связь с поддержкой
• Email: support@yourdomain.com

<b>Для продолжения необходимо ваше согласие:</b>"""
        
        # Клавиатура с чек-боксом
        checkbox_emoji = "☑️" if self.user_consents[user_id]['checkbox_state'] else "⬜"
        
        keyboard = [
            [InlineKeyboardButton(
                f"{checkbox_emoji} Я согласен(на) с условиями автопродления",
                callback_data="toggle_consent_checkbox"
            )],
            [
                InlineKeyboardButton("✅ Подтвердить и оплатить", 
                                   callback_data="confirm_with_auto_renewal"),
                InlineKeyboardButton("❌ Отказаться", 
                                   callback_data="decline_auto_renewal")
            ],
            [InlineKeyboardButton("📄 Пользовательское соглашение", 
                                callback_data="show_user_agreement")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CONSENT_WAITING
    
    async def toggle_checkbox(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Переключает состояние чек-бокса."""
        query = update.callback_query
        user_id = update.effective_user.id
        
        # Переключаем состояние
        if user_id in self.user_consents:
            self.user_consents[user_id]['checkbox_state'] = not self.user_consents[user_id]['checkbox_state']
            
            # Обновляем сообщение с новым состоянием чек-бокса
            await self.show_auto_renewal_consent(update, context)
            await query.answer("✅ Отмечено" if self.user_consents[user_id]['checkbox_state'] else "Снято")
        else:
            await query.answer("Ошибка. Попробуйте заново.")
    
    async def confirm_with_consent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждает оплату с автопродлением после получения согласия."""
        query = update.callback_query
        user_id = update.effective_user.id
        
        # Проверяем, что чек-бокс отмечен
        if user_id not in self.user_consents or not self.user_consents[user_id]['checkbox_state']:
            await query.answer(
                "⚠️ Необходимо отметить согласие с условиями автопродления",
                show_alert=True
            )
            return CONSENT_WAITING
        
        await query.answer("✅ Согласие получено")
        
        # Сохраняем согласие в базу данных
        await self.save_consent_to_db(user_id, context)
        
        # Устанавливаем флаг автопродления
        context.user_data['enable_auto_renewal'] = True
        context.user_data['consent_timestamp'] = datetime.now()
        context.user_data['consent_ip'] = query.message.chat.id  # Можно получить IP если нужно
        
        # Переходим к оплате
        from .handlers import handle_payment_confirmation_with_recurrent
        return await handle_payment_confirmation_with_recurrent(update, context)
    
    async def decline_auto_renewal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отказ от автопродления - переход к обычной оплате."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        # Очищаем данные о согласии
        if user_id in self.user_consents:
            del self.user_consents[user_id]
        
        context.user_data['enable_auto_renewal'] = False
        
        # Переходим к обычной оплате без автопродления
        text = """💳 <b>Оплата без автопродления</b>

Вы выбрали разовую оплату без автоматического продления.

После окончания подписки вам нужно будет продлить её вручную.

Продолжить оплату?"""
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Оплатить", callback_data="confirm_payment"),
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")
            ],
            [InlineKeyboardButton("🔄 Вернуться к автопродлению", 
                                callback_data="back_to_auto_renewal")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return ConversationHandler.END
    
    async def save_consent_to_db(self, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Сохраняет согласие пользователя в базу данных."""
        try:
            import aiosqlite
            from .subscription_manager import SubscriptionManager
            
            subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
            
            async with aiosqlite.connect(subscription_manager.database_file) as conn:
                # Создаем таблицу для хранения согласий если её нет (полная схема)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS auto_renewal_consents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        plan_id TEXT,
                        amount INTEGER,
                        period_days INTEGER DEFAULT 30,
                        consent_text TEXT NOT NULL,
                        consent_checkbox_state BOOLEAN DEFAULT 1,
                        ip_address TEXT,
                        user_agent TEXT,
                        telegram_chat_id INTEGER,
                        message_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    )
                """)

                # Сохраняем согласие (используем полную схему)
                plan_data = context.user_data.get('selected_plan_data', {})
                consent_text = f"Согласие на автопродление подписки {plan_data.get('name')} за {plan_data.get('price_rub')} руб. ежемесячно"

                await conn.execute("""
                    INSERT INTO auto_renewal_consents
                    (user_id, plan_id, amount, period_days, consent_text, consent_checkbox_state,
                     telegram_chat_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    user_id,
                    context.user_data.get('selected_plan'),
                    plan_data.get('price_rub', 0) * 100,  # В копейках
                    30,  # период в днях
                    consent_text,
                    True,  # чекбокс активен
                    user_id  # telegram_chat_id совпадает с user_id
                ))
                
                await conn.commit()
                logger.info(f"Consent saved for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error saving consent: {e}")
    
    async def show_user_agreement(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает пользовательское соглашение."""
        query = update.callback_query
        await query.answer()
        
        text = """📄 <b>Пользовательское соглашение - Автоматическое продление</b>

<b>1. Общие положения</b>
1.1. Настоящее соглашение регулирует условия автоматического продления подписки.
1.2. Активируя автопродление, вы соглашаетесь с условиями данного соглашения.

<b>2. Условия автопродления</b>
2.1. Списание происходит автоматически каждые 30 дней.
2.2. Сумма списания соответствует стоимости выбранного тарифа.
2.3. Списание происходит с привязанной банковской карты.

<b>3. Уведомления</b>
3.1. За 3 дня до списания вы получите уведомление.
3.2. Уведомления отправляются в Telegram.

<b>4. Отмена автопродления</b>
4.1. Вы можете отменить автопродление в любое время.
4.2. Для отмены используйте команду /auto_renewal.
4.3. Отмена вступает в силу немедленно.

<b>5. Возвраты</b>
5.1. Возврат средств осуществляется согласно политике возвратов.
5.2. Для возврата обратитесь в поддержку: /support

<b>6. Ответственность</b>
6.1. Вы несете ответственность за наличие средств на карте.
6.2. При недостатке средств подписка приостанавливается.

<b>7. Контакт</b>
Поддержка: @obshestvonapalcahsupport"""

        keyboard = [[
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_consent")
        ]]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# Функция для создания обработчиков
def get_consent_handlers():
    """Возвращает обработчики для согласия на автопродление."""
    consent_manager = AutoRenewalConsent()
    
    return [
        CallbackQueryHandler(
            consent_manager.show_auto_renewal_consent,
            pattern="^setup_auto_renewal$"
        ),
        CallbackQueryHandler(
            consent_manager.toggle_checkbox,
            pattern="^toggle_consent_checkbox$"
        ),
        CallbackQueryHandler(
            consent_manager.confirm_with_consent,
            pattern="^confirm_with_auto_renewal$"
        ),
        CallbackQueryHandler(
            consent_manager.decline_auto_renewal,
            pattern="^decline_auto_renewal$"
        ),
        CallbackQueryHandler(
            consent_manager.show_user_agreement,
            pattern="^show_user_agreement$"
        )
    ]