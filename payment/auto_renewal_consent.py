"""
Модуль для управления автопродлением подписок и согласиями пользователей.
Полноценная реализация с уведомлениями и многомесячными подписками.
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
# Если используете aiogram где-то еще, замените на telegram
# from aiogram import types, Bot
# from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
# from aiogram.dispatcher import FSMContext
# from aiogram.dispatcher.filters.state import State, StatesGroup

logger = logging.getLogger(__name__)

# Состояния для автопродления
# Замените aiogram states на обычные константы для telegram-python-bot
SHOWING_TERMS = "showing_terms"
CONSENT_CHECKBOX = "consent_checkbox"
FINAL_CONFIRMATION = "final_confirmation"

class AutoRenewalConsent:
    """Класс для управления согласиями на автопродление."""
    
    def __init__(self, subscription_manager):
        self.subscription_manager = subscription_manager
        self.user_consents = {}
        
    async def handle_choice_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора типа оплаты."""
        query = update.callback_query
        await query.answer()
        
        if query.data == "choose_auto_renewal":
            # Показываем экран с условиями и чек-боксом
            return await self.show_consent_screen(update, context)
        elif query.data == "choose_no_auto_renewal":
            # Обычная оплата без автопродления
            context.user_data['enable_auto_renewal'] = False
            # Переходим к оплате
            from .handlers import handle_payment_confirmation_with_recurrent
            return await handle_payment_confirmation_with_recurrent(update, context)
        elif query.data == "show_auto_renewal_terms":
            # Показываем подробные условия
            return await self.show_detailed_terms(update, context)
    
    async def show_consent_screen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает экран согласия с чек-боксом."""
        query = update.callback_query
        user_id = update.effective_user.id
        
        # Инициализируем состояние согласия для пользователя
        if user_id not in self.user_consents:
            self.user_consents[user_id] = {
                'checkbox_state': False,
                'timestamp': None
            }
        
        checkbox = "☑️" if self.user_consents[user_id]['checkbox_state'] else "⬜"
        
        text = f"""📋 <b>Условия автоматического продления</b>

При включении автопродления:
- Подписка продлевается автоматически каждый месяц
- Списание происходит за день до окончания текущего периода
- Вы можете отменить автопродление в любой момент
- История всех платежей сохраняется в боте

{checkbox} Я согласен с условиями автоматического продления

Нажмите на чек-бокс для подтверждения согласия."""

        keyboard = [
            [InlineKeyboardButton(
                f"{checkbox} Подтвердить согласие",
                callback_data="toggle_consent_checkbox"
            )],
            [InlineKeyboardButton(
                "✅ Продолжить" if self.user_consents[user_id]['checkbox_state'] else "⚠️ Отметьте согласие",
                callback_data="confirm_with_auto_renewal" if self.user_consents[user_id]['checkbox_state'] else "need_consent_reminder"
            )],
            [InlineKeyboardButton(
                "📖 Подробные условия",
                callback_data="show_user_agreement"
            )],
            [InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="back_to_payment_choice"
            )]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CONSENT_CHECKBOX
    
    async def toggle_consent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Переключает состояние чек-бокса согласия."""
        query = update.callback_query
        user_id = update.effective_user.id
        
        if user_id in self.user_consents:
            self.user_consents[user_id]['checkbox_state'] = not self.user_consents[user_id]['checkbox_state']
            # Обновляем экран с новым состоянием
            await self.show_consent_screen(update, context)
            await query.answer("✅ Отмечено" if self.user_consents[user_id]['checkbox_state'] else "Снято")
        else:
            await query.answer("Ошибка. Попробуйте заново.")
        
        return CONSENT_CHECKBOX
    
    async def confirm_with_auto_renewal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждает оплату с автопродлением."""
        query = update.callback_query
        user_id = update.effective_user.id
        
        if user_id not in self.user_consents or not self.user_consents[user_id]['checkbox_state']:
            await query.answer(
                "⚠️ Необходимо отметить согласие с условиями автопродления",
                show_alert=True
            )
            return CONSENT_CHECKBOX
        
        await query.answer("✅ Согласие получено")
        
        # Сохраняем согласие
        context.user_data['enable_auto_renewal'] = True
        context.user_data['consent_timestamp'] = datetime.now()
        
        # Переходим к оплате
        from .handlers import handle_payment_confirmation_with_recurrent
        return await handle_payment_confirmation_with_recurrent(update, context)
    
    async def proceed_to_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Переход к финальному подтверждению платежа."""
            query = update.callback_query
            
            plan_name = context.user_data.get('selected_plan', 'Стандарт')
            duration = context.user_data.get('duration_months', 1)
            # Получаем цену с учетом триала
            plan_id = context.user_data.get('selected_plan')
            if plan_id == 'trial_7days':
                price = 1
            else:
                price = context.user_data.get('price') or context.user_data.get('total_price', 999)
            email = context.user_data.get('email', '')
            auto_renewal = context.user_data.get('enable_auto_renewal', False)
            
            renewal_text = "🔄 С автопродлением" if auto_renewal else "💳 Разовая оплата"
            
            text = f"""✅ <b>Подтверждение оплаты</b>

    📋 <b>Детали заказа:</b>
    • Тариф: <b>{plan_name}</b>
    • Период: <b>{duration} мес.</b>
    • Email: <b>{email}</b>
    • Тип оплаты: <b>{renewal_text}</b>

    💰 <b>К оплате: {price} ₽</b>

    Нажмите "Оплатить" для перехода к платежной форме."""

            keyboard = [
                [InlineKeyboardButton(
                    f"💳 Оплатить {price} ₽",
                    callback_data="proceed_to_payment"
                )],
                [InlineKeyboardButton(
                    "❌ Отменить",
                    callback_data="cancel_payment"
                )]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return FINAL_CONFIRMATION
        
    async def save_consent_to_db(self, user_id: int, plan_id: str, amount: int, period_days: int):
        """Сохранить согласие пользователя в БД."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO auto_renewal_consents 
                (user_id, plan_id, amount, period_days, consent_text, consent_checkbox_state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                plan_id,
                amount,
                period_days,
                f"Согласие на автопродление подписки {plan_id} каждые {period_days} дней",
                1,
                datetime.now()
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Saved auto-renewal consent for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error saving consent: {e}")
    
    async def show_detailed_terms(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает подробные условия автопродления."""
        query = update.callback_query
        await query.answer()
        
        text = """📜 <b>Пользовательское соглашение об автопродлении</b>

<b>1. Общие положения</b>
Автоматическое продление (автопродление) — это услуга, позволяющая автоматически продлевать подписку без необходимости ручного подтверждения.

<b>2. Как это работает</b>
- После первой оплаты сохраняется токен вашей карты
- За день до окончания подписки происходит автоматическое списание
- Вы получаете уведомление о предстоящем и совершенном платеже
- Подписка продлевается на тот же срок

<b>3. Безопасность</b>
- Мы не храним данные вашей карты
- Все платежи проходят через защищенный процессинг Тинькофф
- Соответствие стандарту PCI DSS

<b>4. Отмена автопродления</b>
- Вы можете отменить автопродление в любой момент
- Используйте команду /auto_renewal
- Отмена не влияет на текущий оплаченный период

<b>5. Возвраты</b>
- Возврат возможен в течение 14 дней
- Обратитесь в поддержку @obshestvonapalcahsupport"""

        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_payment_choice")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return SHOWING_TERMS
    
    async def handle_back_navigation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка навигации назад."""
        # Возвращаемся к выбору типа оплаты
        return await show_auto_renewal_choice(update, context)



class SubscriptionNotificationManager:
    """Менеджер уведомлений о подписках."""
    
    def __init__(self, bot, db_path: str = "/opt/ege-bot/subscriptions.db"):
        self.bot = bot
        self.db_path = db_path
        self.is_running = False
        
    async def start(self):
        """Запустить проверку подписок."""
        if self.is_running:
            return
        
        self.is_running = True
        asyncio.create_task(self._notification_loop())
        logger.info("Subscription notification manager started")
    
    async def stop(self):
        """Остановить проверку подписок."""
        self.is_running = False
        logger.info("Subscription notification manager stopped")
    
    async def _notification_loop(self):
        """Основной цикл проверки подписок."""
        while self.is_running:
            try:
                await self.check_expiring_subscriptions()
                await self.process_auto_renewals()
                
                # Проверяем каждые 6 часов
                await asyncio.sleep(21600)
                
            except Exception as e:
                logger.error(f"Error in notification loop: {e}")
                await asyncio.sleep(300)  # При ошибке ждем 5 минут
    
    async def check_expiring_subscriptions(self):
        """Проверить истекающие подписки и отправить уведомления."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Находим подписки, истекающие через 3 дня
            three_days_later = datetime.now() + timedelta(days=3)
            
            cursor.execute("""
                SELECT DISTINCT user_id, plan_id, end_date, auto_renewal_enabled
                FROM expiring_subscriptions
                WHERE end_date BETWEEN ? AND ?
                AND last_notification_date IS NULL OR last_notification_date < ?
            """, (
                datetime.now(),
                three_days_later,
                datetime.now() - timedelta(days=1)
            ))
            
            expiring_subs = cursor.fetchall()
            
            for user_id, plan_id, end_date, auto_renewal in expiring_subs:
                await self.send_expiry_notification(
                    user_id, plan_id, end_date, bool(auto_renewal)
                )
                
                # Обновляем дату последнего уведомления
                cursor.execute("""
                    UPDATE expiring_subscriptions
                    SET last_notification_date = ?
                    WHERE user_id = ? AND plan_id = ?
                """, (datetime.now(), user_id, plan_id))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error checking expiring subscriptions: {e}")
    
    async def send_expiry_notification(self, user_id: int, plan_id: str, end_date: datetime, auto_renewal: bool):
        """Отправить уведомление об истечении подписки."""
        
        days_left = (end_date - datetime.now()).days
        
        if auto_renewal:
            text = f"""⏰ <b>Напоминание об автопродлении</b>

Ваша подписка "{plan_id}" будет автоматически продлена через {days_left} дней.

📅 Дата продления: {end_date.strftime('%d.%m.%Y')}
💳 Сумма списания: согласно тарифу

Если вы хотите отменить автопродление, используйте команду /my_subscriptions"""
        else:
            text = f"""⚠️ <b>Подписка скоро закончится</b>

Ваша подписка "{plan_id}" истекает через {days_left} дней.

📅 Дата окончания: {end_date.strftime('%d.%m.%Y')}

Чтобы продлить подписку, используйте команду /subscribe"""
        
        keyboard = [
            [InlineKeyboardButton(
                "🔄 Управление подпиской", 
                callback_data="manage_subscription"
            )]
        ]
        
        try:
            await self.bot.send_message(
                user_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Sent expiry notification to user {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to send notification to user {user_id}: {e}")
    
    async def process_auto_renewals(self):
        """Обработать автоматические продления подписок."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Находим подписки для автопродления
            cursor.execute("""
                SELECT user_id, plan_id, amount, recurrent_token
                FROM auto_renewal_settings
                WHERE enabled = 1 
                AND next_renewal_date <= ?
                AND failures_count < 3
            """, (datetime.now(),))
            
            renewals = cursor.fetchall()
            
            for user_id, plan_id, amount, token in renewals:
                success, order_id, payment_id = await self.process_single_renewal(
                    user_id, plan_id, amount, token
                )

                if success:
                    # Обновляем дату следующего продления
                    next_date = datetime.now() + timedelta(days=30)
                    cursor.execute("""
                        UPDATE auto_renewal_settings
                        SET next_renewal_date = ?, failures_count = 0
                        WHERE user_id = ?
                    """, (next_date, user_id))

                    # Записываем в историю (ИСПРАВЛЕНО: добавлены order_id и payment_id)
                    cursor.execute("""
                        INSERT INTO auto_renewal_history
                        (user_id, plan_id, payment_id, order_id, status, amount, created_at)
                        VALUES (?, ?, ?, ?, 'success', ?, ?)
                    """, (user_id, plan_id, payment_id, order_id, amount, datetime.now()))

                else:
                    # Увеличиваем счетчик неудач
                    cursor.execute("""
                        UPDATE auto_renewal_settings
                        SET failures_count = failures_count + 1
                        WHERE user_id = ?
                    """, (user_id,))

                    # Записываем неудачу в историю (ИСПРАВЛЕНО: добавлены order_id и payment_id)
                    cursor.execute("""
                        INSERT INTO auto_renewal_history
                        (user_id, plan_id, payment_id, order_id, status, amount, error_message, created_at)
                        VALUES (?, ?, ?, ?, 'failed', ?, 'Payment failed', ?)
                    """, (user_id, plan_id, payment_id, order_id, amount, datetime.now()))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error processing auto renewals: {e}")
    
    async def process_single_renewal(self, user_id: int, plan_id: str, amount: int, token: str) -> tuple:
        """
        Обработать одно автопродление.

        Returns:
            tuple: (success: bool, order_id: str, payment_id: str)
        """

        # Здесь должна быть интеграция с платежной системой
        # Пример для Тинькофф:
        try:
            from payment.tinkoff import TinkoffPayment

            order_id = f"AUTO_{user_id}_{datetime.now().timestamp()}"
            tinkoff = TinkoffPayment()
            result = await tinkoff.charge_recurrent(
                rebill_id=token,
                amount=amount * 100,  # В копейках
                order_id=order_id
            )

            payment_id = result.get('PaymentId', '')

            if result.get('Success'):
                # Отправляем уведомление об успешном продлении
                await self.bot.send_message(
                    user_id,
                    f"✅ Подписка '{plan_id}' успешно продлена!\n"
                    f"Списано: {amount} ₽\n"
                    f"Следующее продление: {(datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y')}"
                )
                return (True, order_id, str(payment_id))
            else:
                # Отправляем уведомление о проблеме
                await self.bot.send_message(
                    user_id,
                    f"❌ Не удалось продлить подписку '{plan_id}'.\n"
                    f"Проверьте баланс карты или обновите платежные данные.\n"
                    f"Используйте /my_subscriptions для управления подпиской."
                )
                return (False, order_id, str(payment_id) if payment_id else None)

        except Exception as e:
            logger.error(f"Error charging recurrent payment for user {user_id}: {e}")
            return (False, None, None)

async def show_auto_renewal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор типа оплаты."""
    
    # Получаем subscription_manager из контекста приложения
    from payment.subscription_manager import SubscriptionManager
    
    # Попробуем получить из bot_data
    subscription_manager = context.application.bot_data.get('subscription_manager')
    if not subscription_manager:
        subscription_manager = SubscriptionManager()
    
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # Определяем цену и название плана
    if plan_id == 'trial':
        plan_name = "Пробный период"
        price = 1
    elif plan_id == 'package_full':
        plan_name = "Полный пакет"
        # Определяем правильную цену
        plan_id = context.user_data.get('selected_plan')
        if plan_id == 'trial_7days':
            price = 1  # Пробный период всегда 1 рубль
        else:
            # Получаем цену из контекста или рассчитываем
            price = context.user_data.get('total_price')
            if not price:
                from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
                plan_info = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
                if plan_info:
                    base_price = plan_info.get('price_rub', 999)
                    price = base_price * duration
                else:
                    price = 999 * duration  # Fallback
    elif plan_id == 'package_second':
        plan_name = "Подготовка к части 2"
        price = 390 * duration
    elif plan_id and plan_id.startswith('custom_'):
        plan_name = "Индивидуальная подборка"
        # Используем уже рассчитанную цену из контекста
        price = context.user_data.get('total_price')
        
        if not price:
            # Рассчитываем правильно если цены нет
            custom_plan = context.user_data.get('custom_plan', {})
            base_price = custom_plan.get('price_rub', 0)
            
            from payment.config import DURATION_DISCOUNTS
            if duration in DURATION_DISCOUNTS:
                multiplier = DURATION_DISCOUNTS[duration]['multiplier']
                price = int(base_price * multiplier)
            else:
                price = base_price * duration
    else:
        plan_name = "Стандартный план"
        # Определяем правильную цену
        plan_id = context.user_data.get('selected_plan')
        if plan_id == 'trial_7days':
            price = 1  # Пробный период всегда 1 рубль
        else:
            # Получаем цену из контекста или рассчитываем
            price = context.user_data.get('total_price')
            if not price:
                from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
                plan_info = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
                if plan_info:
                    base_price = plan_info.get('price_rub', 999)
                    price = base_price * duration
                else:
                    price = 999 * duration  # Fallback
    
    # Сохраняем цену в контекст
    context.user_data['total_price'] = price
    
    text = f"""💳 <b>Выберите тип оплаты</b>

📋 <b>Ваш заказ:</b>
- Тариф: {plan_name}
- Срок: {duration} мес.
- Стоимость: {price} ₽

<b>Доступные варианты:</b>

🔄 <b>С автопродлением</b>
После окончания срока подписка продлевается автоматически.
Вы можете отменить автопродление в любой момент.

💳 <b>Разовая оплата</b>
Подписка действует только выбранный срок.
После окончания нужно продлить вручную."""

    keyboard = [
        [InlineKeyboardButton("🔄 С автопродлением", callback_data="choose_auto_renewal")],
        [InlineKeyboardButton("💳 Разовая оплата", callback_data="choose_no_auto_renewal")],
        [InlineKeyboardButton("📖 Условия автопродления", callback_data="show_auto_renewal_terms")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_duration")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return SHOWING_TERMS

class MultiMonthSubscriptionManager:
    """Менеджер многомесячных подписок."""
    
    @staticmethod
    def calculate_discount(months: int) -> float:
        """Рассчитать скидку для многомесячной подписки."""
        discounts = {
            1: 0,      # Без скидки
            3: 0.10,   # 10% скидка
            6: 0.15,   # 15% скидка
            12: 0.20   # 20% скидка
        }
        return discounts.get(months, 0)
    
    @staticmethod
    def calculate_price(base_price: int, months: int) -> int:
        """Рассчитать итоговую цену с учетом скидки."""
        discount = MultiMonthSubscriptionManager.calculate_discount(months)
        total = base_price * months
        discounted = total * (1 - discount)
        return int(discounted)
    
    @staticmethod
    def get_duration_options(base_price: int) -> List[Dict[str, Any]]:
        """Получить варианты длительности подписки."""
        options = []
        
        for months in [1, 3, 6, 12]:
            price = MultiMonthSubscriptionManager.calculate_price(base_price, months)
            discount = MultiMonthSubscriptionManager.calculate_discount(months)
            
            option = {
                'months': months,
                'price': price,
                'discount_percent': int(discount * 100),
                'monthly_price': price // months,
                'savings': base_price * months - price
            }
            
            if months == 1:
                option['label'] = f"1 месяц - {price} ₽"
            elif months == 3:
                option['label'] = f"3 месяца - {price} ₽ (скидка {option['discount_percent']}%)"
            elif months == 6:
                option['label'] = f"6 месяцев - {price} ₽ (скидка {option['discount_percent']}%)"
            elif months == 12:
                option['label'] = f"1 год - {price} ₽ (скидка {option['discount_percent']}%)"
            
            options.append(option)
        
        return options


async def show_auto_renewal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор типа оплаты."""
    
    # Получаем subscription_manager из контекста приложения
    from payment.subscription_manager import SubscriptionManager
    
    # Попробуем получить из bot_data
    subscription_manager = context.application.bot_data.get('subscription_manager')
    if not subscription_manager:
        subscription_manager = SubscriptionManager()
    
    # НЕ создаем новый экземпляр, а используем существующий
    # Удалите эту строку: consent_handler = AutoRenewalConsent()
    
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # Определяем цену и название плана
    if plan_id == 'trial':
        plan_name = "Пробный период"
        price = 1
    elif plan_id == 'package_full':
        plan_name = "Полный пакет"
        # Определяем правильную цену
        plan_id = context.user_data.get('selected_plan')
        if plan_id == 'trial_7days':
            price = 1  # Пробный период всегда 1 рубль
        else:
            # Получаем цену из контекста или рассчитываем
            price = context.user_data.get('total_price')
            if not price:
                from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
                plan_info = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
                if plan_info:
                    base_price = plan_info.get('price_rub', 999)
                    price = base_price * duration
                else:
                    price = 999 * duration  # Fallback
    elif plan_id == 'package_second':
        plan_name = "Подготовка к части 2"
        price = 390 * duration
    elif plan_id and plan_id.startswith('custom_'):
        plan_name = "Индивидуальная подборка"
        modules = context.user_data.get('selected_modules', [])
        from payment.handlers import calculate_custom_price
        price = calculate_custom_price(modules, duration)
    else:
        plan_name = "Стандартный план"
        # Определяем правильную цену
        plan_id = context.user_data.get('selected_plan')
        if plan_id == 'trial_7days':
            price = 1  # Пробный период всегда 1 рубль
        else:
            # Получаем цену из контекста или рассчитываем
            price = context.user_data.get('total_price')
            if not price:
                from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
                plan_info = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
                if plan_info:
                    base_price = plan_info.get('price_rub', 999)
                    price = base_price * duration
                else:
                    price = 999 * duration  # Fallback
    
    # Сохраняем цену в контекст
    context.user_data['total_price'] = price
    
    text = f"""💳 <b>Выберите тип оплаты</b>

📋 <b>Ваш заказ:</b>
- Тариф: {plan_name}
- Срок: {duration} мес.
- Стоимость: {price} ₽

<b>Доступные варианты:</b>

🔄 <b>С автопродлением</b>
После окончания срока подписка продлевается автоматически.
Вы можете отменить автопродление в любой момент.

💳 <b>Разовая оплата</b>
Подписка действует только выбранный срок.
После окончания нужно продлить вручную."""

    keyboard = [
        [InlineKeyboardButton("🔄 С автопродлением", callback_data="choose_auto_renewal")],
        [InlineKeyboardButton("💳 Разовая оплата", callback_data="choose_no_auto_renewal")],
        [InlineKeyboardButton("📖 Условия автопродления", callback_data="show_auto_renewal_terms")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_duration")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return SHOWING_TERMS


# Экспортируем необходимые классы и функции
__all__ = [
    'AutoRenewalConsent',
    'SubscriptionNotificationManager',
    'MultiMonthSubscriptionManager',
    'SHOWING_TERMS',
    'CONSENT_CHECKBOX', 
    'FINAL_CONFIRMATION',
    'show_auto_renewal_choice'
]