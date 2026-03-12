#!/usr/bin/env python3
"""
Скрипт для проверки наличия OCR обработчиков в коде.
Запустите на сервере, чтобы убедиться, что код обновился.
"""

import os
import sys

def check_file_content(filepath, patterns):
    """Проверяет наличие паттернов в файле"""
    if not os.path.exists(filepath):
        return False, f"Файл {filepath} не найден"

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    missing = []
    for pattern in patterns:
        if pattern not in content:
            missing.append(pattern)

    if missing:
        return False, f"Не найдены паттерны: {', '.join(missing)}"

    return True, "OK"


def main():
    print("=" * 70)
    print("Проверка наличия OCR обработчиков")
    print("=" * 70)

    checks = [
        {
            "file": "task19/plugin.py",
            "patterns": [
                "handle_confirm_ocr",
                "t19_confirm_ocr",
                "handle_edit_ocr",
                "t19_edit_ocr",
                "handle_retry_photo",
                "t19_retry_photo"
            ],
            "description": "OCR обработчики в plugin.py"
        },
        {
            "file": "task19/handlers.py",
            "patterns": [
                "async def handle_confirm_ocr",
                "async def handle_edit_ocr",
                "async def handle_retry_photo",
                "import html"
            ],
            "description": "OCR обработчики в handlers.py"
        },
        {
            "file": "core/vision_service.py",
            "patterns": [
                "html.escape",
                "preview_escaped"
            ],
            "description": "HTML escaping в vision_service.py"
        }
    ]

    all_ok = True

    for check in checks:
        print(f"\n✓ Проверяю: {check['description']}")
        print(f"  Файл: {check['file']}")

        ok, msg = check_file_content(check['file'], check['patterns'])

        if ok:
            print(f"  ✅ {msg}")
        else:
            print(f"  ❌ {msg}")
            all_ok = False

    print("\n" + "=" * 70)

    if all_ok:
        print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
        print("\nКод обновлен корректно!")
        print("\nТеперь нужно перезапустить бота:")
        print("  sudo systemctl restart your-bot.service")
        return 0
    else:
        print("❌ НЕКОТОРЫЕ ПРОВЕРКИ НЕ ПРОЙДЕНЫ")
        print("\nКод не обновился! Выполните:")
        print("  cd /path/to/ege-superbot")
        print("  git fetch origin")
        print("  git checkout claude/add-ocr-recognition-011CUm1kKgU5nc35gTt5hnBS")
        print("  git pull origin claude/add-ocr-recognition-011CUm1kKgU5nc35gTt5hnBS")
        print("  sudo systemctl restart your-bot.service")
        return 1


if __name__ == "__main__":
    sys.exit(main())
