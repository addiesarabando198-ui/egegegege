"""
B2B API - FastAPI приложение для интеграции с онлайн-школами.

Предоставляет:
- POST /api/v1/check - отправка ответа на проверку
- GET /api/v1/check/{id} - получение результата проверки
- GET /api/v1/questions - доступ к банку заданий
- GET /api/v1/me - информация о клиенте
- GET /api/v1/usage - статистика использования

Документация: /docs (Swagger UI), /redoc (ReDoc)
"""

import logging
import json
import os
import uuid
import aiosqlite
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from starlette.middleware.base import BaseHTTPMiddleware

from b2b_api.routes import check_router, questions_router, client_router, admin_router
from b2b_api.middleware.rate_limiter import RateLimitMiddleware, get_rate_limiter, RateLimitExceeded
from b2b_api.services.api_logger import APILoggingMiddleware, get_api_logger
from core.config import DEBUG
from core.db import DATABASE_FILE


# ==================== Structured JSON Logging ====================

class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter для production."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "client_id"):
            log_entry["client_id"] = record.client_id
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging():
    """Настраивает логирование: JSON в production, текст в debug."""
    root_logger = logging.getLogger("b2b_api")
    root_logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

    handler = logging.StreamHandler()
    if DEBUG:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
    else:
        handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)


setup_logging()
logger = logging.getLogger(__name__)


# ==================== Counter Reset ====================

async def reset_daily_counters():
    """Сбрасывает дневные счётчики checks_today для всех клиентов."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE b2b_clients
                SET checks_today = 0,
                    last_daily_reset = ?
                WHERE checks_today > 0
            """, (datetime.now(timezone.utc).isoformat(),))
            await db.commit()
            logger.info("Daily counters reset completed")
    except Exception as e:
        logger.error(f"Error resetting daily counters: {e}", exc_info=True)


async def reset_monthly_counters():
    """Сбрасывает месячные счётчики checks_this_month для всех клиентов."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE b2b_clients
                SET checks_this_month = 0,
                    last_monthly_reset = ?
                WHERE checks_this_month > 0
            """, (datetime.now(timezone.utc).isoformat(),))
            await db.commit()
            logger.info("Monthly counters reset completed")
    except Exception as e:
        logger.error(f"Error resetting monthly counters: {e}", exc_info=True)


async def counter_reset_scheduler():
    """
    Фоновая задача для автоматического сброса счётчиков.

    - Ежедневно в 00:00 UTC сбрасывает checks_today
    - Каждый 1-й день месяца сбрасывает checks_this_month
    """
    last_daily_reset_date = None
    last_monthly_reset_month = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            today = now.date()
            current_month = (now.year, now.month)

            # Ежедневный сброс
            if last_daily_reset_date != today:
                await reset_daily_counters()
                last_daily_reset_date = today

            # Ежемесячный сброс
            if last_monthly_reset_month != current_month:
                await reset_monthly_counters()
                last_monthly_reset_month = current_month

        except Exception as e:
            logger.error(f"Error in counter reset scheduler: {e}", exc_info=True)

        # Проверяем каждые 60 секунд
        await asyncio.sleep(60)


# ==================== CORS ====================

def get_cors_origins() -> list:
    """
    Загружает разрешённые CORS-домены из переменной окружения.

    B2B_CORS_ORIGINS=https://school1.ru,https://app.school2.ru
    """
    if DEBUG:
        return ["*"]

    origins_str = os.getenv("B2B_CORS_ORIGINS", "")
    if not origins_str:
        # По умолчанию запрещаем все, кроме same-origin
        return []

    origins = [o.strip() for o in origins_str.split(",") if o.strip()]
    return origins


# ==================== Lifespan ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager для приложения."""
    # Startup
    logger.info("B2B API starting up...")

    # Запускаем rate limiter cleanup task
    rate_limiter = get_rate_limiter()
    await rate_limiter.start_cleanup_task()

    # Запускаем API logger
    api_logger = get_api_logger()
    await api_logger.start()

    # Запускаем scheduler сброса счётчиков
    counter_task = asyncio.create_task(counter_reset_scheduler())

    # Запускаем scheduler биллинга
    from b2b_api.services.billing_scheduler import start_billing_scheduler
    billing_task = start_billing_scheduler()

    logger.info("B2B API ready")

    yield

    # Shutdown
    logger.info("B2B API shutting down...")
    counter_task.cancel()
    billing_task.cancel()
    try:
        await counter_task
    except asyncio.CancelledError:
        pass
    try:
        await billing_task
    except asyncio.CancelledError:
        pass
    await api_logger.stop()
    logger.info("B2B API stopped")


# ==================== Application ====================

app = FastAPI(
    title="EGE Superbot B2B API",
    version="1.1.0",
    description="""
## B2B API для интеграции с онлайн-школами

Позволяет автоматически проверять ответы учеников на задания ЕГЭ по обществознанию (17-25).

### Возможности

- **Проверка ответов** - отправляйте ответы учеников и получайте оценки с комментариями
- **Банк заданий** - доступ к базе заданий для тренировки
- **Аналитика** - статистика использования API
- **Идемпотентность** - заголовок `Idempotency-Key` предотвращает дублирование проверок

### Аутентификация

Используйте API ключ в заголовке `X-API-Key` или как Bearer token:

```
X-API-Key: b2b_live_sk_xxx...
```

или

```
Authorization: Bearer b2b_live_sk_xxx...
```

### Rate Limiting

- Лимиты зависят от вашего тарифа
- Информация о лимитах в заголовках ответа (`X-RateLimit-*`)
- При превышении лимита возвращается статус 429

### Поддержка

Для получения API ключа и вопросов по интеграции: api@example.com
    """,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan
)


# ==================== Middleware ====================

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Добавляет уникальный request_id для трассировки запросов."""
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        forwarded_proto = request.headers.get("x-forwarded-proto")
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto
        return await call_next(request)


# Добавляем middleware (порядок важен — последний добавленный выполняется первым!)
app.add_middleware(ProxyHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(APILoggingMiddleware, api_prefix="/api/v1")

# CORS настройки
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=[
        "X-RateLimit-Limit-Minute",
        "X-RateLimit-Remaining-Minute",
        "X-RateLimit-Limit-Daily",
        "X-RateLimit-Remaining-Daily",
        "X-RateLimit-Limit-Monthly",
        "X-RateLimit-Remaining-Monthly",
        "X-Request-ID"
    ]
)


# ==================== Routes ====================

app.include_router(
    check_router,
    prefix="/api/v1"
)

app.include_router(
    questions_router,
    prefix="/api/v1"
)

app.include_router(
    client_router,
    prefix="/api/v1"
)

app.include_router(
    admin_router,
    prefix="/api/v1"
)


# ==================== Root / Health ====================

@app.get("/", tags=["root"])
async def root():
    """Корневой endpoint API."""
    return {
        "service": "EGE Superbot B2B API",
        "version": "1.1.0",
        "status": "healthy",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health", tags=["root"])
async def health_check():
    """
    Health check с проверкой зависимостей.

    Возвращает:
    - status: healthy / degraded / unhealthy
    - checks: статус каждой зависимости
    """
    checks = {}

    # Проверяем БД
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("SELECT 1")
            await cursor.fetchone()
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "message": str(e)}

    # Проверяем наличие AI-провайдера
    try:
        ai_provider = os.getenv("AI_PROVIDER", "claude")
        if ai_provider == "claude":
            has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
        else:
            has_key = bool(os.getenv("YANDEX_GPT_API_KEY"))
        checks["ai_service"] = {
            "status": "ok" if has_key else "warning",
            "provider": ai_provider,
            "configured": has_key
        }
    except Exception as e:
        checks["ai_service"] = {"status": "error", "message": str(e)}

    # Определяем общий статус
    statuses = [c.get("status") for c in checks.values()]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif "error" in statuses:
        overall = "unhealthy"
    else:
        overall = "degraded"

    status_code = 200 if overall != "unhealthy" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "service": "b2b-api",
            "version": "1.1.0",
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


# ==================== Docs ====================

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
    )


# ==================== Error Handlers ====================

@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=exc.detail,
        headers={"Retry-After": str(exc.retry_after)}
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"Unhandled error [request_id={request_id}]: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": str(exc) if DEBUG else "An internal error occurred",
            "request_id": request_id
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "b2b_api.app:app",
        host="0.0.0.0",
        port=8001,
        reload=DEBUG,
        log_level="info" if not DEBUG else "debug"
    )
