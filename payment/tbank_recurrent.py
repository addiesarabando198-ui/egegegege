# payment/tbank_recurrent.py - Интеграция с рекуррентными платежами Т-Банка

import logging
import hashlib
import aiohttp
import json
from typing import Dict, Optional, Any
from datetime import datetime
from .config import TINKOFF_TERMINAL_KEY, TINKOFF_SECRET_KEY, TINKOFF_API_URL

logger = logging.getLogger(__name__)


class TBankRecurrentPayments:
    """Класс для работы с рекуррентными платежами Т-Банка."""
    
    def __init__(self):
        self.terminal_key = TINKOFF_TERMINAL_KEY
        self.secret_key = TINKOFF_SECRET_KEY
        self.api_url = TINKOFF_API_URL
    
    def _generate_token(self, params: Dict[str, Any]) -> str:
        """Генерирует подпись запроса."""
        # Добавляем Password и TerminalKey
        token_params = {**params}
        token_params['Password'] = self.secret_key
        token_params['TerminalKey'] = self.terminal_key
        
        # Исключаем Token из подписи если есть
        token_params.pop('Token', None)
        
        # Сортируем по ключам и конкатенируем значения
        sorted_values = [str(token_params[k]) for k in sorted(token_params.keys())]
        concatenated = ''.join(sorted_values)
        
        # Создаем SHA-256 хеш
        return hashlib.sha256(concatenated.encode()).hexdigest()
    
    async def init_primary_payment(self, order_id: str, amount_kopecks: int, 
                                  customer_key: str, description: str,
                                  user_email: str = None) -> Dict:
        """
        Инициализирует первичный платеж с возможностью рекуррентных списаний.
        
        Args:
            order_id: Уникальный ID заказа
            amount_kopecks: Сумма в копейках
            customer_key: Уникальный идентификатор покупателя
            description: Описание платежа
            user_email: Email для отправки чека
            
        Returns:
            Словарь с PaymentId и PaymentURL
        """
        try:
            params = {
                'TerminalKey': self.terminal_key,
                'Amount': amount_kopecks,
                'OrderId': order_id,
                'Description': description,
                'CustomerKey': customer_key,
                'Recurrent': 'Y',  # ВАЖНО: Указываем что платеж рекуррентный
                'DATA': {
                    'Email': user_email or '',
                }
            }
            
            # Генерируем подпись
            params['Token'] = self._generate_token(params)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}Init",
                    json=params,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    result = await response.json()
                    
                    if result.get('Success'):
                        logger.info(f"Primary payment initialized: {result.get('PaymentId')}")
                        return {
                            'success': True,
                            'payment_id': result.get('PaymentId'),
                            'payment_url': result.get('PaymentURL'),
                            'order_id': order_id
                        }
                    else:
                        logger.error(f"Failed to init primary payment: {result}")
                        return {
                            'success': False,
                            'error': result.get('Message', 'Unknown error')
                        }
                        
        except Exception as e:
            logger.exception(f"Error initializing primary payment: {e}")
            return {'success': False, 'error': str(e)}
    
    async def init_recurrent_payment(self, order_id: str, amount_kopecks: int,
                                    description: str) -> Dict:
        """
        Инициализирует рекуррентный платеж (без Recurrent=Y).
        
        Args:
            order_id: Уникальный ID заказа
            amount_kopecks: Сумма в копейках
            description: Описание платежа
            
        Returns:
            Словарь с PaymentId для последующего вызова Charge
        """
        try:
            params = {
                'TerminalKey': self.terminal_key,
                'Amount': amount_kopecks,
                'OrderId': order_id,
                'Description': description,
                # НЕ указываем Recurrent и CustomerKey для повторного платежа
            }
            
            params['Token'] = self._generate_token(params)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}Init",
                    json=params,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    result = await response.json()
                    
                    if result.get('Success'):
                        logger.info(f"Recurrent payment initialized: {result.get('PaymentId')}")
                        return {
                            'success': True,
                            'payment_id': result.get('PaymentId')
                        }
                    else:
                        logger.error(f"Failed to init recurrent payment: {result}")
                        return {
                            'success': False,
                            'error': result.get('Message', 'Unknown error')
                        }
                        
        except Exception as e:
            logger.exception(f"Error initializing recurrent payment: {e}")
            return {'success': False, 'error': str(e)}
    
    async def charge_recurrent(self, payment_id: str, rebill_id: str, 
                              client_ip: str = None) -> Dict:
        """
        Проводит рекуррентное списание по сохраненным реквизитам.
        
        Args:
            payment_id: ID платежа из метода Init
            rebill_id: ID рекуррента из первичного платежа
            client_ip: IP адрес клиента (опционально)
            
        Returns:
            Результат списания
        """
        try:
            params = {
                'TerminalKey': self.terminal_key,
                'PaymentId': payment_id,
                'RebillId': rebill_id,
            }
            
            if client_ip:
                params['IP'] = client_ip
            
            params['Token'] = self._generate_token(params)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}Charge",
                    json=params,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    result = await response.json()
                    
                    if result.get('Success'):
                        status = result.get('Status')
                        if status == 'CONFIRMED':
                            logger.info(f"Recurrent payment confirmed: {payment_id}")
                            return {
                                'success': True,
                                'status': status,
                                'payment_id': payment_id,
                                'amount': result.get('Amount')
                            }
                        elif status == 'REJECTED':
                            logger.warning(f"Recurrent payment rejected: {payment_id}")
                            return {
                                'success': False,
                                'status': status,
                                'error': result.get('Message', 'Payment rejected')
                            }
                    else:
                        logger.error(f"Charge failed: {result}")
                        return {
                            'success': False,
                            'error': result.get('Message', 'Charge failed'),
                            'error_code': result.get('ErrorCode')
                        }
                        
        except Exception as e:
            logger.exception(f"Error charging recurrent payment: {e}")
            return {'success': False, 'error': str(e)}
    
    async def get_payment_status(self, payment_id: str) -> Dict:
        """Проверяет статус платежа."""
        try:
            params = {
                'TerminalKey': self.terminal_key,
                'PaymentId': payment_id,
            }
            
            params['Token'] = self._generate_token(params)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}GetState",
                    json=params,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    result = await response.json()
                    
                    if result.get('Success'):
                        return {
                            'success': True,
                            'status': result.get('Status'),
                            'payment_id': payment_id
                        }
                    else:
                        return {
                            'success': False,
                            'error': result.get('Message', 'Failed to get status')
                        }
                        
        except Exception as e:
            logger.exception(f"Error getting payment status: {e}")
            return {'success': False, 'error': str(e)}


class RecurrentPaymentManager:
    """Менеджер для управления рекуррентными платежами."""
    
    def __init__(self, subscription_manager):
        self.subscription_manager = subscription_manager
        self.tbank_api = TBankRecurrentPayments()
    
    async def process_auto_renewal(self, user_id: int) -> bool:
        """
        Обрабатывает автоматическое продление подписки.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            True если продление успешно, False в противном случае
        """
        try:
            import aiosqlite
            from datetime import datetime, timezone
            
            # Получаем информацию об автопродлении
            auto_renewal = await self.subscription_manager.get_auto_renewal_status(user_id)
            
            if not auto_renewal or not auto_renewal['enabled']:
                logger.info(f"Auto-renewal not enabled for user {user_id}")
                return False
            
            rebill_id = auto_renewal.get('recurrent_token')
            if not rebill_id:
                logger.error(f"No rebill_id found for user {user_id}")
                await self._handle_renewal_failure(user_id, "No payment token")
                return False
            
            # Получаем информацию о последней подписке
            last_subscription = await self.subscription_manager.get_last_subscription_info(user_id)
            if not last_subscription:
                logger.error(f"No subscription info found for user {user_id}")
                return False
            
            # Создаем новый заказ для рекуррентного платежа
            order_id = f"RECURRENT_{user_id}_{int(datetime.now().timestamp())}"
            amount_kopecks = last_subscription['amount'] * 100  # Переводим в копейки
            description = f"Автопродление подписки {last_subscription['plan_name']}"
            
            # Шаг 1: Инициализируем платеж (без Recurrent=Y)
            init_result = await self.tbank_api.init_recurrent_payment(
                order_id=order_id,
                amount_kopecks=amount_kopecks,
                description=description
            )
            
            if not init_result['success']:
                logger.error(f"Failed to init recurrent payment: {init_result}")
                await self._handle_renewal_failure(user_id, init_result.get('error'))
                return False
            
            payment_id = init_result['payment_id']
            
            # Шаг 2: Выполняем списание через Charge
            charge_result = await self.tbank_api.charge_recurrent(
                payment_id=payment_id,
                rebill_id=rebill_id
            )
            
            if charge_result['success']:
                # Активируем подписку
                await self.subscription_manager.activate_subscription(
                    order_id=order_id,
                    user_id=user_id,
                    plan_id=last_subscription['plan_id']
                )
                
                # Записываем успешное продление
                await self._record_renewal_success(
                    user_id=user_id,
                    order_id=order_id,
                    plan_id=last_subscription['plan_id'],
                    amount=last_subscription['amount']
                )
                
                # Обновляем дату следующего продления
                await self._update_next_renewal_date(user_id)
                
                logger.info(f"Auto-renewal successful for user {user_id}")
                return True
            else:
                # Обрабатываем неудачное списание
                error_msg = charge_result.get('error', 'Payment failed')
                await self._handle_renewal_failure(user_id, error_msg)
                return False
                
        except Exception as e:
            logger.exception(f"Error processing auto-renewal for user {user_id}: {e}")
            await self._handle_renewal_failure(user_id, str(e))
            return False
    
    async def _record_renewal_success(self, user_id: int, order_id: str, 
                                     plan_id: str, amount: int):
        """Записывает успешное автопродление в БД."""
        try:
            import aiosqlite
            from datetime import datetime
            
            async with aiosqlite.connect(self.subscription_manager.database_file) as conn:
                # ИСПРАВЛЕНО: добавлен order_id в INSERT запрос
                await conn.execute("""
                    INSERT INTO auto_renewal_history
                    (user_id, plan_id, payment_id, order_id, status, amount, created_at)
                    VALUES (?, ?, ?, ?, 'success', ?, CURRENT_TIMESTAMP)
                """, (user_id, plan_id, order_id, order_id, amount))
                
                # Сбрасываем счетчик неудач
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET failures_count = 0, last_renewal_attempt = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (user_id,))
                
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error recording renewal success: {e}")
    
    async def _handle_renewal_failure(self, user_id: int, error_message: str):
        """Обрабатывает неудачное автопродление."""
        try:
            import aiosqlite
            
            async with aiosqlite.connect(self.subscription_manager.database_file) as conn:
                # Увеличиваем счетчик неудач
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET failures_count = failures_count + 1,
                        last_renewal_attempt = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (user_id,))
                
                # Проверяем количество неудач
                cursor = await conn.execute(
                    "SELECT failures_count FROM auto_renewal_settings WHERE user_id = ?",
                    (user_id,)
                )
                row = await cursor.fetchone()
                
                if row and row[0] >= 3:
                    # После 3 неудач отключаем автопродление
                    await conn.execute("""
                        UPDATE auto_renewal_settings 
                        SET enabled = 0 
                        WHERE user_id = ?
                    """, (user_id,))
                    logger.warning(f"Auto-renewal disabled for user {user_id} after 3 failures")
                
                # Записываем в историю
                await conn.execute("""
                    INSERT INTO auto_renewal_history 
                    (user_id, plan_id, payment_id, status, amount, error_message, created_at)
                    VALUES (?, '', '', 'failed', 0, ?, CURRENT_TIMESTAMP)
                """, (user_id, error_message))
                
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error handling renewal failure: {e}")
    
    async def _update_next_renewal_date(self, user_id: int):
        """Обновляет дату следующего автопродления."""
        try:
            import aiosqlite
            from datetime import datetime, timedelta, timezone
            
            next_date = datetime.now(timezone.utc) + timedelta(days=30)
            
            async with aiosqlite.connect(self.subscription_manager.database_file) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET next_renewal_date = ? 
                    WHERE user_id = ?
                """, (next_date, user_id))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error updating next renewal date: {e}")
    
    async def save_rebill_id(self, user_id: int, order_id: str, rebill_id: str):
        """
        Сохраняет RebillId после успешного первичного платежа.
        
        Args:
            user_id: ID пользователя
            order_id: ID заказа
            rebill_id: Токен для рекуррентных платежей от Т-Банка
        """
        try:
            import aiosqlite
            from datetime import datetime, timedelta, timezone
            
            # Определяем дату следующего продления (через 30 дней)
            next_renewal = datetime.now(timezone.utc) + timedelta(days=30)
            
            async with aiosqlite.connect(self.subscription_manager.database_file) as conn:
                # Сохраняем или обновляем настройки автопродления
                await conn.execute("""
                    INSERT OR REPLACE INTO auto_renewal_settings 
                    (user_id, enabled, payment_method, recurrent_token, 
                     next_renewal_date, failures_count, updated_at)
                    VALUES (?, 0, 'recurrent', ?, ?, 0, CURRENT_TIMESTAMP)
                """, (user_id, rebill_id, next_renewal))
                
                # Также обновляем в таблице payments
                await conn.execute("""
                    UPDATE payments 
                    SET metadata = json_set(
                        COALESCE(metadata, '{}'),
                        '$.rebill_id', ?
                    )
                    WHERE order_id = ?
                """, (rebill_id, order_id))
                
                await conn.commit()
                
                logger.info(f"RebillId saved for user {user_id}: {rebill_id[:10]}...")
                
        except Exception as e:
            logger.error(f"Error saving rebill_id: {e}")