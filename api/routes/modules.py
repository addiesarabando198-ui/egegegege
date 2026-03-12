"""
Routes для получения списка доступных модулей (разделов заданий).
"""

from fastapi import APIRouter, Depends
import logging

from api.middleware.telegram_auth import get_current_teacher
from api.schemas.module import ModulesListResponse, Module
from teacher_mode.models import TeacherProfile
from teacher_mode.services.topics_loader import load_topics_for_module

router = APIRouter()
logger = logging.getLogger(__name__)


# Информация о модулях
MODULES_INFO = {
    'test_part': {
        'name': '📝 Тестовая часть (1-16)',
        'description': 'Вопросы из тестовой части ЕГЭ по обществознанию'
    },
    'task19': {
        'name': '💡 Задание 19',
        'description': 'Анализ ситуации, выбор верных суждений'
    },
    'task20': {
        'name': '📊 Задание 20',
        'description': 'Работа с графиками, схемами и таблицами'
    },
    'task24': {
        'name': '📋 Задание 24',
        'description': 'Составление сложного плана по теме'
    },
    'task25': {
        'name': '✍️ Задание 25',
        'description': 'Написание мини-сочинения, эссе'
    }
}


@router.get(
    "/modules",
    response_model=ModulesListResponse,
    summary="Получить список модулей",
    description="Возвращает список всех доступных модулей с количеством вопросов"
)
async def get_modules(
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> ModulesListResponse:
    """
    Получает список всех доступных модулей для создания заданий.

    Модули:
    - test_part: Тестовая часть (задания 1-16)
    - task19: Задание 19
    - task20: Задание 20
    - task24: Задание 24 (планы)
    - task25: Задание 25 (эссе)
    """
    try:
        modules = []

        # Загружаем информацию о каждом модуле
        for module_code in ['test_part', 'task19', 'task20', 'task24', 'task25']:
            # Загружаем темы для модуля
            topics_data = load_topics_for_module(module_code)
            total_questions = topics_data.get('total_count', 0)

            # Получаем информацию о модуле
            module_info = MODULES_INFO.get(module_code, {})

            module = Module(
                code=module_code,
                name=module_info.get('name', module_code),
                total_questions=total_questions,
                description=module_info.get('description', '')
            )
            modules.append(module)

        logger.info(f"Получен список модулей для учителя {teacher.user_id}")

        return ModulesListResponse(modules=modules)

    except Exception as e:
        logger.error(f"Ошибка при получении списка модулей: {e}")
        # Возвращаем пустой список в случае ошибки
        return ModulesListResponse(modules=[])
