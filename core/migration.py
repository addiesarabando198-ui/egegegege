# core/migration.py
"""
Модуль для миграции данных пользователей из общего хранилища practice_stats
в изолированные хранилища для каждого модуля.
"""

import logging
from typing import Dict, Any, Set

logger = logging.getLogger(__name__)


def migrate_to_isolated_storage(user_data: dict, module_name: str, module_data: dict = None):
    """
    Мигрирует данные из общего practice_stats в изолированное хранилище модуля.
    
    Args:
        user_data: Словарь user_data (context.user_data)
        module_name: Имя модуля (task19, task20, task25)
        module_data: Данные модуля с темами для определения принадлежности (опционально)
    
    Returns:
        int: Количество мигрированных тем
    """
    
    # Task24 не нуждается в миграции - у него своя система
    if module_name == 'task24':
        logger.info(f"Module {module_name} doesn't need migration - already isolated")
        return 0
    
    # test_part использует БД, тоже не нуждается в миграции practice_stats
    if module_name == 'test_part':
        logger.info(f"Module {module_name} uses database - no migration needed")
        return 0
    
    isolated_storage_name = f'{module_name}_practice_stats'
    results_storage_name = f'{module_name}_results'
    
    # Если изолированное хранилище уже существует, пропускаем миграцию
    if isolated_storage_name in user_data:
        logger.debug(f"Isolated storage {isolated_storage_name} already exists - skipping migration")
        return 0
    
    # Создаем изолированное хранилище
    user_data[isolated_storage_name] = {}
    
    # Собираем topic_ids для этого модуля
    module_topic_ids = set()
    
    # Из результатов модуля (самый надежный источник)
    if results_storage_name in user_data:
        for result in user_data[results_storage_name]:
            topic_id = result.get('topic_id')
            if topic_id is not None:
                module_topic_ids.add(str(topic_id))
    
    # Из данных модуля, если переданы
    if module_data and 'topics' in module_data:
        for topic in module_data['topics']:
            topic_id = topic.get('id')
            if topic_id is not None:
                module_topic_ids.add(str(topic_id))
    
    migrated_count = 0
    
    # Если есть общий practice_stats и topic_ids для миграции
    if 'practice_stats' in user_data and module_topic_ids:
        for topic_id_str in module_topic_ids:
            if topic_id_str in user_data['practice_stats']:
                # Копируем данные в изолированное хранилище
                topic_data = user_data['practice_stats'][topic_id_str].copy()
                topic_data['module'] = module_name  # Добавляем идентификатор модуля
                user_data[isolated_storage_name][topic_id_str] = topic_data
                migrated_count += 1
    
    # Дополнительная миграция из results если данных нет в practice_stats
    if results_storage_name in user_data:
        for result in user_data[results_storage_name]:
            topic_id_str = str(result.get('topic_id', 0))
            
            # Если этой темы еще нет в изолированном хранилище
            if topic_id_str not in user_data[isolated_storage_name]:
                user_data[isolated_storage_name][topic_id_str] = {
                    'attempts': 1,
                    'scores': [result.get('score', 0)],
                    'last_attempt': result.get('timestamp'),
                    'best_score': result.get('score', 0),
                    'topic_title': result.get('topic_title', result.get('topic', f'Тема {topic_id_str}')),
                    'topic_id': result.get('topic_id'),
                    'module': module_name
                }
                migrated_count += 1
    
    if migrated_count > 0:
        logger.info(f"Migrated {migrated_count} topics to {isolated_storage_name}")
    else:
        logger.debug(f"No topics to migrate for {module_name}")
    
    return migrated_count


def cleanup_old_practice_stats(user_data: dict, force: bool = False) -> bool:
    """
    Удаляет старое общее хранилище practice_stats после миграции.
    
    Args:
        user_data: Словарь user_data (context.user_data)
        force: Принудительное удаление без проверки миграции
    
    Returns:
        bool: True если удаление выполнено, False если нет
    """
    
    if force:
        if 'practice_stats' in user_data:
            old_size = len(user_data.get('practice_stats', {}))
            user_data.pop('practice_stats', None)
            logger.info(f"Force removed old practice_stats with {old_size} entries")
            return True
        return False
    
    # Проверяем, что все модули мигрированы
    required_storages = [
        'task19_practice_stats',
        'task20_practice_stats',
        'task25_practice_stats'
    ]
    
    all_migrated = all(
        storage in user_data 
        for storage in required_storages
    )
    
    if all_migrated and 'practice_stats' in user_data:
        # Безопасно удаляем старое хранилище
        old_size = len(user_data.get('practice_stats', {}))
        user_data.pop('practice_stats', None)
        logger.info(f"Removed old practice_stats with {old_size} entries after successful migration")
        return True
    
    if not all_migrated:
        missing = [s for s in required_storages if s not in user_data]
        logger.warning(f"Cannot remove practice_stats - missing storages: {missing}")
    
    return False


def verify_data_isolation(user_data: dict) -> Dict[str, Any]:
    """
    Проверяет, что данные модулей изолированы правильно.
    
    Args:
        user_data: Словарь user_data (context.user_data)
    
    Returns:
        dict: Отчет о состоянии изоляции
    """
    report = {
        'test_part': {
            'isolated': True,  # Всегда изолирован (использует БД)
            'storage': 'database',
            'entries': 0
        },
        'task19': {
            'isolated': 'task19_practice_stats' in user_data,
            'storage': 'task19_practice_stats',
            'entries': len(user_data.get('task19_practice_stats', {})),
            'has_old_data': False
        },
        'task20': {
            'isolated': 'task20_practice_stats' in user_data,
            'storage': 'task20_practice_stats',
            'entries': len(user_data.get('task20_practice_stats', {})),
            'has_old_data': False
        },
        'task24': {
            'isolated': True,  # Всегда изолирован (своя система)
            'storage': 'practiced_topics + scores_history',
            'entries': len(user_data.get('practiced_topics', set()))
        },
        'task25': {
            'isolated': 'task25_practice_stats' in user_data,
            'storage': 'task25_practice_stats',
            'entries': len(user_data.get('task25_practice_stats', {})),
            'has_old_data': False
        },
        'old_practice_stats': {
            'exists': 'practice_stats' in user_data,
            'entries': len(user_data.get('practice_stats', {})),
            'can_be_removed': False
        }
    }
    
    # Проверяем, можно ли удалить старое хранилище
    all_migrated = all(
        report[module]['isolated'] 
        for module in ['task19', 'task20', 'task25']
    )
    report['old_practice_stats']['can_be_removed'] = (
        all_migrated and report['old_practice_stats']['exists']
    )
    
    # Проверяем наличие старых данных в practice_stats
    if 'practice_stats' in user_data:
        old_stats = user_data['practice_stats']
        
        # Анализируем, какие данные остались в старом хранилище
        for topic_id, data in old_stats.items():
            # Проверяем по метке module если есть
            if 'module' in data:
                module = data['module']
                if module in report:
                    report[module]['has_old_data'] = True
            # Или пытаемся определить по topic_id из results
            else:
                # Проверяем в результатах каждого модуля
                for module in ['task19', 'task20', 'task25']:
                    results_key = f'{module}_results'
                    if results_key in user_data:
                        for result in user_data[results_key]:
                            if str(result.get('topic_id')) == topic_id:
                                report[module]['has_old_data'] = True
                                break
    
    return report


def get_migration_status(user_data: dict) -> str:
    """
    Возвращает текстовый отчет о статусе миграции.
    
    Args:
        user_data: Словарь user_data (context.user_data)
    
    Returns:
        str: Форматированный текст с отчетом
    """
    report = verify_data_isolation(user_data)
    
    lines = ["📊 <b>Статус изоляции данных модулей</b>\n"]
    
    # Статус каждого модуля
    for module in ['test_part', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25']:
        status = report[module]
        if status['isolated']:
            emoji = "✅"
            status_text = "изолирован"
        else:
            emoji = "⚠️"
            status_text = "требует миграции"
        
        lines.append(f"{emoji} <b>{module}:</b> {status_text}")
        lines.append(f"   Хранилище: {status['storage']}")
        if 'entries' in status and status['entries'] > 0:
            lines.append(f"   Записей: {status['entries']}")
        if status.get('has_old_data'):
            lines.append(f"   ⚠️ Есть немигрированные данные")
        lines.append("")
    
    # Статус старого хранилища
    old_stats = report['old_practice_stats']
    if old_stats['exists']:
        lines.append("⚠️ <b>Старое хранилище practice_stats:</b>")
        lines.append(f"   Записей: {old_stats['entries']}")
        if old_stats['can_be_removed']:
            lines.append("   ✅ Можно безопасно удалить")
        else:
            lines.append("   ❌ Нельзя удалить (не все модули мигрированы)")
    else:
        lines.append("✅ <b>Старое хранилище удалено</b>")
    
    return "\n".join(lines)


def migrate_all_modules(user_data: dict, module_data_dict: Dict[str, dict] = None) -> Dict[str, int]:
    """
    Выполняет миграцию для всех модулей разом.
    
    Args:
        user_data: Словарь user_data (context.user_data)
        module_data_dict: Словарь с данными модулей {module_name: module_data}
    
    Returns:
        dict: Количество мигрированных тем для каждого модуля
    """
    modules_to_migrate = ['task19', 'task20', 'task25']
    migration_results = {}
    
    for module_name in modules_to_migrate:
        module_data = None
        if module_data_dict and module_name in module_data_dict:
            module_data = module_data_dict[module_name]
        
        migrated = migrate_to_isolated_storage(user_data, module_name, module_data)
        migration_results[module_name] = migrated
    
    # Проверяем, можно ли очистить старое хранилище
    if all(migration_results.values()) or all(
        f'{m}_practice_stats' in user_data for m in modules_to_migrate
    ):
        cleanup_success = cleanup_old_practice_stats(user_data)
        migration_results['cleanup'] = cleanup_success
    
    return migration_results


# Вспомогательные функции для использования в handlers

def ensure_module_migration(context_or_user_data, module_name: str, module_data: dict = None):
    """
    Гарантирует, что миграция выполнена для модуля при входе.
    Использовать в начале cmd_taskXX и return_to_menu функций.
    
    Args:
        context_or_user_data: Объект контекста ContextTypes.DEFAULT_TYPE или словарь user_data
        module_name: Имя модуля
        module_data: Данные модуля (опционально)
    """
    # Быстрая проверка - если уже мигрировано, ничего не делаем
    if module_name in ['task24', 'test_part']:
        return  # Эти модули не нуждаются в миграции
    
    # Определяем, что нам передали - context или user_data
    if hasattr(context_or_user_data, 'user_data'):
        # Это context объект
        user_data = context_or_user_data.user_data
    else:
        # Это уже user_data словарь
        user_data = context_or_user_data
    
    isolated_storage_name = f'{module_name}_practice_stats'
    if isolated_storage_name not in user_data:
        # Выполняем миграцию
        migrate_to_isolated_storage(user_data, module_name, module_data)


# Для отладки и администрирования

def get_storage_stats(user_data: dict) -> Dict[str, Any]:
    """
    Возвращает статистику по всем хранилищам данных.
    
    Args:
        user_data: Словарь user_data (context.user_data)
    
    Returns:
        dict: Статистика по хранилищам
    """
    stats = {
        'total_keys': len(user_data),
        'storages': {}
    }
    
    # Проверяем все известные хранилища
    storage_patterns = [
        ('task19_results', 'list'),
        ('task19_practice_stats', 'dict'),
        ('task19_achievements', 'set'),
        ('task20_results', 'list'),
        ('task20_practice_stats', 'dict'),
        ('practiced_topics', 'set'),  # task24
        ('scores_history', 'list'),   # task24
        ('task25_results', 'list'),
        ('task25_practice_stats', 'dict'),
        ('task25_achievements', 'set'),
        ('practice_stats', 'dict'),   # старое общее хранилище
    ]
    
    for key, expected_type in storage_patterns:
        if key in user_data:
            value = user_data[key]
            stats['storages'][key] = {
                'type': type(value).__name__,
                'size': len(value) if hasattr(value, '__len__') else 1,
                'expected_type': expected_type,
                'valid': type(value).__name__ == expected_type
            }
    
    # Неизвестные ключи
    known_keys = {k for k, _ in storage_patterns}
    unknown_keys = set(user_data.keys()) - known_keys
    if unknown_keys:
        stats['unknown_keys'] = list(unknown_keys)
    
    return stats