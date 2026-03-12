"""
Routes для работы с черновиками заданий.
Черновики хранятся в БД и позволяют сохранять незавершенные задания.
"""

from fastapi import APIRouter, Depends, HTTPException
import aiosqlite
import json
import logging
import secrets

from api.middleware.telegram_auth import get_current_teacher
from api.schemas.draft import (
    SaveDraftRequest,
    SaveDraftResponse,
    DraftsListResponse,
    Draft,
    DeleteDraftResponse
)
from teacher_mode.models import TeacherProfile
from teacher_mode.utils.datetime_utils import utc_now, parse_datetime_safe
from core.config import DATABASE_FILE

router = APIRouter()
logger = logging.getLogger(__name__)


def generate_draft_id() -> str:
    """Генерирует уникальный ID для черновика"""
    return f"draft_{secrets.token_urlsafe(8)}"


@router.post(
    "/drafts",
    response_model=SaveDraftResponse,
    summary="Сохранить черновик",
    description="Сохраняет черновик задания для последующего редактирования"
)
async def save_draft(
    request: SaveDraftRequest,
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> SaveDraftResponse:
    """
    Сохраняет черновик задания.

    Черновики используются для:
    - Сохранения незавершенных заданий
    - Возможности продолжить создание позже
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Генерируем ID черновика
            draft_id = generate_draft_id()
            now = utc_now()

            # Сериализуем данные черновика
            draft_data_json = json.dumps(request.draft_data)

            # Сохраняем черновик
            await db.execute("""
                INSERT INTO assignment_drafts
                (draft_id, teacher_id, draft_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (draft_id, teacher.user_id, draft_data_json, now.isoformat(), now.isoformat()))

            await db.commit()

            logger.info(f"Сохранен черновик {draft_id} учителем {teacher.user_id}")

            return SaveDraftResponse(
                draft_id=draft_id,
                saved_at=now
            )

    except Exception as e:
        logger.error(f"Ошибка при сохранении черновика: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to save draft"
        )


@router.get(
    "/drafts",
    response_model=DraftsListResponse,
    summary="Получить список черновиков",
    description="Возвращает все сохраненные черновики учителя"
)
async def get_drafts(
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> DraftsListResponse:
    """
    Получает список всех черновиков учителя.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT draft_id, draft_data, created_at, updated_at
                FROM assignment_drafts
                WHERE teacher_id = ?
                ORDER BY updated_at DESC
            """, (teacher.user_id,))

            rows = await cursor.fetchall()

            # Формируем список черновиков
            drafts = []
            for row in rows:
                try:
                    draft_data = json.loads(row['draft_data'])
                except json.JSONDecodeError:
                    draft_data = {}

                draft = Draft(
                    draft_id=row['draft_id'],
                    created_at=parse_datetime_safe(row['created_at']) or utc_now(),
                    updated_at=parse_datetime_safe(row['updated_at']) or utc_now(),
                    data=draft_data
                )
                drafts.append(draft)

            logger.info(f"Получено {len(drafts)} черновиков для учителя {teacher.user_id}")

            return DraftsListResponse(drafts=drafts)

    except Exception as e:
        logger.error(f"Ошибка при получении черновиков: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve drafts"
        )


@router.put(
    "/drafts/{draft_id}",
    response_model=SaveDraftResponse,
    summary="Обновить черновик",
    description="Обновляет существующий черновик"
)
async def update_draft(
    draft_id: str,
    request: SaveDraftRequest,
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> SaveDraftResponse:
    """
    Обновляет существующий черновик.

    Проверяет, что черновик принадлежит данному учителю.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем что черновик существует и принадлежит учителю
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT draft_id
                FROM assignment_drafts
                WHERE draft_id = ? AND teacher_id = ?
            """, (draft_id, teacher.user_id))

            row = await cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Draft not found"
                )

            # Обновляем черновик
            now = utc_now()
            draft_data_json = json.dumps(request.draft_data)

            await db.execute("""
                UPDATE assignment_drafts
                SET draft_data = ?, updated_at = ?
                WHERE draft_id = ? AND teacher_id = ?
            """, (draft_data_json, now.isoformat(), draft_id, teacher.user_id))

            await db.commit()

            logger.info(f"Обновлен черновик {draft_id} учителем {teacher.user_id}")

            return SaveDraftResponse(
                draft_id=draft_id,
                saved_at=now
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обновлении черновика: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update draft"
        )


@router.delete(
    "/drafts/{draft_id}",
    response_model=DeleteDraftResponse,
    summary="Удалить черновик",
    description="Удаляет черновик из системы"
)
async def delete_draft(
    draft_id: str,
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> DeleteDraftResponse:
    """
    Удаляет черновик.

    Проверяет, что черновик принадлежит данному учителю.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Удаляем черновик
            cursor = await db.execute("""
                DELETE FROM assignment_drafts
                WHERE draft_id = ? AND teacher_id = ?
            """, (draft_id, teacher.user_id))

            await db.commit()

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Draft not found"
                )

            logger.info(f"Удален черновик {draft_id} учителем {teacher.user_id}")

            return DeleteDraftResponse(
                success=True,
                message="Черновик успешно удален"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при удалении черновика: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete draft"
        )
