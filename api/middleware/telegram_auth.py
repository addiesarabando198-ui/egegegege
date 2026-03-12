"""
Middleware для аутентификации Telegram WebApp.
Валидирует initData согласно официальной документации Telegram.
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from fastapi import Header, HTTPException, Depends
from hashlib import sha256
import hmac
import json
import logging
from urllib.parse import parse_qsl
from typing import Optional

from core.config import BOT_TOKEN
from teacher_mode.services.teacher_service import get_teacher_profile
from teacher_mode.models import TeacherProfile

logger = logging.getLogger(__name__)


def verify_telegram_webapp_data(init_data: str) -> dict:
    """
    Проверяет подпись Telegram WebApp initData.

    Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Args:
        init_data: Строка initData от Telegram WebApp

    Returns:
        dict с данными пользователя

    Raises:
        HTTPException: Если данные невалидны
    """
    if not init_data:
        logger.warning("Попытка доступа без init data")
        raise HTTPException(status_code=401, detail="Missing init data")

    try:
        # Парсим initData
        data_dict = dict(parse_qsl(init_data))

        # Извлекаем hash
        received_hash = data_dict.pop('hash', None)
        if not received_hash:
            logger.warning("Отсутствует hash в init data")
            raise HTTPException(status_code=401, detail="Missing hash")

        # Создаем строку для проверки
        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(data_dict.items())
        )

        # Вычисляем ожидаемый hash
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            sha256
        ).digest()

        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            sha256
        ).hexdigest()

        # Сравниваем хеши безопасным способом
        if not hmac.compare_digest(received_hash, expected_hash):
            logger.warning("Неверная подпись init data")
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Извлекаем user_id
        user_data = json.loads(data_dict.get('user', '{}'))
        user_id = user_data.get('id')

        if not user_id:
            logger.warning("Отсутствует user ID в init data")
            raise HTTPException(status_code=401, detail="Missing user ID")

        logger.info(f"Успешная аутентификация пользователя {user_id} через WebApp")

        return {
            'user_id': user_id,
            'user_data': user_data,
            'auth_date': data_dict.get('auth_date')
        }

    except json.JSONDecodeError:
        logger.error("Ошибка парсинга JSON в init data")
        raise HTTPException(status_code=401, detail="Invalid user data format")
    except Exception as e:
        logger.error(f"Ошибка валидации init data: {e}")
        raise HTTPException(status_code=401, detail="Invalid init data")


async def get_current_teacher(
    x_telegram_init_data: str = Header(alias="X-Telegram-Init-Data")
) -> TeacherProfile:
    """
    Dependency для получения текущего учителя из initData.

    Использование в routes:
    ```python
    @router.get("/profile")
    async def get_profile(teacher = Depends(get_current_teacher)):
        return {"teacher_id": teacher.user_id}
    ```

    Args:
        x_telegram_init_data: initData из заголовка X-Telegram-Init-Data

    Returns:
        TeacherProfile текущего учителя

    Raises:
        HTTPException: Если пользователь не является учителем или аутентификация неуспешна
    """
    # Валидируем initData
    auth_data = verify_telegram_webapp_data(x_telegram_init_data)
    user_id = auth_data['user_id']

    # Получаем профиль учителя
    teacher = await get_teacher_profile(user_id)

    if not teacher:
        logger.warning(f"Попытка доступа к API учителя от не-учителя: user_id={user_id}")
        raise HTTPException(
            status_code=403,
            detail="Not a teacher. User does not have teacher access."
        )

    # Проверяем активность подписки
    if not teacher.has_active_subscription:
        logger.warning(f"Попытка доступа учителя без активной подписки: user_id={user_id}")
        raise HTTPException(
            status_code=403,
            detail="Teacher subscription is not active"
        )

    logger.info(f"Авторизован учитель {user_id} (код: {teacher.teacher_code})")
    return teacher


async def get_current_user_id(
    x_telegram_init_data: str = Header(alias="X-Telegram-Init-Data")
) -> int:
    """
    Dependency для получения только user_id из initData.
    Использовать для endpoints, где не требуется проверка роли учителя.

    Args:
        x_telegram_init_data: initData из заголовка X-Telegram-Init-Data

    Returns:
        int: user_id пользователя
    """
    auth_data = verify_telegram_webapp_data(x_telegram_init_data)
    return auth_data['user_id']
