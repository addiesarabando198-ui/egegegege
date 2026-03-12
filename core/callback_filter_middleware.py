"""
Middleware для фильтрации старых callback queries при запуске бота.

Проблема:
При перезапуске бота Telegram отправляет все накопившиеся обновления,
включая старые callback queries (от нажатий на кнопки). Telegram разрешает
отвечать на callback query только в течение 30-60 секунд. Если бот пытается
ответить на старый callback query, возникает ошибка:
"Query is too old and response timeout expired or query id is invalid"

Решение:
Этот middleware фильтрует callback queries только в течение короткого окна
после запуска бота (STARTUP_FILTER_WINDOW). В этот период Telegram присылает
очередь накопившихся обновлений, которые нужно отбросить. После окна запуска
все callback'и обрабатываются нормально, даже от старых сообщений.
"""

import logging
import time
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

# Окно после запуска бота, в течение которого фильтруются старые callback'и (секунды).
# Telegram обычно отправляет все накопившиеся обновления в первые секунды после старта.
STARTUP_FILTER_WINDOW = 30

# Время запуска бота (устанавливается при регистрации middleware)
BOT_START_TIME = None


async def filter_old_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Фильтрует старые callback queries только во время окна запуска бота.

    Во время STARTUP_FILTER_WINDOW после старта бота отбрасывает callback'и
    от сообщений, созданных до запуска. После этого окна пропускает все.
    """
    if not update.callback_query:
        return

    callback_query = update.callback_query

    if not BOT_START_TIME:
        return

    current_time = time.time()
    time_since_start = current_time - BOT_START_TIME

    # После окна запуска пропускаем все callback'и без проверки
    if time_since_start > STARTUP_FILTER_WINDOW:
        return

    # Во время окна запуска — фильтруем callback'и от сообщений из прошлой сессии
    if callback_query.message and callback_query.message.date:
        callback_time = callback_query.message.date.timestamp()

        if callback_time < BOT_START_TIME:
            age = current_time - callback_time
            logger.info(
                f"Ignoring old callback query during startup "
                f"(age: {age:.1f}s, user: {update.effective_user.id}, "
                f"data: {callback_query.data})"
            )

            try:
                await callback_query.answer()
            except BadRequest as e:
                logger.debug(f"Failed to answer old callback query: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error answering old callback: {e}")

            return None

    return


def register_callback_filter_middleware(app):
    """
    Регистрирует middleware для фильтрации старых callback queries.

    Должен быть зарегистрирован с group=-2 (раньше других middleware),
    чтобы блокировать старые callbacks до их обработки.
    """
    global BOT_START_TIME
    BOT_START_TIME = time.time()

    app.add_handler(
        CallbackQueryHandler(
            filter_old_callbacks,
            pattern=".*"
        ),
        group=-2
    )

    logger.info(
        f"Callback filter middleware registered "
        f"(startup filter window: {STARTUP_FILTER_WINDOW}s)"
    )
