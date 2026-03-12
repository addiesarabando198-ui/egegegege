"""
API Key аутентификация для B2B API.

Поддерживает:
- Аутентификация через заголовок X-API-Key
- Аутентификация через Bearer token
- Проверка scopes (разрешений)
- Кэширование для производительности
"""

import logging
import hashlib
import secrets
import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from functools import lru_cache
from fastapi import Header, HTTPException, Depends, Security
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from core.db import DATABASE_FILE
from b2b_api.schemas.client import B2BClient, ClientStatus, ClientTier

logger = logging.getLogger(__name__)

# Security schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


# Настройки лимитов по тарифам
TIER_LIMITS = {
    ClientTier.FREE: {
        "rate_limit_per_minute": 5,
        "rate_limit_per_day": 50,
        "monthly_quota": 100,
        "scopes": ["check:create", "check:read"]
    },
    ClientTier.TRIAL: {
        "rate_limit_per_minute": 10,
        "rate_limit_per_day": 200,
        "monthly_quota": 500,
        "scopes": ["check:create", "check:read", "questions:read"]
    },
    ClientTier.BASIC: {
        "rate_limit_per_minute": 20,
        "rate_limit_per_day": 500,
        "monthly_quota": 2000,
        "scopes": ["check:create", "check:read", "questions:read"]
    },
    ClientTier.STANDARD: {
        "rate_limit_per_minute": 30,
        "rate_limit_per_day": 1000,
        "monthly_quota": 10000,
        "scopes": ["check:create", "check:read", "questions:read", "stats:read"]
    },
    ClientTier.PREMIUM: {
        "rate_limit_per_minute": 60,
        "rate_limit_per_day": 5000,
        "monthly_quota": 50000,
        "scopes": ["check:create", "check:read", "questions:read", "stats:read", "questions:samples"]
    },
    ClientTier.ENTERPRISE: {
        "rate_limit_per_minute": 120,
        "rate_limit_per_day": 20000,
        "monthly_quota": None,  # Безлимит
        "scopes": ["check:create", "check:read", "questions:read", "stats:read", "questions:samples", "admin"]
    }
}


def generate_api_key(prefix: str = "b2b_live") -> Tuple[str, str]:
    """
    Генерирует новый API ключ.

    Returns:
        (raw_key, hashed_key) - исходный ключ для клиента и хеш для хранения
    """
    # Генерируем случайный ключ
    random_part = secrets.token_urlsafe(32)
    raw_key = f"{prefix}_sk_{random_part}"

    # Хешируем для хранения в БД
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()

    return raw_key, hashed_key


def hash_api_key(api_key: str) -> str:
    """Хеширует API ключ для сравнения с БД."""
    return hashlib.sha256(api_key.encode()).hexdigest()


class APIKeyAuth:
    """Класс для работы с API ключами."""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        # Простой кэш для частых запросов (TTL 5 минут)
        self._cache = {}
        self._cache_ttl = timedelta(minutes=5)

    def _get_from_cache(self, key_hash: str) -> Optional[dict]:
        """Получает данные из кэша."""
        if key_hash in self._cache:
            data, timestamp = self._cache[key_hash]
            if datetime.now(timezone.utc) - timestamp < self._cache_ttl:
                return data
            else:
                del self._cache[key_hash]
        return None

    def _set_cache(self, key_hash: str, data: dict):
        """Сохраняет данные в кэш."""
        self._cache[key_hash] = (data, datetime.now(timezone.utc))

        # Очищаем старые записи если кэш слишком большой
        if len(self._cache) > 1000:
            now = datetime.now(timezone.utc)
            self._cache = {
                k: v for k, v in self._cache.items()
                if now - v[1] < self._cache_ttl
            }

    async def verify_key(self, api_key: str) -> Optional[dict]:
        """
        Проверяет API ключ и возвращает информацию о клиенте.

        Returns:
            dict с информацией о клиенте или None если ключ невалидный
        """
        if not api_key:
            return None

        key_hash = hash_api_key(api_key)

        # Проверяем кэш
        cached = self._get_from_cache(key_hash)
        if cached:
            logger.debug(f"API key found in cache: {key_hash[:16]}...")
            return cached

        try:
            async with aiosqlite.connect(self.database_file) as db:
                db.row_factory = aiosqlite.Row

                # Ищем ключ и связанного клиента
                cursor = await db.execute("""
                    SELECT
                        k.key_id,
                        k.client_id,
                        k.name as key_name,
                        k.scopes,
                        k.is_active,
                        k.expires_at,
                        c.company_name,
                        c.contact_email,
                        c.contact_name,
                        c.status,
                        c.tier,
                        c.rate_limit_per_minute,
                        c.rate_limit_per_day,
                        c.monthly_quota,
                        c.checks_today,
                        c.checks_this_month,
                        c.total_checks,
                        c.created_at,
                        c.last_activity_at,
                        c.trial_expires_at
                    FROM b2b_api_keys k
                    JOIN b2b_clients c ON k.client_id = c.client_id
                    WHERE k.key_hash = ?
                """, (key_hash,))

                row = await cursor.fetchone()

                if not row:
                    logger.warning(f"API key not found: {key_hash[:16]}...")
                    return None

                # Проверяем активность ключа
                if not row['is_active']:
                    logger.warning(f"API key is deactivated: {row['key_id']}")
                    return None

                # Проверяем срок действия ключа
                if row['expires_at']:
                    expires_at = datetime.fromisoformat(row['expires_at'])
                    if expires_at < datetime.now(timezone.utc):
                        logger.warning(f"API key expired: {row['key_id']}")
                        return None

                # Проверяем статус клиента
                if row['status'] == ClientStatus.SUSPENDED.value:
                    logger.warning(f"Client suspended: {row['client_id']}")
                    return None

                # Проверяем trial
                if row['status'] == ClientStatus.TRIAL.value and row['trial_expires_at']:
                    trial_expires = datetime.fromisoformat(row['trial_expires_at'])
                    if trial_expires < datetime.now(timezone.utc):
                        logger.warning(f"Trial expired: {row['client_id']}")
                        return None

                # Формируем данные клиента
                tier = ClientTier(row['tier'])
                tier_limits = TIER_LIMITS.get(tier, TIER_LIMITS[ClientTier.BASIC])

                client_data = {
                    "key_id": row['key_id'],
                    "client_id": row['client_id'],
                    "company_name": row['company_name'],
                    "contact_email": row['contact_email'],
                    "contact_name": row['contact_name'],
                    "status": row['status'],
                    "tier": row['tier'],
                    "scopes": row['scopes'].split(',') if row['scopes'] else tier_limits['scopes'],
                    "rate_limit_per_minute": row['rate_limit_per_minute'] or tier_limits['rate_limit_per_minute'],
                    "rate_limit_per_day": row['rate_limit_per_day'] or tier_limits['rate_limit_per_day'],
                    "monthly_quota": row['monthly_quota'] if row['monthly_quota'] is not None else tier_limits['monthly_quota'],
                    "checks_today": row['checks_today'] or 0,
                    "checks_this_month": row['checks_this_month'] or 0,
                    "total_checks": row['total_checks'] or 0,
                    "created_at": row['created_at'],
                    "last_activity_at": row['last_activity_at']
                }

                # Обновляем last_used_at для ключа
                await db.execute("""
                    UPDATE b2b_api_keys
                    SET last_used_at = ?
                    WHERE key_id = ?
                """, (datetime.now(timezone.utc).isoformat(), row['key_id']))
                await db.commit()

                # Сохраняем в кэш
                self._set_cache(key_hash, client_data)

                logger.info(f"API key verified: client={row['client_id']}, tier={row['tier']}")
                return client_data

        except Exception as e:
            logger.error(f"Error verifying API key: {e}", exc_info=True)
            return None

    async def check_scope(self, client_data: dict, required_scope: str) -> bool:
        """Проверяет, есть ли у клиента нужный scope."""
        scopes = client_data.get('scopes', [])

        # admin имеет доступ ко всему
        if 'admin' in scopes:
            return True

        return required_scope in scopes

    async def increment_usage(self, client_id: str):
        """Увеличивает счётчики использования."""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    UPDATE b2b_clients
                    SET
                        checks_today = checks_today + 1,
                        checks_this_month = checks_this_month + 1,
                        total_checks = total_checks + 1,
                        last_activity_at = ?
                    WHERE client_id = ?
                """, (datetime.now(timezone.utc).isoformat(), client_id))
                await db.commit()
        except Exception as e:
            logger.error(f"Error incrementing usage for {client_id}: {e}")


# Глобальный экземпляр
_api_key_auth: Optional[APIKeyAuth] = None


def get_api_key_auth() -> APIKeyAuth:
    """Возвращает глобальный экземпляр APIKeyAuth."""
    global _api_key_auth
    if _api_key_auth is None:
        _api_key_auth = APIKeyAuth()
    return _api_key_auth


async def verify_api_key(
    api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)
) -> dict:
    """
    FastAPI dependency для проверки API ключа.

    Поддерживает:
    - X-API-Key header
    - Bearer token
    """
    # Определяем ключ из заголовков
    key = None
    if api_key:
        key = api_key
    elif bearer:
        key = bearer.credentials

    if not key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Use X-API-Key header or Bearer token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    auth = get_api_key_auth()
    client_data = await auth.verify_key(key)

    if not client_data:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return client_data


async def get_current_client(
    client_data: dict = Depends(verify_api_key)
) -> B2BClient:
    """
    FastAPI dependency для получения текущего клиента.
    """
    return B2BClient(
        client_id=client_data['client_id'],
        company_name=client_data['company_name'],
        contact_email=client_data['contact_email'],
        contact_name=client_data['contact_name'],
        status=ClientStatus(client_data['status']),
        tier=ClientTier(client_data['tier']),
        rate_limit_per_minute=client_data['rate_limit_per_minute'],
        rate_limit_per_day=client_data['rate_limit_per_day'],
        monthly_quota=client_data['monthly_quota'],
        checks_today=client_data['checks_today'],
        checks_this_month=client_data['checks_this_month'],
        total_checks=client_data['total_checks'],
        created_at=datetime.fromisoformat(client_data['created_at']),
        last_activity_at=datetime.fromisoformat(client_data['last_activity_at']) if client_data['last_activity_at'] else None
    )


def require_scope(scope: str):
    """
    Декоратор/dependency для проверки scope.

    Использование:
    @router.get("/admin/stats")
    async def admin_stats(client = Depends(require_scope("admin"))):
        ...
    """
    async def check_scope(client_data: dict = Depends(verify_api_key)) -> dict:
        auth = get_api_key_auth()
        if not await auth.check_scope(client_data, scope):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required scope: {scope}"
            )
        return client_data

    return check_scope
