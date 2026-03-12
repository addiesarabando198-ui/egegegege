"""
Десктопное приложение для составления расписания
Запускается как нативное окно (не в браузере)
"""

import threading
import sys
import os
import time

# Добавляем путь к модулю
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_flask():
    """Запуск Flask-сервера в фоновом режиме"""
    # Подавляем вывод Flask в консоль
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    from app import app
    app.run(debug=False, host='127.0.0.1', port=5000, use_reloader=False, threaded=True)


def main():
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Даём Flask время на запуск
    time.sleep(1.5)

    try:
        import webview

        # Создаём нативное окно
        window = webview.create_window(
            title='Генератор расписания - Школа Покровский квартал',
            url='http://127.0.0.1:5000',
            width=1400,
            height=900,
            resizable=True,
            min_size=(1000, 700),
            confirm_close=True,
            text_select=True
        )

        # Запускаем GUI (пробуем разные движки)
        try:
            webview.start(debug=False)
        except Exception:
            # Если не получилось - пробуем с другим движком
            webview.start(debug=False, gui='cef')

    except ImportError:
        # Если pywebview не установлен - открываем в браузере
        import webbrowser
        print("\n  Открываю в браузере...")
        webbrowser.open('http://127.0.0.1:5000')

        # Держим сервер запущенным
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    except Exception as e:
        # При любой другой ошибке - тоже в браузер
        import webbrowser
        print(f"\n  Ошибка окна: {e}")
        print("  Открываю в браузере...")
        webbrowser.open('http://127.0.0.1:5000')

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
