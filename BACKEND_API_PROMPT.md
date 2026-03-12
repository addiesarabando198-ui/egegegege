# 🚀 Промпт для создания Backend API для WebApp учителя

## 📋 Контекст

Frontend WebApp для режима учителя полностью завершен. Теперь нужно создать Backend API endpoints, чтобы WebApp мог взаимодействовать с существующей системой бота.

**Что уже готово:**
- ✅ Frontend: HTML, CSS, JavaScript (4000+ строк)
- ✅ Архитектурная документация: `WebApp/TEACHER_WEBAPP_ARCHITECTURE.md`
- ✅ Существующие сервисы: `teacher_mode/services/`
- ✅ Существующие модели: `teacher_mode/models.py`

**Что нужно создать:**
- ⏳ FastAPI приложение для WebApp
- ⏳ API Routes для заданий, учеников, вопросов
- ⏳ Middleware для Telegram WebApp аутентификации
- ⏳ Pydantic schemas для валидации
- ⏳ Интеграция с существующими сервисами

---

## 🎯 Задача

Создай Backend API для WebApp учителя на FastAPI, который будет обрабатывать запросы от Frontend.

### Требования:

1. **Безопасность**: Валидация `initData` от Telegram WebApp
2. **Интеграция**: Использовать существующие сервисы из `teacher_mode/services/`
3. **Валидация**: Pydantic schemas для всех запросов/ответов
4. **Совместимость**: Работать с существующими моделями SQLAlchemy

---

## 📁 Структура файлов для создания

Создай следующую структуру:

```
api/
├── __init__.py
├── app.py                      # FastAPI приложение (главный файл)
├── middleware/
│   ├── __init__.py
│   └── telegram_auth.py        # Middleware для валидации Telegram initData
├── routes/
│   ├── __init__.py
│   ├── teacher.py              # GET /profile, /stats
│   ├── students.py             # GET /students, /students/{id}/stats
│   ├── modules.py              # GET /modules
│   ├── questions.py            # GET /questions
│   ├── assignments.py          # POST /assignments, GET /assignments
│   └── drafts.py               # POST /drafts, GET /drafts, DELETE /drafts/{id}
└── schemas/
    ├── __init__.py
    ├── teacher.py              # TeacherProfile, TeacherStats
    ├── student.py              # Student, StudentStats
    ├── module.py               # Module
    ├── question.py             # Question
    ├── assignment.py           # CreateAssignment, Assignment
    └── draft.py                # Draft
```

---

## 🔌 API Endpoints (детальное описание)

### 1. Teacher Profile

**Endpoint:** `GET /api/teacher/profile`

**Аутентификация:** Required (Telegram initData)

**Response:**
```json
{
  "teacher_id": 123,
  "user_id": 987654321,
  "name": "Иван Иванович",
  "username": "ivan_teacher",
  "subscription": {
    "tier": "premium",
    "expires_at": "2025-12-31T23:59:59Z"
  },
  "stats": {
    "total_students": 45,
    "total_assignments": 120,
    "active_assignments": 15
  }
}
```

**Логика:**
```python
# Используй существующий сервис
from teacher_mode.services.teacher_service import TeacherService

teacher = await TeacherService.get_by_user_id(user_id)
stats = await TeacherService.get_stats(teacher.id)
```

---

### 2. Students List

**Endpoint:** `GET /api/teacher/students`

**Query Parameters:**
- `search` (optional): Поиск по имени/username
- `limit` (default: 50): Количество записей
- `offset` (default: 0): Смещение для пагинации

**Response:**
```json
{
  "total": 45,
  "students": [
    {
      "id": 1,
      "user_id": 111222333,
      "name": "Мария Петрова",
      "username": "maria_p",
      "connected_at": "2024-09-01T10:00:00Z",
      "stats": {
        "completed_assignments": 12,
        "average_score": 85.5
      }
    }
  ]
}
```

**Логика:**
```python
# Используй существующую модель
from teacher_mode.models import TeacherStudentRelationship

# Получи учеников учителя
students = TeacherStudentRelationship.query.filter_by(teacher_id=teacher.id)

# Если есть поиск
if search:
    students = students.join(User).filter(
        or_(
            User.first_name.ilike(f'%{search}%'),
            User.username.ilike(f'%{search}%')
        )
    )

# Пагинация
students = students.limit(limit).offset(offset).all()
```

---

### 3. Modules List

**Endpoint:** `GET /api/teacher/modules`

**Response:**
```json
{
  "modules": [
    {
      "code": "test_part",
      "name": "📝 Тестовая часть (1-16)",
      "total_questions": 450,
      "description": "Вопросы из тестовой части ЕГЭ"
    },
    {
      "code": "task19",
      "name": "💡 Задание 19",
      "total_questions": 120,
      "description": "Анализ ситуации"
    }
  ]
}
```

**Логика:**
```python
# Используй существующий сервис
from teacher_mode.services.topics_loader import load_topics_for_module

modules = []
for module_code in ['test_part', 'task19', 'task20', 'task24', 'task25']:
    topics_data = load_topics_for_module(module_code)
    modules.append({
        'code': module_code,
        'name': get_module_name(module_code),
        'total_questions': topics_data['total_count'],
        'description': get_module_description(module_code)
    })
```

---

### 4. Questions List

**Endpoint:** `GET /api/teacher/questions`

**Query Parameters:**
- `module` (required): Код модуля
- `search` (optional): Поиск по тексту
- `limit` (default: 20): Количество записей
- `offset` (default: 0): Смещение

**Response:**
```json
{
  "total": 450,
  "questions": [
    {
      "id": "test_part_123",
      "module": "test_part",
      "number": 5,
      "text": "Выберите верные суждения о...",
      "type": "multiple_choice",
      "difficulty": "medium",
      "topic": "Социальная стратификация"
    }
  ]
}
```

**Логика:**
```python
# Используй существующий сервис
from teacher_mode.services.question_loader import load_questions_for_module

questions_data = load_questions_for_module(module_code)

# Если есть поиск, фильтруй
if search:
    questions = [q for q in questions_data if search.lower() in q['text'].lower()]

# Пагинация
start = offset
end = offset + limit
questions = questions[start:end]
```

---

### 5. Create Assignment

**Endpoint:** `POST /api/teacher/assignments`

**Request Body:**
```json
{
  "assignment_type": "mixed",
  "title": "Домашнее задание №5",
  "description": "Подготовка к контрольной",
  "deadline": "2025-01-15T23:59:59Z",
  "student_ids": [1, 2, 3],
  "modules": [
    {
      "module_code": "test_part",
      "selection_mode": "random",
      "question_count": 10
    },
    {
      "module_code": "task19",
      "selection_mode": "specific",
      "question_ids": ["task19_45", "task19_67"]
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "assignment_id": 456,
  "created_at": "2025-12-29T15:30:00Z",
  "message": "Задание успешно создано и отправлено 3 ученикам",
  "students_notified": 3
}
```

**Логика:**
```python
# Используй существующий сервис
from teacher_mode.services.assignment_service import AssignmentService

# Создай задание
assignment = await AssignmentService.create_assignment(
    teacher_id=teacher.id,
    title=data.title,
    description=data.description,
    assignment_type=data.assignment_type,
    deadline=data.deadline,
    modules=data.modules
)

# Назначь ученикам
for student_id in data.student_ids:
    await AssignmentService.assign_to_student(
        assignment_id=assignment.id,
        student_id=student_id
    )

# Отправь уведомления
from teacher_mode.services.notification_service import send_assignment_notifications
await send_assignment_notifications(assignment.id, data.student_ids)
```

**Валидация (Pydantic):**
```python
from pydantic import BaseModel, Field, validator

class ModuleSelection(BaseModel):
    module_code: str = Field(..., regex=r'^(test_part|task19|task20|task24|task25)$')
    selection_mode: str = Field(..., regex=r'^(all|random|specific)$')
    question_count: Optional[int] = Field(None, ge=1, le=100)
    question_ids: Optional[List[str]] = None

    @validator('question_ids')
    def validate_question_ids(cls, v, values):
        if values.get('selection_mode') == 'specific' and not v:
            raise ValueError('question_ids required for specific selection')
        return v

class CreateAssignmentRequest(BaseModel):
    assignment_type: str
    title: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    deadline: Optional[datetime] = None
    student_ids: List[int] = Field(..., min_items=1, max_items=100)
    modules: List[ModuleSelection] = Field(..., min_items=1, max_items=5)
```

---

### 6. Drafts

**Save Draft:** `POST /api/teacher/drafts`

**Request:**
```json
{
  "draft_data": {
    "assignment_type": "mixed",
    "title": "Незаконченное...",
    "modules": []
  }
}
```

**Response:**
```json
{
  "draft_id": "draft_789",
  "saved_at": "2025-12-29T15:35:00Z"
}
```

**Get Drafts:** `GET /api/teacher/drafts`

**Response:**
```json
{
  "drafts": [
    {
      "draft_id": "draft_789",
      "created_at": "2025-12-29T15:35:00Z",
      "data": {...}
    }
  ]
}
```

---

## 🔐 Telegram WebApp Authentication

**Критически важно!** Валидируй `initData` от Telegram.

### Middleware для аутентификации

Создай `api/middleware/telegram_auth.py`:

```python
from fastapi import Header, HTTPException
from hashlib import sha256
import hmac
import json
from urllib.parse import parse_qsl
from core.config import BOT_TOKEN

def verify_telegram_webapp_data(init_data: str) -> dict:
    """
    Проверяет подпись Telegram WebApp initData.

    Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing init data")

    # Парсим initData
    data_dict = dict(parse_qsl(init_data))

    # Извлекаем hash
    received_hash = data_dict.pop('hash', None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing hash")

    # Создаем строку для проверки
    data_check_string = '\n'.join(
        f'{k}={v}' for k, v in sorted(data_dict.items())
    )

    # Вычисляем ожидаемый hash
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        sha256
    ).digest()

    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        sha256
    ).hexdigest()

    # Сравниваем
    if not hmac.compare_digest(received_hash, expected_hash):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Извлекаем user_id
    user_data = json.loads(data_dict.get('user', '{}'))
    user_id = user_data.get('id')

    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user ID")

    return {
        'user_id': user_id,
        'user_data': user_data,
        'auth_date': data_dict.get('auth_date')
    }


async def get_current_teacher(
    init_data: str = Header(alias="X-Telegram-Init-Data")
):
    """
    Dependency для получения текущего учителя из initData.
    """
    # Валидируем initData
    auth_data = verify_telegram_webapp_data(init_data)
    user_id = auth_data['user_id']

    # Получаем учителя
    from teacher_mode.models import TeacherProfile
    teacher = TeacherProfile.query.filter_by(user_id=user_id).first()

    if not teacher:
        raise HTTPException(
            status_code=403,
            detail="Not a teacher. User does not have teacher access."
        )

    return teacher
```

**Использование в routes:**

```python
from fastapi import Depends
from api.middleware.telegram_auth import get_current_teacher

@router.get("/profile")
async def get_profile(teacher = Depends(get_current_teacher)):
    return {
        "teacher_id": teacher.id,
        "user_id": teacher.user_id,
        # ...
    }
```

---

## 🏗️ Структура FastAPI приложения

### app.py (главный файл)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import teacher, students, modules, questions, assignments, drafts

app = FastAPI(
    title="Teacher WebApp API",
    version="1.0.0",
    description="Backend API для WebApp режима учителя"
)

# CORS для разработки (в продакшене ограничь origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://t.me", "https://web.telegram.org"],  # Только Telegram
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Регистрация роутов
app.include_router(teacher.router, prefix="/api/teacher", tags=["teacher"])
app.include_router(students.router, prefix="/api/teacher", tags=["students"])
app.include_router(modules.router, prefix="/api/teacher", tags=["modules"])
app.include_router(questions.router, prefix="/api/teacher", tags=["questions"])
app.include_router(assignments.router, prefix="/api/teacher", tags=["assignments"])
app.include_router(drafts.router, prefix="/api/teacher", tags=["drafts"])

@app.get("/")
async def root():
    return {"message": "Teacher WebApp API is running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 📝 Pydantic Schemas (примеры)

### schemas/teacher.py

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class SubscriptionInfo(BaseModel):
    tier: str
    expires_at: Optional[datetime]

class TeacherStats(BaseModel):
    total_students: int
    total_assignments: int
    active_assignments: int

class TeacherProfileResponse(BaseModel):
    teacher_id: int
    user_id: int
    name: str
    username: Optional[str]
    subscription: SubscriptionInfo
    stats: TeacherStats

    class Config:
        from_attributes = True  # Для SQLAlchemy моделей
```

### schemas/assignment.py

```python
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime

class ModuleSelection(BaseModel):
    module_code: str = Field(..., regex=r'^(test_part|task19|task20|task24|task25)$')
    selection_mode: str = Field(..., regex=r'^(all|random|specific)$')
    question_count: Optional[int] = Field(None, ge=1, le=100)
    question_ids: Optional[List[str]] = None

    @validator('question_ids')
    def validate_question_ids(cls, v, values):
        if values.get('selection_mode') == 'specific' and not v:
            raise ValueError('question_ids required for specific selection')
        return v

class CreateAssignmentRequest(BaseModel):
    assignment_type: str
    title: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    deadline: Optional[datetime] = None
    student_ids: List[int] = Field(..., min_items=1, max_items=100)
    modules: List[ModuleSelection] = Field(..., min_items=1, max_items=5)

    @validator('deadline')
    def validate_deadline(cls, v):
        if v and v < datetime.utcnow():
            raise ValueError('Deadline cannot be in the past')
        return v

class CreateAssignmentResponse(BaseModel):
    success: bool
    assignment_id: int
    created_at: datetime
    message: str
    students_notified: int
```

---

## 🔄 Интеграция с существующими сервисами

**Важно:** Используй существующие сервисы, не дублируй логику!

### Примеры использования:

```python
# teacher_mode/services/assignment_service.py
from teacher_mode.services.assignment_service import AssignmentService

# Создание задания
assignment = await AssignmentService.create_homework_assignment(
    teacher_id=teacher.id,
    assignment_type=data.assignment_type,
    title=data.title,
    description=data.description,
    deadline=data.deadline,
    selected_questions=selected_questions  # Список question_id
)

# teacher_mode/services/teacher_service.py
from teacher_mode.services.teacher_service import get_teacher_stats

stats = get_teacher_stats(teacher_id)

# teacher_mode/services/topics_loader.py
from teacher_mode.services.topics_loader import load_topics_for_module

topics_data = load_topics_for_module('task19')
```

**Если сервисы асинхронные не поддерживают**, оберни в `run_in_executor`:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor()

async def get_students_async(teacher_id):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor,
        get_students_sync,  # Синхронная функция
        teacher_id
    )
```

---

## 🧪 Тестирование

Создай тесты для каждого endpoint:

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)

def test_get_profile():
    # Mock initData
    init_data = "..."

    response = client.get(
        "/api/teacher/profile",
        headers={"X-Telegram-Init-Data": init_data}
    )

    assert response.status_code == 200
    data = response.json()
    assert "teacher_id" in data
    assert "stats" in data
```

---

## 📦 Deployment

### Запуск локально

```bash
cd api
pip install fastapi uvicorn pydantic

# Development
uvicorn app:app --reload --port 8000

# Production
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

### Docker (опционально)

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## ✅ Чеклист завершения

После создания Backend проверь:

- [ ] Все 7 основных endpoints работают
- [ ] Telegram authentication валидирует initData
- [ ] Pydantic schemas валидируют запросы
- [ ] Интеграция с существующими сервисами работает
- [ ] CORS настроен корректно
- [ ] Ошибки обрабатываются gracefully
- [ ] Логирование настроено
- [ ] Swagger docs доступны на `/docs`

---

## 🔗 Полезные ссылки

- [Архитектурная документация](WebApp/TEACHER_WEBAPP_ARCHITECTURE.md)
- [Telegram WebApp Validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

---

## 🚨 Важные замечания

1. **НЕ** переписывай существующие сервисы - используй их!
2. **ОБЯЗАТЕЛЬНО** валидируй `initData` от Telegram
3. **НЕ** храни чувствительные данные в Frontend
4. **ОБЯЗАТЕЛЬНО** используй Pydantic для валидации
5. **НЕ** забудь про rate limiting (можно добавить позже)

---

## 🎯 Начни с этого

1. Создай структуру папок `api/`
2. Напиши `telegram_auth.py` middleware (это критично!)
3. Создай базовый `app.py`
4. Реализуй простой endpoint `/api/teacher/profile` для теста
5. Убедись, что аутентификация работает
6. Затем добавляй остальные endpoints по одному

**Удачи! После завершения Backend у тебя будет полностью рабочий WebApp! 🚀**
