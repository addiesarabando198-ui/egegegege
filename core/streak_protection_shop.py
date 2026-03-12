"""
Streak Protection Shop - магазин защит для стриков

Phase 3: Protection Mechanics
- Покупка Freeze (заморозка стрика) - 49₽
- Покупка Repair (восстановление стрика) - 99-249₽
- Покупка Error Shield (щит от ошибок) - 29₽
- Интеграция с Tinkoff платежами
"""

import logging
import aiosqlite
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, Application
from telegram.constants import ParseMode

from core.db import DATABASE_FILE
from core.streak_manager import get_streak_manager, StreakState

logger = logging.getLogger(__name__)


class StreakProtectionShop:
    """Магазин защит для стриков"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        self.streak_manager = get_streak_manager()

        # Цены на защиты
        self.FREEZE_PRICE = 49  # Заморозка на 1 день
        self.ERROR_SHIELD_PRICE = 29  # Щит от 1 ошибки
        self.REPAIR_BASE_PRICE = 99  # Базовая цена восстановления

    # ============================================================
    # SHOP UI
    # ============================================================

    async def show_shop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показывает главный экран магазина защит"""
        query = update.callback_query
        if query:
            await query.answer()

        user_id = update.effective_user.id

        try:
            # Получаем информацию о текущих стриках и защитах
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT
                        current_daily_streak,
                        streak_state,
                        freeze_count,
                        error_shield_count
                    FROM user_streaks
                    WHERE user_id = ?
                """, (user_id,))

                row = await cursor.fetchone()

                if row:
                    current_streak, state, freeze_count, shield_count = row
                else:
                    current_streak, state, freeze_count, shield_count = 0, 'active', 0, 0

            # Проверяем, можно ли восстановить стрик
            can_repair = await self._can_repair_streak(user_id)
            repair_price = await self._calculate_repair_price(user_id)

            text = f"""
🛡️ <b>Магазин защит стрика</b>

<b>Твой текущий стрик:</b> 🔥 {current_streak} дней
<b>У тебя есть:</b>
  ❄️ Заморозки: {freeze_count}
  🛡️ Щиты от ошибок: {shield_count}

━━━━━━━━━━━━━━━━━━━━

<b>💎 Доступные защиты:</b>

<b>1. ❄️ Заморозка стрика</b> - 49₽
Пропусти один день без потери стрика.
• Автоматически активируется при пропуске
• Можно накапливать
• Бесплатные заморозки: за 7, 30, 60 дней

<b>2. 🛡️ Щит от ошибок</b> - 29₽
Защита от неправильного ответа.
• Стрик правильных ответов не сбросится
• Действует на 1 неправильный ответ
• Автоматически применяется

<b>3. 🔧 Восстановление стрика</b> - {repair_price}₽
Верни потерянный стрик за деньги!
• Доступно в течение 48 часов после потери
• Цена зависит от длины стрика
"""

            if not can_repair:
                text += "\n<i>❌ Восстановление недоступно (нет потерянного стрика)</i>"

            text += "\n\n💡 <b>Совет:</b> Premium подписка (249₽/мес) включает безлимитные заморозки!"

            keyboard = []

            # Кнопка покупки заморозки
            keyboard.append([
                InlineKeyboardButton(
                    f"❄️ Купить заморозку - 49₽",
                    callback_data="buy_freeze"
                )
            ])

            # Кнопка покупки щита
            keyboard.append([
                InlineKeyboardButton(
                    f"🛡️ Купить щит - 29₽",
                    callback_data="buy_error_shield"
                )
            ])

            # Кнопка восстановления (если доступно)
            if can_repair:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🔧 Восстановить стрик - {repair_price}₽",
                        callback_data="buy_repair"
                    )
                ])

            # Кнопка Premium
            keyboard.append([
                InlineKeyboardButton(
                    "👑 Premium подписка - 249₽/мес",
                    callback_data="about_premium"
                )
            ])

            keyboard.append([
                InlineKeyboardButton("« Назад", callback_data="to_main_menu")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            if query:
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )

            logger.info(f"Showed protection shop for user {user_id}")

        except Exception as e:
            logger.error(f"Error showing shop: {e}", exc_info=True)
            if query:
                await query.answer("Произошла ошибка при загрузке магазина", show_alert=True)

    # ============================================================
    # FREEZE PURCHASE
    # ============================================================

    async def buy_freeze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик покупки заморозки"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id

        try:
            text = f"""
❄️ <b>Заморозка стрика</b>

<b>Что это:</b>
Заморозка позволяет пропустить один день без потери стрика.

<b>Как работает:</b>
• Если ты пропустишь день, заморозка автоматически сохранит твой стрик
• Можно купить несколько заморозок и накапливать их
• Заморозки никогда не сгорают

<b>Стоимость:</b> 49₽ за 1 заморозку

<b>💡 Бесплатные заморозки:</b>
• За 7-дневный стрик: +1 заморозка
• За 30-дневный стрик: +1 заморозка
• За 60-дневный стрик: +2 заморозки

Подтверди покупку, чтобы продолжить.
"""

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💳 Оплатить 49₽",
                    callback_data="confirm_buy_freeze"
                )],
                [InlineKeyboardButton("« Назад", callback_data="streak_shop")]
            ])

            await query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

            logger.info(f"User {user_id} viewing freeze purchase")

        except Exception as e:
            logger.error(f"Error in buy_freeze: {e}", exc_info=True)
            await query.answer("Произошла ошибка", show_alert=True)

    async def confirm_buy_freeze(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Подтверждение покупки заморозки - создание платежа"""
        query = update.callback_query
        await query.answer("Создаю платеж...")

        user_id = update.effective_user.id

        try:
            # Создаем платеж через Tinkoff
            payment_manager = context.bot_data.get('payment_manager')

            if not payment_manager:
                await query.answer(
                    "Платежная система временно недоступна. Попробуйте позже.",
                    show_alert=True
                )
                return

            # Создаем платеж
            payment_result = await payment_manager.create_payment(
                user_id=user_id,
                amount=self.FREEZE_PRICE * 100,  # В копейках
                description="Заморозка стрика (1 шт)",
                payment_type="streak_freeze",
                metadata={
                    'type': 'freeze',
                    'quantity': 1
                }
            )

            if payment_result and 'payment_url' in payment_result:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "💳 Перейти к оплате",
                        url=payment_result['payment_url']
                    )],
                    [InlineKeyboardButton("« Отмена", callback_data="streak_shop")]
                ])

                await query.edit_message_text(
                    f"💳 <b>Оплата заморозки стрика</b>\n\n"
                    f"Сумма: <b>49₽</b>\n\n"
                    f"Нажми кнопку ниже, чтобы перейти к оплате.\n"
                    f"После успешной оплаты заморозка автоматически добавится в твой инвентарь.",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

                logger.info(f"Created freeze payment for user {user_id}: {payment_result.get('payment_id')}")

            else:
                await query.answer(
                    "Не удалось создать платеж. Попробуйте позже.",
                    show_alert=True
                )

        except Exception as e:
            logger.error(f"Error confirming freeze purchase: {e}", exc_info=True)
            await query.answer("Произошла ошибка при создании платежа", show_alert=True)

    # ============================================================
    # ERROR SHIELD PURCHASE
    # ============================================================

    async def buy_error_shield(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик покупки щита от ошибок"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id

        try:
            text = f"""
🛡️ <b>Щит от ошибок</b>

<b>Что это:</b>
Щит защищает твой стрик правильных ответов от сброса при неправильном ответе.

<b>Как работает:</b>
• Если ты ответишь неправильно, щит автоматически сработает
• Стрик правильных ответов НЕ сбросится
• Действует на 1 неправильный ответ

<b>Стоимость:</b> 29₽ за 1 щит

<b>💡 Бесплатные щиты:</b>
• За 10 правильных ответов подряд: +1 щит

<b>Пример:</b>
У тебя стрик 15 правильных ответов.
Ты отвечаешь неправильно → щит срабатывает → стрик остается 15!

Подтверди покупку, чтобы продолжить.
"""

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💳 Оплатить 29₽",
                    callback_data="confirm_buy_shield"
                )],
                [InlineKeyboardButton("« Назад", callback_data="streak_shop")]
            ])

            await query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

            logger.info(f"User {user_id} viewing shield purchase")

        except Exception as e:
            logger.error(f"Error in buy_error_shield: {e}", exc_info=True)
            await query.answer("Произошла ошибка", show_alert=True)

    async def confirm_buy_shield(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Подтверждение покупки щита - создание платежа"""
        query = update.callback_query
        await query.answer("Создаю платеж...")

        user_id = update.effective_user.id

        try:
            payment_manager = context.bot_data.get('payment_manager')

            if not payment_manager:
                await query.answer(
                    "Платежная система временно недоступна. Попробуйте позже.",
                    show_alert=True
                )
                return

            payment_result = await payment_manager.create_payment(
                user_id=user_id,
                amount=self.ERROR_SHIELD_PRICE * 100,
                description="Щит от ошибок (1 шт)",
                payment_type="error_shield",
                metadata={
                    'type': 'error_shield',
                    'quantity': 1
                }
            )

            if payment_result and 'payment_url' in payment_result:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "💳 Перейти к оплате",
                        url=payment_result['payment_url']
                    )],
                    [InlineKeyboardButton("« Отмена", callback_data="streak_shop")]
                ])

                await query.edit_message_text(
                    f"💳 <b>Оплата щита от ошибок</b>\n\n"
                    f"Сумма: <b>29₽</b>\n\n"
                    f"Нажми кнопку ниже, чтобы перейти к оплате.\n"
                    f"После успешной оплаты щит автоматически добавится в твой инвентарь.",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

                logger.info(f"Created shield payment for user {user_id}: {payment_result.get('payment_id')}")

            else:
                await query.answer(
                    "Не удалось создать платеж. Попробуйте позже.",
                    show_alert=True
                )

        except Exception as e:
            logger.error(f"Error confirming shield purchase: {e}", exc_info=True)
            await query.answer("Произошла ошибка при создании платежа", show_alert=True)

    # ============================================================
    # REPAIR PURCHASE
    # ============================================================

    async def buy_repair(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик покупки восстановления стрика"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id

        try:
            # Проверяем, можно ли восстановить
            can_repair = await self._can_repair_streak(user_id)

            if not can_repair:
                await query.answer(
                    "❌ Восстановление недоступно!\n\n"
                    "У тебя нет потерянного стрика или прошло более 48 часов.",
                    show_alert=True
                )
                return

            # Получаем информацию о потерянном стрике
            lost_streak, hours_ago = await self._get_lost_streak_info(user_id)
            repair_price = await self._calculate_repair_price(user_id)

            hours_left = 48 - hours_ago

            text = f"""
🔧 <b>Восстановление стрика</b>

<b>Твой потерянный стрик:</b> 🔥 {lost_streak} дней
<b>Потерян:</b> {hours_ago} ч. назад
<b>Времени на восстановление:</b> {hours_left} ч.

<b>Как работает:</b>
• Твой стрик будет полностью восстановлен
• Ты продолжишь с {lost_streak} дней
• Доступно только в течение 48 часов после потери

<b>Стоимость восстановления:</b>

Цена зависит от длины потерянного стрика:
• 1-6 дней: <b>99₽</b>
• 7-29 дней: <b>149₽</b>
• 30-59 дней: <b>199₽</b>
• 60+ дней: <b>249₽</b>

<b>Твоя цена: {repair_price}₽</b>

💡 <i>Совет: В будущем используй заморозки, чтобы не терять стрик!</i>

Подтверди покупку, чтобы восстановить стрик.
"""

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"💳 Восстановить за {repair_price}₽",
                    callback_data="confirm_buy_repair"
                )],
                [InlineKeyboardButton("« Назад", callback_data="streak_shop")]
            ])

            await query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

            logger.info(f"User {user_id} viewing repair purchase: {lost_streak} days for {repair_price}₽")

        except Exception as e:
            logger.error(f"Error in buy_repair: {e}", exc_info=True)
            await query.answer("Произошла ошибка", show_alert=True)

    async def confirm_buy_repair(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Подтверждение покупки восстановления - создание платежа"""
        query = update.callback_query
        await query.answer("Создаю платеж...")

        user_id = update.effective_user.id

        try:
            # Проверяем еще раз, что восстановление доступно
            can_repair = await self._can_repair_streak(user_id)

            if not can_repair:
                await query.answer(
                    "❌ Восстановление больше недоступно!",
                    show_alert=True
                )
                return

            lost_streak, _ = await self._get_lost_streak_info(user_id)
            repair_price = await self._calculate_repair_price(user_id)

            payment_manager = context.bot_data.get('payment_manager')

            if not payment_manager:
                await query.answer(
                    "Платежная система временно недоступна. Попробуйте позже.",
                    show_alert=True
                )
                return

            payment_result = await payment_manager.create_payment(
                user_id=user_id,
                amount=repair_price * 100,
                description=f"Восстановление стрика ({lost_streak} дней)",
                payment_type="streak_repair",
                metadata={
                    'type': 'repair',
                    'streak_days': lost_streak
                }
            )

            if payment_result and 'payment_url' in payment_result:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "💳 Перейти к оплате",
                        url=payment_result['payment_url']
                    )],
                    [InlineKeyboardButton("« Отмена", callback_data="streak_shop")]
                ])

                await query.edit_message_text(
                    f"💳 <b>Оплата восстановления стрика</b>\n\n"
                    f"Восстановление: <b>{lost_streak} дней</b>\n"
                    f"Сумма: <b>{repair_price}₽</b>\n\n"
                    f"Нажми кнопку ниже, чтобы перейти к оплате.\n"
                    f"После успешной оплаты твой стрик будет восстановлен!",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

                logger.info(f"Created repair payment for user {user_id}: {lost_streak} days for {repair_price}₽")

            else:
                await query.answer(
                    "Не удалось создать платеж. Попробуйте позже.",
                    show_alert=True
                )

        except Exception as e:
            logger.error(f"Error confirming repair purchase: {e}", exc_info=True)
            await query.answer("Произошла ошибка при создании платежа", show_alert=True)

    # ============================================================
    # PAYMENT SUCCESS HANDLERS
    # ============================================================

    async def grant_freeze(self, user_id: int, quantity: int = 1) -> bool:
        """Выдает заморозки пользователю после оплаты"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    UPDATE user_streaks
                    SET freeze_count = freeze_count + ?
                    WHERE user_id = ?
                """, (quantity, user_id))

                # Логируем покупку
                await db.execute("""
                    INSERT INTO streak_protection_log (
                        user_id,
                        protection_type,
                        action,
                        quantity,
                        payment_amount,
                        created_at
                    ) VALUES (?, 'freeze', 'purchased', ?, ?, ?)
                """, (user_id, quantity, self.FREEZE_PRICE * quantity,
                      datetime.now(timezone.utc).isoformat()))

                await db.commit()

            logger.info(f"Granted {quantity} freeze(s) to user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error granting freeze: {e}", exc_info=True)
            return False

    async def grant_error_shield(self, user_id: int, quantity: int = 1) -> bool:
        """Выдает щиты от ошибок пользователю после оплаты"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    UPDATE user_streaks
                    SET error_shield_count = error_shield_count + ?
                    WHERE user_id = ?
                """, (quantity, user_id))

                await db.execute("""
                    INSERT INTO streak_protection_log (
                        user_id,
                        protection_type,
                        action,
                        quantity,
                        payment_amount,
                        created_at
                    ) VALUES (?, 'error_shield', 'purchased', ?, ?, ?)
                """, (user_id, quantity, self.ERROR_SHIELD_PRICE * quantity,
                      datetime.now(timezone.utc).isoformat()))

                await db.commit()

            logger.info(f"Granted {quantity} error shield(s) to user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error granting error shield: {e}", exc_info=True)
            return False

    async def apply_repair(self, user_id: int) -> bool:
        """Восстанавливает потерянный стрик после оплаты"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Получаем информацию о потерянном стрике
                cursor = await db.execute("""
                    SELECT streak_before_loss, max_daily_streak
                    FROM user_streaks
                    WHERE user_id = ?
                      AND streak_state = 'recoverable'
                """, (user_id,))

                row = await cursor.fetchone()

                if not row:
                    logger.warning(f"No recoverable streak found for user {user_id}")
                    return False

                lost_streak, max_streak = row

                # Восстанавливаем стрик
                await db.execute("""
                    UPDATE user_streaks
                    SET current_daily_streak = ?,
                        max_daily_streak = ?,
                        streak_state = 'active',
                        last_activity_date = ?,
                        streak_before_loss = NULL,
                        streak_lost_at = NULL
                    WHERE user_id = ?
                """, (lost_streak, max(max_streak, lost_streak),
                      datetime.now(timezone.utc).date().isoformat(), user_id))

                # Логируем восстановление
                repair_price = await self._calculate_repair_price(user_id)
                await db.execute("""
                    INSERT INTO streak_protection_log (
                        user_id,
                        protection_type,
                        action,
                        streak_days_affected,
                        payment_amount,
                        created_at
                    ) VALUES (?, 'repair', 'applied', ?, ?, ?)
                """, (user_id, lost_streak, repair_price,
                      datetime.now(timezone.utc).isoformat()))

                await db.commit()

            logger.info(f"Repaired streak for user {user_id}: restored {lost_streak} days")
            return True

        except Exception as e:
            logger.error(f"Error applying repair: {e}", exc_info=True)
            return False

    # ============================================================
    # HELPER METHODS
    # ============================================================

    async def _can_repair_streak(self, user_id: int) -> bool:
        """Проверяет, может ли пользователь восстановить стрик"""
        try:
            lost_streak, hours_ago = await self._get_lost_streak_info(user_id)
            return lost_streak > 0 and hours_ago < 48

        except Exception as e:
            logger.error(f"Error checking repair availability: {e}")
            return False

    async def _get_lost_streak_info(self, user_id: int) -> Tuple[int, int]:
        """
        Возвращает информацию о потерянном стрике.

        Returns:
            (lost_streak_days, hours_since_loss)
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT
                        streak_before_loss,
                        streak_lost_at
                    FROM user_streaks
                    WHERE user_id = ?
                      AND streak_state IN ('lost', 'recoverable')
                      AND streak_before_loss > 0
                """, (user_id,))

                row = await cursor.fetchone()

                if not row or not row[1]:
                    return 0, 0

                lost_streak = row[0] or 0
                lost_at = datetime.fromisoformat(row[1])
                hours_ago = int((datetime.now(timezone.utc) - lost_at).total_seconds() / 3600)

                return lost_streak, hours_ago

        except Exception as e:
            logger.error(f"Error getting lost streak info: {e}")
            return 0, 0

    async def _calculate_repair_price(self, user_id: int) -> int:
        """Рассчитывает стоимость восстановления на основе длины стрика"""
        try:
            lost_streak, _ = await self._get_lost_streak_info(user_id)

            if lost_streak == 0:
                return 0
            elif lost_streak < 7:
                return 99
            elif lost_streak < 30:
                return 149
            elif lost_streak < 60:
                return 199
            else:
                return 249

        except Exception as e:
            logger.error(f"Error calculating repair price: {e}")
            return self.REPAIR_BASE_PRICE


# Глобальный экземпляр
_shop_instance: Optional[StreakProtectionShop] = None


def get_streak_protection_shop() -> StreakProtectionShop:
    """Возвращает глобальный экземпляр магазина"""
    global _shop_instance
    if _shop_instance is None:
        _shop_instance = StreakProtectionShop()
    return _shop_instance


# ============================================================
# CALLBACK HANDLERS REGISTRATION
# ============================================================

def register_protection_shop_handlers(application: Application):
    """Регистрирует все handlers магазина защит"""
    shop = get_streak_protection_shop()

    # Главный экран магазина
    application.add_handler(
        CallbackQueryHandler(shop.show_shop, pattern="^streak_shop$")
    )

    # Freeze handlers
    application.add_handler(
        CallbackQueryHandler(shop.buy_freeze, pattern="^buy_freeze$")
    )
    application.add_handler(
        CallbackQueryHandler(shop.confirm_buy_freeze, pattern="^confirm_buy_freeze$")
    )

    # Error Shield handlers
    application.add_handler(
        CallbackQueryHandler(shop.buy_error_shield, pattern="^buy_error_shield$")
    )
    application.add_handler(
        CallbackQueryHandler(shop.confirm_buy_shield, pattern="^confirm_buy_shield$")
    )

    # Repair handlers
    application.add_handler(
        CallbackQueryHandler(shop.buy_repair, pattern="^buy_repair$")
    )
    application.add_handler(
        CallbackQueryHandler(shop.confirm_buy_repair, pattern="^confirm_buy_repair$")
    )

    logger.info("Protection shop handlers registered")
