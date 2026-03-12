#!/bin/bash
# Скрипт для проверки структуры базы данных

echo "=========================================="
echo "ПРОВЕРКА СТРУКТУРЫ БАЗЫ ДАННЫХ"
echo "=========================================="
echo ""

DB_FILE="quiz_async.db"

if [ ! -f "$DB_FILE" ]; then
    echo "❌ Файл $DB_FILE не найден!"
    exit 1
fi

echo "✅ База данных: $DB_FILE ($(ls -lh $DB_FILE | awk '{print $5}'))"
echo ""

echo "=========================================="
echo "1. СПИСОК ВСЕХ ТАБЛИЦ"
echo "=========================================="
sqlite3 "$DB_FILE" ".tables"
echo ""

echo "=========================================="
echo "2. ТАБЛИЦЫ, СВЯЗАННЫЕ С ПЛАТЕЖАМИ"
echo "=========================================="
sqlite3 "$DB_FILE" ".tables" | tr ' ' '\n' | grep -i "payment\|subscription\|module\|user\|teacher" || echo "Не найдено"
echo ""

echo "=========================================="
echo "3. СТРУКТУРА ТАБЛИЦЫ PAYMENTS (если есть)"
echo "=========================================="
sqlite3 "$DB_FILE" ".schema payments" 2>/dev/null || echo "Таблица payments не найдена"
echo ""

echo "=========================================="
echo "4. СТРУКТУРА ТАБЛИЦЫ MODULE_SUBSCRIPTIONS (если есть)"
echo "=========================================="
sqlite3 "$DB_FILE" ".schema module_subscriptions" 2>/dev/null || echo "Таблица module_subscriptions не найдена"
echo ""

echo "=========================================="
echo "5. СТРУКТУРА ТАБЛИЦЫ USERS (если есть)"
echo "=========================================="
sqlite3 "$DB_FILE" ".schema users" 2>/dev/null || echo "Таблица users не найдена"
echo ""

echo "=========================================="
echo "6. ПОИСК ПЛАТЕЖЕЙ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ"
echo "=========================================="
echo "Ищем платежи для user_id 974972138 и 1893563949..."
echo ""

# Проверяем таблицу payments
result=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM payments WHERE user_id IN (974972138, 1893563949)" 2>/dev/null)
if [ ! -z "$result" ] && [ "$result" != "0" ]; then
    echo "✅ Найдено в таблице payments: $result платежей"
    echo "Детали:"
    sqlite3 "$DB_FILE" "SELECT order_id, user_id, plan_id, COALESCE(amount, amount_kopecks/100) as amount_rub, status, created_at, completed_at FROM payments WHERE user_id IN (974972138, 1893563949) ORDER BY created_at DESC LIMIT 10"
    echo ""
else
    echo "ℹ️  Платежи для этих пользователей не найдены"
    echo ""
fi

echo "=========================================="
echo "7. ПОИСК ПОДПИСОК ДЛЯ ПОЛЬЗОВАТЕЛЕЙ"
echo "=========================================="
echo "Ищем подписки для user_id 974972138 и 1893563949..."
echo ""

# Проверяем таблицу module_subscriptions
result=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM module_subscriptions WHERE user_id IN (974972138, 1893563949)" 2>/dev/null)
if [ ! -z "$result" ] && [ "$result" != "0" ]; then
    echo "✅ Найдено в таблице module_subscriptions: $result подписок"
    echo "Детали:"
    sqlite3 "$DB_FILE" "SELECT user_id, module_code, plan_id, is_active, expires_at, created_at FROM module_subscriptions WHERE user_id IN (974972138, 1893563949) ORDER BY created_at DESC LIMIT 20"
    echo ""
else
    echo "ℹ️  Подписки для этих пользователей не найдены"
    echo ""
fi

echo "=========================================="
echo "ГОТОВО!"
echo "=========================================="

