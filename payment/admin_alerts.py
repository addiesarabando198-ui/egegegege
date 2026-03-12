# payment/admin_alerts.py
"""Система критичных алертов для администратора платежной системы."""
import logging
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from .config import PAYMENT_ADMIN_CHAT_ID

logger = logging.getLogger(__name__)


async def notify_admin_critical(bot: Bot, title: str, details: dict, user_id: int = None):
    """
    Отправляет критичное уведомление администратору о проблемах с платежами.

    Args:
        bot: Экземпляр Telegram Bot
        title: Заголовок проблемы
        details: Детали проблемы (словарь)
        user_id: ID пользователя (если применимо)
    """
    if not PAYMENT_ADMIN_CHAT_ID or PAYMENT_ADMIN_CHAT_ID == 0:
        logger.warning("PAYMENT_ADMIN_CHAT_ID not configured, skipping admin alert")
        return

    try:
        # Формируем сообщение
        message = f"🚨 <b>CRITICAL PAYMENT ERROR</b>\n\n"
        message += f"<b>{title}</b>\n\n"

        # Добавляем детали
        message += "<b>Details:</b>\n"
        for key, value in details.items():
            message += f"• {key}: <code>{value}</code>\n"

        # Добавляем user_id если есть
        if user_id:
            message += f"\n<b>User ID:</b> <code>{user_id}</code>\n"

        # Добавляем timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message += f"\n<b>Time:</b> {timestamp}\n"

        # Добавляем действие
        message += "\n⚠️ <b>Manual intervention required!</b>"

        # Отправляем админу
        await bot.send_message(
            chat_id=PAYMENT_ADMIN_CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Critical alert sent to admin: {title}")

    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")


async def notify_admin_payment_activation_failed(
    bot: Bot,
    order_id: str,
    user_id: int,
    plan_id: str,
    amount: int,
    error: str = None
):
    """
    Уведомляет админа когда платеж успешно прошел, но активация подписки упала.

    Это КРИТИЧНАЯ ситуация - деньги списаны, но доступ не предоставлен!
    """
    await notify_admin_critical(
        bot=bot,
        title="Payment Succeeded But Activation Failed",
        details={
            'order_id': order_id,
            'plan_id': plan_id,
            'amount': f"{amount}₽",
            'error': error or 'Unknown error',
            'action': 'Check DB and activate subscription manually'
        },
        user_id=user_id
    )


async def notify_admin_auto_renewal_activation_failed(
    bot: Bot,
    order_id: str,
    user_id: int,
    plan_id: str,
    amount: int
):
    """
    Уведомляет админа когда автопродление списало деньги, но активация упала.
    """
    await notify_admin_critical(
        bot=bot,
        title="Auto-Renewal Payment Succeeded But Activation Failed",
        details={
            'order_id': order_id,
            'plan_id': plan_id,
            'amount': f"{amount}₽",
            'type': 'Auto-renewal',
            'action': 'Check auto_renewal_settings and activate subscription manually'
        },
        user_id=user_id
    )


async def notify_admin_multiple_renewal_failures(
    bot: Bot,
    user_id: int,
    failures_count: int,
    last_error: str
):
    """
    Уведомляет админа когда у пользователя множественные неудачи автопродления.
    """
    if failures_count >= 3:
        await notify_admin_critical(
            bot=bot,
            title="Auto-Renewal Failed 3+ Times",
            details={
                'failures_count': failures_count,
                'last_error': last_error,
                'status': 'Auto-renewal disabled',
                'action': 'Contact user to update payment method'
            },
            user_id=user_id
        )


async def notify_admin_webhook_processing_error(
    bot: Bot,
    order_id: str,
    error: str,
    webhook_data: dict = None
):
    """
    Уведомляет админа об ошибке обработки webhook от Tinkoff.
    """
    details = {
        'order_id': order_id,
        'error': error,
    }

    if webhook_data:
        details['payment_id'] = webhook_data.get('PaymentId', 'N/A')
        details['status'] = webhook_data.get('Status', 'N/A')

    await notify_admin_critical(
        bot=bot,
        title="Webhook Processing Error",
        details=details,
        user_id=None
    )


async def notify_admin_info(bot: Bot, message: str):
    """
    Отправляет информационное сообщение админу (не критичное).

    Args:
        bot: Экземпляр Telegram Bot
        message: Текст сообщения
    """
    if not PAYMENT_ADMIN_CHAT_ID or PAYMENT_ADMIN_CHAT_ID == 0:
        return

    try:
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_message = f"ℹ️ <b>Payment System Info</b> ({timestamp})\n\n{message}"

        await bot.send_message(
            chat_id=PAYMENT_ADMIN_CHAT_ID,
            text=full_message,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Failed to send admin info: {e}")
