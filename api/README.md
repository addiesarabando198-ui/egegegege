# Teacher WebApp Backend API

Backend API для WebApp режима учителя бота по обществознанию.

## 🚀 Быстрый старт

### Установка зависимостей

```bash
pip install -r requirements.txt
```

### Применение миграций БД

```bash
python3 api/migrations/apply_migration.py
```

### Запуск сервера

#### Режим разработки (с автоперезагрузкой)

```bash
cd api
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

#### Продакшн режим

```bash
cd api
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

Или через Python:

```bash
cd api
python3 app.py
```

## 📚 Документация API

После запуска сервера документация доступна по адресам:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 🔐 Аутентификация

Все API endpoints требуют аутентификацию через Telegram WebApp `initData`.

### Как это работает:

1. Frontend WebApp отправляет `initData` в заголовке `X-Telegram-Init-Data`
2. Backend валидирует подпись с использованием `BOT_TOKEN`
3. Извлекается `user_id` и проверяется профиль учителя
4. Проверяется активность подписки

### Пример запроса:

```bash
curl -X GET "http://localhost:8000/api/teacher/profile" \
  -H "X-Telegram-Init-Data: query_id=...&user=...&hash=..."
```

## 📋 API Endpoints

### Teacher Profile

- `GET /api/teacher/profile` - Получить профиль учителя
- `GET /api/teacher/stats` - Получить статистику учителя

### Students

- `GET /api/teacher/students` - Список учеников (с поиском и пагинацией)
- `GET /api/teacher/students/{student_id}/stats` - Статистика ученика

### Modules

- `GET /api/teacher/modules` - Список доступных модулей

### Questions

- `GET /api/teacher/questions?module={module}` - Список вопросов из модуля
- `GET /api/teacher/questions/{question_id}` - Конкретный вопрос

### Assignments

- `POST /api/teacher/assignments` - Создать задание
- `GET /api/teacher/assignments` - Список заданий (с фильтрацией)

### Drafts

- `POST /api/teacher/drafts` - Сохранить черновик
- `GET /api/teacher/drafts` - Список черновиков
- `PUT /api/teacher/drafts/{draft_id}` - Обновить черновик
- `DELETE /api/teacher/drafts/{draft_id}` - Удалить черновик

## 🏗️ Структура проекта

```
api/
├── app.py                      # Главное FastAPI приложение
├── middleware/
│   ├── __init__.py
│   └── telegram_auth.py        # Аутентификация Telegram WebApp
├── routes/
│   ├── __init__.py
│   ├── teacher.py              # Профиль учителя
│   ├── students.py             # Ученики
│   ├── modules.py              # Модули
│   ├── questions.py            # Вопросы
│   ├── assignments.py          # Задания
│   └── drafts.py               # Черновики
├── schemas/
│   ├── __init__.py
│   ├── teacher.py              # Pydantic схемы для учителя
│   ├── student.py              # Pydantic схемы для учеников
│   ├── module.py               # Pydantic схемы для модулей
│   ├── question.py             # Pydantic схемы для вопросов
│   ├── assignment.py           # Pydantic схемы для заданий
│   └── draft.py                # Pydantic схемы для черновиков
└── migrations/
    ├── 001_create_drafts_table.sql
    └── apply_migration.py
```

## 🔧 Конфигурация

API использует следующие переменные окружения из `.env`:

- `BOT_TOKEN` или `TELEGRAM_BOT_TOKEN` - токен Telegram бота (обязательно)
- `DATABASE_FILE` - путь к SQLite БД (по умолчанию: `quiz_async.db`)
- `DEBUG` - режим отладки (по умолчанию: `False`)

## 🧪 Тестирование

### Health Check

```bash
curl http://localhost:8000/health
```

Ответ:
```json
{
  "status": "healthy",
  "service": "teacher-webapp-api"
}
```

### Проверка корневого endpoint

```bash
curl http://localhost:8000/
```

## 🔒 Безопасность

### Что реализовано:

✅ Валидация Telegram WebApp initData с проверкой подписи
✅ Проверка принадлежности учителя
✅ Проверка активности подписки
✅ CORS настроен только для Telegram доменов
✅ Pydantic валидация всех входящих данных
✅ SQL injection защита через параметризованные запросы

### Рекомендации для продакшена:

- Используйте HTTPS
- Настройте rate limiting
- Добавьте логирование запросов
- Используйте отдельную БД для продакшена
- Настройте мониторинг

## 🐛 Отладка

### Включить debug режим:

В `.env`:
```
DEBUG=true
```

### Логирование:

Все логи выводятся в stdout с уровнем INFO (DEBUG в debug режиме).

### Проверка структуры БД:

```bash
sqlite3 quiz_async.db ".schema assignment_drafts"
```

## 📦 Deployment

### Docker (рекомендуется)

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Запуск:

```bash
docker build -t teacher-api .
docker run -p 8000:8000 --env-file .env teacher-api
```

### Systemd Service

Создайте `/etc/systemd/system/teacher-api.service`:

```ini
[Unit]
Description=Teacher WebApp API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/ege-superbot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

Запуск:

```bash
sudo systemctl enable teacher-api
sudo systemctl start teacher-api
sudo systemctl status teacher-api
```

## 🤝 Интеграция с Frontend

Frontend WebApp должен:

1. Получить `initData` от Telegram WebApp API
2. Отправлять его в заголовке `X-Telegram-Init-Data` при каждом запросе
3. Обрабатывать ошибки 401 (невалидная аутентификация) и 403 (нет доступа)

Пример на JavaScript:

```javascript
// Получаем initData от Telegram
const initData = window.Telegram.WebApp.initData;

// Отправляем запрос
fetch('http://api.example.com/api/teacher/profile', {
  headers: {
    'X-Telegram-Init-Data': initData
  }
})
.then(response => response.json())
.then(data => console.log(data));
```

## 📄 Лицензия

Этот проект является частью бота по обществознанию.

## 👥 Поддержка

При возникновении проблем создайте issue в репозитории проекта.
