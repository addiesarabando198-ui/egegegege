# Аудит готовности к B2B-распространению (v2)

**Дата:** 2026-03-09
**Предыдущий аудит:** 2026-03-01
**Область:** Модуль учителя (`teacher_mode/`) + Быстрая проверка (все виды) + B2B API (`b2b_api/`)

---

## Оглавление

1. [Сравнение с предыдущим аудитом](#1-сравнение-с-предыдущим-аудитом)
2. [Реализовано в этом цикле](#2-реализовано-в-этом-цикле)
3. [Текущая оценка](#3-текущая-оценка)
4. [Оставшиеся проблемы](#4-оставшиеся-проблемы)
5. [Рекомендации](#5-рекомендации)

---

## 1. Сравнение с предыдущим аудитом

### Проблемы, закрытые РАНЕЕ (до этого цикла)

| ID | Проблема | Статус | Где реализовано |
|----|----------|--------|-----------------|
| HIGH-1 | Нет SSRF-защиты для callback_url | **ЗАКРЫТА** | `b2b_api/utils/url_validator.py` — проверка HTTPS, блокировка приватных IP, localhost, metadata endpoints, нестандартных портов |
| HIGH-4 | CORS настроен небезопасно | **ЗАКРЫТА** | `b2b_api/app.py:145-160` — динамическая загрузка из `B2B_CORS_ORIGINS` env; в production пустой список (запрещено всё, кроме same-origin) |
| HIGH-6 | Счётчики не сбрасываются | **ЗАКРЫТА** | `b2b_api/app.py:78-141` — `counter_reset_scheduler()` — фоновая задача, ежедневный и ежемесячный сброс |
| MED-1 | Нет structured logging | **ЗАКРЫТА** | `b2b_api/app.py:38-72` — `JSONFormatter` в production + `RequestIDMiddleware` для correlation ID |
| MED-3 | API не поддерживает task17/18 | **ЗАКРЫТА** | `b2b_api/routes/check.py:37-84` — `get_evaluator()` поддерживает задания 17-25 |
| MED-4 | Нет idempotency | **ЗАКРЫТА** | `b2b_api/routes/check.py:87-110` + `b2b_api/schemas/check.py:80-84` — поле `idempotency_key`, поиск дублей перед созданием |
| MED-5 | Health check не проверяет зависимости | **ЗАКРЫТА** | `b2b_api/app.py:322-377` — проверка БД (SELECT 1) и наличия AI API ключа |

### Проблемы, закрытые В ЭТОМ ЦИКЛЕ

| ID | Проблема | Статус | Что сделано |
|----|----------|--------|-------------|
| CRIT-4 | Webhook не реализован | **ЗАКРЫТА** | `b2b_api/services/webhook_delivery.py` — полная реализация с HMAC-SHA256 подписью, retry (3 попытки с exp. backoff: 5s, 30s, 120s), логированием в `b2b_webhook_deliveries` |
| CRIT-5 | Нет тестов B2B API | **ЗАКРЫТА** | `tests/test_b2b_api.py` — **48 тестов** покрывающих: auth, rate limiting, SSRF, idempotency, webhook, counter reset, schemas, key generation, tier limits |
| HIGH-3 | Нет admin API | **ЗАКРЫТА** | `b2b_api/routes/admin.py` — CRUD клиентов, создание/деактивация/ротация API ключей, scope-based авторизация (требуется `admin` scope) |
| MED-6 | `idempotency_key` не в миграции | **ЗАКРЫТА** | `b2b_api/migrations/b2b_tables.sql` — добавлена колонка + индекс |

---

## 2. Реализовано в этом цикле

### 2.1 Webhook delivery (`b2b_api/services/webhook_delivery.py`)

- **HMAC-SHA256 подпись** — заголовок `X-Webhook-Signature: sha256=<hex>`
- **Retry-логика** — 3 попытки с задержками 5s, 30s, 120s
- **Заголовки**: `X-Webhook-Event`, `X-Webhook-Delivery-ID`, `X-Webhook-Attempt`
- **Логирование** — каждая попытка записывается в `b2b_webhook_deliveries`
- **Интеграция** — автоматическая отправка при завершении проверки (`routes/check.py:191-205`)
- **Секрет** — настраивается через `B2B_WEBHOOK_SECRET` env

### 2.2 Admin API (`b2b_api/routes/admin.py`)

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/v1/admin/clients` | POST | Создание клиента |
| `/api/v1/admin/clients` | GET | Список клиентов (пагинация, фильтры) |
| `/api/v1/admin/clients/{id}` | GET | Детали клиента |
| `/api/v1/admin/clients/{id}` | PATCH | Обновление (статус, тариф, лимиты) |
| `/api/v1/admin/clients/{id}/keys` | POST | Создание API ключа |
| `/api/v1/admin/clients/{id}/keys` | GET | Список ключей |
| `/api/v1/admin/keys/{key_id}` | DELETE | Деактивация ключа |
| `/api/v1/admin/keys/{key_id}/rotate` | POST | Ротация ключа |

- Все endpoints защищены `require_scope("admin")`
- При смене тарифа автоматически обновляются лимиты
- Ротация ключа: деактивирует старый + создаёт новый с теми же параметрами

### 2.3 Тесты B2B API (`tests/test_b2b_api.py`)

| Категория | Кол-во тестов | Что покрыто |
|-----------|:---:|-------------|
| URL Validator (SSRF) | 10 | HTTPS-only, localhost, private IP, metadata, ports, IPv6 |
| API Key Auth | 8 | Валидный/невалидный ключ, кэш, suspended, expired, increment, scopes |
| Rate Limiter | 7 | Sliding window, daily counter, full check, monthly exceeded, cleanup |
| Webhook Delivery | 4 | HMAC подпись, разные payload/secret, запись в БД |
| Idempotency | 2 | Поиск существующей/несуществующей проверки |
| Counter Reset | 2 | Дневной и месячный сброс |
| Schemas | 9 | Валидация task_number, strictness, SSRF, metadata, idempotency_key |
| Key Generation | 3 | Формат, уникальность, хеширование |
| Tier Limits | 3 | Free/Enterprise лимиты, все тарифы имеют конфигурацию |
| **Итого** | **48** | |

---

## 3. Текущая оценка

| Категория | Было | Стало | Статус |
|-----------|:----:|:-----:|--------|
| Функциональность teacher_mode | 8/10 | 8/10 | Хорошо |
| Быстрая проверка (task17-25) | 8/10 | 8/10 | Хорошо |
| B2B API (функциональность) | 7/10 | **9/10** | Хорошо |
| Безопасность | 4/10 | **7/10** | Удовлетворительно |
| Изоляция данных / multi-tenancy | 3/10 | 3/10 | Критично |
| Масштабируемость | 2/10 | 2/10 | Критично |
| Биллинг B2B | 2/10 | 2/10 | Критично |
| Тестирование | 2/10 | **7/10** | Удовлетворительно |
| Мониторинг / observability | 3/10 | **5/10** | Удовлетворительно |
| Документация API | 6/10 | **7/10** | Хорошо |

**Блокирующих проблем:** 5 → **3**
**Серьезных проблем:** 7 → **3**
**Средних проблем:** 6 → **1**

---

## 4. Оставшиеся проблемы

### CRIT-1: SQLite не подходит для B2B production (без изменений)

**Файлы:** `core/config.py:20`, `core/db.py`, все сервисы

Вся система по-прежнему использует SQLite. Каждый сервис (`teacher_mode`, `b2b_api`) работает с одним файлом `quiz_async.db`. При множественных B2B-клиентах:
- `BEGIN EXCLUSIVE` блокирует всю БД
- Нет connection pooling (каждый запрос создаёт новое соединение в `b2b_api`)
- Горизонтальное масштабирование невозможно

**Решение:** Миграция на PostgreSQL + asyncpg + connection pool.

---

### CRIT-2: Отсутствие изоляции данных между тенантами (без изменений)

**Файлы:** `b2b_api/routes/check.py`, `b2b_api/migrations/b2b_tables.sql`

Все B2B-клиенты хранят данные в одних таблицах. Защита — только `WHERE client_id = ?`.

**Решение:** PostgreSQL RLS или schema-per-tenant.

---

### CRIT-3: In-memory состояние (без изменений)

| Компонент | Данные в памяти |
|-----------|-----------------|
| `SlidingWindowCounter` | Счетчики запросов/мин |
| `DailyCounter` | Счетчики запросов/день |
| `APILogger._queue` | Очередь логов (до 50 записей) |
| `APIKeyAuth._cache` | Кэш API-ключей (TTL 5 мин) |

При перезапуске:
- Rate limits сбрасываются — возможен abuse
- Логи в очереди теряются (до 50 записей для биллинга)

**Решение:** Redis для rate limiting и кэша. WAL-based queue или Redis для логов.

---

### HIGH-2: Нет биллинговой логики (без изменений)

Таблица `b2b_billing_summary` создана, но нет кода для:
- Генерации invoice
- Интеграции с платёжным шлюзом
- Overage billing
- Email-уведомлений

**Решение:** Billing service с ежемесячной агрегацией.

---

### HIGH-5: Нет горизонтального масштабирования (без изменений)

Один процесс uvicorn, один файл SQLite, in-memory rate limiter.

**Решение:** PostgreSQL + Redis + Celery + gunicorn workers.

---

### HIGH-7: B2B API и teacher_mode — параллельные системы (без изменений)

Два мира квот, подписок и биллинга не связаны.

**Решение:** Единая система квот / абстракция над подписками.

---

### MED-2: White-label branding неполный (без изменений)

Нет привязки branding к B2B-клиенту.

---

## 5. Рекомендации

### Фаза 1: Оставшиеся блокеры (для MVP B2B) — 3-4 недели

| # | Задача | Приоритет | Трудоемкость |
|---|--------|-----------|-------------|
| 1 | Миграция на PostgreSQL | CRIT | 2-3 недели |
| 2 | Row-Level Security / tenant isolation | CRIT | 1 неделя |
| 3 | Redis для rate limiting + кэша | CRIT | 3-5 дней |

### Фаза 2: Важные улучшения — 3-4 недели

| # | Задача | Приоритет | Трудоемкость |
|---|--------|-----------|-------------|
| 4 | Биллинг B2B (invoice, overage) | HIGH | 2 недели |
| 5 | Celery/RQ для фоновых AI-задач | HIGH | 1 неделя |
| 6 | Единая система квот teacher_mode + B2B | HIGH | 1-2 недели |

### Фаза 3: Полноценный B2B-продукт — 3-4 недели

| # | Задача | Приоритет | Трудоемкость |
|---|--------|-----------|-------------|
| 7 | Клиентский портал (self-service) | MED | 2-3 недели |
| 8 | Monitoring (Prometheus + Grafana) | MED | 1 неделя |
| 9 | White-label branding привязка | LOW | 1 неделя |

---

## Заключение

С момента предыдущего аудита (2026-03-01) закрыто **11 из 18 проблем**:
- 7 были закрыты до этого цикла (SSRF, CORS, counter reset, structured logging, task17/18, idempotency, health check)
- 4 закрыты в этом цикле (webhook delivery, тесты B2B API, admin API, миграция idempotency_key)

**Оставшиеся 7 проблем** — преимущественно инфраструктурные (PostgreSQL, Redis, биллинг, масштабирование) и архитектурные (изоляция тенантов, унификация квот). Они требуют значительных изменений в стеке и не решаются исключительно на уровне кода приложения.

**Рекомендация:** После завершения Фазы 1 (PostgreSQL + RLS + Redis) можно запускать ограниченный B2B-пилот с 2-3 школами.
