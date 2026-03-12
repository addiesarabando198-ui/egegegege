# 🚀 Диагностика на сервере

## Шаг 1: Найти базу данных

```bash
# Перейти в директорию бота
cd /opt/ege-bot

# Найти все .db файлы
find . -name "*.db" -type f -exec ls -lh {} \;

# Должен быть файл quiz_async.db с данными (не пустой)
ls -lh quiz_async.db
```

## Шаг 2: Обновить и запустить диагностический скрипт

```bash
# Обновить код с GitHub
git pull origin claude/fix-message-deletion-bug-VVnT9

# Проверить, что скрипт на месте
ls -lh diagnose_payment.py

# Запустить диагностику
python3 diagnose_payment.py 974972138
python3 diagnose_payment.py 1893563949

# Или проверить все проблемные платежи
python3 diagnose_payment.py check_incomplete
```

## Шаг 3: Найти логи

```bash
# Поиск логов бота
find /var/log -name "*ege*" -o -name "*bot*" 2>/dev/null

# Или поиск в директории приложения
find /opt/ege-bot -name "*.log" 2>/dev/null

# Проверить systemd логи если бот запускается как сервис
journalctl -u ege-bot -n 100 --no-pager | grep -E "(974972138|1893563949)"
journalctl -u ege-bot -n 500 --no-pager | grep -i "activate_subscription\|failed"
```

## Шаг 4: Прямая проверка в базе данных

```bash
# Открыть базу данных
sqlite3 quiz_async.db
```

Затем выполнить SQL-запросы:

```sql
-- Проверить, что таблица users существует
.tables

-- Проверить платежи пользователей
SELECT order_id, payment_id, amount, plan_id, status, created_at, completed_at
FROM payments
WHERE user_id IN (974972138, 1893563949)
ORDER BY created_at DESC;

-- Проверить подписки
SELECT user_id, module_code, plan_id, is_active, expires_at, activated_at
FROM module_subscriptions
WHERE user_id IN (974972138, 1893563949)
ORDER BY activated_at DESC;

-- Найти completed платежи БЕЗ подписок
SELECT DISTINCT p.order_id, p.user_id, p.plan_id, p.amount, p.created_at
FROM payments p
LEFT JOIN module_subscriptions ms
  ON p.user_id = ms.user_id
  AND ms.is_active = 1
  AND ms.expires_at > datetime('now')
WHERE p.status = 'completed'
  AND ms.id IS NULL
  AND p.user_id IN (974972138, 1893563949);

-- Выход из sqlite
.quit
```

## Шаг 5: Ручная активация подписки (если нужно)

Если диагностика показала, что платеж completed, но подписок нет:

```sql
-- Открыть БД
sqlite3 quiz_async.db

-- Найти order_id и plan_id платежа
SELECT order_id, plan_id, amount, status, created_at
FROM payments
WHERE user_id = 974972138 AND status = 'completed'
ORDER BY created_at DESC
LIMIT 1;

-- Активировать подписку вручную
-- Пример для package_full (30 дней, модули: test_part, task19, task20, task22, task24, task25)
INSERT OR REPLACE INTO module_subscriptions
(user_id, module_code, plan_id, expires_at, is_active, activated_at, created_at)
VALUES
  (974972138, 'test_part', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task19', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task20', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task22', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task24', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (974972138, 'task25', 'package_full', datetime('now', '+30 days'), 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- Проверить результат
SELECT module_code, plan_id, expires_at, is_active
FROM module_subscriptions
WHERE user_id = 974972138;

-- Повторить для второго пользователя
-- (заменить 974972138 на 1893563949)

.quit
```

## Шаг 6: Перезапустить бота (если нужно)

```bash
# Если бот запускается через systemd
sudo systemctl restart ege-bot

# Или через screen/tmux
# Найти сессию
screen -ls
# Переподключиться
screen -r ege-bot
# Ctrl+C для остановки, затем перезапустить

# Проверить статус
sudo systemctl status ege-bot
```

## Типичные проблемы и решения

### Проблема: "no such table: users"
**Решение:** БД пустая или не та. Найдите правильную БД с данными.

```bash
# Найти все .db файлы и их размеры
find /opt/ege-bot -name "*.db" -exec ls -lh {} \;

# quiz_async.db должна быть не пустой (несколько МБ)
```

### Проблема: "database is locked"
**Решение:** Бот использует БД. Остановите бота или используйте режим read-only.

```bash
# Остановить бота
sudo systemctl stop ege-bot

# Выполнить диагностику
python3 diagnose_payment.py 974972138

# Запустить бота
sudo systemctl start ege-bot
```

### Проблема: Логи не найдены
**Решение:** Бот может писать логи в stdout/stderr. Проверьте journalctl.

```bash
# Логи за последний час
journalctl -u ege-bot --since "1 hour ago" --no-pager

# Логи с ошибками
journalctl -u ege-bot --priority=err --no-pager -n 100

# Логи конкретных пользователей
journalctl -u ege-bot --no-pager | grep -E "(974972138|1893563949)"
```

## Контактная информация для отладки

Если проблема не решается:
1. Соберите вывод диагностического скрипта
2. Соберите SQL-запросы из шага 4
3. Соберите логи из journalctl
4. Предоставьте всю информацию для анализа
