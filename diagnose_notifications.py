#!/usr/bin/env python3
"""
Диагностика системы retention уведомлений.
Проверяет почему не отправляются уведомления.
"""

import sqlite3
from datetime import datetime, timezone


DATABASE_FILE = "quiz_async.db"


def diagnose():
    """Диагностика системы уведомлений"""

    print("=" * 60)
    print("ДИАГНОСТИКА СИСТЕМЫ RETENTION УВЕДОМЛЕНИЙ")
    print("=" * 60)
    print()

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # 1. Общая статистика базы
    print("📊 ОБЩАЯ СТАТИСТИКА:")

    # Всего пользователей
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    print(f"  Всего пользователей: {total_users}")

    # Пользователи с активностью
    cursor.execute("""
        SELECT COUNT(DISTINCT user_id) FROM answered_questions
    """)
    active_users = cursor.fetchone()[0]
    print(f"  С активностью: {active_users}")

    # Пользователи с подпиской
    now = datetime.now(timezone.utc)
    cursor.execute("""
        SELECT COUNT(DISTINCT user_id) FROM user_subscriptions
        WHERE expires_at > ?
    """, (now.isoformat(),))
    subscribed_users = cursor.fetchone()[0]
    print(f"  С активной подпиской: {subscribed_users}")

    print()

    # 2. Статистика по активности (последние 30 дней)
    print("📈 АКТИВНОСТЬ (последние 30 дней):")
    cursor.execute("""
        SELECT COUNT(DISTINCT user_id) FROM answered_questions
        WHERE timestamp > datetime('now', '-30 days')
    """)
    active_30d = cursor.fetchone()[0]
    print(f"  Активных за 30 дней: {active_30d}")

    cursor.execute("""
        SELECT COUNT(DISTINCT user_id) FROM answered_questions
        WHERE timestamp > datetime('now', '-7 days')
    """)
    active_7d = cursor.fetchone()[0]
    print(f"  Активных за 7 дней: {active_7d}")

    cursor.execute("""
        SELECT COUNT(DISTINCT user_id) FROM answered_questions
        WHERE timestamp > datetime('now', '-1 day')
    """)
    active_1d = cursor.fetchone()[0]
    print(f"  Активных за 24 часа: {active_1d}")

    print()

    # 3. Потенциальные кандидаты для уведомлений
    print("🎯 ПОТЕНЦИАЛЬНЫЕ КАНДИДАТЫ:")

    # BOUNCED (зарегистрировались недавно, но не активны)
    cursor.execute("""
        SELECT COUNT(*) FROM users u
        WHERE u.created_at > datetime('now', '-7 days')
        AND NOT EXISTS (
            SELECT 1 FROM answered_questions aq
            WHERE aq.user_id = u.user_id
        )
    """)
    bounced = cursor.fetchone()[0]
    print(f"  BOUNCED (новые без активности): {bounced}")

    # CURIOUS (были активны, но давно не заходили, без подписки)
    cursor.execute("""
        SELECT COUNT(DISTINCT aq.user_id) FROM answered_questions aq
        WHERE aq.timestamp < datetime('now', '-3 days')
        AND aq.user_id NOT IN (
            SELECT user_id FROM user_subscriptions
            WHERE expires_at > ?
        )
        AND aq.user_id IN (
            SELECT user_id FROM answered_questions
            GROUP BY user_id HAVING COUNT(*) >= 3
        )
    """, (now.isoformat(),))
    curious = cursor.fetchone()[0]
    print(f"  CURIOUS (неактивны 3+ дня, без подписки): {curious}")

    # ACTIVE_FREE (активны, без подписки)
    cursor.execute("""
        SELECT COUNT(DISTINCT aq.user_id) FROM answered_questions aq
        WHERE aq.timestamp > datetime('now', '-7 days')
        AND aq.user_id NOT IN (
            SELECT user_id FROM user_subscriptions
            WHERE expires_at > ?
        )
    """, (now.isoformat(),))
    active_free = cursor.fetchone()[0]
    print(f"  ACTIVE_FREE (активны, без подписки): {active_free}")

    print()

    # 4. Настройки уведомлений
    print("⚙️  НАСТРОЙКИ УВЕДОМЛЕНИЙ:")

    # Сколько отключили уведомления
    cursor.execute("""
        SELECT COUNT(*) FROM notification_preferences WHERE enabled = 0
    """)
    disabled_count = cursor.fetchone()[0]
    print(f"  Отключили уведомления: {disabled_count}")

    # Причины отключения
    cursor.execute("""
        SELECT disabled_reason, COUNT(*)
        FROM notification_preferences
        WHERE enabled = 0
        GROUP BY disabled_reason
    """)
    reasons = cursor.fetchall()
    if reasons:
        for reason, count in reasons:
            print(f"    {reason or 'user_choice'}: {count}")

    print()

    # 5. История отправки
    print("📨 ИСТОРИЯ ОТПРАВКИ (последние 7 дней):")
    cursor.execute("""
        SELECT segment, COUNT(*)
        FROM notification_log
        WHERE sent_at > datetime('now', '-7 days')
        GROUP BY segment
    """)
    sent = cursor.fetchall()
    if sent:
        for segment, count in sent:
            print(f"  {segment}: {count} уведомлений")
    else:
        print("  ⚠️  Нет отправленных уведомлений за последние 7 дней")

    # Всего за всё время
    cursor.execute("SELECT COUNT(*) FROM notification_log")
    total_sent = cursor.fetchone()[0]
    print(f"  Всего за всё время: {total_sent}")

    print()

    # 6. Активные cooldown
    print("⏱️  АКТИВНЫЕ COOLDOWN:")
    cursor.execute("""
        SELECT trigger, COUNT(*)
        FROM notification_cooldown
        WHERE cooldown_until > datetime('now')
        GROUP BY trigger
    """)
    cooldowns = cursor.fetchall()
    if cooldowns:
        for trigger, count in cooldowns:
            print(f"  {trigger}: {count} пользователей")
    else:
        print("  Нет активных cooldown")

    print()

    # 7. Примеры пользователей
    print("🔍 ПРИМЕРЫ ПОЛЬЗОВАТЕЛЕЙ:")

    # Пример BOUNCED пользователя
    cursor.execute("""
        SELECT u.user_id, u.created_at FROM users u
        WHERE u.created_at > datetime('now', '-7 days')
        AND NOT EXISTS (
            SELECT 1 FROM answered_questions aq
            WHERE aq.user_id = u.user_id
        )
        LIMIT 1
    """)
    bounced_example = cursor.fetchone()
    if bounced_example:
        user_id, created_at = bounced_example
        print(f"\n  BOUNCED пользователь {user_id}:")
        print(f"    Зарегистрирован: {created_at}")

        # Проверка уведомлений
        cursor.execute("""
            SELECT enabled FROM notification_preferences WHERE user_id = ?
        """, (user_id,))
        pref = cursor.fetchone()
        enabled = pref[0] if pref else True
        print(f"    Уведомления включены: {enabled}")

        # Cooldown
        cursor.execute("""
            SELECT COUNT(*) FROM notification_cooldown
            WHERE user_id = ? AND cooldown_until > datetime('now')
        """, (user_id,))
        has_cooldown = cursor.fetchone()[0] > 0
        print(f"    Есть cooldown: {has_cooldown}")

    # Пример CURIOUS пользователя
    cursor.execute("""
        SELECT aq.user_id, MAX(aq.timestamp) as last_activity FROM answered_questions aq
        WHERE aq.timestamp < datetime('now', '-3 days')
        AND aq.user_id NOT IN (
            SELECT user_id FROM user_subscriptions
            WHERE expires_at > ?
        )
        GROUP BY aq.user_id
        HAVING COUNT(*) >= 3
        LIMIT 1
    """, (now.isoformat(),))
    curious_example = cursor.fetchone()
    if curious_example:
        user_id, last_activity = curious_example
        print(f"\n  CURIOUS пользователь {user_id}:")
        print(f"    Последняя активность: {last_activity}")

        # Проверка уведомлений
        cursor.execute("""
            SELECT enabled FROM notification_preferences WHERE user_id = ?
        """, (user_id,))
        pref = cursor.fetchone()
        enabled = pref[0] if pref else True
        print(f"    Уведомления включены: {enabled}")

        # Недавние уведомления
        cursor.execute("""
            SELECT trigger, sent_at FROM notification_log
            WHERE user_id = ? AND sent_at > datetime('now', '-7 days')
            ORDER BY sent_at DESC
        """, (user_id,))
        recent = cursor.fetchall()
        if recent:
            print(f"    Недавние уведомления:")
            for trigger, sent_at in recent:
                print(f"      {trigger} - {sent_at}")
        else:
            print(f"    Недавних уведомлений нет")

    print()
    print("=" * 60)
    print("✅ Диагностика завершена")
    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    diagnose()
