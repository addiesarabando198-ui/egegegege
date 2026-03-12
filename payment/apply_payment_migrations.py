#!/usr/bin/env python3
"""
Универсальный скрипт для применения миграций к базе данных платежей.
Автоматически определяет, какая БД используется.

Использование:
    python apply_payment_migrations.py
"""

import sqlite3
import logging
import shutil
import sys
import os
from pathlib import Path
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_databases():
    """Ищет все возможные базы данных."""
    script_dir = Path(__file__).parent
    parent_dir = script_dir.parent
    
    possible_dbs = [
        # В родительской директории
        parent_dir / 'quiz_async.db',
        parent_dir / 'baza8.db',
        parent_dir / 'subscriptions.db',
        # В текущей директории (payment)
        script_dir / 'subscriptions.db',
        script_dir / 'quiz_async.db',
        # Альтернативные пути
        Path('/opt/ege-bot/quiz_async.db'),
        Path('/opt/ege-bot/subscriptions.db'),
        Path('/opt/ege-bot/baza8.db'),
    ]
    
    found_dbs = []
    for db_path in possible_dbs:
        if db_path.exists():
            found_dbs.append(db_path)
            logger.info(f"✓ Найдена БД: {db_path}")
    
    return found_dbs


def check_payment_tables(db_path):
    """Проверяет наличие таблиц платежей в БД."""
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Проверяем таблицы, связанные с платежами
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND (name LIKE '%payment%' 
                 OR name LIKE '%subscription%' 
                 OR name LIKE '%module%'
                 OR name = 'users')
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        
        # Проверяем количество записей в payments если есть
        payment_count = 0
        if 'payments' in tables:
            cursor.execute("SELECT COUNT(*) FROM payments")
            payment_count = cursor.fetchone()[0]
        
        conn.close()
        
        return tables, payment_count
        
    except Exception as e:
        logger.error(f"Ошибка при проверке {db_path}: {e}")
        return [], 0


def check_column_exists(conn, table_name, column_name):
    """Проверяет существование колонки в таблице."""
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def apply_migrations(db_path):
    """Применяет миграции к базе данных."""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Применение миграций к: {db_path}")
    logger.info(f"{'='*60}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Создаем резервную копию
        backup_path = db_path.with_suffix('.db.backup_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
        shutil.copy2(db_path, backup_path)
        logger.info(f"✓ Создана резервная копия: {backup_path}")
        
        # Начинаем транзакцию
        conn.execute("BEGIN TRANSACTION")
        
        # 1. Создаем/обновляем таблицу payments
        logger.info("\n📋 Проверка таблицы payments...")
        
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='payments'
        """)
        
        if not cursor.fetchone():
            logger.info("  → Создание таблицы payments...")
            cursor.execute("""
                CREATE TABLE payments (
                    payment_id TEXT PRIMARY KEY,
                    order_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    plan_id TEXT NOT NULL,
                    amount_kopecks INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    metadata TEXT DEFAULT '{}',
                    rebill_id TEXT,
                    is_recurrent BOOLEAN DEFAULT 0,
                    auto_renewal_enabled BOOLEAN DEFAULT 0,
                    email TEXT
                )
            """)
            logger.info("  ✓ Таблица payments создана")
        else:
            # МИГРАЦИЯ: Переименование amount в amount_kopecks
            if check_column_exists(conn, 'payments', 'amount') and not check_column_exists(conn, 'payments', 'amount_kopecks'):
                logger.info("  → Миграция колонки amount -> amount_kopecks...")
                try:
                    cursor.execute("ALTER TABLE payments ADD COLUMN amount_kopecks INTEGER")
                    cursor.execute("UPDATE payments SET amount_kopecks = amount WHERE amount_kopecks IS NULL")
                    logger.info("  ✓ Колонка amount_kopecks создана и данные скопированы")
                except sqlite3.OperationalError as e:
                    logger.warning(f"  ! Предупреждение миграции amount_kopecks: {e}")

            # Добавляем недостающие колонки
            columns_to_add = [
                ('metadata', "TEXT DEFAULT '{}'"),
                ('rebill_id', 'TEXT'),
                ('is_recurrent', 'BOOLEAN DEFAULT 0'),
                ('auto_renewal_enabled', 'BOOLEAN DEFAULT 0'),
                ('email', 'TEXT'),
                ('completed_at', 'TIMESTAMP')
            ]

            for column_name, column_def in columns_to_add:
                if not check_column_exists(conn, 'payments', column_name):
                    logger.info(f"  → Добавление колонки {column_name}...")
                    try:
                        cursor.execute(f"ALTER TABLE payments ADD COLUMN {column_name} {column_def}")
                        logger.info(f"  ✓ Колонка {column_name} добавлена")
                    except sqlite3.OperationalError as e:
                        if "duplicate column" not in str(e):
                            logger.warning(f"  ! Предупреждение при добавлении {column_name}: {e}")
                else:
                    logger.info(f"  ✓ Колонка {column_name} уже существует")
        
        # 2. Создаем таблицу user_emails
        logger.info("\n📋 Создание таблицы user_emails...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_emails (
                user_id INTEGER PRIMARY KEY,
                email TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("  ✓ Таблица user_emails готова")
        
        # 3. Создаем таблицу auto_renewal_settings
        logger.info("\n📋 Создание таблицы auto_renewal_settings...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_renewal_settings (
                user_id INTEGER PRIMARY KEY,
                enabled BOOLEAN DEFAULT 0,
                payment_method TEXT CHECK(payment_method IN ('card', 'recurrent')),
                recurrent_token TEXT,
                card_token TEXT,
                next_renewal_date TIMESTAMP,
                failures_count INTEGER DEFAULT 0,
                last_renewal_attempt TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("  ✓ Таблица auto_renewal_settings готова")
        
        # 4. Создаем таблицу auto_renewal_consents
        logger.info("\n📋 Создание таблицы auto_renewal_consents...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_renewal_consents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_id TEXT,
                amount INTEGER,
                period_days INTEGER DEFAULT 30,
                consent_text TEXT NOT NULL,
                consent_checkbox_state BOOLEAN DEFAULT 1,
                ip_address TEXT,
                user_agent TEXT,
                telegram_chat_id INTEGER,
                message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("  ✓ Таблица auto_renewal_consents готова")
        
        # 5. Создаем таблицу webhook_logs
        logger.info("\n📋 Создание таблицы webhook_logs...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payment_id TEXT,
                data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id, status)
            )
        """)
        logger.info("  ✓ Таблица webhook_logs готова (с UNIQUE constraint для предотвращения дубликатов)")
        
        # 6. Создаем таблицу auto_renewal_history
        logger.info("\n📋 Создание таблицы auto_renewal_history...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_renewal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_id TEXT NOT NULL,
                payment_id TEXT,
                order_id TEXT,
                status TEXT CHECK(status IN ('success', 'failed', 'pending')),
                amount INTEGER,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("  ✓ Таблица auto_renewal_history готова")

        # 7. НОВОЕ: Создаем таблицу notification_history
        logger.info("\n📋 Создание таблицы notification_history...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                order_id TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, order_id, notification_type)
            )
        """)
        logger.info("  ✓ Таблица notification_history готова")

        # 8. Создаем индексы
        logger.info("\n📋 Создание индексов...")
        
        indices = [
            ("idx_payments_order", "payments(order_id)"),
            ("idx_payments_user", "payments(user_id)"),
            ("idx_payments_status", "payments(status)"),
            ("idx_user_emails_updated", "user_emails(updated_at)"),
            ("idx_auto_renewal_consents_user", "auto_renewal_consents(user_id, created_at DESC)"),
            ("idx_webhook_logs_order", "webhook_logs(order_id, status)"),
            ("idx_auto_renewal_next_date", "auto_renewal_settings(next_renewal_date)"),
            ("idx_auto_renewal_enabled", "auto_renewal_settings(enabled)"),
            ("idx_renewal_history_user", "auto_renewal_history(user_id, created_at)")
        ]
        
        for index_name, index_def in indices:
            try:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}")
                logger.info(f"  ✓ Индекс {index_name}")
            except Exception as e:
                logger.warning(f"  ! Предупреждение при создании индекса {index_name}: {e}")
        
        # 8. Проверяем и обновляем module_subscriptions если есть
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='module_subscriptions'
        """)
        
        if cursor.fetchone():
            logger.info("\n📋 Проверка таблицы module_subscriptions...")
            # Добавляем колонки если их нет
            if not check_column_exists(conn, 'module_subscriptions', 'payment_id'):
                try:
                    cursor.execute("ALTER TABLE module_subscriptions ADD COLUMN payment_id TEXT")
                    logger.info("  ✓ Добавлена колонка payment_id")
                except:
                    pass
            
            if not check_column_exists(conn, 'module_subscriptions', 'is_trial'):
                try:
                    cursor.execute("ALTER TABLE module_subscriptions ADD COLUMN is_trial BOOLEAN DEFAULT 0")
                    logger.info("  ✓ Добавлена колонка is_trial")
                except:
                    pass
        
        # Коммитим изменения
        conn.commit()
        logger.info(f"\n{'='*60}")
        logger.info("✅ Все миграции успешно применены!")
        logger.info(f"{'='*60}")
        
        # Показываем итоговую статистику
        cursor.execute("SELECT COUNT(*) FROM payments")
        payment_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            ORDER BY name
        """)
        all_tables = cursor.fetchall()
        
        logger.info(f"\n📊 Статистика БД:")
        logger.info(f"  • Всего таблиц: {len(all_tables)}")
        logger.info(f"  • Записей в payments: {payment_count}")
        logger.info(f"  • Резервная копия: {backup_path.name}")
        
    except Exception as e:
        logger.error(f"\n❌ Ошибка при применении миграций: {e}")
        conn.rollback()
        raise
    
    finally:
        conn.close()


def main():
    """Главная функция."""
    
    logger.info("🔍 Поиск баз данных...")
    found_dbs = find_databases()
    
    if not found_dbs:
        logger.error("❌ Не найдено ни одной базы данных!")
        logger.info("Создайте БД или укажите правильный путь.")
        sys.exit(1)
    
    logger.info(f"\n📊 Найдено БД: {len(found_dbs)}")
    
    # Анализируем найденные БД
    db_info = []
    for db_path in found_dbs:
        tables, payment_count = check_payment_tables(db_path)
        db_info.append({
            'path': db_path,
            'tables': tables,
            'payment_count': payment_count,
            'has_payments': 'payments' in tables,
            'has_modules': any('module' in t for t in tables),
            'size': db_path.stat().st_size
        })
    
    # Выбираем БД для миграции
    target_db = None
    
    # Приоритет 1: БД с таблицей payments и записями
    for info in db_info:
        if info['has_payments'] and info['payment_count'] > 0:
            target_db = info['path']
            logger.info(f"\n✓ Выбрана БД с платежами: {target_db}")
            break
    
    # Приоритет 2: БД с таблицей payments без записей
    if not target_db:
        for info in db_info:
            if info['has_payments']:
                target_db = info['path']
                logger.info(f"\n✓ Выбрана БД с таблицей payments: {target_db}")
                break
    
    # Приоритет 3: БД с модулями
    if not target_db:
        for info in db_info:
            if info['has_modules']:
                target_db = info['path']
                logger.info(f"\n✓ Выбрана БД с модулями: {target_db}")
                break
    
    # Приоритет 4: самая большая БД
    if not target_db:
        info = max(db_info, key=lambda x: x['size'])
        target_db = info['path']
        logger.info(f"\n✓ Выбрана самая большая БД: {target_db}")
    
    # Показываем информацию о выбранной БД
    for info in db_info:
        if info['path'] == target_db:
            logger.info(f"\n📋 Информация о БД:")
            logger.info(f"  • Путь: {info['path']}")
            logger.info(f"  • Размер: {info['size'] / 1024:.1f} KB")
            logger.info(f"  • Таблиц: {len(info['tables'])}")
            if info['tables']:
                logger.info(f"  • Основные таблицы: {', '.join(info['tables'][:5])}")
            logger.info(f"  • Записей в payments: {info['payment_count']}")
    
    # Спрашиваем подтверждение
    print(f"\n{'='*60}")
    response = input(f"Применить миграции к {target_db.name}? (y/n): ")
    
    if response.lower() != 'y':
        logger.info("Отменено пользователем")
        sys.exit(0)
    
    # Применяем миграции
    try:
        apply_migrations(target_db)
        logger.info("\n✅ Готово! Теперь можно перезапустить бота.")
        logger.info("Команда: sudo systemctl restart ege-bot")
    except Exception as e:
        logger.error(f"\n❌ Ошибка: {e}")
        logger.info("Восстановите БД из резервной копии если нужно")
        sys.exit(1)


if __name__ == "__main__":
    main()