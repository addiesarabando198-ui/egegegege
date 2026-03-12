"""
Экспорт экспертных оценок из БД в формат JSONL для дообучения YandexGPT.

Формат обучающих данных YandexGPT:
{"request": [{"role": "system", "text": "..."}, {"role": "user", "text": "..."}], "response": "..."}

Источники данных:
1. user_feedback с resolution_type='approved' — подтверждённые экспертами оценки
2. task_specific_hints — экспертные уточнения критериев
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import aiosqlite

from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)


class TrainingDataExporter:
    """Экспорт данных из БД для дообучения YandexGPT."""

    # Системные промпты для каждого типа задания (совпадают с ai_evaluator.py)
    SYSTEM_PROMPTS = {
        "task19": (
            "Ты — эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 19. "
            "Задание 19 требует привести три примера, иллюстрирующих определённое положение или понятие. "
            "Каждый пример должен быть конкретным, соответствовать теме и раскрывать суть явления."
        ),
        "task20": (
            "Ты — эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 20. "
            "Задание 20 требует сформулировать три суждения, раскрывающих различные аспекты темы. "
            "Суждения должны быть корректными с точки зрения обществознания, логичными и содержательными."
        ),
        "task24": (
            "Ты — эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 24. "
            "Задание 24 требует составить развёрнутый план по заданной теме."
        ),
        "task25": (
            "Ты — эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 25. "
            "Это самое сложное задание ЕГЭ. Оно требует: "
            "1) Обоснование (теоретическое объяснение). "
            "2) Три примера из РАЗНЫХ источников. "
            "Каждый пример должен чётко иллюстрировать обоснование."
        ),
    }

    def __init__(self, db_path: str = DATABASE_FILE):
        self.db_path = db_path

    async def export_training_data(
        self,
        output_dir: str,
        task_types: Optional[List[str]] = None,
        min_score: Optional[int] = None,
        validation_split: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Экспортирует обучающие данные из БД в JSONL-файлы.

        Args:
            output_dir: Директория для сохранения файлов
            task_types: Фильтр по типам заданий (None = все)
            min_score: Минимальный балл для включения в выборку
            validation_split: Доля данных для валидации (0.0–1.0)

        Returns:
            Статистика экспорта:
                - total_samples: общее число примеров
                - train_samples: число обучающих примеров
                - val_samples: число валидационных примеров
                - by_task_type: распределение по типам заданий
                - train_path: путь к обучающему файлу
                - val_path: путь к валидационному файлу
        """
        os.makedirs(output_dir, exist_ok=True)

        # Собираем данные из разных источников
        samples = []
        samples.extend(await self._export_approved_complaints(task_types))
        samples.extend(await self._export_high_quality_evaluations(task_types, min_score))

        if not samples:
            logger.warning("Нет данных для экспорта. Проверьте наличие одобренных жалоб и оценок в БД.")
            return {
                "total_samples": 0,
                "train_samples": 0,
                "val_samples": 0,
                "by_task_type": {},
                "train_path": None,
                "val_path": None,
            }

        # Дедупликация по содержимому запроса
        seen = set()
        unique_samples = []
        for sample in samples:
            key = json.dumps(sample["request"], ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique_samples.append(sample)
        samples = unique_samples

        logger.info(f"Собрано {len(samples)} уникальных обучающих примеров")

        # Разбиение на train/val
        import random
        random.seed(42)
        random.shuffle(samples)

        val_count = max(1, int(len(samples) * validation_split))
        val_samples = samples[:val_count]
        train_samples = samples[val_count:]

        # Записываем файлы
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        train_path = os.path.join(output_dir, f"train_{timestamp}.jsonl")
        val_path = os.path.join(output_dir, f"val_{timestamp}.jsonl")

        self._write_jsonl(train_path, train_samples)
        self._write_jsonl(val_path, val_samples)

        # Статистика
        by_task = {}
        for s in samples:
            tt = s.get("_task_type", "unknown")
            by_task[tt] = by_task.get(tt, 0) + 1

        stats = {
            "total_samples": len(samples),
            "train_samples": len(train_samples),
            "val_samples": len(val_samples),
            "by_task_type": by_task,
            "train_path": train_path,
            "val_path": val_path,
        }

        logger.info(f"Экспорт завершён: {stats}")
        return stats

    async def _export_approved_complaints(
        self, task_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Экспорт одобренных жалоб — записей, где эксперт скорректировал оценку AI.

        Каждая одобренная жалоба содержит:
        - user_answer: ответ ученика
        - ai_feedback: первоначальный ответ AI
        - admin_response: экспертная корректировка
        - k1_score, k2_score: баллы (возможно скорректированные)
        - topic_name, task_type: контекст
        """
        samples = []

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                query = """
                    SELECT
                        task_type, topic_name, user_answer,
                        ai_feedback, admin_response,
                        k1_score, k2_score, complaint_reason
                    FROM user_feedback
                    WHERE resolution_type = 'approved'
                      AND user_answer IS NOT NULL
                      AND user_answer != ''
                      AND admin_response IS NOT NULL
                      AND admin_response != ''
                """
                params: List[Any] = []

                if task_types:
                    placeholders = ",".join("?" for _ in task_types)
                    query += f" AND task_type IN ({placeholders})"
                    params.extend(task_types)

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()

                for row in rows:
                    sample = self._complaint_to_training_sample(row)
                    if sample:
                        samples.append(sample)

                logger.info(f"Экспортировано {len(samples)} примеров из одобренных жалоб")

        except Exception as e:
            logger.error(f"Ошибка при экспорте жалоб: {e}", exc_info=True)

        return samples

    async def _export_high_quality_evaluations(
        self,
        task_types: Optional[List[str]] = None,
        min_score: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Экспорт высококачественных оценок — записей с высоким баллом
        и без жалоб (AI оценил правильно).

        Критерии отбора:
        - Ученик получил высокий балл (по умолчанию >= max_score - 1)
        - На эту оценку не было жалоб
        - Есть сохранённый ai_feedback
        """
        samples = []

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                # Берём оценки из user_feedback, где нет жалоб и оценка высокая
                query = """
                    SELECT
                        task_type, topic_name, user_answer,
                        ai_feedback, k1_score, k2_score
                    FROM user_feedback
                    WHERE feedback_type = 'general'
                      AND user_answer IS NOT NULL
                      AND user_answer != ''
                      AND ai_feedback IS NOT NULL
                      AND ai_feedback != ''
                      AND complaint_reason IS NULL
                """
                params: List[Any] = []

                if task_types:
                    placeholders = ",".join("?" for _ in task_types)
                    query += f" AND task_type IN ({placeholders})"
                    params.extend(task_types)

                if min_score is not None:
                    query += " AND (COALESCE(k1_score, 0) + COALESCE(k2_score, 0)) >= ?"
                    params.append(min_score)

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()

                for row in rows:
                    sample = self._evaluation_to_training_sample(row)
                    if sample:
                        samples.append(sample)

                logger.info(
                    f"Экспортировано {len(samples)} примеров из высококачественных оценок"
                )

        except Exception as e:
            logger.error(f"Ошибка при экспорте оценок: {e}", exc_info=True)

        return samples

    def _complaint_to_training_sample(self, row: Any) -> Optional[Dict[str, Any]]:
        """Преобразование одобренной жалобы в обучающий пример."""
        task_type = row["task_type"] or "task25"
        topic = row["topic_name"] or "Общая тема"
        answer = row["user_answer"]
        admin_response = row["admin_response"]
        k1 = row["k1_score"]
        k2 = row["k2_score"]

        if not answer or not admin_response:
            return None

        system_prompt = self.SYSTEM_PROMPTS.get(task_type, self.SYSTEM_PROMPTS["task25"])

        # Формируем пользовательский запрос (аналогично реальному промпту оценки)
        user_prompt = self._build_evaluation_prompt(task_type, topic, answer)

        # Формируем эталонный ответ на основе экспертной корректировки
        response = self._build_expert_response(
            task_type, admin_response, k1, k2, row["complaint_reason"]
        )

        return {
            "request": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_prompt},
            ],
            "response": response,
            "_task_type": task_type,  # Метаданные (не отправляются в API)
        }

    def _evaluation_to_training_sample(self, row: Any) -> Optional[Dict[str, Any]]:
        """Преобразование качественной оценки в обучающий пример."""
        task_type = row["task_type"] or "task25"
        topic = row["topic_name"] or "Общая тема"
        answer = row["user_answer"]
        ai_feedback = row["ai_feedback"]

        if not answer or not ai_feedback:
            return None

        system_prompt = self.SYSTEM_PROMPTS.get(task_type, self.SYSTEM_PROMPTS["task25"])
        user_prompt = self._build_evaluation_prompt(task_type, topic, answer)

        return {
            "request": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_prompt},
            ],
            "response": ai_feedback,
            "_task_type": task_type,
        }

    def _build_evaluation_prompt(self, task_type: str, topic: str, answer: str) -> str:
        """Строит промпт оценки, аналогичный реальному промпту из ai_evaluator."""
        max_scores = {
            "task19": 3,
            "task20": 3,
            "task24": 4,
            "task25": 6,
        }
        max_score = max_scores.get(task_type, 6)

        return (
            f'Проверь ответ на задание по теме: "{topic}"\n\n'
            f"Ответ ученика:\n{answer}\n\n"
            f"Оцени ответ по критериям ЕГЭ (максимум {max_score} баллов). "
            f"Верни структурированный JSON с полями: score, criteria_scores, "
            f"main_issues, suggestions."
        )

    def _build_expert_response(
        self,
        task_type: str,
        admin_response: str,
        k1: Optional[int],
        k2: Optional[int],
        complaint_reason: Optional[str],
    ) -> str:
        """Строит эталонный ответ на основе экспертной корректировки."""
        scores = {}
        if k1 is not None:
            scores["К1"] = k1
        if k2 is not None:
            scores["К2"] = k2

        total = sum(scores.values()) if scores else None

        result: Dict[str, Any] = {}
        if total is not None:
            result["score"] = total
        if scores:
            result["criteria_scores"] = scores
        result["feedback"] = admin_response
        if complaint_reason:
            result["correction_note"] = (
                f"Предыдущая оценка была скорректирована. Причина: {complaint_reason}"
            )

        return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _write_jsonl(path: str, samples: List[Dict[str, Any]]) -> None:
        """Записывает примеры в JSONL-файл."""
        with open(path, "w", encoding="utf-8") as f:
            for sample in samples:
                # Удаляем служебные поля перед записью
                export_sample = {
                    "request": sample["request"],
                    "response": sample["response"],
                }
                f.write(json.dumps(export_sample, ensure_ascii=False) + "\n")

        logger.info(f"Записано {len(samples)} примеров в {path}")

    async def get_data_stats(self) -> Dict[str, Any]:
        """
        Возвращает статистику доступных данных для дообучения.

        Returns:
            Словарь со статистикой:
                - approved_complaints: кол-во одобренных жалоб
                - total_feedback: общее кол-во записей обратной связи
                - by_task_type: распределение по типам заданий
                - by_resolution: распределение по типам резолюций
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                # Одобренные жалобы с данными
                cursor = await db.execute("""
                    SELECT COUNT(*) as cnt
                    FROM user_feedback
                    WHERE resolution_type = 'approved'
                      AND user_answer IS NOT NULL AND user_answer != ''
                      AND admin_response IS NOT NULL AND admin_response != ''
                """)
                row = await cursor.fetchone()
                approved = row["cnt"] if row else 0

                # Общее кол-во с ответами
                cursor = await db.execute("""
                    SELECT COUNT(*) as cnt
                    FROM user_feedback
                    WHERE user_answer IS NOT NULL AND user_answer != ''
                      AND ai_feedback IS NOT NULL AND ai_feedback != ''
                """)
                row = await cursor.fetchone()
                total = row["cnt"] if row else 0

                # По типам заданий
                cursor = await db.execute("""
                    SELECT task_type, COUNT(*) as cnt
                    FROM user_feedback
                    WHERE user_answer IS NOT NULL AND user_answer != ''
                    GROUP BY task_type
                """)
                by_task = {r["task_type"]: r["cnt"] for r in await cursor.fetchall()}

                # По резолюциям
                cursor = await db.execute("""
                    SELECT resolution_type, COUNT(*) as cnt
                    FROM user_feedback
                    WHERE resolution_type IS NOT NULL
                    GROUP BY resolution_type
                """)
                by_resolution = {
                    r["resolution_type"]: r["cnt"] for r in await cursor.fetchall()
                }

                return {
                    "approved_complaints": approved,
                    "total_feedback_with_answers": total,
                    "by_task_type": by_task,
                    "by_resolution": by_resolution,
                }

        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}", exc_info=True)
            return {
                "approved_complaints": 0,
                "total_feedback_with_answers": 0,
                "by_task_type": {},
                "by_resolution": {},
            }
