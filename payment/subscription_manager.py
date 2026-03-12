# payment/subscription_manager.py
"""Менеджер подписок с поддержкой модульной системы."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from decimal import Decimal
import json
from functools import wraps
import aiosqlite
from enum import Enum

# Используем ваши функции из core.db
from core.db import DATABASE_FILE, execute_with_retry
from .config import (
    SUBSCRIPTION_MODE,
    SUBSCRIPTION_PLANS,
    ALL_PAID_MODULES,
    get_subscription_end_date,
    get_plan_modules
)

logger = logging.getLogger(__name__)

class SubscriptionManager:
    """Управление подписками пользователей."""
    
    def __init__(self):
        """Инициализация менеджера подписок."""
        # Не используем динамический класс, чтобы избежать проблем с pickle
        self.subscription_mode = SUBSCRIPTION_MODE
        # ДОБАВИТЬ ЭТУ СТРОКУ:
        self.database_file = DATABASE_FILE  # Используем импортированный DATABASE_FILE
        logger.info(f"SubscriptionManager initialized with mode: {self.subscription_mode}")
    
    @property
    def config(self):
        """Совместимость со старым кодом."""
        return {'SUBSCRIPTION_MODE': self.subscription_mode}

    async def is_payment_already_activated(self, order_id: str) -> bool:
        """
        Проверяет, был ли платеж уже активирован.
        Защита от повторной обработки webhook.

        ВАЖНО: Проверяет не только статус платежа, но и наличие активных подписок,
        чтобы избежать ситуации, когда статус 'completed', но подписки не созданы.
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # Получаем информацию о платеже
                cursor = await conn.execute(
                    """
                    SELECT status, user_id FROM payments
                    WHERE order_id = ?
                    """,
                    (order_id,)
                )
                result = await cursor.fetchone()

                if not result:
                    return False

                status, user_id = result

                # Если статус не 'completed' или 'activated', платеж точно не активирован
                if status not in ['completed', 'activated']:
                    return False

                # ИСПРАВЛЕНИЕ: Дополнительно проверяем наличие активных подписок
                # Это защищает от случая, когда статус установлен в 'completed',
                # но подписки не были созданы из-за ошибки
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) FROM module_subscriptions
                    WHERE user_id = ? AND is_active = 1
                    """,
                    (user_id,)
                )
                count_result = await cursor.fetchone()

                if count_result and count_result[0] > 0:
                    logger.info(f"Payment {order_id} already activated with {count_result[0]} active subscriptions")
                    return True
                else:
                    # Статус 'completed', но подписок нет - это ошибка!
                    logger.warning(
                        f"Payment {order_id} has status '{status}' but no active subscriptions found. "
                        f"This indicates a previous activation failure. Will retry activation."
                    )
                    return False

        except Exception as e:
            logger.error(f"Error checking payment activation status: {e}")
            return False

    async def get_failed_renewals(self, hours: int = 24) -> List[Dict]:
        """Получает список неудачных попыток автопродления."""
        try:
            from datetime import datetime, timedelta, timezone
            
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                
                cursor = await conn.execute("""
                    SELECT DISTINCT
                        ars.user_id,
                        ars.failures_count,
                        ars.recurrent_token,
                        ars.last_renewal_attempt
                    FROM auto_renewal_settings ars
                    WHERE 
                        ars.enabled = 1
                        AND ars.failures_count > 0
                        AND ars.failures_count < 3
                        AND ars.last_renewal_attempt >= ?
                """, (since,))
                
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting failed renewals: {e}")
            return []

    async def _send_activation_notification(self, user_id: int, plan_id: str, duration_months: int):
        """
        Отправляет уведомление пользователю об активации подписки.
        
        Args:
            user_id: ID пользователя
            plan_id: ID плана
            duration_months: Длительность подписки в месяцах
        """
        try:
            # Получаем бота из контекста если есть
            from telegram import Bot
            from core.config import BOT_TOKEN
            
            bot = Bot(token=BOT_TOKEN)
            
            # Формируем текст уведомления
            # Используем правильные названия с префиксом module_
            plan_names = {
                'trial_7days': '🎁 Пробный период (7 дней)',
                'package_full': '🥇 Полный пакет',
                'package_second': '🥈 Вторая часть',
                'module_test_part': '📝 Тестовая часть',
                'module_task19': '🎯 Задание 19',
                'module_task20': '📖 Задание 20',
                'module_task24': '💎 Задание 24',
                'module_task25': '✍️ Задание 25',
                # Для обратной совместимости
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
            }
            
            plan_name = plan_names.get(plan_id, plan_id)
            
            # Для кастомных планов
            if plan_id.startswith('custom_'):
                # Извлекаем модули из plan_id
                modules_str = plan_id.replace('custom_', '')
                modules_list = []
                
                # Парсим названия модулей
                parts = modules_str.split('_')
                for part in parts:
                    if part == 'testpart':
                        modules_list.append('тестовая часть')
                    elif part.startswith('task'):
                        modules_list.append(f'задание {part[4:]}')
                
                plan_name = f"Индивидуальный набор: {', '.join(modules_list)}"
            
            # Определяем срок
            if plan_id == 'trial_7days':
                duration_text = "7 дней"
            elif duration_months == 1:
                duration_text = "1 месяц"
            else:
                duration_text = f"{duration_months} месяца" if duration_months in [2, 3, 4] else f"{duration_months} месяцев"
            
            message = f"""✅ <b>Подписка успешно активирована!</b>

📦 Тариф: <b>{plan_name}</b>
⏱ Срок действия: <b>{duration_text}</b>

Теперь вам доступны все материалы выбранного тарифа.

Используйте /menu для навигации по разделам.
Проверить статус подписки: /my_subscriptions

Приятного обучения! 🎓"""
            
            await bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='HTML'
            )
            
            logger.info(f"Sent activation notification to user {user_id}")
            
        except Exception as e:
            # Не критичная ошибка - просто логируем
            logger.warning(f"Could not send activation notification: {e}")
            # Не прерываем процесс активации - подписка уже активирована

    async def get_renewal_failures_count(self, user_id: int) -> int:
        """
        Возвращает количество неудачных попыток автопродления для пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            Количество неудач или 0
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                cursor = await conn.execute("""
                    SELECT failures_count FROM auto_renewal_settings WHERE user_id = ?
                """, (user_id,))
                result = await cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting renewal failures count: {e}")
            return 0

    async def increment_renewal_failures(self, user_id: int):
        """Увеличивает счетчик неудачных попыток автопродления."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings
                    SET failures_count = failures_count + 1,
                        last_renewal_attempt = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (user_id,))

                # Проверяем, не превышен ли лимит
                cursor = await conn.execute("""
                    SELECT failures_count FROM auto_renewal_settings WHERE user_id = ?
                """, (user_id,))
                
                row = await cursor.fetchone()
                if row and row[0] >= 3:
                    # Отключаем автопродление после 3 неудач
                    await self.disable_auto_renewal(user_id)
                    logger.warning(f"Auto-renewal disabled for user {user_id} after 3 failures")
                
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error incrementing renewal failures: {e}")

    async def reset_renewal_failures(self, user_id: int):
        """Сбрасывает счетчик неудачных попыток."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET failures_count = 0
                    WHERE user_id = ?
                """, (user_id,))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error resetting renewal failures: {e}")

    async def update_next_renewal_date(self, user_id: int):
        """Обновляет дату следующего автопродления."""
        try:
            from datetime import datetime, timedelta, timezone
            
            next_date = datetime.now(timezone.utc) + timedelta(days=30)
            
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET next_renewal_date = ?
                    WHERE user_id = ?
                """, (next_date, user_id))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error updating next renewal date: {e}")

    async def get_user_email(self, user_id: int) -> str:
        """Получает email пользователя."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                cursor = await conn.execute("""
                    SELECT email FROM users WHERE user_id = ?
                """, (user_id,))
                
                row = await cursor.fetchone()
                return row[0] if row else f"user{user_id}@example.com"
                
        except Exception as e:
            logger.error(f"Error getting user email: {e}")
            return f"user{user_id}@example.com"

    async def get_auto_renewal_status(self, user_id: int) -> Optional[Dict]:
        """Получает статус автопродления для пользователя."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("""
                    SELECT * FROM auto_renewal_settings WHERE user_id = ?
                """, (user_id,))
                
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Error getting auto-renewal status: {e}")
            return None

    async def get_last_payment_info(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о последнем платеже пользователя."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("""
                    SELECT order_id, plan_id, amount, status, metadata, created_at
                    FROM payments 
                    WHERE user_id = ? AND status = 'completed'
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, (user_id,))
                
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    # Парсим metadata если есть
                    if row['metadata']:
                        try:
                            metadata = json.loads(row['metadata'])
                            result['recurrent_id'] = metadata.get('recurrent_token')
                        except json.JSONDecodeError:
                            pass
                    return result
                return None
                
        except Exception as e:
            logger.error(f"Error getting last payment info: {e}")
            return None

    async def get_last_subscription_info(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о последней подписке пользователя."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                
                if self.subscription_mode == 'modular':
                    # Для модульной системы получаем последние активные модули
                    cursor = await conn.execute("""
                        SELECT plan_id, expires_at 
                        FROM module_subscriptions 
                        WHERE user_id = ? 
                        ORDER BY expires_at DESC 
                        LIMIT 1
                    """, (user_id,))
                else:
                    # Для единой системы
                    cursor = await conn.execute("""
                        SELECT plan_id, expires_at 
                        FROM user_subscriptions 
                        WHERE user_id = ? 
                        ORDER BY activated_at DESC 
                        LIMIT 1
                    """, (user_id,))
                
                row = await cursor.fetchone()
                if row:
                    plan_id = row['plan_id']

                    # Получаем информацию о плане
                    plan = SUBSCRIPTION_PLANS.get(plan_id)
                    
                    if plan:
                        return {
                            'plan_id': plan_id,
                            'plan_name': plan.get('name', plan_id),
                            'amount': plan.get('price_rub', 0),
                            'expires_at': row['expires_at']
                        }
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting last subscription info: {e}")
            return None

    async def save_user_email(self, user_id: int, email: str) -> bool:
        """Сохраняет email пользователя."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (user_id, email))
                await conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving user email: {e}")
            return False

    async def get_users_for_auto_renewal(self) -> List[Dict]:
        """
        Получает список пользователей для автопродления.
        
        ИСПРАВЛЕНИЕ: Добавлена проверка plan_id в JOIN для корректного получения суммы платежа.
        """
        try:
            from datetime import datetime, timezone
            
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                
                cursor = await conn.execute("""
                    SELECT 
                        ars.user_id,
                        ars.recurrent_token,
                        ms.plan_id,
                        COALESCE(p.amount / 100, 0) as amount  -- ИСПРАВЛЕНО: добавлен COALESCE для NULL
                    FROM auto_renewal_settings ars
                    INNER JOIN module_subscriptions ms ON ars.user_id = ms.user_id
                    LEFT JOIN (
                        SELECT user_id, plan_id, MAX(amount) as amount
                        FROM payments
                        WHERE status = 'completed'
                        GROUP BY user_id, plan_id
                    ) p ON ars.user_id = p.user_id AND ms.plan_id = p.plan_id  -- ИСПРАВЛЕНО: добавлен AND ms.plan_id = p.plan_id
                    WHERE 
                        ars.enabled = 1 
                        AND ars.recurrent_token IS NOT NULL
                        AND ms.is_active = 1
                        AND ms.expires_at <= datetime('now', '+1 day')
                        AND ars.failures_count < 3
                """)
                
                rows = await cursor.fetchall()
                
                # КРИТИЧНОЕ ДОПОЛНЕНИЕ: Валидация данных перед возвратом
                validated_users = []
                for row in rows:
                    user_dict = dict(row)
                    
                    # Проверяем что у нас есть все необходимые данные
                    if user_dict.get('amount', 0) <= 0:
                        logger.warning(
                            f"User {user_dict['user_id']} has invalid amount for auto-renewal. "
                            f"Skipping renewal to prevent charging incorrect amount."
                        )
                        continue
                    
                    if not user_dict.get('recurrent_token'):
                        logger.warning(
                            f"User {user_dict['user_id']} missing recurrent_token. "
                            f"Skipping renewal."
                        )
                        continue
                    
                    validated_users.append(user_dict)
                
                logger.info(f"Found {len(validated_users)} validated users for auto-renewal")
                return validated_users
                
        except Exception as e:
            logger.error(f"Error getting users for auto-renewal: {e}")
            return []

    async def update_order_payment_id(self, order_id: str, payment_id: str):
        """Обновляет payment_id для заказа.
        
        Args:
            order_id: ID заказа
            payment_id: ID платежа от платежной системы
            
        Returns:
            bool: True если успешно обновлено
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    UPDATE payments 
                    SET payment_id = ?, created_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                """, (payment_id, order_id))
                await conn.commit()
                logger.info(f"Updated payment_id for order {order_id}: {payment_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating payment_id: {e}")
            return False
    
    async def save_pending_order(self, order_id: str, user_id: int, plan_id: str, 
                                 amount: int, duration_months: int = 1, 
                                 email: str = None, enable_auto_renewal: bool = False):
        """Сохраняет информацию о pending заказе.
        
        Args:
            order_id: Уникальный ID заказа
            user_id: ID пользователя Telegram
            plan_id: ID плана подписки
            amount: Сумма в рублях
            duration_months: Длительность подписки в месяцах
            email: Email пользователя
            enable_auto_renewal: Флаг автопродления
            
        Returns:
            bool: True если успешно сохранено
        """
        try:
            import json
            
            metadata = json.dumps({
                'plan_id': plan_id,
                'duration_months': duration_months,
                'email': email,
                'enable_auto_renewal': enable_auto_renewal
            })
            
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO payments 
                    (order_id, user_id, plan_id, amount_kopecks, status, metadata, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                """, (order_id, user_id, plan_id, amount * 100, metadata))
                await conn.commit()
                
                logger.info(f"Saved pending order: {order_id} for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error saving pending order: {e}")
            return False    

    async def get_payment_by_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Получает информацию о платеже по order_id.
        
        Args:
            order_id: ID заказа
            
        Returns:
            Словарь с информацией о платеже или None
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("""
                    SELECT * FROM payments WHERE order_id = ?
                """, (order_id,))
                
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Error getting payment by order_id: {e}")
            return None

    def _extract_modules_from_plan_id(self, plan_id: str) -> List[str]:
        """
        Извлекает модули из custom plan_id.
        Возвращает нормализованные названия модулей (без префикса module_).
        
        Примеры:
        - custom_testpart_task19 -> ['test_part', 'task19']
        - custom_module_test_part_module_task19 -> ['test_part', 'task19']
        """
        if not plan_id.startswith('custom_'):
            return []
        
        # Убираем префикс custom_
        modules_str = plan_id.replace('custom_', '')
        modules = []
        
        # Разбиваем по подчеркиванию
        parts = modules_str.split('_')
        
        # Обрабатываем каждую часть
        i = 0
        while i < len(parts):
            # Пропускаем слово "module" если оно встречается
            if parts[i] == 'module':
                i += 1
                continue
                
            # Проверяем на составные названия модулей
            if parts[i] == 'test' and i + 1 < len(parts) and parts[i + 1] == 'part':
                modules.append('test_part')
                i += 2
            elif parts[i] == 'testpart':
                modules.append('test_part')
                i += 1
            elif parts[i].startswith('task'):
                modules.append(parts[i])
                i += 1
            else:
                # Неизвестный модуль - пробуем добавить как есть
                if parts[i]:  # Игнорируем пустые строки
                    modules.append(parts[i])
                i += 1
        
        return modules

    async def save_payment_metadata(self, payment_id: str, metadata: dict):
        """Сохраняет метаданные платежа для custom планов.
        
        Args:
            payment_id: ID платежа
            metadata: Словарь с метаданными (modules, duration_months, plan_name и т.д.)
        """
        async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
            # Создаем таблицу если она не существует
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payment_metadata (
                    payment_id TEXT PRIMARY KEY,
                    metadata TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Сохраняем метаданные
            await conn.execute("""
                INSERT OR REPLACE INTO payment_metadata (payment_id, metadata, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (payment_id, json.dumps(metadata)))
            
            await conn.commit()
            
            logger.info(f"Saved metadata for payment {payment_id}: {metadata}")

    # Исправленный метод save_payment_info для payment/subscription_manager.py

    async def save_payment_info(self, user_id: int, payment_id: str, order_id: str, 
                               amount: int, plan_id: str, duration: int,
                               email: str, metadata: Dict = None) -> bool:
        """
        Сохраняет информацию о платеже в базу данных.
        
        Args:
            user_id: ID пользователя
            payment_id: ID платежа от Tinkoff
            order_id: Уникальный ID заказа
            amount: Сумма в рублях
            plan_id: ID плана подписки
            duration: Длительность в месяцах
            email: Email пользователя
            metadata: Дополнительные данные (опционально)
        
        Returns:
            True при успешном сохранении
        """
        try:
            import json
            from datetime import datetime
            
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # Сначала проверим структуру таблицы payments
                cursor = await conn.execute("PRAGMA table_info(payments)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                logger.debug(f"Available columns in payments table: {column_names}")
                
                # Сохраняем email пользователя
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, email)
                )
                
                # Конвертируем metadata в JSON
                metadata_json = json.dumps(metadata or {})
                
                # ИСПРАВЛЕНИЕ: Используем правильное имя столбца amount_kopecks
                # Проверяем, какие столбцы есть в таблице
                if 'amount_kopecks' in column_names:
                    # Используем amount_kopecks (правильное имя)
                    await conn.execute(
                        """
                        INSERT INTO payments (
                            payment_id, order_id, user_id, plan_id, 
                            amount_kopecks, status, created_at, metadata
                        )
                        VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, ?)
                        """,
                        (payment_id, order_id, user_id, plan_id, amount * 100, metadata_json)
                    )
                elif 'amount' in column_names:
                    # Если есть столбец amount (старая версия)
                    await conn.execute(
                        """
                        INSERT INTO payments (
                            payment_id, order_id, user_id, plan_id, 
                            amount, status, created_at, metadata
                        )
                        VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, ?)
                        """,
                        (payment_id, order_id, user_id, plan_id, amount * 100, metadata_json)
                    )
                else:
                    # Если нет ни того, ни другого - создаем таблицу
                    logger.warning("Column amount/amount_kopecks not found, creating table...")
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS payments (
                            payment_id TEXT PRIMARY KEY,
                            order_id TEXT UNIQUE NOT NULL,
                            user_id INTEGER NOT NULL,
                            plan_id TEXT NOT NULL,
                            amount_kopecks INTEGER NOT NULL,
                            status TEXT DEFAULT 'pending',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            completed_at TIMESTAMP,
                            metadata TEXT DEFAULT '{}',
                            rebill_id TEXT,
                            is_recurrent BOOLEAN DEFAULT 0,
                            auto_renewal_enabled BOOLEAN DEFAULT 0
                        )
                    """)
                    
                    # И сохраняем данные
                    await conn.execute(
                        """
                        INSERT INTO payments (
                            payment_id, order_id, user_id, plan_id, 
                            amount_kopecks, status, created_at, metadata
                        )
                        VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, ?)
                        """,
                        (payment_id, order_id, user_id, plan_id, amount * 100, metadata_json)
                    )
                
                # Если включено автопродление, сохраняем эту информацию
                if metadata and metadata.get('enable_auto_renewal'):
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO auto_renewal_consents (
                            user_id, plan_id, amount, period_days,
                            consent_text, consent_checkbox_state,
                            telegram_chat_id, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            user_id, 
                            plan_id, 
                            amount, 
                            duration * 30,
                            f"Согласие на автопродление подписки {plan_id} на сумму {amount} руб. каждые {duration * 30} дней",
                            user_id  # telegram_chat_id = user_id
                        )
                    )
                
                await conn.commit()
                
                logger.info(f"Payment info saved: order_id={order_id}, user_id={user_id}, amount={amount}₽")
                return True
                
        except Exception as e:
            logger.error(f"Error saving payment info: {e}", exc_info=True)
            return False
            
    async def get_user_active_modules(self, user_id: int) -> List[str]:
        """
        Получает список кодов активных модулей пользователя.
        Это алиас для get_user_modules, но возвращает только коды модулей.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Список кодов активных модулей (например, ['test_part', 'task19'])
        """
        modules = await self.get_user_modules(user_id)
        # Возвращаем только коды модулей
        return [module['module_code'] for module in modules]
        
    async def init_tables(self):
        """Инициализирует таблицы в БД с правильной схемой."""
        try:
            async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
                # Создаем таблицу payments с ПРАВИЛЬНОЙ схемой
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        order_id TEXT UNIQUE NOT NULL,
                        plan_id TEXT NOT NULL,
                        amount_kopecks INTEGER NOT NULL,
                        status TEXT DEFAULT 'pending',
                        payment_id TEXT,
                        metadata TEXT,
                        email TEXT,  -- ВАЖНО: колонка email включена в схему
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """)
                
                # Проверяем и добавляем недостающие колонки для существующих таблиц
                cursor = await conn.execute("PRAGMA table_info(payments)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]

                # МИГРАЦИЯ: Переименование amount в amount_kopecks (проблема #5)
                if 'amount' in column_names and 'amount_kopecks' not in column_names:
                    logger.info("Migrating 'amount' column to 'amount_kopecks' in payments table...")
                    # SQLite не поддерживает RENAME COLUMN напрямую в старых версиях
                    # Используем подход: создаем новую колонку, копируем данные, удаляем старую
                    try:
                        # Создаем новую колонку
                        await conn.execute("ALTER TABLE payments ADD COLUMN amount_kopecks INTEGER")

                        # Копируем данные из amount в amount_kopecks
                        await conn.execute("UPDATE payments SET amount_kopecks = amount WHERE amount_kopecks IS NULL")

                        # Делаем amount_kopecks NOT NULL через UPDATE (удалить старую колонку нельзя в SQLite)
                        # Просто оставляем обе колонки, но используем amount_kopecks
                        logger.info("✅ Migrated amount to amount_kopecks (old column preserved for compatibility)")
                    except Exception as migration_error:
                        logger.warning(f"Migration warning for amount_kopecks: {migration_error}")

                # Добавляем недостающие колонки если таблица уже существовала
                if 'metadata' not in column_names:
                    await conn.execute("ALTER TABLE payments ADD COLUMN metadata TEXT")
                    logger.info("Added metadata column to payments table")

                if 'email' not in column_names:
                    await conn.execute("ALTER TABLE payments ADD COLUMN email TEXT")
                    logger.info("Added email column to payments table")

                if 'completed_at' not in column_names:
                    await conn.execute("ALTER TABLE payments ADD COLUMN completed_at TIMESTAMP")
                    logger.info("Added completed_at column to payments table")

                await conn.commit()
                    
                # Индексы для payments
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_payments_user 
                    ON payments(user_id)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_payments_status 
                    ON payments(status)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_payments_order 
                    ON payments(order_id)
                """)
                
                # Таблица для хранения email пользователей отдельно
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_emails (
                        user_id INTEGER PRIMARY KEY,
                        email TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Для модульного режима
                if self.subscription_mode == 'modular':
                    # Таблица модульных подписок
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS module_subscriptions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            module_code TEXT NOT NULL,
                            plan_id TEXT NOT NULL,
                            expires_at TIMESTAMP NOT NULL,
                            is_active BOOLEAN DEFAULT 1,
                            is_trial BOOLEAN DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, module_code)
                        )
                    """)

                    # МИГРАЦИЯ: Добавляем is_trial если колонки нет в существующей таблице
                    try:
                        cursor = await conn.execute("PRAGMA table_info(module_subscriptions)")
                        ms_columns = await cursor.fetchall()
                        ms_column_names = [col[1] for col in ms_columns]
                        if 'is_trial' not in ms_column_names:
                            await conn.execute("ALTER TABLE module_subscriptions ADD COLUMN is_trial BOOLEAN DEFAULT 0")
                            logger.info("Added is_trial column to module_subscriptions")
                    except Exception as migration_error:
                        logger.warning(f"Migration warning for module_subscriptions.is_trial: {migration_error}")
                    
                    # Индексы для module_subscriptions
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_user 
                        ON module_subscriptions(user_id)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_expires 
                        ON module_subscriptions(expires_at)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_module_subs_active 
                        ON module_subscriptions(is_active)
                    """)
                    
                    # История пробных периодов
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS trial_history (
                            user_id INTEGER PRIMARY KEY,
                            trial_activated_at TIMESTAMP,
                            trial_expires_at TIMESTAMP
                        )
                    """)
                    
                    logger.info("Modular subscription tables created")
                    
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS auto_renewal_settings (
                            user_id INTEGER PRIMARY KEY,
                            enabled BOOLEAN DEFAULT 0,
                            payment_method TEXT,  -- 'card' или 'recurrent_token'
                            recurrent_token TEXT,  -- Токен для рекуррентных платежей
                            card_id TEXT,  -- ID сохраненной карты
                            last_renewal_attempt TIMESTAMP,
                            next_renewal_date TIMESTAMP,
                            failures_count INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Таблица истории автопродлений
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS auto_renewal_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            plan_id TEXT NOT NULL,
                            payment_id TEXT,
                            status TEXT NOT NULL,  -- 'success', 'failed', 'cancelled'
                            amount INTEGER NOT NULL,
                            error_message TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES users(user_id)
                        )
                    """)
                    
                    # Таблица для уведомлений об истечении подписки
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS subscription_notifications (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            notification_type TEXT NOT NULL, -- 'expiry_7days', 'expiry_3days', 'expiry_1day', 'expired'
                            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            subscription_end_date TIMESTAMP,
                            UNIQUE(user_id, notification_type, subscription_end_date)
                        )
                    """)
                    
                    await conn.commit()
                    logger.info("Extended subscription tables created")
                    
                else:
                    # Единая таблица подписок (для обычного режима)
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS user_subscriptions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            plan_id TEXT NOT NULL,
                            payment_id TEXT,
                            status TEXT DEFAULT 'active',
                            expires_at TIMESTAMP NOT NULL,
                            activated_at TIMESTAMP,
                            is_active BOOLEAN DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id)
                        )
                    """)

                    # МИГРАЦИЯ: Добавляем недостающие колонки в существующие таблицы
                    try:
                        # Проверяем, существует ли колонка payment_id
                        cursor = await conn.execute("PRAGMA table_info(user_subscriptions)")
                        columns = await cursor.fetchall()
                        column_names = [col[1] for col in columns]

                        if 'payment_id' not in column_names:
                            await conn.execute("ALTER TABLE user_subscriptions ADD COLUMN payment_id TEXT")
                            logger.info("Added payment_id column to user_subscriptions")

                        if 'status' not in column_names:
                            await conn.execute("ALTER TABLE user_subscriptions ADD COLUMN status TEXT DEFAULT 'active'")
                            logger.info("Added status column to user_subscriptions")

                        if 'activated_at' not in column_names:
                            await conn.execute("ALTER TABLE user_subscriptions ADD COLUMN activated_at TIMESTAMP")
                            logger.info("Added activated_at column to user_subscriptions")
                    except Exception as migration_error:
                        logger.warning(f"Migration warning for user_subscriptions: {migration_error}")

                    logger.info("Standard subscription tables created")
                
                # Таблица для логирования webhook запросов (нужна для дедупликации)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS webhook_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payment_id TEXT,
                        data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(order_id, status)
                    )
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_webhook_logs_order
                    ON webhook_logs(order_id, status)
                """)

                # Таблица для защиты от повторной отправки уведомлений
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS notification_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        order_id TEXT NOT NULL,
                        notification_type TEXT NOT NULL,
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, order_id, notification_type)
                    )
                """)

                await conn.commit()
                logger.info("All tables initialized successfully")
                
        except Exception as e:
            logger.error(f"Error initializing tables: {e}")
            raise
    
    async def deactivate_subscription(self, user_id: int, plan_id: str) -> bool:
        """
        Деактивация подписки пользователя (при возврате средств)
        
        Args:
            user_id: ID пользователя
            plan_id: ID плана подписки
            
        Returns:
            bool: Успешность операции
        """
        try:
            async with aiosqlite.connect(self.db_path, timeout=30.0) as db:
                # Получаем модули, связанные с планом
                modules = self.SUBSCRIPTION_PLANS.get(plan_id, {}).get('modules', [])
                
                if plan_id == 'package_full':
                    # Для полного пакета деактивируем все модули
                    await db.execute("""
                        DELETE FROM user_subscriptions 
                        WHERE user_id = ?
                    """, (user_id,))
                else:
                    # Для остальных планов деактивируем только конкретные модули
                    for module in modules:
                        await db.execute("""
                            DELETE FROM user_subscriptions 
                            WHERE user_id = ? AND module_id = ?
                        """, (user_id, module))
                
                # Обновляем статус в module_subscriptions
                await db.execute("""
                    UPDATE module_subscriptions 
                    SET status = 'refunded', 
                        end_date = CURRENT_TIMESTAMP,
                        created_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND plan_id = ? AND status = 'active'
                """, (user_id, plan_id))
                
                await db.commit()
                
                logger.info(f"Подписка {plan_id} деактивирована для пользователя {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Ошибка деактивации подписки: {e}")
            return False

    # Добавьте этот метод для получения информации о платеже:
    async def get_payment_by_order_id(self, order_id: str) -> Optional[dict]:
        """Получает информацию о платеже по order_id."""
        try:
            async with aiosqlite.connect(self.db_path, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM payments WHERE order_id = ?
                """, (order_id,))
                
                row = await cursor.fetchone()
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Error getting payment info: {e}")
            return None
    
    async def get_subscription_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получает информацию о подписке пользователя для отображения."""
        if SUBSCRIPTION_MODE == 'modular':
            # Модульная система
            modules = await self.get_user_modules(user_id)
            if not modules:
                return None
                
            # Формируем информацию
            module_names = {
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
            }
            
            active_modules = []
            min_expires = None
            
            for module in modules:
                # ИСПРАВЛЕНИЕ: Возвращаем коды модулей, а не названия
                active_modules.append(module['module_code'])

                if min_expires is None or (module['expires_at'].replace(tzinfo=None) if hasattr(module['expires_at'], 'tzinfo') else module['expires_at']) < (min_expires.replace(tzinfo=None) if hasattr(min_expires, 'tzinfo') else min_expires):
                    min_expires = module['expires_at']

            # ИСПРАВЛЕНИЕ: Исключаем test_part при проверке активности подписки
            # test_part бесплатен и не должен считаться платной подпиской
            paid_modules = [m for m in active_modules if m != 'test_part']

            # ИСПРАВЛЕНИЕ: Добавляем поле is_active только если есть платные модули
            return {
                'type': 'modular',
                'modules': active_modules,
                'expires_at': min_expires,
                'modules_count': len(modules),
                'is_active': len(paid_modules) > 0  # Подписка активна только если есть платные модули
            }
        else:
            # Старая система
            subscription = await self.check_active_subscription(user_id)
            if subscription:
                plan = SUBSCRIPTION_PLANS.get(subscription['plan_id'], {})
                return {
                    'type': 'unified',
                    'plan_name': plan.get('name', 'Подписка'),
                    'plan_id': subscription['plan_id'],
                    'expires_at': subscription['expires_at'],
                    'is_active': True  # Подписка активна
                }
            return None  # Возвращаем None если подписки нет
    
    async def check_active_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверяет активную подписку пользователя."""
        if SUBSCRIPTION_MODE == 'modular':
            return await self._check_modular_subscriptions(user_id)
        else:
            return await self._check_unified_subscription(user_id)
    
    async def _check_unified_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверка единой подписки - ИСПРАВЛЕННАЯ версия."""
        try:
            async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
                # Проверяем в правильной таблице user_subscriptions
                cursor = await conn.execute(
                    """
                    SELECT plan_id, expires_at, activated_at
                    FROM user_subscriptions
                    WHERE user_id = ? AND status = 'active' AND expires_at > ?
                    ORDER BY expires_at DESC
                    LIMIT 1
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                row = await cursor.fetchone()
                
                if row:
                    plan_id, expires_at, activated_at = row

                    # Парсим даты и добавляем timezone если необходимо
                    expires_dt = datetime.fromisoformat(expires_at)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                    activated_dt = None
                    if activated_at:
                        activated_dt = datetime.fromisoformat(activated_at)
                        if activated_dt.tzinfo is None:
                            activated_dt = activated_dt.replace(tzinfo=timezone.utc)

                    return {
                        'plan_id': plan_id,
                        'expires_at': expires_dt,
                        'activated_at': activated_dt,
                        'active_modules': get_plan_modules(plan_id)  # Для совместимости
                    }
                
                # Проверяем также старую таблицу subscriptions для обратной совместимости
                cursor = await conn.execute(
                    """
                    SELECT plan_id, expires_at, created_at
                    FROM subscriptions
                    WHERE user_id = ? AND is_active = 1 AND expires_at > ?
                    ORDER BY expires_at DESC
                    LIMIT 1
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                row = await cursor.fetchone()

                if row:
                    plan_id, expires_at, created_at = row

                    # Парсим даты и добавляем timezone если необходимо
                    expires_dt = datetime.fromisoformat(expires_at)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                    created_dt = datetime.fromisoformat(created_at)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)

                    return {
                        'plan_id': plan_id,
                        'expires_at': expires_dt,
                        'created_at': created_dt,
                        'active_modules': get_plan_modules(plan_id)
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"Error checking unified subscription: {e}")
            return None
    
    async def _check_modular_subscriptions(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Проверка модульных подписок."""
        try:
            async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
                # Получаем все активные модули
                cursor = await conn.execute(
                    """
                    SELECT DISTINCT module_code, MAX(expires_at) as expires_at
                    FROM module_subscriptions
                    WHERE user_id = ? AND is_active = 1 AND expires_at > ?
                    GROUP BY module_code
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                modules = await cursor.fetchall()
                
                if not modules:
                    return None
                
                active_modules = [row[0] for row in modules]
                
                # Определяем эквивалентный план
                # Используем ALL_PAID_MODULES для проверки полного пакета
                if set(active_modules) >= set(ALL_PAID_MODULES):
                    plan_id = 'package_full'
                elif set(active_modules) >= set(m for m in ALL_PAID_MODULES if m != 'test_part'):
                    plan_id = 'package_second_part'
                else:
                    plan_id = 'custom_modules'
                
                # Берем минимальную дату окончания
                # Парсим даты и добавляем timezone если необходимо
                expires_dates = []
                modules_info = {}
                for row in modules:
                    module_code, expires_str = row[0], row[1]
                    expires_dt = datetime.fromisoformat(expires_str)

                    # Если naive, добавляем UTC
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                    expires_dates.append(expires_dt)
                    modules_info[module_code] = expires_dt

                min_expires = min(expires_dates)

                return {
                    'plan_id': plan_id,
                    'expires_at': min_expires,
                    'active_modules': active_modules,
                    'modules_info': modules_info
                }
        except Exception as e:
            logger.error(f"Error checking modular subscriptions: {e}")
            return None
    
    async def check_module_access(self, user_id: int, module_code: str) -> bool:
        """
        Проверяет доступ пользователя к конкретному модулю.

        Args:
            user_id: ID пользователя
            module_code: Код модуля (например, 'test_part', 'task19', etc.)

        Returns:
            True если есть доступ, False если нет
        """
        logger.info(f"Checking module access for user {user_id}, module {module_code}")

        if SUBSCRIPTION_MODE == 'modular':
            try:
                async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
                    # Проверяем в таблице module_subscriptions
                    cursor = await conn.execute(
                        """
                        SELECT id FROM module_subscriptions
                        WHERE user_id = ?
                        AND module_code = ?
                        AND is_active = 1
                        AND expires_at > datetime('now')
                        """,
                        (user_id, module_code)
                    )
                    result = await cursor.fetchone()

                    if result:
                        logger.info(f"User {user_id} has active module subscription for {module_code}")
                        return True

                    # ИСПРАВЛЕНИЕ: Проверяем plan_id в module_subscriptions
                    # Если у пользователя есть подписка с планом, который включает данный модуль,
                    # но запись для этого модуля не была создана (например, модуль добавлен позже),
                    # всё равно даём доступ
                    cursor = await conn.execute(
                        """
                        SELECT DISTINCT plan_id FROM module_subscriptions
                        WHERE user_id = ?
                        AND is_active = 1
                        AND expires_at > datetime('now')
                        """,
                        (user_id,)
                    )
                    user_plans = await cursor.fetchall()

                    for (plan_id_from_db,) in user_plans:
                        if plan_id_from_db:
                            # Получаем конфигурацию плана
                            plan_config = SUBSCRIPTION_PLANS.get(plan_id_from_db, {})
                            plan_modules = plan_config.get('modules', [])

                            if module_code in plan_modules:
                                logger.info(f"User {user_id} has access to {module_code} via active plan {plan_id_from_db}")
                                return True

                    # Проверяем общую подписку (некоторые планы дают доступ ко всем модулям)
                    cursor = await conn.execute(
                        """
                        SELECT plan_id FROM user_subscriptions
                        WHERE user_id = ?
                        AND status = 'active'
                        AND expires_at > datetime('now')
                        """,
                        (user_id,)
                    )
                    subscription = await cursor.fetchone()

                    if subscription:
                        plan_id = subscription[0]

                        # Полный доступ
                        if plan_id in ['package_full', 'trial_7days']:
                            logger.info(f"User {user_id} has full access plan: {plan_id}")
                            return True

                        # Пакет "Вторая часть"
                        elif plan_id == 'package_second_part' and module_code in ['task19', 'task20', 'task25']:
                            logger.info(f"User {user_id} has second part package, access to {module_code}")
                            return True

                        # Старые планы pro_month и pro_ege (доступ ко всему кроме task24)
                        elif plan_id in ['pro_month', 'pro_ege'] and module_code not in ['task24']:
                            logger.info(f"User {user_id} has Pro subscription, access to {module_code} granted")
                            return True

                        # Любой другой активный план — проверяем через конфигурацию
                        else:
                            plan_config = SUBSCRIPTION_PLANS.get(plan_id, {})
                            plan_modules = plan_config.get('modules', [])
                            if module_code in plan_modules:
                                logger.info(f"User {user_id} has access to {module_code} via plan {plan_id}")
                                return True

            except Exception as e:
                logger.error(f"Error checking module access: {e}")
                return False
        else:
            # В обычном режиме проверяем любую активную подписку
            subscription = await self.check_active_subscription(user_id)
            if subscription:
                return True

        # Проверяем подаренные подписки (от учителей через промокоды)
        # Подаренная подписка даёт полный доступ ко всем модулям
        try:
            async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
                cursor = await conn.execute(
                    """
                    SELECT id FROM gifted_subscriptions
                    WHERE recipient_id = ?
                      AND status = 'active'
                      AND expires_at > datetime('now')
                    LIMIT 1
                    """,
                    (user_id,)
                )
                gifted = await cursor.fetchone()
                if gifted:
                    logger.info(
                        f"User {user_id} has active gifted subscription, granting access to {module_code}"
                    )
                    return True
        except Exception as e:
            logger.error(f"Error checking gifted subscription access: {e}")

        logger.info(f"User {user_id} has no access to module {module_code}")
        return False
    
    async def create_payment(self, user_id: int, plan_id: str, amount_kopecks: int,
                            duration_months: int = 1, metadata: dict = None) -> Dict[str, Any]:
        """
        Создает запись о платеже с сохранением метаданных.

        ИСПРАВЛЕНИЕ: Добавлена идемпотентность - если у пользователя уже есть
        pending платеж для того же плана, созданный недавно, возвращается существующий.
        Это защищает от дублирования при двойном клике кнопки "Оплатить".
        """
        import uuid
        import json

        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # НОВОЕ: Проверяем существующие pending платежи за последние 5 минут
                cursor = await conn.execute(
                    """
                    SELECT order_id, plan_id, amount_kopecks, metadata, created_at
                    FROM payments
                    WHERE user_id = ?
                      AND plan_id = ?
                      AND status = 'pending'
                      AND created_at > datetime('now', '-5 minutes')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (user_id, plan_id)
                )
                existing_payment = await cursor.fetchone()

                if existing_payment:
                    order_id, plan_id_db, amount_db, metadata_str, created_at = existing_payment

                    # Парсим метаданные
                    try:
                        existing_metadata = json.loads(metadata_str) if metadata_str else {}
                    except:
                        existing_metadata = {}

                    existing_duration = existing_metadata.get('duration_months', 1)

                    # Проверяем, совпадают ли параметры
                    if amount_db == amount_kopecks and existing_duration == duration_months:
                        logger.info(
                            f"♻️  Reusing existing pending payment {order_id} for user {user_id} "
                            f"(created {created_at}, idempotency check)"
                        )
                        return {
                            'order_id': order_id,
                            'user_id': user_id,
                            'plan_id': plan_id,
                            'amount_kopecks': amount_db,
                            'duration_months': existing_duration,
                            'reused': True  # Флаг что это переиспользованный платеж
                        }
                    else:
                        # Параметры не совпадают - создаем новый платеж
                        logger.info(
                            f"Parameters mismatch for pending payment {order_id}: "
                            f"amount {amount_db} vs {amount_kopecks}, duration {existing_duration} vs {duration_months}. "
                            f"Creating new payment."
                        )

                # Создаем новый платеж
                order_id = f"ORD_{user_id}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

                # КРИТИЧЕСКИ ВАЖНО: Подготавливаем метаданные
                payment_metadata = metadata or {}
                payment_metadata['duration_months'] = duration_months
                payment_metadata['plan_id'] = plan_id
                payment_metadata['user_id'] = user_id

                await conn.execute(
                    """
                    INSERT INTO payments (user_id, order_id, plan_id, amount_kopecks, status, metadata, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, order_id, plan_id, amount_kopecks, json.dumps(payment_metadata))
                )
                await conn.commit()

                logger.info(f"✅ Created new payment {order_id} with duration_months={duration_months}")

                return {
                    'order_id': order_id,
                    'user_id': user_id,
                    'plan_id': plan_id,
                    'amount_kopecks': amount_kopecks,
                    'duration_months': duration_months,
                    'reused': False
                }

        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            raise
    
    async def activate_subscription(self, order_id: str, payment_id: str = None) -> bool:
        """
        Активирует подписку после успешной оплаты с защитой от race conditions.

        ИСПРАВЛЕНИЕ: Использует эксклюзивные транзакции для предотвращения дублирования
        при одновременных webhook от платежной системы.
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # КРИТИЧЕСКИ ВАЖНО: Начинаем эксклюзивную транзакцию
                # Это блокирует другие попытки активации этого же платежа
                await conn.execute("BEGIN EXCLUSIVE TRANSACTION")

                try:
                    # Получаем информацию о платеже с блокировкой строки
                    cursor = await conn.execute(
                        """
                        SELECT user_id, plan_id, metadata, status
                        FROM payments
                        WHERE order_id = ?
                        """,
                        (order_id,)
                    )
                    payment_info = await cursor.fetchone()

                    if not payment_info:
                        logger.error(f"Payment not found for order {order_id}")
                        await conn.rollback()
                        return False

                    user_id, plan_id, metadata_str, current_status = payment_info

                    # КЛЮЧЕВАЯ ПРОВЕРКА: Если платеж уже обработан - выходим
                    if current_status == 'completed':
                        logger.info(f"Payment {order_id} already completed (status check inside transaction)")
                        await conn.rollback()
                        return True  # Возвращаем success, т.к. подписка уже активна

                    # Парсим metadata
                    try:
                        metadata = json.loads(metadata_str) if metadata_str else {}
                    except:
                        metadata = {}

                    duration_months = metadata.get('duration_months', 1)

                    logger.info(f"Activating subscription: user={user_id}, plan={plan_id}, duration={duration_months}")

                    # Активируем в зависимости от типа плана
                    if plan_id.startswith('custom_'):
                        # Кастомный план с модулями
                        success = await self._activate_custom_modules(
                            conn, user_id, plan_id, duration_months, metadata
                        )
                    else:
                        # Стандартный план
                        success = await self._activate_standard_plan(
                            conn, user_id, plan_id, duration_months
                        )

                    if success:
                        # ИСПРАВЛЕНИЕ: Логируем активированные модули для отладки
                        cursor = await conn.execute(
                            """SELECT module_code, expires_at FROM module_subscriptions
                               WHERE user_id = ? AND is_active = 1
                               ORDER BY module_code""",
                            (user_id,)
                        )
                        active_modules = await cursor.fetchall()
                        module_list = [m[0] for m in active_modules]
                        logger.info(f"📦 Activated modules for user {user_id}: {module_list}")

                        # Обновляем статус платежа на completed
                        await conn.execute(
                            """
                            UPDATE payments
                            SET status = 'completed',
                                completed_at = CURRENT_TIMESTAMP,
                                payment_id = COALESCE(payment_id, ?)
                            WHERE order_id = ?
                            """,
                            (payment_id, order_id)
                        )

                        # Коммитим транзакцию - теперь изменения атомарны
                        await conn.commit()
                        logger.info(f"✅ Subscription activated successfully for order {order_id} (atomic transaction)")
                        return True
                    else:
                        # Откатываем если активация не удалась
                        logger.error(f"Failed to activate subscription for order {order_id}, rolling back")
                        await conn.rollback()
                        return False

                except Exception as e:
                    # При любой ошибке откатываем транзакцию
                    logger.error(f"Error during activation transaction: {e}")
                    await conn.rollback()
                    raise

        except Exception as e:
            logger.error(f"Error activating subscription: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _activate_standard_plan(self, conn, user_id: int, plan_id: str, duration_months: int) -> bool:
        """
        Активирует стандартный план подписки.
        ИСПРАВЛЕНО: Использует переданное соединение для атомарности транзакции.

        Args:
            conn: Существующее соединение с БД (для использования в транзакции)
            user_id: ID пользователя
            plan_id: ID плана подписки
            duration_months: Длительность подписки в месяцах
        """
        try:
            # Получаем информацию о плане
            plan = SUBSCRIPTION_PLANS.get(plan_id)
            if not plan:
                logger.error(f"Unknown plan: {plan_id}")
                return False

            # ВАЖНО: Используем модули из конфигурации
            modules = plan.get('modules', [])

            if not modules:
                logger.error(f"Plan {plan_id} has no modules defined")
                return False

            logger.info(f"Activating plan {plan_id} for user {user_id} with modules: {modules}")

            # ИСПРАВЛЕНИЕ: Используем функцию get_subscription_end_date для правильного расчета
            # Она корректно обрабатывает trial_7days (7 дней) и обычные планы (30 * months)
            expires_at = get_subscription_end_date(plan_id, duration_months).isoformat()

            # КРИТИЧНО: Вычисляем длительность в днях для логики продления
            if plan_id == 'trial_7days':
                duration_days = 7
            else:
                duration_days = 30 * duration_months

            # ИСПРАВЛЕНО: Используем переданное соединение вместо создания нового
            # Обрабатываем каждый модуль
            for module_code in modules:
                # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Сначала проверяем, есть ли запись
                cursor = await conn.execute(
                    """
                    SELECT expires_at, is_active FROM module_subscriptions
                    WHERE user_id = ? AND module_code = ?
                    """,
                    (user_id, module_code)
                )
                existing = await cursor.fetchone()

                if existing:
                    # Запись существует - обновляем её
                    existing_expires, is_active = existing

                    try:
                        existing_expires_dt = datetime.fromisoformat(existing_expires)

                        # Если existing_expires_dt naive (без timezone), добавляем UTC
                        if existing_expires_dt.tzinfo is None:
                            existing_expires_dt = existing_expires_dt.replace(tzinfo=timezone.utc)
                    except:
                        existing_expires_dt = datetime.now(timezone.utc)

                    # Если подписка активна и не истекла - продлеваем от текущей даты окончания
                    if is_active and existing_expires_dt > datetime.now(timezone.utc):
                        # Вычисляем новую дату: существующая + новая длительность
                        new_expires_dt = existing_expires_dt + timedelta(days=duration_days)

                        # КРИТИЧНО: Защита от "понижения" подписки
                        # Если новая дата истечения РАНЬШЕ существующей, не меняем подписку
                        # (например, trial НЕ должен перезаписывать package_full)
                        expires_at_dt = datetime.fromisoformat(expires_at)
                        if expires_at_dt.tzinfo is None:
                            expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)

                        # Берем максимальную дату из двух
                        final_expires_dt = max(new_expires_dt, expires_at_dt, existing_expires_dt)
                        new_expires = final_expires_dt.isoformat()

                        # Определяем, нужно ли обновлять plan_id
                        # Обновляем только если новая подписка расширяет существующую
                        update_plan_id = (expires_at_dt > existing_expires_dt)

                        logger.info(f"Extending subscription for user {user_id}, module {module_code}: {existing_expires_dt} -> {final_expires_dt}, update_plan={update_plan_id}")
                    else:
                        # Иначе - устанавливаем новую дату от текущего момента
                        new_expires = expires_at
                        update_plan_id = True  # Для истекших подписок обновляем plan_id
                        logger.info(f"Reactivating expired subscription for user {user_id}, module {module_code}")

                    # Обновляем существующую запись
                    if update_plan_id:
                        await conn.execute(
                            """
                            UPDATE module_subscriptions
                            SET expires_at = ?,
                                plan_id = ?,
                                is_active = 1,
                                created_at = CURRENT_TIMESTAMP
                            WHERE user_id = ? AND module_code = ?
                            """,
                            (new_expires, plan_id, user_id, module_code)
                        )
                    else:
                        # Обновляем только дату, но НЕ plan_id (защита от понижения)
                        await conn.execute(
                            """
                            UPDATE module_subscriptions
                            SET expires_at = ?,
                                is_active = 1
                            WHERE user_id = ? AND module_code = ?
                            """,
                            (new_expires, user_id, module_code)
                        )
                    logger.info(f"✅ Updated subscription for user {user_id}, module {module_code}")

                else:
                    # Записи нет - создаём новую
                    try:
                        await conn.execute(
                            """
                            INSERT INTO module_subscriptions
                            (user_id, module_code, plan_id, expires_at, is_active, created_at)
                            VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                            """,
                            (user_id, module_code, plan_id, expires_at)
                        )
                        logger.info(f"✅ Created new subscription for user {user_id}, module {module_code}")

                    except aiosqlite.IntegrityError as ie:
                        # Race condition: запись появилась между проверкой и вставкой
                        logger.warning(
                            f"⚠️ Race condition detected for user {user_id}, module {module_code}. "
                            f"Retrying with UPDATE..."
                        )

                        # Пытаемся обновить существующую запись
                        await conn.execute(
                            """
                            UPDATE module_subscriptions
                            SET expires_at = ?,
                                plan_id = ?,
                                is_active = 1,
                                created_at = CURRENT_TIMESTAMP
                            WHERE user_id = ? AND module_code = ?
                            """,
                            (expires_at, plan_id, user_id, module_code)
                        )
                        logger.info(f"✅ Updated subscription after race condition for user {user_id}, module {module_code}")

            # Сохраняем историю пробного периода (вне цикла, один раз для всего плана)
            if plan_id == 'trial_7days':
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO trial_history (user_id, trial_activated_at, trial_expires_at)
                    VALUES (?, CURRENT_TIMESTAMP, ?)
                    """,
                    (user_id, expires_at)
                )
                logger.info(f"✅ Marked trial as used for user {user_id}")

            # Сохраняем историю пробного периода учителей
            if plan_id == 'teacher_trial_7days':
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO teacher_trial_history (user_id, used_at, trial_plan)
                    VALUES (?, CURRENT_TIMESTAMP, ?)
                    """,
                    (user_id, plan_id)
                )
                logger.info(f"✅ Marked teacher trial as used for user {user_id}")

            # ИСПРАВЛЕНО: Не делаем commit здесь - он будет выполнен в родительской транзакции

            # ДОБАВЛЕНО: Обработка учительских подписок
            if plan.get('type') == 'teacher':
                logger.info(f"Processing teacher subscription for user {user_id}, plan: {plan_id}")

                try:
                    # КРИТИЧНО: Валидация plan_id перед созданием профиля
                    from payment.config import is_teacher_plan
                    if not is_teacher_plan(plan_id):
                        logger.error(f"❌ Invalid teacher plan_id: {plan_id}. Skipping teacher profile creation.")
                        # Не прерываем - подписка в module_subscriptions уже активирована
                    else:
                        # Импортируем функции для работы с учителями
                        from teacher_mode.services.teacher_service import (
                            get_teacher_profile,
                            create_teacher_profile
                        )

                        # Проверяем, существует ли профиль учителя
                        teacher_profile = await get_teacher_profile(user_id)

                        if not teacher_profile:
                            # Профиль не существует - создаем новый
                            # Получаем имя пользователя из таблицы users
                            # ИСПРАВЛЕНО: Используем переданное соединение
                            cursor = await conn.execute(
                                "SELECT first_name, username FROM users WHERE user_id = ?",
                                (user_id,)
                            )
                            user_data = await cursor.fetchone()

                            if user_data:
                                display_name = user_data[0] or user_data[1] or f"User {user_id}"
                            else:
                                display_name = f"User {user_id}"

                            # ИСПРАВЛЕНО: Передаем существующее соединение для предотвращения database lock
                            # create_teacher_profile будет использовать это соединение вместо создания нового
                            try:
                                teacher_profile = await create_teacher_profile(
                                    user_id=user_id,
                                    display_name=display_name,
                                    subscription_tier=plan_id,
                                    db_connection=conn  # ИСПРАВЛЕНО: Передаем соединение
                                )

                                if teacher_profile:
                                    logger.info(f"✅ Created teacher profile for user {user_id}, code: {teacher_profile.teacher_code}")
                                else:
                                    logger.error(f"❌ Failed to create teacher profile for user {user_id}")
                            except aiosqlite.IntegrityError:
                                # Профиль уже создан другой транзакцией
                                logger.info(f"✅ Teacher profile already exists for user {user_id} (created by concurrent transaction)")
                                teacher_profile = await get_teacher_profile(user_id)

                        # Определяем тип действия для логирования
                        previous_tier = teacher_profile.subscription_tier if teacher_profile else None
                        action = self._determine_subscription_action(previous_tier, plan_id)

                        # ИСПРАВЛЕНО: Обновляем статус подписки в профиле учителя используя переданное соединение
                        try:
                            await conn.execute("""
                                UPDATE teacher_profiles
                                SET has_active_subscription = 1,
                                    subscription_expires = ?,
                                    subscription_tier = ?
                                WHERE user_id = ?
                            """, (expires_at, plan_id, user_id))
                            logger.info(f"✅ Updated teacher subscription status for user {user_id}")

                            # Логируем изменение подписки
                            await self._log_teacher_subscription_change(
                                user_id=user_id,
                                plan_id=plan_id,
                                action=action,
                                previous_tier=previous_tier,
                                new_tier=plan_id,
                                expires_at=expires_at
                            )
                        except Exception as update_error:
                            logger.error(f"❌ Failed to update teacher_profiles: {update_error}")
                            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: НЕ откатываем транзакцию!
                            # Пользователь должен получить модульные подписки даже если профиль учителя не обновился
                            # Отправляем алерт админу, но продолжаем активацию
                            try:
                                from .admin_alerts import notify_admin_payment_activation_failed
                                # Попробуем отправить алерт (может не быть бота в контексте)
                                logger.warning(f"⚠️ Teacher profile update failed but subscription will be activated")
                            except:
                                pass

                except Exception as e:
                    logger.error(f"❌ Error processing teacher subscription for user {user_id}: {e}")
                    import traceback
                    traceback.print_exc()
                    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: НЕ откатываем транзакцию!
                    # Модульные подписки уже созданы и должны работать
                    # Если профиль учителя не создался - это не критично для доступа к модулям
                    logger.warning(
                        f"⚠️ Teacher subscription processing failed for user {user_id}, "
                        f"but module subscriptions are already activated. User will have access."
                    )

            logger.info(
                f"✅ SUCCESS: Plan {plan_id} activated for user {user_id} "
                f"with {len(modules)} modules for {duration_months} month(s)"
            )
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in _activate_standard_plan: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _determine_subscription_action(self, previous_tier: Optional[str], new_tier: str) -> str:
        """
        Определяет тип действия с подпиской на основе предыдущего и нового тарифа.

        Args:
            previous_tier: Предыдущий тариф (None если подписки не было)
            new_tier: Новый тариф

        Returns:
            Тип действия: 'activated', 'renewed', 'upgraded', 'downgraded'
        """
        if previous_tier is None:
            return 'activated'

        if previous_tier == new_tier:
            return 'renewed'

        # Определяем уровни тарифов для сравнения
        tier_levels = {
            'teacher_basic': 1,
            'teacher_standard': 2,
            'teacher_premium': 3
        }

        prev_level = tier_levels.get(previous_tier, 0)
        new_level = tier_levels.get(new_tier, 0)

        if new_level > prev_level:
            return 'upgraded'
        elif new_level < prev_level:
            return 'downgraded'
        else:
            return 'renewed'

    async def _log_teacher_subscription_change(
        self,
        user_id: int,
        plan_id: str,
        action: str,
        previous_tier: Optional[str],
        new_tier: str,
        expires_at: datetime
    ) -> None:
        """
        Логирует изменение подписки учителя в таблицу teacher_subscription_history.

        Args:
            user_id: ID пользователя
            plan_id: ID плана подписки
            action: Тип действия ('activated', 'renewed', 'upgraded', 'downgraded', 'expired', 'cancelled')
            previous_tier: Предыдущий тариф (None для новых подписок)
            new_tier: Новый тариф
            expires_at: Дата истечения подписки
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                await conn.execute("""
                    INSERT INTO teacher_subscription_history
                    (user_id, plan_id, action, previous_tier, new_tier, expires_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, plan_id, action, previous_tier, new_tier, expires_at))
                await conn.commit()
                logger.info(
                    f"✅ Logged teacher subscription change for user {user_id}: "
                    f"{action} ({previous_tier} → {new_tier})"
                )
        except Exception as e:
            # Не прерываем работу, если логирование не удалось
            logger.error(f"❌ Failed to log teacher subscription change for user {user_id}: {e}")

    async def _rollback_teacher_subscription(self, user_id: int, plan_id: str) -> None:
        """
        Откатывает активацию подписки учителя в случае ошибки обновления teacher_profiles.

        Args:
            user_id: ID пользователя
            plan_id: ID плана подписки

        Raises:
            Exception: Если не удалось откатить изменения
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Деактивируем все модули для этого плана
                await conn.execute(
                    """
                    UPDATE module_subscriptions
                    SET is_active = 0
                    WHERE user_id = ? AND plan_id = ?
                    """,
                    (user_id, plan_id)
                )
                await conn.commit()
                logger.info(f"✅ Successfully rolled back module_subscriptions for user {user_id}, plan {plan_id}")
        except Exception as e:
            logger.error(f"❌ Failed to rollback module_subscriptions for user {user_id}: {e}")
            raise


    # Дополнительная функция для исправления существующих неполных подписок
    async def fix_incomplete_trial_subscriptions(self):
        """
        Исправляет существующие пробные подписки, у которых активированы не все модули.
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # Находим всех пользователей с trial_7days
                cursor = await conn.execute(
                    """
                    SELECT DISTINCT user_id, MAX(expires_at) as expires_at 
                    FROM module_subscriptions 
                    WHERE plan_id = 'trial_7days' AND is_active = 1
                    GROUP BY user_id
                    """
                )
                trial_users = await cursor.fetchall()
                
                if not trial_users:
                    logger.info("No active trial subscriptions found")
                    return
                
                # Получаем правильный список модулей для trial
                trial_plan = SUBSCRIPTION_PLANS.get('trial_7days')
                if not trial_plan:
                    logger.error("trial_7days plan not found in config")
                    return
                
                correct_modules = trial_plan.get('modules', [])
                logger.info(f"Correct modules for trial: {correct_modules}")
                
                fixed_count = 0
                for user_id, expires_at in trial_users:
                    # Проверяем какие модули уже есть
                    cursor = await conn.execute(
                        """
                        SELECT module_code FROM module_subscriptions 
                        WHERE user_id = ? AND plan_id = 'trial_7days' AND is_active = 1
                        """,
                        (user_id,)
                    )
                    existing_modules = [row[0] for row in await cursor.fetchall()]
                    
                    # Находим недостающие модули
                    missing_modules = set(correct_modules) - set(existing_modules)
                    
                    if missing_modules:
                        logger.info(f"User {user_id} missing modules: {missing_modules}")
                        
                        # Добавляем недостающие модули
                        for module_code in missing_modules:
                            await conn.execute(
                                """
                                INSERT OR REPLACE INTO module_subscriptions 
                                (user_id, module_code, plan_id, expires_at, is_active, created_at)
                                VALUES (?, ?, 'trial_7days', ?, 1, CURRENT_TIMESTAMP)
                                """,
                                (user_id, module_code, expires_at)
                            )
                        
                        fixed_count += 1
                        logger.info(f"Fixed trial subscription for user {user_id}")
                
                await conn.commit()
                logger.info(f"Fixed {fixed_count} incomplete trial subscriptions")
                
        except Exception as e:
            logger.error(f"Error fixing trial subscriptions: {e}")
            import traceback
            traceback.print_exc()

    async def _activate_custom_modules(self, conn, user_id: int, plan_id: str,
                                      duration_months: int, metadata: dict) -> bool:
        """
        Активирует кастомные модули для пользователя.
        Работает с модулями в формате module_* из конфигурации.

        Args:
            conn: Существующее соединение с БД (для использования в транзакции)
            user_id: ID пользователя
            plan_id: ID плана подписки
            duration_months: Длительность подписки в месяцах
            metadata: Метаданные с информацией о модулях
        """
        try:
            from datetime import datetime, timedelta
            
            # Получаем список модулей из metadata или из plan_id
            modules = metadata.get('modules', [])
            
            # Если модули не в metadata, извлекаем из plan_id
            if not modules:
                modules = self._extract_modules_from_plan_id(plan_id)
            
            # Правильно парсим модули в зависимости от типа
            if isinstance(modules, str):
                if ',' in modules:
                    modules = [m.strip() for m in modules.split(',') if m.strip()]
                elif '_' in modules:
                    # Для строк вида "testpart_task19"
                    temp_modules = []
                    parts = modules.split('_')
                    i = 0
                    while i < len(parts):
                        if parts[i] == 'test' and i + 1 < len(parts) and parts[i + 1] == 'part':
                            temp_modules.append('test_part')
                            i += 2
                        elif parts[i] == 'testpart':
                            temp_modules.append('test_part')
                            i += 1
                        elif parts[i].startswith('task'):
                            temp_modules.append(parts[i])
                            i += 1
                        else:
                            temp_modules.append(parts[i])
                            i += 1
                    modules = temp_modules
                else:
                    modules = [modules]
            elif not isinstance(modules, list):
                logger.error(f"Invalid modules format: {type(modules)}")
                return False
            
            # Нормализуем названия модулей
            # Динамически генерируем маппинг из ALL_PAID_MODULES
            module_mapping = {}
            for mod in ALL_PAID_MODULES:
                module_mapping[mod] = mod  # task19 -> task19
                module_mapping[f'module_{mod}'] = mod  # module_task19 -> task19
            # Дополнительные алиасы
            module_mapping['testpart'] = 'test_part'
            module_mapping['test'] = 'test_part'
            module_mapping['module_testpart'] = 'test_part'
            
            normalized_modules = []
            for module in modules:
                module_lower = module.lower().strip()
                if module_lower in module_mapping:
                    normalized = module_mapping[module_lower]
                    if normalized not in normalized_modules:
                        normalized_modules.append(normalized)
                    logger.info(f"Module {module} normalized to {normalized}")
                else:
                    # Если не нашли в маппинге, пробуем убрать префикс module_
                    if module_lower.startswith('module_'):
                        clean_module = module_lower[7:]  # Убираем 'module_'
                        if clean_module in module_mapping:
                            normalized = module_mapping[clean_module]
                            if normalized not in normalized_modules:
                                normalized_modules.append(normalized)
                            logger.info(f"Module {module} normalized to {normalized}")
                        else:
                            logger.warning(f"Unknown module after removing prefix: {clean_module}")
                    else:
                        logger.warning(f"Unknown module: {module}")
            
            if not normalized_modules:
                logger.error(f"No valid modules found in {modules}")
                return False
            
            logger.info(f"Final normalized modules: {normalized_modules}")

            # ИСПРАВЛЕНИЕ: Рассчитываем дату истечения правильно
            # Для кастомных планов используем стандартный расчет (30 дней * месяцы)
            # Добавляем timezone для консистентности
            expires_at = datetime.now(timezone.utc) + timedelta(days=30 * duration_months)

            # ИСПРАВЛЕНО: Используем переданное соединение вместо создания нового
            for module_code in normalized_modules:
                # Проверяем существующую запись
                cursor = await conn.execute(
                    """
                    SELECT expires_at, is_active FROM module_subscriptions
                    WHERE user_id = ? AND module_code = ?
                    """,
                    (user_id, module_code)
                )
                existing = await cursor.fetchone()

                if existing:
                    existing_expires, is_active = existing
                    existing_expires_dt = datetime.fromisoformat(existing_expires)

                    # Если подписка активна и еще не истекла - продлеваем от нее
                    if is_active and existing_expires_dt > datetime.now(timezone.utc):
                        new_expires = existing_expires_dt + timedelta(days=30 * duration_months)
                    else:
                        new_expires = expires_at

                    # Обновляем существующую запись
                    await conn.execute(
                        """
                        UPDATE module_subscriptions
                        SET expires_at = ?,
                            plan_id = ?,
                            is_active = 1,
                            created_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND module_code = ?
                        """,
                        (new_expires.isoformat(), plan_id, user_id, module_code)
                    )
                    logger.info(f"Updated subscription for user {user_id}, module {module_code}")
                else:
                    # Создаем новую запись
                    try:
                        await conn.execute(
                            """
                            INSERT INTO module_subscriptions (
                                user_id, module_code, plan_id, expires_at,
                                is_active, created_at
                            ) VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                            """,
                            (user_id, module_code, plan_id, expires_at.isoformat())
                        )
                        logger.info(f"Created subscription for user {user_id}, module {module_code}")
                    except aiosqlite.IntegrityError:
                        # На случай race condition
                        logger.warning(f"Race condition for user {user_id}, module {module_code}. Using UPDATE.")
                        await conn.execute(
                            """
                            UPDATE module_subscriptions
                            SET expires_at = ?,
                                plan_id = ?,
                                is_active = 1,
                                created_at = CURRENT_TIMESTAMP
                            WHERE user_id = ? AND module_code = ?
                            """,
                            (expires_at.isoformat(), plan_id, user_id, module_code)
                        )

            # ИСПРАВЛЕНО: Не делаем commit здесь - он будет выполнен в родительской транзакции
            
            logger.info(f"Successfully activated {len(normalized_modules)} modules for user {user_id}: {normalized_modules}")
            return True
            
        except Exception as e:
            logger.error(f"Error activating custom modules: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def init_database(self):
        """Инициализирует базу данных с поддержкой автопродления."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # Существующие таблицы
                await self._create_existing_tables(conn)
                
                # НОВОЕ: Таблицы для автопродления
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS auto_renewal_settings (
                        user_id INTEGER PRIMARY KEY,
                        enabled BOOLEAN DEFAULT 0,
                        payment_method TEXT CHECK(payment_method IN ('card', 'recurrent')),
                        recurrent_token TEXT,
                        next_renewal_date TIMESTAMP,
                        failures_count INTEGER DEFAULT 0,
                        last_renewal_attempt TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS auto_renewal_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        plan_id TEXT NOT NULL,
                        payment_id TEXT,
                        order_id TEXT,
                        status TEXT CHECK(status IN ('success', 'failed', 'pending')),
                        amount INTEGER,
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Добавляем индексы
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_auto_renewal_next_date 
                    ON auto_renewal_settings(next_renewal_date)
                """)
                
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_renewal_history_user 
                    ON auto_renewal_history(user_id, created_at)
                """)
                
                await conn.commit()
                logger.info("Database initialized with auto-renewal support")
                
        except Exception as e:
            logger.exception(f"Error initializing database: {e}")

    async def save_rebill_id(self, user_id: int, order_id: str, rebill_id: str):
        """Сохраняет RebillId для рекуррентных платежей.
        
        Args:
            user_id: ID пользователя
            order_id: ID заказа
            rebill_id: Токен для рекуррентных платежей
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # Обновляем RebillId в payments
                await conn.execute("""
                    UPDATE payments 
                    SET rebill_id = ?
                    WHERE order_id = ?
                """, (rebill_id, order_id))
                
                # Сохраняем в auto_renewal_settings
                await conn.execute("""
                    INSERT OR REPLACE INTO auto_renewal_settings
                    (user_id, enabled, payment_method, recurrent_token, last_renewal_attempt, failures_count)
                    VALUES (?, 1, 'recurrent', ?, CURRENT_TIMESTAMP, 0)
                """, (user_id, rebill_id))
                
                await conn.commit()
                logger.info(f"Saved RebillId for user {user_id}, order {order_id}")
                
        except Exception as e:
            logger.error(f"Error saving rebill_id: {e}")

    async def enable_auto_renewal(self, user_id: int, payment_method: str = 'recurrent', 
                                  recurrent_token: str = None) -> bool:
        """Включает автопродление для пользователя.
        
        Args:
            user_id: ID пользователя
            payment_method: Метод оплаты ('recurrent' или 'card')
            recurrent_token: Токен для рекуррентных платежей
            
        Returns:
            bool: True если успешно включено
        """
        try:
            from datetime import datetime, timedelta, timezone
            
            # Получаем дату следующего продления
            subscription = await self.get_active_subscription(user_id)
            if subscription:
                if isinstance(subscription, dict):
                    next_renewal = subscription.get('expires_at')
                else:
                    next_renewal = subscription.expires_at if hasattr(subscription, 'expires_at') else None
            else:
                # Если нет активной подписки, ставим дату через месяц
                next_renewal = datetime.now(timezone.utc) + timedelta(days=30)
            
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO auto_renewal_settings
                    (user_id, enabled, payment_method, recurrent_token, next_renewal_date, failures_count)
                    VALUES (?, 1, ?, ?, ?, 0)
                """, (user_id, payment_method, recurrent_token, next_renewal))
                await conn.commit()
                
                logger.info(f"Auto-renewal enabled for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error enabling auto-renewal: {e}")
            return False
    
    async def disable_auto_renewal(self, user_id: int) -> bool:
        """Отключает автопродление для пользователя."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    UPDATE auto_renewal_settings 
                    SET enabled = 0, created_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (user_id,))
                
                await conn.commit()
                logger.info(f"Auto-renewal disabled for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error disabling auto-renewal: {e}")
            return False
    
    async def process_auto_renewal(self, user_id: int) -> bool:
        """Обрабатывает автопродление подписки."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # Получаем настройки автопродления
                cursor = await conn.execute("""
                    SELECT enabled, payment_method, recurrent_token, card_id 
                    FROM auto_renewal_settings 
                    WHERE user_id = ? AND enabled = 1
                """, (user_id,))
                
                settings = await cursor.fetchone()
                if not settings:
                    logger.info(f"Auto-renewal not enabled for user {user_id}")
                    return False
                
                enabled, payment_method, recurrent_token, card_id = settings
                
                # Получаем информацию о текущей подписке
                subscription = await self.check_active_subscription(user_id)
                if not subscription:
                    # Подписка истекла, пытаемся продлить
                    
                    # Здесь должна быть интеграция с Tinkoff API для рекуррентного платежа
                    # Пример структуры:
                    success = await self._process_recurrent_payment(
                        user_id, 
                        recurrent_token,
                        subscription.get('plan_id'),
                        subscription.get('amount', 0)
                    )
                    
                    if success:
                        # Генерируем уникальный ID для этой транзакции
                        auto_transaction_id = f"AUTO_{user_id}_{datetime.now().timestamp()}"

                        # Записываем успешное продление (ИСПРАВЛЕНО: добавлен order_id)
                        await conn.execute("""
                            INSERT INTO auto_renewal_history
                            (user_id, plan_id, payment_id, order_id, status, amount)
                            VALUES (?, ?, ?, ?, 'success', ?)
                        """, (user_id, subscription['plan_id'],
                              auto_transaction_id,  # payment_id
                              auto_transaction_id,  # order_id (тот же ID)
                              subscription['amount']))
                        
                        # Обновляем дату следующего продления
                        next_date = datetime.now(timezone.utc) + timedelta(days=30)
                        await conn.execute("""
                            UPDATE auto_renewal_settings 
                            SET next_renewal_date = ?, failures_count = 0, 
                                last_renewal_attempt = CURRENT_TIMESTAMP 
                            WHERE user_id = ?
                        """, (next_date, user_id))
                    else:
                        # Записываем неудачную попытку
                        await conn.execute("""
                            UPDATE auto_renewal_settings 
                            SET failures_count = failures_count + 1, 
                                last_renewal_attempt = CURRENT_TIMESTAMP 
                            WHERE user_id = ?
                        """, (user_id,))
                        
                        # Если 3 неудачные попытки - отключаем автопродление
                        cursor = await conn.execute(
                            "SELECT failures_count FROM auto_renewal_settings WHERE user_id = ?",
                            (user_id,)
                        )
                        failures = await cursor.fetchone()
                        if failures and failures[0] >= 3:
                            await self.disable_auto_renewal(user_id)
                            # Уведомляем пользователя
                            return False
                    
                    await conn.commit()
                    return success
                    
                return True
                
        except Exception as e:
            logger.error(f"Error processing auto-renewal: {e}")
            return False
    
    async def _process_recurrent_payment(self, user_id: int, recurrent_token: str, 
                                        plan_id: str, amount: int) -> bool:
        """Обрабатывает рекуррентный платеж через Tinkoff API."""
        try:
            from .tinkoff_api import TinkoffAPI
            
            api = TinkoffAPI()
            
            # Создаем рекуррентный платеж
            payment_data = {
                'Amount': amount * 100,  # В копейках
                'OrderId': f"AUTO_{user_id}_{datetime.now().timestamp()}",
                'Description': f'Автопродление подписки {plan_id}',
                'CustomerKey': str(user_id),
                'Recurrent': 'Y',
                'RebillId': recurrent_token
            }
            
            result = await api.init_recurrent_payment(payment_data)
            
            if result.get('Success'):
                payment_id = result.get('PaymentId')
                
                # Подтверждаем платеж
                confirm_result = await api.confirm_payment(payment_id)
                
                if confirm_result.get('Status') == 'CONFIRMED':
                    # Активируем подписку
                    await self.activate_subscription(
                        f"AUTO_{user_id}_{datetime.now().timestamp()}",
                        user_id,
                        plan_id
                    )
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Recurrent payment error: {e}")
            return False
    
    # ============= УВЕДОМЛЕНИЯ =============
    
    async def get_expiring_subscriptions(self, days_before: int) -> List[Dict]:
        """Получает список подписок, истекающих через указанное количество дней."""
        try:
            check_date = datetime.now(timezone.utc) + timedelta(days=days_before)
            check_date_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
            check_date_end = check_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                conn.row_factory = aiosqlite.Row
                
                if self.subscription_mode == 'modular':
                    # Для модульной системы
                    cursor = await conn.execute("""
                        SELECT DISTINCT user_id, MIN(expires_at) as expires_at, 
                               GROUP_CONCAT(module_code) as modules
                        FROM module_subscriptions
                        WHERE is_active = 1 
                        AND expires_at BETWEEN ? AND ?
                        GROUP BY user_id
                    """, (check_date_start, check_date_end))
                else:
                    # Для единой системы
                    cursor = await conn.execute("""
                        SELECT user_id, plan_id, expires_at
                        FROM user_subscriptions
                        WHERE status = 'active'
                        AND expires_at BETWEEN ? AND ?
                    """, (check_date_start, check_date_end))
                
                results = await cursor.fetchall()
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Error getting expiring subscriptions: {e}")
            return []

    async def deactivate_expired_subscription(self, user_id: int) -> bool:
        """Деактивирует истекшую подписку пользователя."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                if self.subscription_mode == 'modular':
                    # Сначала проверяем, какие модули истекли
                    cursor = await conn.execute("""
                        SELECT plan_id FROM module_subscriptions
                        WHERE user_id = ?
                        AND is_active = 1
                        AND expires_at <= datetime('now')
                    """, (user_id,))
                    expired_plans = [row[0] for row in await cursor.fetchall()]

                    # Деактивируем все истекшие модули
                    await conn.execute("""
                        UPDATE module_subscriptions
                        SET is_active = 0
                        WHERE user_id = ?
                        AND is_active = 1
                        AND expires_at <= datetime('now')
                    """, (user_id,))

                    # ДОБАВЛЕНО: Проверяем, истекла ли учительская подписка
                    from payment.config import is_teacher_plan
                    teacher_plan_expired = any(is_teacher_plan(plan) for plan in expired_plans)

                    if teacher_plan_expired:
                        # Проверяем, остались ли активные учительские подписки
                        cursor = await conn.execute("""
                            SELECT plan_id FROM module_subscriptions
                            WHERE user_id = ? AND is_active = 1
                        """, (user_id,))
                        active_plans = [row[0] for row in await cursor.fetchall()]

                        # Проверяем, есть ли среди активных хотя бы один учительский план
                        has_active_teacher_plan = any(is_teacher_plan(plan) for plan in active_plans)

                        if not has_active_teacher_plan:
                            # Нет активных учительских подписок - обновляем профиль
                            await conn.execute("""
                                UPDATE teacher_profiles
                                SET has_active_subscription = 0
                                WHERE user_id = ?
                            """, (user_id,))
                            logger.info(f"Deactivated teacher subscription for user {user_id}")
                else:
                    # Деактивируем подписку в единой системе
                    await conn.execute("""
                        UPDATE user_subscriptions
                        SET status = 'expired'
                        WHERE user_id = ?
                        AND status = 'active'
                        AND expires_at <= datetime('now')
                    """, (user_id,))

                await conn.commit()
                logger.info(f"Deactivated expired subscription for user {user_id}")
                return True

        except Exception as e:
            logger.error(f"Error deactivating expired subscription for user {user_id}: {e}")
            return False

    async def has_notification_sent(self, user_id: int, notification_type: str,
                                   subscription_end: datetime) -> bool:
        """Проверяет, было ли уже отправлено уведомление."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                cursor = await conn.execute("""
                    SELECT 1 FROM subscription_notifications
                    WHERE user_id = ? 
                    AND notification_type = ?
                    AND DATE(subscription_end_date) = DATE(?)
                """, (user_id, notification_type, subscription_end))
                
                return await cursor.fetchone() is not None
                
        except Exception as e:
            logger.error(f"Error checking notification: {e}")
            return False
    
    async def mark_notification_sent(self, user_id: int, notification_type: str, 
                                    subscription_end: datetime):
        """Отмечает уведомление как отправленное."""
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                await conn.execute("""
                    INSERT OR IGNORE INTO subscription_notifications
                    (user_id, notification_type, subscription_end_date)
                    VALUES (?, ?, ?)
                """, (user_id, notification_type, subscription_end))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error marking notification: {e}")

    async def _activate_unified_subscription(self, user_id: int, plan_id: str, 
                                                 payment_id: str, duration_months: int = 1):
        """Расширенная активация единой подписки с учетом срока."""
        from datetime import datetime, timedelta, timezone
        
        duration_days = 30 * duration_months
        expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
        
        async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
            # Проверяем существующую активную подписку
            cursor = await conn.execute(
                """
                SELECT expires_at FROM user_subscriptions 
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,)
            )
            existing = await cursor.fetchone()
            
            if existing:
                existing_expires = datetime.fromisoformat(existing[0])
                if existing_expires > datetime.now(timezone.utc):
                    # Продлеваем от существующей даты
                    expires_at = existing_expires + timedelta(days=duration_days)
                
                # Деактивируем старую подписку
                await conn.execute(
                    "UPDATE user_subscriptions SET status = 'replaced' WHERE user_id = ? AND status = 'active'",
                    (user_id,)
                )
            
            # Создаем новую запись о подписке
            await conn.execute(
                """
                INSERT INTO user_subscriptions 
                (user_id, plan_id, payment_id, status, expires_at, activated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (user_id, plan_id, payment_id, expires_at, datetime.now(timezone.utc))
            )
            await conn.commit()
            logger.info(f"Unified subscription activated for {duration_months} months until {expires_at}")

    
    async def _activate_modular_subscription(self, user_id: int, plan_id: str,
                                                payment_id: str, duration_months: int = 1):
        """Расширенная активация модульной подписки с учетом срока."""
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            raise ValueError(f"Unknown plan: {plan_id}")

        # НОВОЕ: Проверяем тип плана
        plan_type = plan.get('type', 'module')

        # Если это plan учителя, активируем teacher подписку
        if plan_type == 'teacher':
            await self._activate_teacher_subscription(user_id, plan_id, duration_months)
            logger.info(f"Teacher subscription activated for user {user_id}, plan {plan_id}")

        # Активируем модули (для teacher планов это дает учителю доступ к заданиям для личной тренировки)
        modules = plan.get('modules', [])
        duration_days = 30 * duration_months
        expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
        
        async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
            for module_code in modules:
                # Проверяем ЛЮБУЮ существующую подписку (активную или неактивную)
                cursor = await conn.execute(
                    """
                    SELECT expires_at, is_active FROM module_subscriptions 
                    WHERE user_id = ? AND module_code = ?
                    """,
                    (user_id, module_code)
                )
                existing = await cursor.fetchone()
                
                if existing:
                    existing_expires, is_active = existing
                    existing_expires_dt = datetime.fromisoformat(existing_expires)

                    # Если existing_expires_dt naive (без timezone), добавляем UTC
                    if existing_expires_dt.tzinfo is None:
                        existing_expires_dt = existing_expires_dt.replace(tzinfo=timezone.utc)

                    # Если подписка активна и еще не истекла - продлеваем от нее
                    if is_active and existing_expires_dt > datetime.now(timezone.utc):
                        new_expires = existing_expires_dt + timedelta(days=duration_days)
                    else:
                        # Иначе - от текущей даты
                        new_expires = expires_at
                    
                    # Обновляем существующую запись
                    await conn.execute(
                        """
                        UPDATE module_subscriptions 
                        SET expires_at = ?, 
                            plan_id = ?, 
                            is_active = 1,
                            created_at = CURRENT_TIMESTAMP 
                        WHERE user_id = ? AND module_code = ?
                        """,
                        (new_expires, plan_id, user_id, module_code)
                    )
                    logger.info(f"Updated existing subscription for user {user_id}, module {module_code}")
                else:
                    # Создаем новую подписку только если записи вообще нет
                    try:
                        await conn.execute(
                            """
                            INSERT INTO module_subscriptions 
                            (user_id, module_code, plan_id, expires_at, is_active, created_at)
                            VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                            """,
                            (user_id, module_code, plan_id, expires_at)
                        )
                        logger.info(f"Created new subscription for user {user_id}, module {module_code}")
                    except aiosqlite.IntegrityError:
                        # На случай race condition - если запись появилась между проверкой и вставкой
                        logger.warning(f"Race condition detected for user {user_id}, module {module_code}. Trying UPDATE.")
                        await conn.execute(
                            """
                            UPDATE module_subscriptions 
                            SET expires_at = ?, 
                                plan_id = ?, 
                                is_active = 1,
                                created_at = CURRENT_TIMESTAMP 
                            WHERE user_id = ? AND module_code = ?
                            """,
                            (expires_at, plan_id, user_id, module_code)
                        )
            
            await conn.commit()
            logger.info(f"Modular subscription activated for {duration_months} months for user {user_id}")

    async def _activate_teacher_subscription(self, user_id: int, plan_id: str, duration_months: int = 1):
        """
        Активирует подписку учителя в таблице teacher_profiles.

        Args:
            user_id: ID пользователя-учителя
            plan_id: ID плана (teacher_basic, teacher_standard, teacher_premium)
            duration_months: Длительность подписки в месяцах
        """
        duration_days = 30 * duration_months
        expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)

        async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
            # Проверяем, существует ли teacher_profile
            cursor = await conn.execute(
                "SELECT user_id, subscription_expires FROM teacher_profiles WHERE user_id = ?",
                (user_id,)
            )
            existing = await cursor.fetchone()

            if existing:
                # Teacher profile существует - обновляем подписку
                existing_expires_str = existing[1]

                # Если есть активная подписка, продлеваем от её даты окончания
                if existing_expires_str:
                    try:
                        existing_expires_dt = datetime.fromisoformat(existing_expires_str)
                        if existing_expires_dt.tzinfo is None:
                            existing_expires_dt = existing_expires_dt.replace(tzinfo=timezone.utc)

                        # Если подписка еще не истекла, продлеваем от нее
                        if existing_expires_dt > datetime.now(timezone.utc):
                            expires_at = existing_expires_dt + timedelta(days=duration_days)
                            logger.info(f"Extending teacher subscription from {existing_expires_dt} to {expires_at}")
                    except Exception as e:
                        logger.warning(f"Error parsing existing expires_at: {e}, using new date")

                # Обновляем подписку
                await conn.execute(
                    """
                    UPDATE teacher_profiles
                    SET has_active_subscription = 1,
                        subscription_tier = ?,
                        subscription_expires = ?
                    WHERE user_id = ?
                    """,
                    (plan_id, expires_at.isoformat(), user_id)
                )
                logger.info(f"Updated teacher subscription for user {user_id}")
                action = 'renewed'
            else:
                # Teacher profile не существует - нужно создать
                # Генерируем уникальный teacher_code через безопасную функцию
                from teacher_mode.services.teacher_service import generate_teacher_code

                # Проверяем уникальность кода
                teacher_code = generate_teacher_code()
                while True:
                    cursor = await conn.execute(
                        "SELECT user_id FROM teacher_profiles WHERE teacher_code = ?",
                        (teacher_code,)
                    )
                    if not await cursor.fetchone():
                        break
                    teacher_code = generate_teacher_code()

                # Получаем имя пользователя
                cursor = await conn.execute(
                    "SELECT first_name, last_name FROM users WHERE user_id = ?",
                    (user_id,)
                )
                user_row = await cursor.fetchone()

                if user_row:
                    first_name, last_name = user_row
                    display_name = f"{first_name or ''} {last_name or ''}".strip() or "Учитель"
                else:
                    display_name = "Учитель"

                # ИСПРАВЛЕНО: Добавляем роль teacher перед созданием профиля
                await conn.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, 'teacher')",
                    (user_id,)
                )

                # Создаем teacher_profile с временной меткой для поля created_at
                # datetime и timezone уже импортированы в начале файла
                now = datetime.now(timezone.utc)

                await conn.execute(
                    """
                    INSERT INTO teacher_profiles
                    (user_id, teacher_code, display_name, has_active_subscription,
                     subscription_tier, subscription_expires, created_at, feedback_settings)
                    VALUES (?, ?, ?, 1, ?, ?, ?, '{}')
                    """,
                    (user_id, teacher_code, display_name, plan_id, expires_at.isoformat(), now.isoformat())
                )
                logger.info(f"Created teacher profile for user {user_id} with code {teacher_code}")
                action = 'activated'

            # Добавляем запись в историю
            await conn.execute(
                """
                INSERT INTO teacher_subscription_history
                (user_id, plan_id, action, new_tier, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, plan_id, action, plan_id, expires_at.isoformat())
            )

            await conn.commit()
            logger.info(
                f"Teacher subscription {action} for user {user_id}: "
                f"plan={plan_id}, expires={expires_at.isoformat()}"
            )

    async def has_used_trial(self, user_id: int) -> bool:
        """Проверяет, использовал ли пользователь пробный период."""
        if SUBSCRIPTION_MODE != 'modular':
            return False
        
        try:
            async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
                cursor = await conn.execute(
                    "SELECT 1 FROM trial_history WHERE user_id = ?",
                    (user_id,)
                )
                return await cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking trial history: {e}")
            return False
    
    async def get_user_modules(self, user_id: int) -> List[Dict[str, Any]]:
        """Получает информацию о модулях пользователя."""
        if SUBSCRIPTION_MODE != 'modular':
            subscription = await self._check_unified_subscription(user_id)
            if subscription:
                modules = get_plan_modules(subscription['plan_id'])
                return [
                    {
                        'module_code': module,
                        'expires_at': subscription['expires_at'],
                        'plan_id': subscription['plan_id']
                    }
                    for module in modules
                ]
            return []
        
        try:
            async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as conn:
                cursor = await conn.execute(
                    """
                    SELECT module_code, plan_id, expires_at, is_trial
                    FROM module_subscriptions
                    WHERE user_id = ? AND is_active = 1 AND expires_at > ?
                    ORDER BY module_code, expires_at DESC
                    """,
                    (user_id, datetime.now(timezone.utc))
                )
                modules = await cursor.fetchall()
                
                # Группируем по модулям
                module_dict = {}
                for row in modules:
                    module_code = row[0]
                    if module_code not in module_dict:
                        module_dict[module_code] = {
                            'module_code': module_code,
                            'expires_at': datetime.fromisoformat(row[2]),
                            'plan_id': row[1],
                            'is_trial': bool(row[3])
                        }
                
                return list(module_dict.values())
        except Exception as e:
            logger.error(f"Error getting user modules: {e}")
            return []
    
    async def get_payment_by_order_id(self, order_id: str) -> Optional[dict]:
            """
            Получает информацию о платеже по order_id.
            
            Args:
                order_id: ID заказа
                
            Returns:
                Словарь с информацией о платеже или None
            """
            try:
                async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                    # ВАЖНО: Используем amount_kopecks, а не amount
                    cursor = await conn.execute(
                        """
                        SELECT 
                            payment_id, user_id, plan_id, 
                            amount_kopecks, status, metadata,
                            created_at, completed_at
                        FROM payments 
                        WHERE order_id = ?
                        """,
                        (order_id,)
                    )
                    
                    row = await cursor.fetchone()
                    
                    if row:
                        payment_id, user_id, plan_id, amount_kopecks, status, metadata_str, created_at, completed_at = row
                        
                        # Парсим metadata
                        try:
                            metadata = json.loads(metadata_str) if metadata_str else {}
                        except:
                            metadata = {}
                        
                        return {
                            'payment_id': payment_id,
                            'order_id': order_id,
                            'user_id': user_id,
                            'plan_id': plan_id,
                            'amount_kopecks': amount_kopecks,
                            'amount_rub': amount_kopecks / 100 if amount_kopecks else 0,
                            'status': status,
                            'metadata': metadata,
                            'created_at': created_at,
                            'completed_at': completed_at
                        }
                    
                    return None
                    
            except Exception as e:
                logger.error(f"Error getting payment by order_id: {e}")
                return None

    async def has_used_teacher_trial(self, user_id: int) -> bool:
        """
        Проверяет, использовал ли пользователь пробный период учителя.

        Args:
            user_id: ID пользователя

        Returns:
            bool: True если пробный период уже использован
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) FROM teacher_trial_history
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )
                result = await cursor.fetchone()
                return result[0] > 0 if result else False

        except Exception as e:
            logger.error(f"Error checking teacher trial usage: {e}")
            # При ошибке считаем, что триал использован (безопасная стратегия)
            return True

    async def update_payment_status(self, order_id: str, status: str) -> bool:
        """Обновляет статус платежа.

        Args:
            order_id: ID заказа
            status: Новый статус ('pending', 'completed', 'failed', 'cancelled')

        Returns:
            bool: True если успешно обновлено
        """
        try:
            async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
                # ИСПРАВЛЕНИЕ: обновляем completed_at вместо created_at
                # created_at должна хранить время создания заказа, а не время изменения статуса
                await conn.execute("""
                    UPDATE payments
                    SET status = ?,
                        completed_at = CASE
                            WHEN ? IN ('completed', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP
                            ELSE completed_at
                        END
                    WHERE order_id = ?
                """, (status, status, order_id))
                await conn.commit()

                logger.info(f"Updated payment status for {order_id}: {status}")
                return True

        except Exception as e:
            logger.error(f"Error updating payment status: {e}")
            return False

def requires_subscription(module_code: Optional[str] = None):
    """
    Декоратор для проверки подписки.
    
    Использование:
    @requires_subscription()  # Проверка любой активной подписки
    @requires_subscription('task24')  # Проверка доступа к конкретному модулю
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update, context):
            user_id = update.effective_user.id
            
            # Получаем менеджер из контекста
            subscription_manager = context.bot_data.get('subscription_manager')
            if not subscription_manager:
                subscription_manager = SubscriptionManager()
            
            # Проверяем подписку
            if module_code:
                # Проверка доступа к конкретному модулю
                has_access = await subscription_manager.check_module_access(user_id, module_code)
                if not has_access:
                    await update.message.reply_text(
                        f"🔒 Для доступа к этой функции необходима подписка.\n\n"
                        f"Используйте /subscribe для оформления."
                    )
                    return
            else:
                # Проверка любой активной подписки
                subscription = await subscription_manager.check_active_subscription(user_id)
                if not subscription:
                    await update.message.reply_text(
                        "🔒 Для использования бота необходима подписка.\n\n"
                        "Используйте /subscribe для оформления."
                    )
                    return
            
            # Выполняем оригинальную функцию
            return await func(update, context)
        
        return wrapper
    return decorator