"""
Тесты для B2B API.

Покрытие:
- API Key аутентификация
- Rate limiting
- SSRF-валидация URL
- Idempotency
- Webhook delivery
- Counter reset
- Schemas validation
- Key generation
- Tier limits
"""

import asyncio
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import aiosqlite

# Добавляем корень проекта
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Подставляем env ДО импорта модулей
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "TEST_TOKEN_FOR_PYTEST")
os.environ.setdefault("DATABASE_FILE", ":memory:")

# Маркер для всего модуля
pytestmark = pytest.mark.asyncio


# ===================== Helpers =====================

async def create_test_db(tmp_path) -> str:
    """Создаёт тестовую SQLite БД с миграциями B2B."""
    db_path = str(tmp_path / "test_b2b.db")

    async with aiosqlite.connect(db_path) as db:
        migration_path = project_root / "b2b_api" / "migrations" / "b2b_tables.sql"
        sql = migration_path.read_text(encoding="utf-8")
        await db.executescript(sql)
        await db.commit()

    return db_path


async def seed_test_client(db_path: str):
    """Создаёт тестового клиента и возвращает (client_id, raw_key)."""
    client_id = "cli_test_001"
    raw_key = f"b2b_live_sk_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            INSERT INTO b2b_clients (
                client_id, company_name, contact_email, contact_name,
                status, tier, rate_limit_per_minute, rate_limit_per_day,
                monthly_quota, checks_today, checks_this_month, total_checks,
                created_at
            ) VALUES (?, ?, ?, ?, 'active', 'standard', 30, 1000, 10000, 0, 0, 0, ?)
        """, (
            client_id, "Test School", "test@school.ru", "Test Admin",
            datetime.now(timezone.utc).isoformat()
        ))

        await db.execute("""
            INSERT INTO b2b_api_keys (
                key_id, client_id, key_hash, key_prefix,
                name, scopes, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            "key_test_001", client_id, key_hash, raw_key[:16],
            "Test Key", "check:create,check:read,questions:read,stats:read,admin",
            datetime.now(timezone.utc).isoformat()
        ))
        await db.commit()

    return client_id, raw_key


# ===================== URL Validator Tests =====================

class TestURLValidator:
    """Тесты SSRF-защиты для callback_url."""

    def test_valid_https_url(self):
        from b2b_api.utils.url_validator import validate_callback_url
        assert validate_callback_url("https://example.com/webhook") is None

    def test_reject_http(self):
        from b2b_api.utils.url_validator import validate_callback_url
        result = validate_callback_url("http://example.com/webhook")
        assert result is not None
        assert "HTTPS" in result

    def test_reject_localhost(self):
        from b2b_api.utils.url_validator import validate_callback_url
        result = validate_callback_url("https://localhost/webhook")
        assert result is not None

    def test_reject_private_ip(self):
        from b2b_api.utils.url_validator import validate_callback_url
        result = validate_callback_url("https://192.168.1.1/webhook")
        assert result is not None
        assert "private" in result.lower()

    def test_reject_metadata_endpoint(self):
        from b2b_api.utils.url_validator import validate_callback_url
        result = validate_callback_url("https://169.254.169.254/latest/meta-data")
        assert result is not None

    def test_reject_non_standard_port(self):
        from b2b_api.utils.url_validator import validate_callback_url
        result = validate_callback_url("https://example.com:9090/webhook")
        assert result is not None

    def test_allow_port_443(self):
        from b2b_api.utils.url_validator import validate_callback_url
        assert validate_callback_url("https://example.com:443/webhook") is None

    def test_allow_port_8443(self):
        from b2b_api.utils.url_validator import validate_callback_url
        assert validate_callback_url("https://example.com:8443/webhook") is None

    def test_none_url(self):
        from b2b_api.utils.url_validator import validate_callback_url
        assert validate_callback_url("") is None

    def test_reject_loopback_ipv6(self):
        from b2b_api.utils.url_validator import validate_callback_url
        result = validate_callback_url("https://[::1]/webhook")
        assert result is not None


# ===================== API Key Auth Tests =====================

class TestAPIKeyAuth:
    """Тесты аутентификации по API ключу."""

    async def test_verify_valid_key(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, raw_key = await seed_test_client(db_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        auth = APIKeyAuth(database_file=db_path)
        result = await auth.verify_key(raw_key)

        assert result is not None
        assert result["client_id"] == client_id
        assert result["tier"] == "standard"
        assert "check:create" in result["scopes"]

    async def test_reject_invalid_key(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        await seed_test_client(db_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        auth = APIKeyAuth(database_file=db_path)
        result = await auth.verify_key("b2b_live_sk_invalid_key_123")
        assert result is None

    async def test_reject_empty_key(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        auth = APIKeyAuth(database_file=db_path)
        result = await auth.verify_key("")
        assert result is None

    async def test_cache_hit(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, raw_key = await seed_test_client(db_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        auth = APIKeyAuth(database_file=db_path)

        result1 = await auth.verify_key(raw_key)
        assert result1 is not None

        result2 = await auth.verify_key(raw_key)
        assert result2 is not None
        assert result2["client_id"] == client_id

    async def test_reject_suspended_client(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, raw_key = await seed_test_client(db_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE b2b_clients SET status = 'suspended' WHERE client_id = ?",
                (client_id,)
            )
            await db.commit()

        auth = APIKeyAuth(database_file=db_path)
        result = await auth.verify_key(raw_key)
        assert result is None

    async def test_reject_expired_key(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        _, raw_key = await seed_test_client(db_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        async with aiosqlite.connect(db_path) as db:
            past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            await db.execute(
                "UPDATE b2b_api_keys SET expires_at = ? WHERE key_id = 'key_test_001'",
                (past,)
            )
            await db.commit()

        auth = APIKeyAuth(database_file=db_path)
        result = await auth.verify_key(raw_key)
        assert result is None

    async def test_increment_usage(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, _ = await seed_test_client(db_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        auth = APIKeyAuth(database_file=db_path)
        await auth.increment_usage(client_id)

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT checks_today, checks_this_month, total_checks FROM b2b_clients WHERE client_id = ?",
                (client_id,)
            )
            row = await cursor.fetchone()
            assert row["checks_today"] == 1
            assert row["checks_this_month"] == 1
            assert row["total_checks"] == 1

    async def test_scope_check(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        _, raw_key = await seed_test_client(db_path)
        from b2b_api.middleware.api_key_auth import APIKeyAuth

        auth = APIKeyAuth(database_file=db_path)
        client_data = await auth.verify_key(raw_key)

        assert await auth.check_scope(client_data, "check:create") is True
        assert await auth.check_scope(client_data, "admin") is True
        # admin scope grants access to everything
        assert await auth.check_scope(client_data, "nonexistent:scope") is True


# ===================== Rate Limiter Tests =====================

class TestRateLimiter:
    """Тесты rate limiting."""

    async def test_sliding_window_allows_within_limit(self):
        from b2b_api.middleware.rate_limiter import SlidingWindowCounter

        counter = SlidingWindowCounter(window_size_seconds=60)
        allowed, count, remaining, _ = await counter.is_allowed("test_client", 10)

        assert allowed is True
        assert count == 1
        assert remaining == 9

    async def test_sliding_window_blocks_over_limit(self):
        from b2b_api.middleware.rate_limiter import SlidingWindowCounter

        counter = SlidingWindowCounter(window_size_seconds=60)

        for _ in range(5):
            await counter.is_allowed("test_client", 5)

        allowed, count, remaining, retry_after = await counter.is_allowed("test_client", 5)
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0

    async def test_daily_counter_allows_within_limit(self):
        from b2b_api.middleware.rate_limiter import DailyCounter

        counter = DailyCounter()
        allowed, count, remaining, _ = await counter.is_allowed("test_client", 100)

        assert allowed is True
        assert count == 1
        assert remaining == 99

    async def test_daily_counter_blocks_over_limit(self):
        from b2b_api.middleware.rate_limiter import DailyCounter

        counter = DailyCounter()

        for _ in range(3):
            await counter.is_allowed("test_client", 3)

        allowed, count, remaining, retry_after = await counter.is_allowed("test_client", 3)
        assert allowed is False
        assert remaining == 0

    async def test_rate_limiter_full_check(self):
        from b2b_api.middleware.rate_limiter import RateLimiter

        limiter = RateLimiter()
        result = await limiter.check(
            client_id="test",
            minute_limit=10,
            daily_limit=100,
            monthly_quota=1000,
            current_monthly_usage=0
        )

        assert result["minute"]["allowed"] is True
        assert result["daily"]["allowed"] is True
        assert result["monthly"]["remaining"] == 1000

    async def test_rate_limiter_monthly_exceeded(self):
        from b2b_api.middleware.rate_limiter import RateLimiter, RateLimitExceeded

        limiter = RateLimiter()
        with pytest.raises(RateLimitExceeded):
            await limiter.check(
                client_id="test",
                minute_limit=10,
                daily_limit=100,
                monthly_quota=1000,
                current_monthly_usage=1000
            )

    async def test_sliding_window_cleanup(self):
        from b2b_api.middleware.rate_limiter import SlidingWindowCounter

        counter = SlidingWindowCounter(window_size_seconds=60)
        await counter.is_allowed("client1", 10)
        await counter.is_allowed("client2", 10)

        await counter.cleanup()


# ===================== Webhook Delivery Tests =====================

class TestWebhookDelivery:
    """Тесты webhook delivery."""

    def test_hmac_signature(self):
        from b2b_api.services.webhook_delivery import compute_hmac_signature

        payload = '{"event": "check.completed"}'
        secret = "test_secret"

        sig1 = compute_hmac_signature(payload, secret)
        sig2 = compute_hmac_signature(payload, secret)

        assert sig1 == sig2
        assert len(sig1) == 64  # SHA-256 hex

    def test_hmac_different_payloads(self):
        from b2b_api.services.webhook_delivery import compute_hmac_signature

        sig1 = compute_hmac_signature("payload1", "secret")
        sig2 = compute_hmac_signature("payload2", "secret")

        assert sig1 != sig2

    def test_hmac_different_secrets(self):
        from b2b_api.services.webhook_delivery import compute_hmac_signature

        sig1 = compute_hmac_signature("payload", "secret1")
        sig2 = compute_hmac_signature("payload", "secret2")

        assert sig1 != sig2

    async def test_create_delivery_record(self, tmp_path):
        from b2b_api.services.webhook_delivery import _create_delivery_record

        db_path = await create_test_db(tmp_path)

        with patch("b2b_api.services.webhook_delivery.DATABASE_FILE", db_path):
            delivery_id = await _create_delivery_record(
                "chk_test", "cli_test", "https://example.com/hook", '{"test": true}'
            )
            assert delivery_id > 0

            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM b2b_webhook_deliveries WHERE id = ?", (delivery_id,)
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row["check_id"] == "chk_test"
                assert row["status"] == "pending"


# ===================== Idempotency Tests =====================

class TestIdempotency:
    """Тесты идемпотентности."""

    async def test_find_existing_check(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, _ = await seed_test_client(db_path)

        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO b2b_checks (
                    check_id, client_id, status, task_number,
                    task_text, answer_text, idempotency_key, created_at
                ) VALUES (?, ?, 'completed', 19, 'test task', 'test answer', ?, ?)
            """, (
                "chk_existing", client_id, "idemp_key_123",
                datetime.now(timezone.utc).isoformat()
            ))
            await db.commit()

        with patch("b2b_api.routes.check.DATABASE_FILE", db_path):
            from b2b_api.routes.check import find_existing_check_by_idempotency_key
            result = await find_existing_check_by_idempotency_key(client_id, "idemp_key_123")

            assert result is not None
            assert result["check_id"] == "chk_existing"
            assert result["status"] == "completed"

    async def test_no_existing_check(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, _ = await seed_test_client(db_path)

        with patch("b2b_api.routes.check.DATABASE_FILE", db_path):
            from b2b_api.routes.check import find_existing_check_by_idempotency_key
            result = await find_existing_check_by_idempotency_key(client_id, "nonexistent_key")
            assert result is None


# ===================== Counter Reset Tests =====================

class TestCounterReset:
    """Тесты сброса счётчиков."""

    async def test_daily_counter_reset(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, _ = await seed_test_client(db_path)

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE b2b_clients SET checks_today = 100 WHERE client_id = ?",
                (client_id,)
            )
            await db.commit()

        with patch("b2b_api.app.DATABASE_FILE", db_path):
            from b2b_api.app import reset_daily_counters
            await reset_daily_counters()

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT checks_today FROM b2b_clients WHERE client_id = ?",
                (client_id,)
            )
            row = await cursor.fetchone()
            assert row["checks_today"] == 0

    async def test_monthly_counter_reset(self, tmp_path):
        db_path = await create_test_db(tmp_path)
        client_id, _ = await seed_test_client(db_path)

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE b2b_clients SET checks_this_month = 5000 WHERE client_id = ?",
                (client_id,)
            )
            await db.commit()

        with patch("b2b_api.app.DATABASE_FILE", db_path):
            from b2b_api.app import reset_monthly_counters
            await reset_monthly_counters()

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT checks_this_month FROM b2b_clients WHERE client_id = ?",
                (client_id,)
            )
            row = await cursor.fetchone()
            assert row["checks_this_month"] == 0


# ===================== Schema Validation Tests =====================

class TestSchemas:
    """Тесты Pydantic-схем."""

    def test_check_request_valid(self):
        from b2b_api.schemas.check import CheckRequest

        req = CheckRequest(
            task_number=19,
            task_text="Приведите три примера...",
            answer_text="1) Пример 1 2) Пример 2 3) Пример 3",
            strictness="standard"
        )
        assert req.task_number == 19

    def test_check_request_invalid_task_below(self):
        from b2b_api.schemas.check import CheckRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CheckRequest(
                task_number=16,
                task_text="test text for task",
                answer_text="answer"
            )

    def test_check_request_invalid_task_above(self):
        from b2b_api.schemas.check import CheckRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CheckRequest(
                task_number=26,
                task_text="test text for task",
                answer_text="answer"
            )

    def test_check_request_invalid_strictness(self):
        from b2b_api.schemas.check import CheckRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CheckRequest(
                task_number=19,
                task_text="test text for task",
                answer_text="answer",
                strictness="invalid_level"
            )

    def test_check_request_callback_url_ssrf_blocked(self):
        from b2b_api.schemas.check import CheckRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CheckRequest(
                task_number=19,
                task_text="test text for task",
                answer_text="answer",
                callback_url="http://169.254.169.254/latest"
            )

    def test_check_request_metadata_too_many_keys(self):
        from b2b_api.schemas.check import CheckRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CheckRequest(
                task_number=19,
                task_text="test text for task",
                answer_text="answer",
                metadata={f"key_{i}": f"val_{i}" for i in range(21)}
            )

    def test_check_request_with_idempotency_key(self):
        from b2b_api.schemas.check import CheckRequest

        req = CheckRequest(
            task_number=20,
            task_text="test text for task",
            answer_text="answer",
            idempotency_key="unique_key_123"
        )
        assert req.idempotency_key == "unique_key_123"

    def test_client_tier_enum(self):
        from b2b_api.schemas.client import ClientTier

        assert ClientTier.FREE.value == "free"
        assert ClientTier.ENTERPRISE.value == "enterprise"

    def test_client_create_schema(self):
        from b2b_api.schemas.client import B2BClientCreate, ClientTier

        client = B2BClientCreate(
            company_name="Test School",
            contact_email="test@school.ru",
            contact_name="Admin",
            tier=ClientTier.STANDARD,
        )
        assert client.company_name == "Test School"
        assert client.tier == ClientTier.STANDARD


# ===================== Key Generation Tests =====================

class TestKeyGeneration:
    """Тесты генерации API ключей."""

    def test_generate_api_key_format(self):
        from b2b_api.middleware.api_key_auth import generate_api_key

        raw, hashed = generate_api_key()
        assert raw.startswith("b2b_live_sk_")
        assert len(hashed) == 64

    def test_generate_api_key_unique(self):
        from b2b_api.middleware.api_key_auth import generate_api_key

        key1, _ = generate_api_key()
        key2, _ = generate_api_key()
        assert key1 != key2

    def test_hash_api_key(self):
        from b2b_api.middleware.api_key_auth import hash_api_key

        key = "b2b_live_sk_test123"
        h = hash_api_key(key)
        assert h == hashlib.sha256(key.encode()).hexdigest()


# ===================== Tier Limits Tests =====================

class TestTierLimits:
    """Тесты лимитов по тарифам."""

    def test_free_tier_limits(self):
        from b2b_api.middleware.api_key_auth import TIER_LIMITS
        from b2b_api.schemas.client import ClientTier

        limits = TIER_LIMITS[ClientTier.FREE]
        assert limits["rate_limit_per_minute"] == 5
        assert limits["rate_limit_per_day"] == 50
        assert limits["monthly_quota"] == 100

    def test_enterprise_unlimited(self):
        from b2b_api.middleware.api_key_auth import TIER_LIMITS
        from b2b_api.schemas.client import ClientTier

        limits = TIER_LIMITS[ClientTier.ENTERPRISE]
        assert limits["monthly_quota"] is None
        assert "admin" in limits["scopes"]

    def test_all_tiers_have_limits(self):
        from b2b_api.middleware.api_key_auth import TIER_LIMITS
        from b2b_api.schemas.client import ClientTier

        for tier in ClientTier:
            assert tier in TIER_LIMITS
            assert "rate_limit_per_minute" in TIER_LIMITS[tier]
            assert "rate_limit_per_day" in TIER_LIMITS[tier]
            assert "scopes" in TIER_LIMITS[tier]
