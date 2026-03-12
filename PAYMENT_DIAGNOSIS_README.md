# 🔍 Диагностика проблем с платежной системой

## Проблема

Пользователи **974972138** и **1893563949** оформили подписку, но после оплаты полный доступ к модулям не был предоставлен.

## ⚡ Быстрая диагностика на сервере

### 1. Запуск диагностического скрипта

```bash
# Проверка конкретного пользователя
python diagnose_payment.py 974972138
python diagnose_payment.py 1893563949

# Поиск всех несогласованных платежей
python diagnose_payment.py check_incomplete
```

### 2. Проверка логов бота

```bash
# Поиск ошибок активации для конкретных пользователей
grep -E "(974972138|1893563949)" /var/log/ege-superbot/bot.log | grep -i "error\|failed\|warning"

# Поиск проблем с webhook
grep "webhook" /var/log/ege-superbot/bot.log | grep -E "(974972138|1893563949)"

# Поиск ошибок активации подписки
grep "activate_subscription\|Failed to activate" /var/log/ege-superbot/bot.log | tail -50
```

### 3. Прямая проверка в базе данных

```bash
sqlite3 quiz_async.db
```

```sql
-- Проверить платежи пользователя
SELECT order_id, payment_id, amount, plan_id, status, created_at, completed_at
FROM payments
WHERE user_id = 974972138 OR user_id = 1893563949
ORDER BY created_at DESC;

-- Проверить активные подписки
SELECT user_id, module_code, plan_id, is_active, expires_at, activated_at
FROM module_subscriptions
WHERE user_id IN (974972138, 1893563949)
ORDER BY activated_at DESC;

-- Найти completed платежи без подписок
SELECT DISTINCT p.order_id, p.user_id, p.plan_id, p.amount, p.created_at
FROM payments p
LEFT JOIN module_subscriptions ms
  ON p.user_id = ms.user_id
  AND ms.is_active = 1
  AND ms.expires_at > datetime('now')
WHERE p.status = 'completed'
  AND ms.id IS NULL
ORDER BY p.created_at DESC;

-- Проверить webhook logs
SELECT order_id, timestamp, payment_status, raw_data
FROM webhook_logs
WHERE order_id IN (
  SELECT order_id FROM payments WHERE user_id IN (974972138, 1893563949)
)
ORDER BY timestamp DESC;
```

---

## 🐛 Найденные баги и проблемы

### 1. ⚠️ Недостаточное логирование ошибок (payment/webhook.py:334-367)

**Проблема:**
```python
if success:
    logger.info("Payment activated successfully")
    await notify_user_success_safe(bot, order_id)
else:
    logger.error(f"Failed to activate subscription for order {order_id}")

    # Уведомление админа только если это не дубликат
    if bot and not is_duplicate:
        await notify_admin_payment_activation_failed(...)

    # ⚠️ ПРОБЛЕМА: Для дубликатов админ НЕ получит уведомление,
    # даже если активация реально не удалась
    if is_duplicate:
        return web.Response(text='OK')  # Возвращаем OK без уведомления админа
```

**Последствия:**
- Если webhook дублируется, но активация реально не удалась, админ не получит уведомление
- Платежная система получит "OK", но подписка не будет активирована

**Решение:**
```python
# Всегда проверяем, активирована ли подписка реально
if not success:
    # Проверить в БД, есть ли активные подписки
    has_active_subs = await check_has_active_subscriptions(order_id)

    if not has_active_subs:
        # ВСЕГДА уведомляем админа если подписки нет
        await notify_admin_payment_activation_failed(...)
```

---

### 2. ⚠️ Race condition при создании профиля учителя (subscription_manager.py:1785-1789)

**Проблема:**
```python
if plan.get('type') == 'teacher':
    try:
        # Создание профиля учителя
        teacher_profile = await create_teacher_profile(user_id, ...)

        # Обновление подписки
        await conn.execute("UPDATE teacher_profiles SET ...")

    except Exception as e:
        logger.error(f"❌ Error processing teacher subscription: {e}")
        # ⚠️ НЕТ ROLLBACK модульной подписки!
        # Подписка в module_subscriptions уже активирована
```

**Последствия:**
- Пользователь оплатил подписку учителя
- Подписка в `module_subscriptions` активирована
- Профиль учителя не создан или не обновлен
- Функционал учителя не работает

**Признаки:**
- Пользователь видит активную подписку, но не может зайти в режим учителя
- В логах: `Error processing teacher subscription`
- В БД: есть записи в `module_subscriptions`, но нет в `teacher_profiles`

---

### 3. ⚠️ Неполная валидация плана учителя (subscription_manager.py:1707-1711)

**Проблема:**
```python
from payment.config import is_teacher_plan
if not is_teacher_plan(plan_id):
    logger.error(f"❌ Invalid teacher plan_id: {plan_id}. Skipping teacher profile creation.")
    # ⚠️ НЕ ПРЕРЫВАЕТ выполнение - подписка активируется БЕЗ профиля учителя!
```

**Последствия:**
- Если `plan_id` неправильный, подписка активируется, но профиль учителя не создается
- Пользователь платит за учительский план, но не получает функционал

---

### 4. ⚠️ Неправильная нормализация модулей (subscription_manager.py:2066-2068)

**Проблема:**
```python
if not normalized_modules:
    logger.error(f"No valid modules found in {modules}")
    return False  # ⚠️ Активация НЕ УДАЛАСЬ
```

**Причины:**
- Модули переданы в неожиданном формате (например, с пробелами, в верхнем регистре)
- Названия модулей не соответствуют маппингу
- Ошибка в metadata платежа

**Признаки:**
- В логах: `No valid modules found in ...`
- Платеж имеет статус `completed`
- Но подписки в `module_subscriptions` НЕТ

---

### 5. ⚠️ Отсутствие модулей в конфигурации плана (subscription_manager.py:1549-1551)

**Проблема:**
```python
modules = plan.get('modules', [])

if not modules:
    logger.error(f"Plan {plan_id} has no modules defined")
    return False  # ⚠️ Активация НЕ УДАЛАСЬ
```

**Причины:**
- План существует в `SUBSCRIPTION_PLANS`, но у него нет ключа `modules`
- Конфигурация повреждена или устарела

**Проверка:**
```python
from payment.config import SUBSCRIPTION_PLANS
plan = SUBSCRIPTION_PLANS.get('package_full')
print(plan.get('modules'))  # Должен вывести список модулей
```

---

### 6. ⚠️ Timeout транзакции (subscription_manager.py:1441)

**Проблема:**
```python
async with aiosqlite.connect(self.database_file, timeout=30.0) as conn:
    await conn.execute("BEGIN EXCLUSIVE TRANSACTION")
    # Если обработка занимает > 30 секунд -> OperationalError
```

**Причины:**
- Долгая обработка создания профиля учителя
- Медленные запросы к БД
- Блокировка БД другими процессами

**Признаки:**
- В логах: `OperationalError: database is locked`
- Webhook возвращает ошибку 500
- Платежная система повторяет webhook многократно

---

## 🔧 Рекомендуемые исправления

### Исправление #1: Улучшить логирование и уведомления

**Файл:** `payment/webhook.py`

```python
async def handle_webhook(request):
    # ... существующий код ...

    if status in ['AUTHORIZED', 'CONFIRMED']:
        success = await subscription_manager.activate_subscription(order_id, payment_id)

        if success:
            # Дополнительная проверка: есть ли реально активные подписки?
            has_subscriptions = await verify_active_subscriptions(user_id)

            if not has_subscriptions:
                logger.error(f"⚠️ WARNING: Activation returned success but no active subscriptions found for user {user_id}, order {order_id}")
                await notify_admin_inconsistent_activation(bot, order_id, user_id)
            else:
                logger.info(f"✅ Payment activated and verified for user {user_id}, order {order_id}")
                await notify_user_success_safe(bot, order_id)
        else:
            logger.error(f"❌ Failed to activate subscription for order {order_id}, user {user_id}")
            await notify_admin_payment_activation_failed(bot, order_id, user_id)
```

---

### Исправление #2: Rollback при ошибке создания профиля учителя

**Файл:** `payment/subscription_manager.py`

```python
async def _activate_standard_plan(self, conn, user_id, plan_id, duration_months):
    # ... существующий код активации модулей ...

    # Обработка учительских подписок
    if plan.get('type') == 'teacher':
        try:
            # Весь код создания профиля учителя
            ...
        except Exception as e:
            logger.error(f"❌ Error processing teacher subscription: {e}")
            # ВАЖНО: Пробрасываем исключение, чтобы транзакция откатилась
            raise  # <--- ДОБАВИТЬ ЭТО!

    return True
```

---

### Исправление #3: Добавить детальное логирование активации

**Файл:** `payment/subscription_manager.py`

```python
async def activate_subscription(self, order_id, payment_id=None):
    logger.info(f"🔵 Starting activation for order {order_id}, payment {payment_id}")

    try:
        # ... существующий код ...

        # После активации модулей
        if success:
            # Логируем, какие модули были активированы
            cursor = await conn.execute(
                """SELECT module_code, expires_at FROM module_subscriptions
                   WHERE user_id = ? AND is_active = 1""",
                (user_id,)
            )
            active_modules = await cursor.fetchall()
            logger.info(f"✅ Activated modules for user {user_id}: {[m[0] for m in active_modules]}")

        return success
    except Exception as e:
        logger.error(f"❌ CRITICAL: Activation failed for order {order_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise
```

---

### Исправление #4: Периодическая проверка несогласованности

Добавить в cron или scheduler:

```python
# payment/consistency_checker.py

async def check_payment_consistency():
    """
    Периодическая задача для поиска платежей без подписок
    """
    async with aiosqlite.connect(DATABASE_FILE) as conn:
        cursor = await conn.execute("""
            SELECT DISTINCT p.order_id, p.user_id, p.plan_id, p.amount
            FROM payments p
            LEFT JOIN module_subscriptions ms
              ON p.user_id = ms.user_id
              AND ms.is_active = 1
              AND ms.expires_at > datetime('now')
            WHERE p.status = 'completed'
              AND p.completed_at > datetime('now', '-7 days')  -- Только последние 7 дней
              AND ms.id IS NULL
        """)

        inconsistent_payments = await cursor.fetchall()

        if inconsistent_payments:
            logger.warning(f"⚠️ Found {len(inconsistent_payments)} payments without subscriptions")
            for payment in inconsistent_payments:
                order_id, user_id, plan_id, amount = payment
                logger.warning(f"  - Order {order_id}: user {user_id}, plan {plan_id}, {amount}₽")

                # Уведомить админа
                await notify_admin_inconsistent_payment(order_id, user_id, plan_id)

                # Попытаться повторно активировать
                try:
                    success = await subscription_manager.activate_subscription(order_id)
                    if success:
                        logger.info(f"✅ Successfully re-activated subscription for order {order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to re-activate subscription for order {order_id}: {e}")
```

---

## 📋 Чек-лист диагностики для конкретных пользователей

### Для пользователей 974972138 и 1893563949:

- [ ] Запустить `python diagnose_payment.py 974972138`
- [ ] Запустить `python diagnose_payment.py 1893563949`
- [ ] Проверить статус платежей в БД (должен быть `completed`)
- [ ] Проверить наличие записей в `module_subscriptions` (должны быть активные подписки)
- [ ] Проверить webhook_logs (должны быть записи с AUTHORIZED/CONFIRMED)
- [ ] Проверить логи бота на наличие ошибок активации
- [ ] Если это учительские планы - проверить наличие записей в `teacher_profiles`
- [ ] Проверить, что `expires_at` в будущем
- [ ] Проверить, что `is_active = 1`

---

## 🚀 Ручное исправление (если автоматическая активация не сработала)

```sql
-- 1. Найти order_id платежа пользователя
SELECT order_id, plan_id, amount, status, created_at
FROM payments
WHERE user_id = 974972138 AND status = 'completed'
ORDER BY created_at DESC
LIMIT 1;

-- 2. Получить plan_id и проверить модули плана
-- (смотрим в payment/config.py какие модули должны быть в плане)

-- 3. Вручную активировать подписку
-- Пример для package_full (модули: test_part, task19, task20, task22, task24, task25)
INSERT OR REPLACE INTO module_subscriptions
(user_id, module_code, plan_id, expires_at, is_active, activated_at, created_at)
VALUES
  (974972138, 'test_part', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task19', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task20', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task22', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task24', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task25', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- 4. Если это учительский план - создать профиль учителя
INSERT OR IGNORE INTO teacher_profiles
(teacher_id, teacher_code, name, has_active_subscription, subscription_tier, subscription_expires, created_at, updated_at)
VALUES
  (974972138, 't_' || abs(random() % 100000000), 'Teacher', 1, 'teacher_basic', datetime('now', '+30 days'), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- 5. Проверить результат
SELECT module_code, plan_id, expires_at, is_active
FROM module_subscriptions
WHERE user_id = 974972138;
```

---

## 📞 Следующие шаги

1. Запустить диагностику для обоих пользователей
2. Проверить логи на ошибки
3. Если подписки отсутствуют - активировать вручную
4. Применить исправления кода
5. Добавить периодическую проверку несогласованности
6. Настроить алерты для админа при проблемах активации
