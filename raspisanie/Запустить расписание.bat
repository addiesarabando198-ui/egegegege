@echo off
chcp 65001 >nul 2>&1
title Генератор расписания

REM ============================================================
REM   ГЕНЕРАТОР РАСПИСАНИЯ - Школа Покровский квартал
REM   Просто запустите этот файл двойным кликом!
REM ============================================================

cd /d "%~dp0"

echo.
echo   ╔══════════════════════════════════════════════════════╗
echo   ║     ГЕНЕРАТОР РАСПИСАНИЯ                             ║
echo   ║     Школа Покровский квартал                         ║
echo   ╚══════════════════════════════════════════════════════╝
echo.
echo   Подождите, идёт запуск программы...
echo.

REM Проверяем наличие Python
where python >nul 2>&1
if errorlevel 1 (
    echo   [!] Python не установлен на компьютере.
    echo.
    echo   Для работы программы необходим Python.
    echo   Скачайте его с сайта: https://python.org/downloads
    echo.
    echo   При установке обязательно поставьте галочку:
    echo   [X] Add Python to PATH
    echo.
    pause
    exit /b 1
)

REM Проверяем и устанавливаем зависимости (тихо, без лишнего вывода)
echo   Проверка компонентов...

pip show flask >nul 2>&1
if errorlevel 1 (
    echo   Установка Flask...
    pip install flask flask-sqlalchemy >nul 2>&1
)

pip show pywebview >nul 2>&1
if errorlevel 1 (
    echo   Установка оконного модуля...
    pip install pywebview >nul 2>&1
)

pip show pandas >nul 2>&1
if errorlevel 1 (
    echo   Установка модуля для Excel...
    pip install pandas openpyxl >nul 2>&1
)

echo   Все компоненты готовы!
echo.
echo   ════════════════════════════════════════════════════════
echo   Программа запускается. Пожалуйста, подождите...
echo   ════════════════════════════════════════════════════════
echo.

REM Запускаем приложение
python run_desktop.py 2>nul

if errorlevel 1 (
    echo.
    echo   [!] Ошибка при запуске в оконном режиме.
    echo   Пробуем открыть в браузере...
    echo.
    start http://localhost:5000
    python app.py
)

pause
