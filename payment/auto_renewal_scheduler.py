# payment/auto_renewal_scheduler.py - Новый файл для автоматического продления подписок

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot
from telegram.constants import ParseMode
from .admin_alerts import (
    notify_admin_auto_renewal_activation_failed,
    notify_admin_multiple_renewal_failures
)

logger = logging.getLogger(__name__)

class AutoRenewalScheduler:
    """Планировщик для автоматического продления подписок."""
    
    def __init__(self, bot: Bot, subscription_manager, tinkoff_api):
        self.bot = bot
        self.subscription_manager = subscription_manager
        self.tinkoff_api = tinkoff_api
        self.scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
        self.is_running = False
    
    def start(self):
        """Запускает планировщик."""
        if not self.is_running:
            # Проверка истекающих подписок каждый день в 10:00 по МСК
            self.scheduler.add_job(
                self.check_expiring_subscriptions,
                CronTrigger(hour=10, minute=0),
                id='check_expiring',
                replace_existing=True
            )
            
            # Обработка автопродлений каждый день в 12:00 по МСК
            self.scheduler.add_job(
                self.process_auto_renewals,
                CronTrigger(hour=12, minute=0),
                id='process_renewals',
                replace_existing=True
            )
            
            # Проверка неудачных попыток продления каждые 4 часа
            self.scheduler.add_job(
                self.retry_failed_renewals,
                CronTrigger(hour='*/4'),
                id='retry_failed',
                replace_existing=True
            )
            
            self.scheduler.start()
            self.is_running = True
            logger.info("Auto-renewal scheduler started")
    
    def stop(self):
        """Останавливает планировщик."""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("Auto-renewal scheduler stopped")
    
    async def check_expiring_subscriptions(self):
        """
        Проверяет истекающие подписки и отправляет уведомления.
        Запускается ежедневно.
        """
        try:
            logger.info("Checking expiring subscriptions...")
            
            # Получаем подписки, истекающие через 3 дня
            expiring_in_3_days = await self.subscription_manager.get_expiring_subscriptions(3)
            
            for subscription in expiring_in_3_days:
                user_id = subscription['user_id']
                expires_at = subscription['expires_at']
                
                # Проверяем статус автопродления
                auto_renewal = await self.subscription_manager.get_auto_renewal_status(user_id)
                
                if auto_renewal and auto_renewal['enabled']:
                    # Автопродление включено
                    message = f"""⏰ <b>Напоминание об автопродлении</b>

Ваша подписка истекает {expires_at.strftime('%d.%m.%Y')}.

🔄 <b>Автопродление включено</b>
Подписка будет автоматически продлена на 1 месяц.
Сумма к списанию: {subscription.get('amount', 0)} ₽

Если вы хотите отменить автопродление, используйте команду /auto_renewal"""
                else:
                    # Автопродление выключено
                    message = f"""⏰ <b>Подписка скоро истекает</b>

Ваша подписка истекает {expires_at.strftime('%d.%m.%Y')}.

❌ Автопродление не настроено.
Чтобы не потерять доступ к материалам, продлите подписку заранее.

Используйте /subscribe для продления или /auto_renewal для настройки автопродления."""
                
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to send expiry notification to user {user_id}: {e}")
            
            # Проверяем подписки, истекающие сегодня
            expiring_today = await self.subscription_manager.get_expiring_subscriptions(0)
            
            for subscription in expiring_today:
                user_id = subscription['user_id']
                
                # Проверяем, был ли это пробный период
                if subscription.get('is_trial'):
                    await self._handle_trial_expiry(user_id, subscription)
                else:
                    await self._handle_regular_expiry(user_id, subscription)
            
            logger.info(f"Processed {len(expiring_in_3_days)} 3-day warnings and {len(expiring_today)} expiring today")
            
        except Exception as e:
            logger.exception(f"Error checking expiring subscriptions: {e}")
    
    async def _handle_trial_expiry(self, user_id: int, subscription: Dict):
        """
        Обрабатывает окончание пробного периода.
        Автоматически переводит на полную подписку если настроено автопродление.
        """
        try:
            auto_renewal = await self.subscription_manager.get_auto_renewal_status(user_id)
            
            if auto_renewal and auto_renewal['enabled'] and auto_renewal.get('recurrent_token'):
                # Автоматически продлеваем на полный месяц после пробного периода
                logger.info(f"Auto-renewing trial subscription for user {user_id}")
                
                # Определяем план для продления (полный доступ после триала)
                new_plan_id = 'package_full'  # Или другой план по умолчанию
                amount_kopecks = 99900  # 999 рублей в копейках
                
                # Создаем новый платеж
                order_id = f"AUTO_TRIAL_{user_id}_{int(datetime.now().timestamp())}"
                
                # Инициализируем платеж для рекуррентного списания
                init_result = await self.tinkoff_api.init_payment(
                    order_id=order_id,
                    amount_kopecks=amount_kopecks,
                    description="Автопродление после пробного периода",
                    user_email=await self.subscription_manager.get_user_email(user_id),
                    receipt_items=[{
                        "Name": "Полный доступ ЕГЭ (1 месяц)",
                        "Price": amount_kopecks,
                        "Quantity": 1,
                        "Amount": amount_kopecks,
                        "Tax": "none"
                    }],
                    enable_recurrent=False  # Не нужно, у нас уже есть токен
                )
                
                if init_result['success']:
                    payment_id = init_result['payment_id']
                    
                    # Выполняем рекуррентное списание
                    charge_result = await self.tinkoff_api.charge_recurrent(
                        payment_id=payment_id,
                        rebill_id=auto_renewal['recurrent_token']
                    )
                    
                    if charge_result['success']:
                        # Активируем новую подписку
                        await self.subscription_manager.activate_subscription(
                            order_id=order_id,
                            user_id=user_id,
                            plan_id=new_plan_id
                        )
                        
                        # Уведомляем пользователя
                        await self.bot.send_message(
                            chat_id=user_id,
                            text=f"""✅ <b>Пробный период завершен</b>

Ваша подписка автоматически продлена на 1 месяц.
План: Полный доступ
Списано: 999 ₽

Спасибо, что остаетесь с нами! 🎓

/my_subscriptions - просмотр подписок
/auto_renewal - управление автопродлением""",
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        # Списание не удалось
                        await self._notify_renewal_failed(user_id, charge_result.get('error'))
                else:
                    logger.error(f"Failed to init payment for trial renewal: {init_result}")
            else:
                # Автопродление не настроено - отправляем предложение
                await self.bot.send_message(
                    chat_id=user_id,
                    text="""🎁 <b>Пробный период завершен!</b>

Надеемся, вам понравился наш сервис!

Чтобы продолжить подготовку к ЕГЭ, оформите полную подписку:
/subscribe - выбрать план подписки

Или настройте автопродление, чтобы не терять доступ:
/auto_renewal - настроить автопродление""",
                    parse_mode=ParseMode.HTML
                )
                
        except Exception as e:
            logger.exception(f"Error handling trial expiry for user {user_id}: {e}")
    
    async def _handle_regular_expiry(self, user_id: int, subscription: Dict):
        """Обрабатывает окончание обычной подписки."""
        try:
            auto_renewal = await self.subscription_manager.get_auto_renewal_status(user_id)
            
            if not auto_renewal or not auto_renewal['enabled']:
                # Автопродление не включено - деактивируем подписку
                await self.subscription_manager.deactivate_expired_subscription(user_id)
                
                await self.bot.send_message(
                    chat_id=user_id,
                    text="""❌ <b>Подписка истекла</b>

Ваша подписка завершилась, и доступ к материалам приостановлен.

Чтобы возобновить доступ:
/subscribe - оформить новую подписку
/auto_renewal - настроить автопродление""",
                    parse_mode=ParseMode.HTML
                )
                
        except Exception as e:
            logger.exception(f"Error handling regular expiry for user {user_id}: {e}")
    
    async def process_auto_renewals(self):
        """
        Обрабатывает автоматические продления подписок.
        Запускается ежедневно.
        """
        try:
            logger.info("Processing auto-renewals...")
            
            # Получаем список пользователей с включенным автопродлением
            users_to_renew = await self.subscription_manager.get_users_for_auto_renewal()
            
            success_count = 0
            failed_count = 0
            
            for user_data in users_to_renew:
                user_id = user_data['user_id']
                rebill_id = user_data['recurrent_token']
                plan_id = user_data['plan_id']
                amount = user_data['amount']
                
                try:
                    # Выполняем автопродление
                    success = await self._process_single_renewal(
                        user_id, rebill_id, plan_id, amount
                    )
                    
                    if success:
                        success_count += 1
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"Failed to process renewal for user {user_id}: {e}")
                    failed_count += 1
                
                # Небольшая задержка между платежами
                await asyncio.sleep(1)
            
            logger.info(f"Auto-renewal complete: {success_count} success, {failed_count} failed")
            
        except Exception as e:
            logger.exception(f"Error processing auto-renewals: {e}")
    
    async def _process_single_renewal(self, user_id: int, rebill_id: str,
                                       plan_id: str, amount: int) -> bool:
        """
        Обрабатывает одно автопродление с проверками безопасности.
        Включает валидацию данных перед списанием средств.
        """
        try:
            # КРИТИЧНАЯ ПРОВЕРКА №1: Валидация суммы
            if amount <= 0:
                logger.error(
                    f"❌ CRITICAL: Attempted auto-renewal for user {user_id} with invalid amount: {amount}. "
                    f"BLOCKING renewal to prevent incorrect charge."
                )
                await self._notify_renewal_failed(
                    user_id, 
                    "Ошибка конфигурации: некорректная сумма платежа. Обратитесь в поддержку."
                )
                return False
            
            # КРИТИЧНАЯ ПРОВЕРКА №2: Валидация токена
            if not rebill_id or len(rebill_id) < 10:
                logger.error(
                    f"❌ CRITICAL: Invalid rebill_id for user {user_id}. "
                    f"BLOCKING renewal."
                )
                await self._notify_renewal_failed(
                    user_id,
                    "Ошибка токена оплаты. Пожалуйста, переоформите автопродление."
                )
                return False
            
            # КРИТИЧНАЯ ПРОВЕРКА №3: Проверяем что у пользователя действительно есть истекающая подписка
            subscription = await self.subscription_manager.check_active_subscription(user_id)
            if subscription and subscription.get('plan_id') != plan_id:
                logger.warning(
                    f"⚠️ Plan mismatch for user {user_id}: expected {plan_id}, "
                    f"found {subscription.get('plan_id')}. Updating plan_id."
                )
                plan_id = subscription.get('plan_id')
            
            order_id = f"AUTO_{user_id}_{int(datetime.now().timestamp())}"
            amount_kopecks = amount * 100
            
            logger.info(
                f"🔄 Processing auto-renewal for user {user_id}: "
                f"amount={amount}₽, plan={plan_id}"
            )
            
            # Инициализируем платеж
            init_result = await self.tinkoff_api.init_recurrent_payment(
                order_id=order_id,
                amount_kopecks=amount_kopecks,
                description=f"Автопродление подписки {plan_id}",
            )
            
            if not init_result['success']:
                logger.error(f"❌ Failed to init renewal payment for user {user_id}: {init_result}")
                await self._notify_renewal_failed(user_id, init_result.get('error'))
                await self.subscription_manager.increment_renewal_failures(user_id)
                return False
            
            payment_id = init_result['payment_id']
            logger.info(f"✅ Payment initialized for user {user_id}: payment_id={payment_id}")
            
            # КРИТИЧНАЯ ТОЧКА: Выполняем рекуррентное списание
            charge_result = await self.tinkoff_api.charge_recurrent(
                payment_id=payment_id,
                rebill_id=rebill_id
            )
            
            # КРИТИЧНАЯ ПРОВЕРКА №4: Проверяем результат списания
            if not charge_result.get('success'):
                logger.error(
                    f"❌ Charge FAILED for user {user_id}: {charge_result.get('error')}"
                )
                await self._notify_renewal_failed(user_id, charge_result.get('error'))
                await self.subscription_manager.increment_renewal_failures(user_id)
                return False
            
            # КРИТИЧНАЯ ПРОВЕРКА №5: Проверяем статус платежа
            charge_status = charge_result.get('status')
            if charge_status != 'CONFIRMED':
                logger.error(
                    f"❌ Charge status is not CONFIRMED for user {user_id}: status={charge_status}"
                )
                await self._notify_renewal_failed(
                    user_id,
                    f"Платеж не подтвержден (статус: {charge_status})"
                )
                await self.subscription_manager.increment_renewal_failures(user_id)
                return False
            
            # ✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - теперь можно активировать подписку
            logger.info(f"✅ Payment CONFIRMED for user {user_id}. Activating subscription...")
            
            activation_success = await self.subscription_manager.activate_subscription(
                order_id=order_id,
                user_id=user_id,
                plan_id=plan_id
            )
            
            if not activation_success:
                logger.error(
                    f"❌ CRITICAL: Payment succeeded but activation failed for user {user_id}! "
                    f"Manual intervention required. order_id={order_id}"
                )
                # Уведомляем администратора о критичной ошибке!
                await notify_admin_auto_renewal_activation_failed(
                    bot=self.bot,
                    order_id=order_id,
                    user_id=user_id,
                    plan_id=plan_id,
                    amount=amount
                )
                return False
            
            # Обновляем дату следующего продления
            await self.subscription_manager.update_next_renewal_date(user_id)
            
            # Уведомляем пользователя об успешном продлении
            await self.bot.send_message(
                chat_id=user_id,
                text=f"""✅ <b>Подписка продлена автоматически</b>

    План: {plan_id}
    Период: 1 месяц
    Списано: {amount} ₽

    Следующее продление: {(datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y')}

    /my_subscriptions - детали подписки
    /auto_renewal - управление автопродлением""",
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"✅ ✅ ✅ Auto-renewal COMPLETE for user {user_id}")
            return True
            
        except Exception as e:
            logger.exception(f"❌ EXCEPTION during auto-renewal for user {user_id}: {e}")
            await self._notify_renewal_failed(user_id, str(e))

            # Увеличиваем счетчик неудач
            await self.subscription_manager.increment_renewal_failures(user_id)

            # Проверяем количество неудач и уведомляем админа если >= 3
            failures_info = await self.subscription_manager.get_renewal_failures_count(user_id)
            if failures_info and failures_info >= 3:
                await notify_admin_multiple_renewal_failures(
                    bot=self.bot,
                    user_id=user_id,
                    failures_count=failures_info,
                    last_error=str(e)
                )

            return False

    async def retry_failed_renewals(self):
        """
        Повторяет неудачные попытки автопродления.
        Запускается каждые 4 часа.
        """
        try:
            logger.info("Retrying failed renewals...")
            
            # Получаем список неудачных попыток за последние 24 часа
            failed_renewals = await self.subscription_manager.get_failed_renewals(hours=24)
            
            retry_count = 0
            success_count = 0
            
            for renewal in failed_renewals:
                user_id = renewal['user_id']
                failures_count = renewal['failures_count']
                
                # Не пытаемся больше 3 раз
                if failures_count >= 3:
                    continue
                
                # Получаем данные для повтора
                auto_renewal = await self.subscription_manager.get_auto_renewal_status(user_id)
                
                if auto_renewal and auto_renewal['enabled']:
                    retry_count += 1
                    
                    success = await self._process_single_renewal(
                        user_id,
                        auto_renewal['recurrent_token'],
                        auto_renewal['plan_id'],
                        auto_renewal['amount']
                    )
                    
                    if success:
                        success_count += 1
                        # Сбрасываем счетчик неудач
                        await self.subscription_manager.reset_renewal_failures(user_id)
                
                # Задержка между попытками
                await asyncio.sleep(2)
            
            logger.info(f"Retry complete: {success_count}/{retry_count} successful")
            
        except Exception as e:
            logger.exception(f"Error retrying failed renewals: {e}")
    
    async def _notify_renewal_failed(self, user_id: int, error: str):
        """Уведомляет пользователя о неудачном автопродлении."""
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=f"""⚠️ <b>Не удалось продлить подписку</b>

Автоматическое продление не выполнено.
Причина: {error}

Возможные причины:
• Недостаточно средств на карте
• Карта заблокирована или истек срок действия
• Превышен лимит операций

Пожалуйста, проверьте вашу карту и при необходимости:
/subscribe - оформите подписку заново
/auto_renewal - обновите данные для автопродления

Мы попробуем списать средства еще раз через несколько часов.""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about renewal failure: {e}")