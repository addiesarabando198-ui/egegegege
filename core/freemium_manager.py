"""
Freemium менеджер для управления лимитами AI-проверок.

Логика:
- Бесплатные пользователи: 3 AI-проверки в неделю (вместо 3 в день)
- Пользователи с подпиской: безлимитные проверки
- Лимиты сбрасываются еженедельно автоматически
- Фидбэк для freemium пользователей менее детальный
"""

import logging
from typing import Tuple, Dict, Optional, Any
from core import db

logger = logging.getLogger(__name__)

# Константы
FREE_WEEKLY_LIMIT = 3  # Бесплатных проверок в неделю (изменено с дневного лимита)


class FreemiumManager:
    """Менеджер для управления лимитами freemium пользователей"""

    def __init__(self, subscription_manager=None):
        """
        Инициализация менеджера.

        Args:
            subscription_manager: Менеджер подписок (опционально)
        """
        self.subscription_manager = subscription_manager
        logger.info(f"FreemiumManager initialized with weekly limit: {FREE_WEEKLY_LIMIT} checks")

    async def check_ai_limit(
        self,
        user_id: int,
        module_code: Optional[str] = None
    ) -> Tuple[bool, int, str]:
        """
        Проверка доступности AI-проверки для пользователя.

        Args:
            user_id: ID пользователя
            module_code: Код модуля (например, 'task19', 'task24')

        Returns:
            Tuple: (can_use, remaining, limit_msg)
                - can_use: Может ли пользователь использовать AI-проверку
                - remaining: Сколько проверок осталось (999 для premium)
                - limit_msg: Сообщение о лимитах
        """
        try:
            # Проверяем наличие активной подписки
            has_subscription = False
            if self.subscription_manager and module_code:
                # ИСПРАВЛЕНО: Используем module_code напрямую, без fallback
                # Если module_code не передан - проверяем наличие любой активной подписки
                has_subscription = await self.subscription_manager.check_module_access(
                    user_id, module_code
                )

            # Если есть подписка - безлимит
            if has_subscription:
                return (True, 999, "✨ У вас безлимитный доступ")

            # Для бесплатных - проверяем недельный лимит
            checks_used = await db.get_weekly_ai_checks_used(user_id)
            remaining = FREE_WEEKLY_LIMIT - checks_used

            if remaining > 0:
                msg = f"Осталось проверок на этой неделе: {remaining}/{FREE_WEEKLY_LIMIT}"
                return (True, remaining, msg)
            else:
                msg = (
                    f"⏰ <b>Вы использовали все {FREE_WEEKLY_LIMIT} бесплатных проверки на этой неделе</b>\n\n"
                    "💎 <b>Хотите продолжить прямо сейчас?</b>\n"
                    "Оформите подписку и получите:\n"
                    "• ♾️ Безлимитные AI-проверки\n"
                    "• 📊 Детальный анализ каждого ответа\n"
                    "• 🎯 Персональные рекомендации по улучшению\n"
                    "• 📚 Доступ ко всем заданиям второй части\n\n"
                    "🎁 <b>Пробный период:</b> 1₽ за 7 дней полного доступа\n"
                    "👑 <b>Полная подписка:</b> 249₽/мес\n\n"
                    "⏳ <i>Или ждите понедельника — бесплатный лимит обновится</i>"
                )
                return (False, 0, msg)

        except Exception as e:
            logger.error(f"Error checking AI limit for user {user_id}: {e}", exc_info=True)
            # ИСПРАВЛЕНО: В случае ошибки БД - блокируем доступ (безопасный вариант)
            return (False, 0, "❌ Временные технические неполадки. Попробуйте позже.")

    async def get_limit_info(
        self,
        user_id: int,
        module_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получение информации о лимитах пользователя.

        Args:
            user_id: ID пользователя
            module_code: Код модуля (опционально)

        Returns:
            Dict с информацией о лимитах
        """
        try:
            # Проверяем подписку
            has_subscription = False
            if self.subscription_manager:
                has_subscription = await self.subscription_manager.check_module_access(
                    user_id, module_code or 'task24'
                )

            # Получаем использованные проверки за неделю
            checks_used = await db.get_weekly_ai_checks_used(user_id)
            checks_remaining = max(0, FREE_WEEKLY_LIMIT - checks_used) if not has_subscription else 999

            return {
                'is_premium': has_subscription,
                'has_subscription': has_subscription,
                'checks_remaining': checks_remaining,
                'checks_limit': FREE_WEEKLY_LIMIT if not has_subscription else 999,
                'checks_used_this_week': checks_used,
                'reset_date': None,  # Лимиты сбрасываются автоматически каждый понедельник
                'module_code': module_code
            }

        except Exception as e:
            logger.error(f"Error getting limit info for user {user_id}: {e}")
            return {
                'is_premium': False,
                'has_subscription': False,
                'checks_remaining': FREE_WEEKLY_LIMIT,
                'checks_limit': FREE_WEEKLY_LIMIT,
                'checks_used_this_week': 0,
                'reset_date': None,
                'module_code': module_code
            }

    def format_limit_message(self, limit_info: Dict[str, Any]) -> str:
        """
        Форматирование сообщения о лимитах.

        Args:
            limit_info: Информация о лимитах

        Returns:
            Отформатированное сообщение
        """
        if limit_info.get('is_premium'):
            return "✨ <b>Безлимитный доступ активен</b>"
        else:
            remaining = limit_info.get('checks_remaining', 0)
            limit = limit_info.get('checks_limit', FREE_WEEKLY_LIMIT)

            if remaining > 0:
                return f"📊 Проверок на этой неделе: {remaining}/{limit}"
            else:
                return f"⏳ Лимит исчерпан. В понедельник: {limit}/{limit}"

    async def use_ai_check(
        self,
        user_id: int,
        module_code: Optional[str] = None
    ) -> bool:
        """
        Регистрация использования AI-проверки.

        Args:
            user_id: ID пользователя
            module_code: Код модуля

        Returns:
            True если использование зарегистрировано успешно
        """
        try:
            # Проверяем, можно ли использовать
            can_use, _, _ = await self.check_ai_limit(user_id, module_code)

            if not can_use:
                logger.warning(f"User {user_id} tried to use AI check but limit exceeded")
                return False

            # Увеличиваем счетчик
            success = await db.increment_ai_check_usage(user_id)

            if success:
                logger.info(f"AI check used by user {user_id} for module {module_code}")

            return success

        except Exception as e:
            logger.error(f"Error using AI check for user {user_id}: {e}")
            return False

    async def reset_weekly_limits(self) -> int:
        """
        Сброс недельных лимитов для всех пользователей.
        (Фактически удаляет старые записи для очистки БД)

        Returns:
            Количество пользователей, для которых сброшены лимиты
        """
        try:
            deleted = await db.reset_weekly_ai_limits()
            logger.info(f"Weekly limits reset: {deleted} old records cleaned")
            return deleted
        except Exception as e:
            logger.error(f"Error resetting weekly limits: {e}")
            return 0

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Получение статистики использования для пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            Словарь со статистикой
        """
        try:
            stats = await db.get_ai_limit_stats(user_id, days=7)
            return stats
        except Exception as e:
            logger.error(f"Error getting user stats for {user_id}: {e}")
            return {
                'total_checks': 0,
                'checks_today': 0,
                'modules_used': []
            }

    def simplify_feedback_for_freemium(self, detailed_feedback: str, score: int, max_score: int) -> str:
        """
        Упрощает детальный фидбек для freemium пользователей.

        Args:
            detailed_feedback: Детальный фидбек от AI
            score: Набранный балл
            max_score: Максимальный балл

        Returns:
            Упрощенный фидбек с призывом к подписке
        """
        # Формируем базовый результат
        text = f"📊 <b>Результат: {score}/{max_score} баллов</b>\n\n"

        # Общая оценка
        if score == max_score:
            text += "✅ Отличный ответ!\n"
        elif score >= max_score * 0.6:
            text += "⚠️ Хороший ответ, но есть недочеты\n"
        elif score > 0:
            text += "⚠️ Ответ требует доработки\n"
        else:
            text += "❌ Ответ не соответствует требованиям\n"

        # Базовые рекомендации (одинаковые для всех заданий)
        text += "\n💡 <b>Общие рекомендации:</b>\n"
        text += "• Приводите конкретные примеры с именами и названиями\n"
        text += "• Избегайте общих фраз и абстрактных рассуждений\n"
        text += "• Следите за фактической точностью\n"
        text += "• Соблюдайте структуру ответа согласно заданию\n"

        # Призыв к подписке
        text += (
            "\n\n💎 <b>Хотите получить детальный разбор?</b>\n"
            "С Premium подпиской вы получите:\n"
            "• 📋 Подробный анализ каждого примера\n"
            "• ✅ Что засчитано и почему\n"
            "• ❌ Конкретные ошибки и как их исправить\n"
            "• 💡 Персональные рекомендации по улучшению\n"
            "• ♾️ Безлимитные AI-проверки\n\n"
            "🎁 <b>Попробуйте:</b> 1₽ за 7 дней полного доступа"
        )

        return text


# Глобальный экземпляр менеджера
_freemium_manager_instance: Optional[FreemiumManager] = None


def get_freemium_manager(subscription_manager=None) -> FreemiumManager:
    """
    Получение глобального экземпляра freemium менеджера.

    Args:
        subscription_manager: Менеджер подписок (опционально)

    Returns:
        Экземпляр FreemiumManager
    """
    global _freemium_manager_instance

    if _freemium_manager_instance is None:
        _freemium_manager_instance = FreemiumManager(subscription_manager)

    return _freemium_manager_instance
