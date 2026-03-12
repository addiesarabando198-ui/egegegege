"""
Routes для проверки ответов B2B API.

POST /api/v1/check - создание проверки
GET /api/v1/check/{id} - получение результата
GET /api/v1/checks - список проверок клиента
"""

import logging
import secrets
import json
import aiosqlite
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks

from core.db import DATABASE_FILE
from b2b_api.schemas.check import (
    CheckRequest,
    CheckResponse,
    CheckResultResponse,
    CheckStatus,
    CriteriaScore,
    CheckListResponse,
    CheckListItem
)
from b2b_api.middleware.api_key_auth import verify_api_key, get_api_key_auth
from b2b_api.middleware.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/check", tags=["check"])


# Импортируем evaluators динамически
def get_evaluator(task_number: int, strictness: str = "standard"):
    """Возвращает evaluator для задания."""
    try:
        if task_number == 17:
            from task17.evaluator import Task17AIEvaluator
            return Task17AIEvaluator()

        elif task_number == 18:
            from task18.evaluator import Task18AIEvaluator
            return Task18AIEvaluator()

        elif task_number == 19:
            from task19.evaluator import Task19AIEvaluator
            return Task19AIEvaluator()

        elif task_number == 20:
            from task20.evaluator import Task20AIEvaluator
            return Task20AIEvaluator()

        elif task_number == 21:
            from task21.evaluator import Task21AIEvaluator
            return Task21AIEvaluator()

        elif task_number == 22:
            from task22.evaluator import Task22AIEvaluator
            return Task22AIEvaluator()

        elif task_number == 23:
            from task23.evaluator import Task23AIEvaluator
            return Task23AIEvaluator()

        elif task_number == 24:
            from task24.evaluator import Task24AIEvaluator
            return Task24AIEvaluator()

        elif task_number == 25:
            from task25.evaluator import Task25AIEvaluator
            return Task25AIEvaluator()

        else:
            raise ValueError(f"Unsupported task number: {task_number}")

    except ImportError as e:
        logger.error(f"Failed to import evaluator for task {task_number}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Evaluator for task {task_number} is not available"
        )


async def find_existing_check_by_idempotency_key(
    client_id: str, idempotency_key: str
) -> Optional[dict]:
    """
    Ищет существующую проверку по idempotency_key.

    Returns:
        dict с check_id и status если найдена, None если нет.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT check_id, status, created_at, external_id
                FROM b2b_checks
                WHERE client_id = ? AND idempotency_key = ?
                LIMIT 1
            """, (client_id, idempotency_key))
            row = await cursor.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        logger.error(f"Error looking up idempotency key: {e}")
    return None


async def process_check(check_id: str, request: CheckRequest, client_id: str):
    """
    Фоновая обработка проверки.
    """
    start_time = datetime.now(timezone.utc)

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Обновляем статус на processing
            await db.execute("""
                UPDATE b2b_checks
                SET status = 'processing', started_at = ?
                WHERE check_id = ?
            """, (start_time.isoformat(), check_id))
            await db.commit()

        # Получаем evaluator
        evaluator = get_evaluator(request.task_number, request.strictness)

        # Выполняем проверку
        result = await evaluator.evaluate(
            answer=request.answer_text,
            topic=request.topic or "",
            task_text=request.task_text
        )

        end_time = datetime.now(timezone.utc)
        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)

        # Формируем данные для сохранения
        criteria_scores_json = json.dumps([
            {
                "criteria_id": k,
                "criteria_name": k,
                "score": v,
                "max_score": result.max_score
            }
            for k, v in result.criteria_scores.items()
        ] if hasattr(result, 'criteria_scores') and result.criteria_scores else [])

        suggestions_json = json.dumps(result.suggestions if hasattr(result, 'suggestions') else [])
        factual_errors_json = json.dumps(result.factual_errors if hasattr(result, 'factual_errors') else [])
        detailed_feedback_json = json.dumps(result.detailed_feedback if hasattr(result, 'detailed_feedback') else {})

        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Обновляем результат
            await db.execute("""
                UPDATE b2b_checks
                SET
                    status = 'completed',
                    total_score = ?,
                    max_score = ?,
                    criteria_scores = ?,
                    feedback = ?,
                    suggestions = ?,
                    factual_errors = ?,
                    detailed_feedback = ?,
                    processing_time_ms = ?,
                    completed_at = ?
                WHERE check_id = ?
            """, (
                result.total_score,
                result.max_score,
                criteria_scores_json,
                result.feedback,
                suggestions_json,
                factual_errors_json,
                detailed_feedback_json,
                processing_time_ms,
                end_time.isoformat(),
                check_id
            ))
            await db.commit()

            # Увеличиваем счётчик использования
            auth = get_api_key_auth()
            await auth.increment_usage(client_id)

        logger.info(f"Check {check_id} completed: score={result.total_score}/{result.max_score}, time={processing_time_ms}ms")

        # Отправляем webhook если указан callback_url
        if request.callback_url:
            from b2b_api.services.webhook_delivery import deliver_webhook
            asyncio.create_task(deliver_webhook(
                check_id=check_id,
                client_id=client_id,
                callback_url=request.callback_url,
                result_data={
                    "check_id": check_id,
                    "status": "completed",
                    "total_score": result.total_score,
                    "max_score": result.max_score,
                    "feedback": result.feedback,
                    "processing_time_ms": processing_time_ms,
                    "external_id": request.external_id,
                },
            ))

    except Exception as e:
        logger.error(f"Error processing check {check_id}: {e}", exc_info=True)

        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE b2b_checks
                SET
                    status = 'failed',
                    error_message = ?,
                    completed_at = ?
                WHERE check_id = ?
            """, (str(e), datetime.now(timezone.utc).isoformat(), check_id))
            await db.commit()


@router.post(
    "",
    response_model=CheckResponse,
    summary="Создать проверку",
    description="""
Отправляет ответ ученика на проверку.

**Поддерживаемые задания:** 17-25

**Уровни строгости:**
- `lenient` - мягкий, засчитывает ответы с небольшими недочётами
- `standard` - стандартный (по умолчанию)
- `strict` - строгий, требует полного соответствия критериям ФИПИ
- `expert` - экспертный, максимальная строгость

**Асинхронная обработка:**
Проверка выполняется асинхронно. После создания запроса используйте
GET /api/v1/check/{id} для получения результата.

**Идемпотентность:**
Укажите `idempotency_key` в теле запроса. При повторном запросе с тем же ключом
вернётся результат первоначальной проверки без создания дубликата.

**Webhook (опционально):**
Укажите `callback_url` (только HTTPS) для получения уведомления о завершении проверки.
    """
)
async def create_check(
    request: CheckRequest,
    background_tasks: BackgroundTasks,
    rate_info: dict = Depends(check_rate_limit)
) -> CheckResponse:
    """
    Создаёт новую проверку ответа.
    """
    client_data = rate_info['client_data']
    client_id = client_data['client_id']

    # Проверяем idempotency key
    if request.idempotency_key:
        existing = await find_existing_check_by_idempotency_key(
            client_id, request.idempotency_key
        )
        if existing:
            logger.info(
                f"Idempotent request: returning existing check {existing['check_id']} "
                f"for key {request.idempotency_key}"
            )
            return CheckResponse(
                check_id=existing['check_id'],
                status=CheckStatus(existing['status']),
                created_at=datetime.fromisoformat(existing['created_at']),
                estimated_time_seconds=None,
                external_id=existing.get('external_id')
            )

    # Генерируем ID проверки
    check_id = f"chk_{secrets.token_hex(12)}"

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Создаём запись о проверке
            await db.execute("""
                INSERT INTO b2b_checks (
                    check_id,
                    client_id,
                    status,
                    task_number,
                    task_text,
                    answer_text,
                    topic,
                    strictness,
                    external_id,
                    callback_url,
                    idempotency_key,
                    metadata,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                check_id,
                client_id,
                CheckStatus.PENDING.value,
                request.task_number,
                request.task_text,
                request.answer_text,
                request.topic,
                request.strictness,
                request.external_id,
                request.callback_url,
                request.idempotency_key,
                json.dumps(request.metadata) if request.metadata else None,
                datetime.now(timezone.utc).isoformat()
            ))
            await db.commit()

        # Запускаем обработку в фоне
        background_tasks.add_task(process_check, check_id, request, client_id)

        logger.info(f"Created check {check_id} for client {client_id}, task {request.task_number}")

        return CheckResponse(
            check_id=check_id,
            status=CheckStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            estimated_time_seconds=30,
            external_id=request.external_id
        )

    except Exception as e:
        logger.error(f"Error creating check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create check")


@router.get(
    "/{check_id}",
    response_model=CheckResultResponse,
    summary="Получить результат проверки",
    description="""
Возвращает результат проверки по ID.

**Статусы:**
- `pending` - в очереди
- `processing` - в процессе проверки
- `completed` - завершена
- `failed` - ошибка

Если проверка ещё не завершена, результаты оценки будут `null`.
    """
)
async def get_check_result(
    check_id: str,
    client_data: dict = Depends(verify_api_key)
) -> CheckResultResponse:
    """
    Получает результат проверки.
    """
    client_id = client_data['client_id']

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT * FROM b2b_checks
                WHERE check_id = ? AND client_id = ?
            """, (check_id, client_id))

            row = await cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Check not found")

            # Парсим JSON поля
            criteria_scores = None
            if row['criteria_scores']:
                try:
                    criteria_data = json.loads(row['criteria_scores'])
                    criteria_scores = [
                        CriteriaScore(
                            criteria_id=c['criteria_id'],
                            criteria_name=c.get('criteria_name', c['criteria_id']),
                            score=c['score'],
                            max_score=c.get('max_score', 0),
                            comment=c.get('comment')
                        )
                        for c in criteria_data
                    ]
                except (json.JSONDecodeError, KeyError):
                    pass

            suggestions = None
            if row['suggestions']:
                try:
                    suggestions = json.loads(row['suggestions'])
                except json.JSONDecodeError:
                    pass

            factual_errors = None
            if row['factual_errors']:
                try:
                    factual_errors = json.loads(row['factual_errors'])
                except json.JSONDecodeError:
                    pass

            return CheckResultResponse(
                check_id=row['check_id'],
                status=CheckStatus(row['status']),
                task_number=row['task_number'],
                task_text=row['task_text'],
                answer_text=row['answer_text'],
                total_score=row['total_score'],
                max_score=row['max_score'],
                criteria_scores=criteria_scores,
                feedback=row['feedback'],
                suggestions=suggestions,
                factual_errors=factual_errors,
                created_at=datetime.fromisoformat(row['created_at']),
                completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
                processing_time_ms=row['processing_time_ms'],
                external_id=row['external_id'],
                error_message=row['error_message']
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting check {check_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get check result")


@router.get(
    "s",
    response_model=CheckListResponse,
    summary="Список проверок",
    description="Возвращает список проверок клиента с пагинацией."
)
async def list_checks(
    client_data: dict = Depends(verify_api_key),
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Элементов на странице"),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    task_number: Optional[int] = Query(None, ge=17, le=25, description="Фильтр по номеру задания")
) -> CheckListResponse:
    """
    Получает список проверок клиента.
    """
    client_id = client_data['client_id']

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Формируем условия
            conditions = ["client_id = ?"]
            params = [client_id]

            if status:
                conditions.append("status = ?")
                params.append(status)

            if task_number:
                conditions.append("task_number = ?")
                params.append(task_number)

            where_clause = " AND ".join(conditions)

            # Получаем общее количество
            cursor = await db.execute(
                f"SELECT COUNT(*) FROM b2b_checks WHERE {where_clause}",
                params
            )
            total = (await cursor.fetchone())[0]

            # Получаем данные с пагинацией
            offset = (page - 1) * per_page
            cursor = await db.execute(f"""
                SELECT
                    check_id, status, task_number,
                    total_score, max_score,
                    created_at, completed_at, external_id
                FROM b2b_checks
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, params + [per_page, offset])

            rows = await cursor.fetchall()

            items = [
                CheckListItem(
                    check_id=row['check_id'],
                    status=CheckStatus(row['status']),
                    task_number=row['task_number'],
                    total_score=row['total_score'],
                    max_score=row['max_score'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
                    external_id=row['external_id']
                )
                for row in rows
            ]

            return CheckListResponse(
                total=total,
                items=items,
                page=page,
                per_page=per_page
            )

    except Exception as e:
        logger.error(f"Error listing checks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list checks")
