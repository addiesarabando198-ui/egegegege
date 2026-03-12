"""
Admin API для управления B2B клиентами, API ключами и биллингом.

POST   /api/v1/admin/clients          - создание клиента
GET    /api/v1/admin/clients          - список клиентов
GET    /api/v1/admin/clients/{id}     - информация о клиенте
PATCH  /api/v1/admin/clients/{id}     - обновление клиента
POST   /api/v1/admin/clients/{id}/keys - создание API ключа
GET    /api/v1/admin/clients/{id}/keys - список ключей клиента
DELETE /api/v1/admin/keys/{key_id}     - деактивация ключа
POST   /api/v1/admin/keys/{key_id}/rotate - ротация ключа

Billing:
POST   /api/v1/admin/clients/{id}/billing/bind-card   - привязка карты
POST   /api/v1/admin/clients/{id}/billing/charge       - ручное списание
DELETE /api/v1/admin/clients/{id}/billing               - отмена автосписаний
GET    /api/v1/admin/clients/{id}/billing/history       - история биллинга
POST   /api/v1/admin/billing/run                        - запуск биллинга за месяц
"""

import logging
import secrets
import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import DATABASE_FILE
from b2b_api.schemas.client import (
    B2BClientCreate,
    B2BClient,
    ClientStatus,
    ClientTier,
    APIKeyResponse,
    APIKeyInfo,
)
from b2b_api.middleware.api_key_auth import (
    generate_api_key,
    require_scope,
    TIER_LIMITS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/clients",
    response_model=B2BClient,
    summary="Создать B2B клиента",
    description="Создаёт нового B2B клиента. Требуется scope `admin`.",
)
async def create_client(
    data: B2BClientCreate,
    _: dict = Depends(require_scope("admin")),
) -> B2BClient:
    """Создаёт нового B2B клиента."""
    client_id = f"cli_{secrets.token_hex(8)}"
    now = datetime.now(timezone.utc).isoformat()

    tier = data.tier
    tier_limits = TIER_LIMITS.get(tier, TIER_LIMITS[ClientTier.BASIC])

    trial_expires = None
    status = ClientStatus.ACTIVE.value
    if tier == ClientTier.TRIAL:
        status = ClientStatus.TRIAL.value
        trial_expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                INSERT INTO b2b_clients (
                    client_id, company_name, contact_email, contact_name,
                    contact_phone, website, status, tier,
                    rate_limit_per_minute, rate_limit_per_day, monthly_quota,
                    notes, created_at, updated_at, trial_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                client_id,
                data.company_name,
                data.contact_email,
                data.contact_name,
                data.contact_phone,
                data.website,
                status,
                tier.value,
                tier_limits["rate_limit_per_minute"],
                tier_limits["rate_limit_per_day"],
                tier_limits["monthly_quota"],
                data.notes,
                now, now,
                trial_expires,
            ))
            await db.commit()

        logger.info(f"Created B2B client: {client_id} ({data.company_name})")

        return B2BClient(
            client_id=client_id,
            company_name=data.company_name,
            contact_email=data.contact_email,
            contact_name=data.contact_name,
            status=ClientStatus(status),
            tier=tier,
            rate_limit_per_minute=tier_limits["rate_limit_per_minute"],
            rate_limit_per_day=tier_limits["rate_limit_per_day"],
            monthly_quota=tier_limits["monthly_quota"],
            checks_today=0,
            checks_this_month=0,
            total_checks=0,
            created_at=datetime.fromisoformat(now),
            last_activity_at=None,
            trial_expires_at=datetime.fromisoformat(trial_expires) if trial_expires else None,
        )

    except Exception as e:
        logger.error(f"Error creating client: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create client")


@router.get(
    "/clients",
    summary="Список B2B клиентов",
    description="Возвращает список всех B2B клиентов. Требуется scope `admin`.",
)
async def list_clients(
    _: dict = Depends(require_scope("admin")),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    tier: Optional[str] = Query(None, description="Фильтр по тарифу"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict:
    """Возвращает список клиентов."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            conditions = []
            params = []

            if status:
                conditions.append("status = ?")
                params.append(status)
            if tier:
                conditions.append("tier = ?")
                params.append(tier)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            cursor = await db.execute(
                f"SELECT COUNT(*) FROM b2b_clients {where}", params
            )
            total = (await cursor.fetchone())[0]

            offset = (page - 1) * per_page
            cursor = await db.execute(f"""
                SELECT * FROM b2b_clients {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, params + [per_page, offset])

            rows = await cursor.fetchall()

            clients = []
            for row in rows:
                clients.append({
                    "client_id": row["client_id"],
                    "company_name": row["company_name"],
                    "contact_email": row["contact_email"],
                    "status": row["status"],
                    "tier": row["tier"],
                    "checks_this_month": row["checks_this_month"] or 0,
                    "total_checks": row["total_checks"] or 0,
                    "monthly_quota": row["monthly_quota"],
                    "created_at": row["created_at"],
                    "last_activity_at": row["last_activity_at"],
                })

            return {"total": total, "items": clients, "page": page, "per_page": per_page}

    except Exception as e:
        logger.error(f"Error listing clients: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list clients")


@router.get(
    "/clients/{client_id}",
    summary="Информация о клиенте",
)
async def get_client(
    client_id: str,
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Возвращает подробную информацию о клиенте."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM b2b_clients WHERE client_id = ?", (client_id,)
            )
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Client not found")

            # Количество активных ключей
            cursor = await db.execute(
                "SELECT COUNT(*) FROM b2b_api_keys WHERE client_id = ? AND is_active = 1",
                (client_id,)
            )
            keys_count = (await cursor.fetchone())[0]

            return {**dict(row), "active_keys_count": keys_count}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting client {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get client")


@router.patch(
    "/clients/{client_id}",
    summary="Обновить клиента",
    description="Обновляет данные клиента (статус, тариф, лимиты). Требуется scope `admin`.",
)
async def update_client(
    client_id: str,
    updates: dict,
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Обновляет данные клиента."""
    allowed_fields = {
        "company_name", "contact_email", "contact_name", "contact_phone",
        "website", "status", "tier", "rate_limit_per_minute",
        "rate_limit_per_day", "monthly_quota", "notes",
    }

    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    # Если меняется тариф — обновляем лимиты
    if "tier" in filtered:
        new_tier = ClientTier(filtered["tier"])
        tier_limits = TIER_LIMITS.get(new_tier, TIER_LIMITS[ClientTier.BASIC])
        filtered.setdefault("rate_limit_per_minute", tier_limits["rate_limit_per_minute"])
        filtered.setdefault("rate_limit_per_day", tier_limits["rate_limit_per_day"])
        filtered.setdefault("monthly_quota", tier_limits["monthly_quota"])

    filtered["updated_at"] = datetime.now(timezone.utc).isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [client_id]

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            result = await db.execute(
                f"UPDATE b2b_clients SET {set_clause} WHERE client_id = ?", values
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Client not found")
            await db.commit()

        logger.info(f"Updated client {client_id}: {list(filtered.keys())}")
        return {"status": "updated", "client_id": client_id, "updated_fields": list(filtered.keys())}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating client {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update client")


@router.post(
    "/clients/{client_id}/keys",
    response_model=APIKeyResponse,
    summary="Создать API ключ",
    description="Создаёт новый API ключ для клиента. Ключ показывается **только один раз**!",
)
async def create_api_key(
    client_id: str,
    name: str = Query(..., description="Название ключа (Production, Staging и т.д.)"),
    expires_in_days: Optional[int] = Query(None, ge=1, le=365, description="Срок действия в днях"),
    _: dict = Depends(require_scope("admin")),
) -> APIKeyResponse:
    """Создаёт новый API ключ для клиента."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Проверяем что клиент существует
            cursor = await db.execute(
                "SELECT tier FROM b2b_clients WHERE client_id = ?", (client_id,)
            )
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Client not found")

            tier = ClientTier(row["tier"])
            tier_limits = TIER_LIMITS.get(tier, TIER_LIMITS[ClientTier.BASIC])
            scopes = tier_limits["scopes"]

            # Генерируем ключ
            raw_key, hashed_key = generate_api_key()
            key_id = f"key_{secrets.token_hex(6)}"
            now = datetime.now(timezone.utc)

            expires_at = None
            if expires_in_days:
                expires_at = (now + timedelta(days=expires_in_days)).isoformat()

            await db.execute("""
                INSERT INTO b2b_api_keys (
                    key_id, client_id, key_hash, key_prefix,
                    name, scopes, is_active, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (
                key_id, client_id, hashed_key, raw_key[:16],
                name, ",".join(scopes), expires_at, now.isoformat()
            ))
            await db.commit()

        logger.info(f"Created API key {key_id} for client {client_id}")

        return APIKeyResponse(
            api_key=raw_key,
            key_id=key_id,
            client_id=client_id,
            name=name,
            created_at=now,
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            scopes=scopes,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create API key")


@router.get(
    "/clients/{client_id}/keys",
    response_model=List[APIKeyInfo],
    summary="Список API ключей клиента",
)
async def list_client_keys(
    client_id: str,
    _: dict = Depends(require_scope("admin")),
) -> List[APIKeyInfo]:
    """Возвращает список API ключей клиента (без самих ключей)."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT key_id, name, scopes, is_active,
                       created_at, last_used_at, expires_at
                FROM b2b_api_keys
                WHERE client_id = ?
                ORDER BY created_at DESC
            """, (client_id,))

            rows = await cursor.fetchall()
            return [
                APIKeyInfo(
                    key_id=row["key_id"],
                    name=row["name"],
                    scopes=row["scopes"].split(",") if row["scopes"] else [],
                    is_active=bool(row["is_active"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
                    expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
                )
                for row in rows
            ]

    except Exception as e:
        logger.error(f"Error listing keys for {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list keys")


@router.delete(
    "/keys/{key_id}",
    summary="Деактивировать API ключ",
)
async def deactivate_key(
    key_id: str,
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Деактивирует API ключ."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            result = await db.execute(
                "UPDATE b2b_api_keys SET is_active = 0 WHERE key_id = ?", (key_id,)
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Key not found")
            await db.commit()

        logger.info(f"Deactivated API key: {key_id}")
        return {"status": "deactivated", "key_id": key_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating key {key_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to deactivate key")


@router.post(
    "/keys/{key_id}/rotate",
    response_model=APIKeyResponse,
    summary="Ротация API ключа",
    description="Деактивирует старый ключ и создаёт новый с теми же параметрами.",
)
async def rotate_key(
    key_id: str,
    _: dict = Depends(require_scope("admin")),
) -> APIKeyResponse:
    """Ротация ключа: деактивирует старый, создаёт новый."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Получаем данные старого ключа
            cursor = await db.execute(
                "SELECT * FROM b2b_api_keys WHERE key_id = ?", (key_id,)
            )
            old_key = await cursor.fetchone()
            if not old_key:
                raise HTTPException(status_code=404, detail="Key not found")

            if not old_key["is_active"]:
                raise HTTPException(status_code=400, detail="Key is already deactivated")

            # Деактивируем старый
            await db.execute(
                "UPDATE b2b_api_keys SET is_active = 0 WHERE key_id = ?", (key_id,)
            )

            # Создаём новый
            raw_key, hashed_key = generate_api_key()
            new_key_id = f"key_{secrets.token_hex(6)}"
            now = datetime.now(timezone.utc)

            await db.execute("""
                INSERT INTO b2b_api_keys (
                    key_id, client_id, key_hash, key_prefix,
                    name, scopes, is_active, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (
                new_key_id,
                old_key["client_id"],
                hashed_key,
                raw_key[:16],
                old_key["name"],
                old_key["scopes"],
                old_key["expires_at"],
                now.isoformat(),
            ))
            await db.commit()

        logger.info(f"Rotated API key: {key_id} -> {new_key_id}")

        scopes = old_key["scopes"].split(",") if old_key["scopes"] else []
        return APIKeyResponse(
            api_key=raw_key,
            key_id=new_key_id,
            client_id=old_key["client_id"],
            name=old_key["name"],
            created_at=now,
            expires_at=datetime.fromisoformat(old_key["expires_at"]) if old_key["expires_at"] else None,
            scopes=scopes,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rotating key {key_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to rotate key")


# ================================================================== #
#  BILLING ENDPOINTS
# ================================================================== #


@router.post(
    "/clients/{client_id}/billing/bind-card",
    summary="Привязать карту клиента",
    description="Создаёт платёж на 1₽ для привязки карты. Вернёт URL для оплаты.",
)
async def bind_card(
    client_id: str,
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Инициирует привязку карты для рекуррентных списаний."""
    from b2b_api.services.billing_service import BillingService

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT contact_email FROM b2b_clients WHERE client_id = ?",
                (client_id,),
            )
            client = await cursor.fetchone()
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")

        billing = BillingService()
        result = await billing.create_card_binding_payment(
            client_id=client_id,
            contact_email=client["contact_email"],
        )

        if not result["success"]:
            raise HTTPException(status_code=502, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error binding card for {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create binding payment")


@router.post(
    "/clients/{client_id}/billing/charge",
    summary="Ручное списание",
    description="Принудительно запускает биллинг для клиента за указанный месяц.",
)
async def charge_client(
    client_id: str,
    year: int = Query(..., ge=2024, le=2030),
    month: int = Query(..., ge=1, le=12),
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Ручной запуск биллинга для конкретного клиента."""
    from b2b_api.services.billing_service import BillingService

    try:
        billing = BillingService()
        result = await billing.bill_client(client_id, year, month)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error charging {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Billing failed")


@router.delete(
    "/clients/{client_id}/billing",
    summary="Отменить автосписания",
    description="Отключает рекуррентные платежи для клиента.",
)
async def cancel_billing(
    client_id: str,
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Отменяет автосписания для клиента."""
    from b2b_api.services.billing_service import BillingService

    try:
        billing = BillingService()
        return await billing.cancel_billing(client_id)
    except Exception as e:
        logger.error(f"Error cancelling billing for {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to cancel billing")


@router.get(
    "/clients/{client_id}/billing/history",
    summary="История биллинга клиента",
)
async def billing_history(
    client_id: str,
    limit: int = Query(12, ge=1, le=36),
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Возвращает историю биллинга клиента."""
    from b2b_api.services.billing_service import BillingService

    try:
        billing = BillingService()
        records = await billing.get_billing_history(client_id, limit)
        return {"client_id": client_id, "records": records}
    except Exception as e:
        logger.error(f"Error getting billing history for {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get billing history")


@router.post(
    "/billing/run",
    summary="Запустить биллинг за месяц",
    description="Запускает биллинг всех активных клиентов за указанный месяц.",
)
async def run_billing(
    year: int = Query(..., ge=2024, le=2030),
    month: int = Query(..., ge=1, le=12),
    _: dict = Depends(require_scope("admin")),
) -> dict:
    """Запускает биллинг всех активных клиентов."""
    from b2b_api.services.billing_service import BillingService

    try:
        billing = BillingService()
        results = await billing.bill_all_clients(year, month)
        successful = sum(1 for r in results if r.get("payment", {}).get("success"))
        return {
            "year": year,
            "month": month,
            "total_clients": len(results),
            "successful": successful,
            "failed": len(results) - successful,
            "details": results,
        }
    except Exception as e:
        logger.error(f"Error running billing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Billing run failed")
