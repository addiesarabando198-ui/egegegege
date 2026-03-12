"""
Импорт внешних экспертных оценок (сканы работ + баллы экспертов) для дообучения.

Пайплайн:
1. Читает сканы из директории
2. Распознаёт рукописный текст через Yandex Vision OCR + LLM-коррекцию
3. Сопоставляет с экспертными оценками из CSV/JSON
4. Формирует обучающие примеры в формате JSONL для дообучения YandexGPT

Формат CSV с экспертными оценками:
    filename,task_type,topic,task_text,k1_score,k2_score,k3_score,expert_comment
    work_01.jpg,task25,Функции государства,"Обоснуйте необходимость...",2,1,3,Хорошее обоснование но примеры слабые
    work_02.png,task19,Социальные институты,"Приведите три примера...",3,,,Все три примера корректны

Формат JSON:
    [
        {
            "filename": "work_01.jpg",
            "task_type": "task25",
            "topic": "Функции государства",
            "task_text": "Обоснуйте необходимость выполнения государством...",
            "scores": {"К1": 2, "К2": 1, "К3": 3},
            "expert_comment": "Хорошее обоснование, но примеры слабые"
        }
    ]
"""

import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from core.finetuning.data_exporter import TrainingDataExporter
from core.image_preprocessor import preprocess_for_ocr

logger = logging.getLogger(__name__)

# Расширения файлов изображений
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


class ExpertDataImporter:
    """Импорт сканов работ с экспертными оценками для дообучения."""

    def __init__(self):
        self._vision_service = None
        self._ai_service = None

    async def _get_vision_service(self):
        """Ленивая инициализация VisionService (требует API-ключи)."""
        if self._vision_service is None:
            from core.vision_service import VisionService
            self._vision_service = VisionService()
            if not self._vision_service.is_available:
                raise RuntimeError(
                    "Yandex Vision API недоступен. "
                    "Установите YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID."
                )
        return self._vision_service

    async def _get_ai_service(self):
        """Ленивая инициализация AI-сервиса для LLM-коррекции OCR."""
        if self._ai_service is None:
            from core.ai_service import get_ai_service
            self._ai_service = get_ai_service()
        return self._ai_service

    def load_expert_scores(self, scores_path: str) -> List[Dict[str, Any]]:
        """
        Загружает экспертные оценки из CSV или JSON файла.

        Args:
            scores_path: Путь к файлу с оценками

        Returns:
            Список записей с экспертными оценками

        Raises:
            ValueError: если формат файла не поддерживается
        """
        path = Path(scores_path)

        if path.suffix.lower() == ".json":
            return self._load_json_scores(path)
        elif path.suffix.lower() == ".csv":
            return self._load_csv_scores(path)
        else:
            raise ValueError(
                f"Неподдерживаемый формат: {path.suffix}. "
                f"Используйте .csv или .json"
            )

    def _load_csv_scores(self, path: Path) -> List[Dict[str, Any]]:
        """Загрузка оценок из CSV."""
        records = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            required = {"filename", "task_type", "topic"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError(
                    f"CSV должен содержать колонки: {required}. "
                    f"Найдены: {reader.fieldnames}"
                )

            for row_num, row in enumerate(reader, start=2):
                scores = {}
                for key in ["k1_score", "k2_score", "k3_score"]:
                    val = row.get(key, "").strip()
                    if val:
                        try:
                            criterion = key.replace("_score", "").upper()
                            criterion = criterion.replace("K", "К")  # Latin K → Cyrillic К
                            scores[criterion] = int(val)
                        except ValueError:
                            logger.warning(
                                f"Строка {row_num}: некорректное значение {key}='{val}', пропуск"
                            )

                record = {
                    "filename": row["filename"].strip(),
                    "task_type": row["task_type"].strip(),
                    "topic": row["topic"].strip(),
                    "task_text": row.get("task_text", "").strip(),
                    "scores": scores,
                    "expert_comment": row.get("expert_comment", "").strip(),
                }
                records.append(record)

        logger.info(f"Загружено {len(records)} записей из CSV: {path}")
        return records

    def _load_json_scores(self, path: Path) -> List[Dict[str, Any]]:
        """Загрузка оценок из JSON."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("JSON должен содержать массив записей")

        records = []
        for i, item in enumerate(data):
            if "filename" not in item or "task_type" not in item:
                logger.warning(f"Запись #{i}: отсутствует filename или task_type, пропуск")
                continue

            record = {
                "filename": item["filename"],
                "task_type": item["task_type"],
                "topic": item.get("topic", ""),
                "task_text": item.get("task_text", ""),
                "scores": item.get("scores", {}),
                "expert_comment": item.get("expert_comment", ""),
            }
            records.append(record)

        logger.info(f"Загружено {len(records)} записей из JSON: {path}")
        return records

    async def ocr_image_file(
        self,
        image_path: str,
        task_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Распознаёт текст из файла изображения через Yandex Vision OCR.

        Args:
            image_path: Путь к файлу изображения
            task_context: Контекст задания для LLM-коррекции

        Returns:
            Словарь: {success, text, confidence, corrected, error}
        """
        vision = await self._get_vision_service()

        with open(image_path, "rb") as f:
            raw_bytes = f.read()

        # Предобработка изображения (как для Telegram-фото)
        preprocessed = preprocess_for_ocr(raw_bytes)

        # OCR через Yandex Vision API
        result = await vision._recognize_text(preprocessed)

        if not result["success"]:
            return result

        # LLM-коррекция рукописного текста
        from core.vision_service import OCR_LLM_CORRECTION_THRESHOLD
        result["corrected"] = False

        if result["confidence"] < OCR_LLM_CORRECTION_THRESHOLD and result["text"]:
            corrected = await vision._correct_ocr_with_llm(
                result["text"], task_context
            )
            if corrected:
                result["text"] = corrected
                result["corrected"] = True

        return result

    async def import_expert_data(
        self,
        scans_dir: str,
        scores_path: str,
        output_dir: str,
        validation_split: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Полный пайплайн импорта: сканы + экспертные оценки → JSONL.

        Args:
            scans_dir: Директория со сканами работ
            scores_path: Путь к файлу с экспертными оценками (CSV/JSON)
            output_dir: Директория для выходных JSONL-файлов
            validation_split: Доля валидационных данных

        Returns:
            Статистика импорта:
                - total_records: кол-во записей в файле оценок
                - processed: успешно обработано
                - ocr_failed: OCR не удался
                - missing_files: файлы не найдены
                - train_path / val_path: пути к JSONL
        """
        os.makedirs(output_dir, exist_ok=True)

        # 1. Загружаем экспертные оценки
        records = self.load_expert_scores(scores_path)
        if not records:
            return {"total_records": 0, "processed": 0, "error": "Нет записей"}

        # 2. Обрабатываем каждую работу
        samples = []
        stats = {
            "total_records": len(records),
            "processed": 0,
            "ocr_failed": 0,
            "missing_files": 0,
            "skipped_no_scores": 0,
        }

        for i, record in enumerate(records):
            filename = record["filename"]
            image_path = os.path.join(scans_dir, filename)

            # Проверяем наличие файла
            if not os.path.exists(image_path):
                logger.warning(f"[{i+1}/{len(records)}] Файл не найден: {image_path}")
                stats["missing_files"] += 1
                continue

            # Проверяем наличие оценок
            if not record["scores"] and not record["expert_comment"]:
                logger.warning(f"[{i+1}/{len(records)}] Нет оценок для: {filename}")
                stats["skipped_no_scores"] += 1
                continue

            task_type = record["task_type"]
            topic = record["topic"]
            task_context = f"ЕГЭ обществознание, {task_type}, тема: {topic}"

            logger.info(
                f"[{i+1}/{len(records)}] OCR: {filename} "
                f"({task_type}, {topic})"
            )

            # 3. OCR скана
            ocr_result = await self.ocr_image_file(image_path, task_context)

            if not ocr_result["success"] or not ocr_result.get("text"):
                logger.warning(
                    f"[{i+1}/{len(records)}] OCR не удался для {filename}: "
                    f"{ocr_result.get('error', 'пустой текст')}"
                )
                stats["ocr_failed"] += 1
                continue

            student_answer = ocr_result["text"]
            confidence = ocr_result.get("confidence", 0)
            corrected = ocr_result.get("corrected", False)

            logger.info(
                f"  OCR OK: {len(student_answer)} символов, "
                f"уверенность: {confidence:.0%}, "
                f"коррекция: {'да' if corrected else 'нет'}"
            )

            # 4. Формируем обучающий пример
            sample = self._build_training_sample(
                task_type=task_type,
                topic=topic,
                student_answer=student_answer,
                scores=record["scores"],
                expert_comment=record["expert_comment"],
                task_text=record.get("task_text", ""),
            )

            if sample:
                samples.append(sample)
                stats["processed"] += 1

        if not samples:
            logger.warning("Не удалось создать ни одного обучающего примера")
            stats["train_path"] = None
            stats["val_path"] = None
            return stats

        # 5. Разбиваем на train/val и записываем JSONL
        import random
        random.seed(42)
        random.shuffle(samples)

        val_count = max(1, int(len(samples) * validation_split))
        val_samples = samples[:val_count]
        train_samples = samples[val_count:]

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        train_path = os.path.join(output_dir, f"expert_train_{timestamp}.jsonl")
        val_path = os.path.join(output_dir, f"expert_val_{timestamp}.jsonl")

        TrainingDataExporter._write_jsonl(train_path, train_samples)
        TrainingDataExporter._write_jsonl(val_path, val_samples)

        stats["train_samples"] = len(train_samples)
        stats["val_samples"] = len(val_samples)
        stats["train_path"] = train_path
        stats["val_path"] = val_path

        logger.info(f"Импорт завершён: {stats}")
        return stats

    def _build_training_sample(
        self,
        task_type: str,
        topic: str,
        student_answer: str,
        scores: Dict[str, int],
        expert_comment: str,
        task_text: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Формирует один обучающий пример из экспертной оценки."""
        system_prompt = TrainingDataExporter.SYSTEM_PROMPTS.get(
            task_type, TrainingDataExporter.SYSTEM_PROMPTS.get("task25", "")
        )

        # Промпт пользователя — аналогичен реальному запросу к модели
        max_scores = {"task19": 3, "task20": 3, "task24": 4, "task25": 6}
        max_score = max_scores.get(task_type, 6)

        # Формируем блок с текстом задания (если есть)
        task_text_block = ""
        if task_text:
            task_text_block = f"Текст задания:\n{task_text}\n\n"

        user_prompt = (
            f'Проверь ответ на задание по теме: "{topic}"\n\n'
            f"{task_text_block}"
            f"Ответ ученика:\n{student_answer}\n\n"
            f"Оцени ответ по критериям ЕГЭ (максимум {max_score} баллов). "
            f"Верни структурированный JSON с полями: score, criteria_scores, "
            f"main_issues, suggestions."
        )

        # Эталонный ответ — экспертная оценка
        total = sum(scores.values()) if scores else 0
        response_data: Dict[str, Any] = {
            "score": total,
            "criteria_scores": scores,
        }

        if expert_comment:
            response_data["feedback"] = expert_comment

            # Извлекаем проблемы и рекомендации из комментария,
            # если они достаточно информативны
            if total < max_score:
                response_data["main_issues"] = [expert_comment]
                response_data["suggestions"] = [
                    "Обратите внимание на замечания эксперта"
                ]
            else:
                response_data["main_issues"] = []
                response_data["suggestions"] = []
        else:
            response_data["feedback"] = (
                f"Оценка: {total}/{max_score}."
            )
            response_data["main_issues"] = []
            response_data["suggestions"] = []

        response = json.dumps(response_data, ensure_ascii=False, indent=2)

        return {
            "request": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_prompt},
            ],
            "response": response,
            "_task_type": task_type,
        }

    @staticmethod
    def generate_scores_template(output_path: str, format: str = "csv") -> None:
        """
        Генерирует шаблон файла экспертных оценок.

        Args:
            output_path: Путь для сохранения шаблона
            format: Формат файла ('csv' или 'json')
        """
        if format == "csv":
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "filename", "task_type", "topic", "task_text",
                    "k1_score", "k2_score", "k3_score",
                    "expert_comment",
                ])
                # Примеры
                writer.writerow([
                    "work_01.jpg", "task25", "Функции государства",
                    "Обоснуйте необходимость выполнения государством функции "
                    "поддержания общественного порядка. Приведите три примера "
                    "реализации данной функции.",
                    "2", "1", "3",
                    "Обоснование корректное, но примеры недостаточно развёрнуты",
                ])
                writer.writerow([
                    "work_02.png", "task19", "Социальные институты",
                    "Приведите три примера, иллюстрирующих функции "
                    "социальных институтов в обществе.",
                    "3", "", "",
                    "Все три примера конкретны и соответствуют теме",
                ])
                writer.writerow([
                    "work_03.jpg", "task20", "Рыночная экономика",
                    "Используя обществоведческие знания, сформулируйте два "
                    "суждения о преимуществах рыночной экономики и одно "
                    "суждение о её недостатках.",
                    "2", "", "",
                    "Второе суждение слишком абстрактное",
                ])
        else:
            template = [
                {
                    "filename": "work_01.jpg",
                    "task_type": "task25",
                    "topic": "Функции государства",
                    "task_text": (
                        "Обоснуйте необходимость выполнения государством функции "
                        "поддержания общественного порядка. Приведите три примера "
                        "реализации данной функции."
                    ),
                    "scores": {"К1": 2, "К2": 1, "К3": 3},
                    "expert_comment": "Обоснование корректное, но примеры недостаточно развёрнуты",
                },
                {
                    "filename": "work_02.png",
                    "task_type": "task19",
                    "topic": "Социальные институты",
                    "task_text": (
                        "Приведите три примера, иллюстрирующих функции "
                        "социальных институтов в обществе."
                    ),
                    "scores": {"К1": 3},
                    "expert_comment": "Все три примера конкретны и соответствуют теме",
                },
                {
                    "filename": "work_03.jpg",
                    "task_type": "task20",
                    "topic": "Рыночная экономика",
                    "task_text": (
                        "Используя обществоведческие знания, сформулируйте два "
                        "суждения о преимуществах рыночной экономики и одно "
                        "суждение о её недостатках."
                    ),
                    "scores": {"К1": 2},
                    "expert_comment": "Второе суждение слишком абстрактное",
                },
            ]
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(template, f, ensure_ascii=False, indent=2)

        logger.info(f"Шаблон создан: {output_path}")
