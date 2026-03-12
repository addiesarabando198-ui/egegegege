# payment/tinkoff.py
"""Интеграция с Tinkoff API для приема платежей с поддержкой рекуррентов."""
import hashlib
import json
import logging
from typing import Dict, Any, Optional, Tuple
import aiohttp
import os
from datetime import datetime

from .config import (
    TINKOFF_TERMINAL_KEY,
    TINKOFF_SECRET_KEY,
    TINKOFF_API_URL,
    WEBHOOK_BASE_URL,
    WEBHOOK_PATH
)

logger = logging.getLogger(__name__)


class TinkoffPayment:
    """Класс для работы с Tinkoff API с поддержкой рекуррентных платежей."""
    
    def __init__(self):
        self.terminal_key = TINKOFF_TERMINAL_KEY
        self.secret_key = TINKOFF_SECRET_KEY
        self.api_url = TINKOFF_API_URL
    
    def calculate_token(self, params: Dict[str, Any]) -> str:
        """Рассчитывает токен для подписи запроса."""
        # Копируем параметры и добавляем пароль
        token_params = params.copy()
        token_params["Password"] = self.secret_key
        
        # Удаляем параметры, которые не участвуют в подписи
        exclude_from_token = ["Receipt", "DATA", "Token", "Shops", "Descriptor", "PaymentFormLanguage"]
        for key in exclude_from_token:
            token_params.pop(key, None)
        
        # Приводим все значения к строкам
        processed = {}
        for key, value in token_params.items():
            if value is None:
                continue
            elif isinstance(value, bool):
                # Для Tinkoff булевы значения должны быть "true"/"false"
                processed[key] = "true" if value else "false"
            elif key == "Recurrent" and value == "Y":
                # Recurrent передается как есть
                processed[key] = value
            else:
                processed[key] = str(value)
        
        # Сортируем по ключам и конкатенируем значения
        sorted_values = [processed[k] for k in sorted(processed.keys())]
        values_string = "".join(sorted_values)
        
        # Вычисляем SHA256
        token = hashlib.sha256(values_string.encode('utf-8')).hexdigest()
        
        # Логируем для отладки (без пароля)
        logger.debug(f"Token calculation: keys={sorted(processed.keys())}, token={token[:10]}...")
        
        return token
    
    async def create_payment(
        self,
        amount_kopecks: int,
        order_id: str,
        description: str,
        customer_email: str,
        user_id: int,
        bot_username: str = None
    ) -> Tuple[str, str]:
        """
        Создает платеж (обертка для init_payment для обратной совместимости).
        
        Args:
            amount_kopecks: Сумма в копейках
            order_id: Уникальный ID заказа
            description: Описание платежа
            customer_email: Email покупателя
            user_id: ID пользователя Telegram
            bot_username: Username бота (опционально)
            
        Returns:
            Кортеж (payment_url, order_id) при успехе
            
        Raises:
            Exception: При ошибке создания платежа
        """
        # Создаем позицию чека
        receipt_items = [
            self.build_receipt_item(
                name=description[:64],  # Ограничиваем длину названия
                price_kopecks=amount_kopecks
            )
        ]
        
        # Дополнительные данные
        user_data = {
            "user_id": str(user_id),
            "email": customer_email
        }
        
        # Вызываем основной метод
        result = await self.init_payment(
            order_id=order_id,
            amount_kopecks=amount_kopecks,
            description=description,
            user_email=customer_email,
            receipt_items=receipt_items,
            user_data=user_data,
            bot_username=bot_username
        )
        
        # Проверяем результат
        if result.get("success"):
            payment_url = result.get("payment_url")
            if not payment_url:
                raise Exception("Payment URL not received from Tinkoff")
            return payment_url, order_id
        else:
            error = result.get("error", "Unknown error")
            raise Exception(f"Failed to create payment: {error}")
    
    def verify_webhook_token(self, data: Dict[str, Any]) -> bool:
        """Проверяет подпись webhook от Tinkoff."""
        if "Token" not in data:
            logger.warning("No token in webhook data")
            return False
        
        received_token = data["Token"]
        params = data.copy()
        
        # Вычисляем ожидаемый токен
        expected_token = self.calculate_token(params)
        
        is_valid = expected_token == received_token
        if not is_valid:
            logger.warning(f"Invalid webhook token. Expected: {expected_token}, Received: {received_token}")
        
        return is_valid
    
    async def init_payment(
        self,
        order_id: str,
        amount_kopecks: int,
        description: str,
        user_email: str,
        receipt_items: list,
        user_data: Optional[Dict[str, str]] = None,
        bot_username: str = None,
        enable_recurrent: bool = False,
        customer_key: str = None
    ) -> Dict[str, Any]:
        """
        Инициирует платеж в Tinkoff с поддержкой рекуррентных платежей.
        
        Args:
            order_id: Уникальный ID заказа
            amount_kopecks: Сумма в копейках
            description: Описание платежа
            user_email: Email пользователя
            receipt_items: Позиции чека
            user_data: Дополнительные данные (не используется из-за проблем с Tinkoff API)
            bot_username: Username бота для deep links
            enable_recurrent: Включить возможность рекуррентных платежей
            customer_key: ID клиента для рекуррентов (обычно user_id)
        """
        
        # Получаем username бота динамически
        if not bot_username:
            bot_username = os.getenv("BOT_USERNAME", "ege_superpuper_bot")
        
        # Убираем @ если он есть
        bot_username = bot_username.lstrip('@')
        
        success_deep_link = f"https://t.me/{bot_username}?start=payment_success_{order_id}"
        fail_deep_link = f"https://t.me/{bot_username}?start=payment_fail_{order_id}"
        
        # Базовые параметры платежа
        payload = {
            "TerminalKey": self.terminal_key,
            "Amount": amount_kopecks,
            "OrderId": order_id,
            "Description": description[:250],
            "SuccessURL": success_deep_link,
            "FailURL": fail_deep_link
        }
        
        # Добавляем NotificationURL только если настроен webhook
        if WEBHOOK_BASE_URL:
            payload["NotificationURL"] = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
        
        # Формируем чек
        payload["Receipt"] = {
            "Email": user_email,
            "Taxation": "usn_income",
            "Items": receipt_items
        }
        
        # Для рекуррентных платежей
        if enable_recurrent and customer_key:
            payload["Recurrent"] = "Y"
            payload["CustomerKey"] = str(customer_key)
            logger.info(f"Enabling recurrent payments for customer {customer_key}")
        
        # ВАЖНО: НЕ добавляем DATA - он вызывает ошибку "Отсутствуют обязательные параметры"
        # Данные пользователя сохраняем в БД по order_id
        
        # Вычисляем токен для подписи
        payload["Token"] = self.calculate_token(payload)
        
        # Отправляем запрос
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}Init",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    text = await response.text()
                    
                    # Пробуем распарсить JSON
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON response: {text}")
                        return {
                            "success": False,
                            "error": "Invalid response from payment gateway"
                        }
                    
                    if response.status == 200 and data.get("Success"):
                        payment_id = data.get("PaymentId")
                        payment_url = data.get("PaymentURL")
                        
                        logger.info(f"Payment initiated successfully: order={order_id}, payment_id={payment_id}")
                        
                        result = {
                            "success": True,
                            "payment_id": payment_id,
                            "payment_url": payment_url,
                            "order_id": order_id
                        }
                        
                        # Отмечаем если рекуррентный платеж включен
                        if enable_recurrent:
                            result["recurrent_enabled"] = True
                            result["customer_key"] = customer_key
                            logger.info(f"✅ Recurrent payment enabled for customer {customer_key}")
                            logger.info(f"RebillId will be available after successful payment")
                        
                        return result
                    else:
                        error = data.get("Message", "Unknown error")
                        error_code = data.get("ErrorCode", "")
                        
                        logger.error(f"Payment init failed: {error}")
                        if error_code:
                            logger.error(f"Error code: {error_code}")
                        
                        return {
                            "success": False,
                            "error": error,
                            "error_code": error_code
                        }
        
        except aiohttp.ClientError as e:
            logger.exception(f"Network error during payment initialization: {e}")
            return {
                "success": False,
                "error": f"Network error: {str(e)}"
            }
        except Exception as e:
            logger.exception(f"Unexpected error initiating payment: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_payment_status(self, payment_id: str) -> Optional[str]:
        """Получает статус платежа."""
        payload = {
            "TerminalKey": self.terminal_key,
            "PaymentId": payment_id
        }
        
        payload["Token"] = self.calculate_token(payload)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}GetState",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    data = await response.json()
                    
                    if data.get("Success"):
                        return data.get("Status")
                    else:
                        logger.error(f"Failed to get payment status: {data.get('Message')}")
                        return None
        
        except Exception as e:
            logger.exception(f"Error getting payment status: {e}")
            return None
    
    # Алиас для обратной совместимости
    async def check_payment_status(self, order_id: str) -> Optional[str]:
        """Проверяет статус платежа по order_id (для обратной совместимости)."""
        # Здесь нужно получить payment_id по order_id из БД
        # Это временное решение, лучше использовать get_payment_status напрямую
        return await self.get_payment_status(order_id)
    
    def build_receipt_item(self, name: str, price_kopecks: int, quantity: int = 1) -> Dict[str, Any]:
        """Создает позицию чека для API."""
        return {
            "Name": name[:64],  # Максимум 64 символа
            "Price": price_kopecks,
            "Quantity": quantity,
            "Amount": price_kopecks * quantity,
            "Tax": "none",  # Без НДС
            "PaymentMethod": "full_prepayment",
            "PaymentObject": "service"
        }
    
    # ============= НОВЫЕ МЕТОДЫ ДЛЯ РЕКУРРЕНТНЫХ ПЛАТЕЖЕЙ =============
    
    async def init_recurrent_payment(
        self,
        order_id: str,
        amount_kopecks: int,
        description: str,
        user_email: str = None
    ) -> Dict[str, Any]:
        """
        Инициализирует платеж для рекуррентного списания (без Recurrent=Y).
        Используется для повторных списаний по сохраненному RebillId.
        
        Args:
            order_id: Уникальный ID заказа
            amount_kopecks: Сумма в копейках
            description: Описание платежа
            user_email: Email для чека (опционально)
            
        Returns:
            Словарь с PaymentId для последующего вызова Charge
        """
        payload = {
            "TerminalKey": self.terminal_key,
            "Amount": amount_kopecks,
            "OrderId": order_id,
            "Description": description[:250]
        }
        
        # Добавляем чек если есть email
        if user_email:
            payload["Receipt"] = {
                "Email": user_email,
                "Taxation": "usn_income",
                "Items": [
                    self.build_receipt_item(
                        name=description[:64],
                        price_kopecks=amount_kopecks
                    )
                ]
            }
        
        payload["Token"] = self.calculate_token(payload)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}Init",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    data = await response.json()
                    
                    if data.get("Success"):
                        logger.info(f"Recurrent payment initialized: {data.get('PaymentId')}")
                        return {
                            "success": True,
                            "payment_id": data.get("PaymentId")
                        }
                    else:
                        logger.error(f"Failed to init recurrent payment: {data}")
                        return {
                            "success": False,
                            "error": data.get("Message", "Unknown error")
                        }
                        
        except Exception as e:
            logger.exception(f"Error initializing recurrent payment: {e}")
            return {"success": False, "error": str(e)}
    
    async def charge_recurrent(
        self,
        payment_id: str,
        rebill_id: str,
        client_ip: str = None
    ) -> Dict[str, Any]:
        """
        Выполняет рекуррентное списание по сохраненным реквизитам.
        
        Args:
            payment_id: ID платежа из Init
            rebill_id: Токен рекуррента из первого успешного платежа
            client_ip: IP клиента (опционально)
            
        Returns:
            Результат списания
        """
        payload = {
            "TerminalKey": self.terminal_key,
            "PaymentId": payment_id,
            "RebillId": rebill_id
        }
        
        if client_ip:
            payload["IP"] = client_ip
        
        payload["Token"] = self.calculate_token(payload)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}Charge",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    data = await response.json()
                    
                    if data.get("Success"):
                        status = data.get("Status")
                        if status == "CONFIRMED":
                            logger.info(f"Recurrent payment confirmed: {payment_id}")
                            return {
                                "success": True,
                                "status": status,
                                "payment_id": payment_id,
                                "amount": data.get("Amount")
                            }
                        elif status in ["REJECTED", "REVERSED"]:
                            logger.warning(f"Recurrent payment rejected: {payment_id}, status: {status}")
                            return {
                                "success": False,
                                "status": status,
                                "error": data.get("Message", f"Payment {status.lower()}")
                            }
                        else:
                            # Платеж в обработке
                            return {
                                "success": False,
                                "status": status,
                                "error": "Payment is processing"
                            }
                    else:
                        error = data.get("Message", "Charge failed")
                        logger.error(f"Charge failed: {error}")
                        return {
                            "success": False,
                            "error": error,
                            "error_code": data.get("ErrorCode")
                        }
                        
        except Exception as e:
            logger.exception(f"Error charging recurrent payment: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_recurrent(self, customer_key: str) -> Dict[str, Any]:
        """
        Отменяет возможность рекуррентных платежей для клиента.
        
        Args:
            customer_key: ID клиента
            
        Returns:
            Результат отмены
        """
        payload = {
            "TerminalKey": self.terminal_key,
            "CustomerKey": str(customer_key)
        }
        
        payload["Token"] = self.calculate_token(payload)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}RemoveCustomer",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    data = await response.json()
                    
                    if data.get("Success"):
                        logger.info(f"Recurrent cancelled for customer {customer_key}")
                        return {"success": True}
                    else:
                        error = data.get("Message", "Failed to cancel")
                        logger.error(f"Failed to cancel recurrent: {error}")
                        return {"success": False, "error": error}
                        
        except Exception as e:
            logger.exception(f"Error cancelling recurrent: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_customer_info(self, customer_key: str) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о сохраненных картах клиента.
        
        Args:
            customer_key: ID клиента
            
        Returns:
            Информация о клиенте и его картах
        """
        payload = {
            "TerminalKey": self.terminal_key,
            "CustomerKey": str(customer_key)
        }
        
        payload["Token"] = self.calculate_token(payload)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}GetCustomer",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    data = await response.json()
                    
                    if data.get("Success"):
                        return data
                    else:
                        logger.error(f"Failed to get customer info: {data.get('Message')}")
                        return None
                        
        except Exception as e:
            logger.exception(f"Error getting customer info: {e}")
            return None


# Для обратной совместимости создаем алиас
TinkoffAPI = TinkoffPayment