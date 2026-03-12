#!/usr/bin/env python3
"""
CLI-скрипт для дообучения YandexGPT на экспертных оценках ЕГЭ.

Использование:
    # Создать шаблон файла экспертных оценок
    python scripts/finetune.py template --output scores.csv

    # Импорт сканов работ + экспертные оценки → JSONL
    python scripts/finetune.py import --scans-dir data/scans --scores scores.csv

    # Просмотр доступных данных (из БД)
    python scripts/finetune.py stats

    # Экспорт данных из БД в JSONL
    python scripts/finetune.py export --output-dir data/training

    # Запуск дообучения (требует S3 credentials)
    python scripts/finetune.py train --train-file data/training/train_*.jsonl

    # Проверка статуса задачи
    python scripts/finetune.py status --job-id <job_id>
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в PATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from core.finetuning.data_exporter import TrainingDataExporter
from core.finetuning.expert_import import ExpertDataImporter
from core.finetuning.tuning_service import (
    YandexGPTTuningService,
    TuningJobConfig,
    TuningStatus,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("finetune")


async def cmd_template(args: argparse.Namespace) -> None:
    """Создать шаблон файла экспертных оценок."""
    fmt = "json" if args.output.endswith(".json") else "csv"
    ExpertDataImporter.generate_scores_template(args.output, format=fmt)

    print(f"\nШаблон создан: {args.output}")
    print(f"Формат: {fmt.upper()}")
    print()
    print("Заполните файл данными ваших экспертных оценок:")
    print("  filename       — имя файла скана (work_01.jpg)")
    print("  task_type      — тип задания (task19, task20, task24, task25)")
    print("  topic          — тема задания")
    print("  task_text      — полный текст задания из КИМ")
    print("  k1_score       — балл по критерию К1")
    print("  k2_score       — балл по критерию К2 (если применимо)")
    print("  k3_score       — балл по критерию К3 (если применимо)")
    print("  expert_comment — комментарий эксперта")
    print()
    print("Затем запустите импорт:")
    print(f"  python scripts/finetune.py import --scans-dir <папка_со_сканами> --scores {args.output}")


async def cmd_import(args: argparse.Namespace) -> None:
    """Импорт сканов работ с экспертными оценками."""
    importer = ExpertDataImporter()

    print(f"\n=== Импорт экспертных данных ===\n")
    print(f"Сканы:  {args.scans_dir}")
    print(f"Оценки: {args.scores}")
    print(f"Выход:  {args.output_dir}")
    print()

    # Предварительная проверка
    records = importer.load_expert_scores(args.scores)
    print(f"Загружено записей с оценками: {len(records)}")

    # Проверяем наличие файлов сканов
    found = 0
    missing = []
    for r in records:
        path = os.path.join(args.scans_dir, r["filename"])
        if os.path.exists(path):
            found += 1
        else:
            missing.append(r["filename"])

    print(f"Найдено сканов: {found}/{len(records)}")
    if missing:
        print(f"Не найдены ({len(missing)}):")
        for m in missing[:5]:
            print(f"  - {m}")
        if len(missing) > 5:
            print(f"  ... и ещё {len(missing) - 5}")
    print()

    if found == 0:
        print("Нет файлов для обработки. Проверьте путь к директории со сканами.")
        return

    print("Запуск OCR и формирование обучающих данных...\n")

    stats = await importer.import_expert_data(
        scans_dir=args.scans_dir,
        scores_path=args.scores,
        output_dir=args.output_dir,
        validation_split=args.val_split,
    )

    print(f"\n=== Результат импорта ===\n")
    print(f"Всего записей:       {stats['total_records']}")
    print(f"Обработано успешно:  {stats['processed']}")
    print(f"OCR не удался:       {stats.get('ocr_failed', 0)}")
    print(f"Файлы не найдены:    {stats.get('missing_files', 0)}")
    print()

    if stats.get("train_path"):
        print(f"Обучающая выборка:    {stats.get('train_samples', 0)} примеров")
        print(f"Валидационная выборка: {stats.get('val_samples', 0)} примеров")
        print()
        print(f"Обучающий файл:       {stats['train_path']}")
        print(f"Валидационный файл:   {stats['val_path']}")
        print()
        print("Следующий шаг — запуск дообучения:")
        print(f"  python scripts/finetune.py train --train-file {stats['train_path']} --wait")
    else:
        print("Не удалось создать обучающие данные.")


async def cmd_stats(args: argparse.Namespace) -> None:
    """Показать статистику доступных данных для дообучения."""
    exporter = TrainingDataExporter()
    stats = await exporter.get_data_stats()

    print("\n=== Статистика данных для дообучения ===\n")
    print(f"Одобренных жалоб (с данными):     {stats['approved_complaints']}")
    print(f"Всего записей с ответами и оценками: {stats['total_feedback_with_answers']}")
    print()

    if stats["by_task_type"]:
        print("По типам заданий:")
        for task, count in sorted(stats["by_task_type"].items()):
            print(f"  {task}: {count}")
    else:
        print("По типам заданий: нет данных")
    print()

    if stats["by_resolution"]:
        print("По резолюциям:")
        for res, count in sorted(stats["by_resolution"].items()):
            print(f"  {res}: {count}")
    else:
        print("По резолюциям: нет данных")

    total = stats["approved_complaints"] + stats["total_feedback_with_answers"]
    print()
    if total < 50:
        print(
            "РЕКОМЕНДАЦИЯ: Для качественного дообучения желательно иметь "
            "не менее 50 обучающих примеров. Сейчас доступно примерно "
            f"{total}. Продолжайте собирать экспертные оценки."
        )
    else:
        print(f"Данных достаточно для запуска дообучения (примерно {total} примеров).")


async def cmd_export(args: argparse.Namespace) -> None:
    """Экспортировать данные в JSONL."""
    exporter = TrainingDataExporter()

    task_types = args.task_types if args.task_types else None

    stats = await exporter.export_training_data(
        output_dir=args.output_dir,
        task_types=task_types,
        min_score=args.min_score,
        validation_split=args.val_split,
    )

    print("\n=== Результат экспорта ===\n")

    if stats["total_samples"] == 0:
        print("Нет данных для экспорта.")
        print(
            "Убедитесь, что в БД есть записи user_feedback "
            "с одобренными жалобами или оценками."
        )
        return

    print(f"Всего примеров:       {stats['total_samples']}")
    print(f"Обучающая выборка:    {stats['train_samples']}")
    print(f"Валидационная выборка: {stats['val_samples']}")
    print()

    if stats["by_task_type"]:
        print("Распределение по заданиям:")
        for task, count in sorted(stats["by_task_type"].items()):
            print(f"  {task}: {count}")
    print()

    print(f"Обучающий файл:       {stats['train_path']}")
    print(f"Валидационный файл:   {stats['val_path']}")
    print()

    # Показать пример первой записи
    if stats["train_path"]:
        with open(stats["train_path"], "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line:
                sample = json.loads(first_line)
                print("Пример обучающей записи:")
                print(json.dumps(sample, ensure_ascii=False, indent=2)[:500] + "...")


async def cmd_train(args: argparse.Namespace) -> None:
    """Запустить дообучение."""
    service = YandexGPTTuningService()

    config = TuningJobConfig(
        base_model=args.base_model,
        learning_rate=args.learning_rate,
        num_epochs=args.epochs,
        batch_size=args.batch_size,
    )

    # Загрузка данных в S3 (если указан локальный файл)
    train_uri = args.train_file
    val_uri = args.val_file

    if not train_uri.startswith("s3://"):
        print("Загрузка данных в Yandex Object Storage...")
        uris = await service.upload_training_data(train_uri, val_uri)
        train_uri = uris["train_uri"]
        val_uri = uris.get("val_uri")
        print(f"  Обучающие данные: {train_uri}")
        if val_uri:
            print(f"  Валидационные данные: {val_uri}")

    print("\nЗапуск дообучения...")
    result = await service.start_tuning(
        train_uri=train_uri,
        val_uri=val_uri,
        config=config,
    )

    if result.status == TuningStatus.FAILED:
        print(f"\nОшибка: {result.error}")
        sys.exit(1)

    print(f"\nЗадача дообучения создана: {result.job_id}")

    if args.wait:
        print("Ожидание завершения...")
        result = await service.wait_for_completion(
            result.job_id, poll_interval=args.poll_interval
        )

        if result.status == TuningStatus.COMPLETED:
            print(f"\nДообучение завершено!")
            print(f"URI модели: {result.model_uri}")
            if result.metrics:
                print(f"Метрики: {json.dumps(result.metrics, indent=2)}")
            print(
                f"\nДобавьте в .env:\n"
                f"YANDEX_GPT_FINETUNED_MODEL_URI={result.model_uri}"
            )
        else:
            print(f"\nОшибка дообучения: {result.error}")
            sys.exit(1)
    else:
        print(
            f"\nДля проверки статуса:\n"
            f"  python scripts/finetune.py status --job-id {result.job_id}"
        )


async def cmd_status(args: argparse.Namespace) -> None:
    """Проверить статус задачи дообучения."""
    service = YandexGPTTuningService()
    result = await service.get_tuning_status(args.job_id)

    print(f"\n=== Статус задачи {args.job_id} ===\n")
    print(f"Статус: {result.status.value}")

    if result.model_uri:
        print(f"URI модели: {result.model_uri}")
        print(
            f"\nДобавьте в .env:\n"
            f"YANDEX_GPT_FINETUNED_MODEL_URI={result.model_uri}"
        )

    if result.metrics:
        print(f"Метрики: {json.dumps(result.metrics, indent=2)}")

    if result.error:
        print(f"Ошибка: {result.error}")


def main():
    parser = argparse.ArgumentParser(
        description="Дообучение YandexGPT на экспертных оценках ЕГЭ",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # template
    template_parser = subparsers.add_parser(
        "template", help="Создать шаблон файла экспертных оценок"
    )
    template_parser.add_argument(
        "--output", default="expert_scores.csv",
        help="Путь для шаблона (.csv или .json)"
    )

    # import
    import_parser = subparsers.add_parser(
        "import", help="Импорт сканов работ с экспертными оценками"
    )
    import_parser.add_argument(
        "--scans-dir", required=True, help="Директория со сканами работ"
    )
    import_parser.add_argument(
        "--scores", required=True, help="CSV/JSON с экспертными оценками"
    )
    import_parser.add_argument(
        "--output-dir", default="data/training", help="Директория для JSONL"
    )
    import_parser.add_argument(
        "--val-split", type=float, default=0.1, help="Доля валидации (0.0-1.0)"
    )

    # stats
    subparsers.add_parser("stats", help="Статистика доступных данных (из БД)")

    # export
    export_parser = subparsers.add_parser("export", help="Экспорт данных в JSONL")
    export_parser.add_argument(
        "--output-dir", default="data/training", help="Директория для файлов"
    )
    export_parser.add_argument(
        "--task-types", nargs="+", help="Фильтр по типам заданий (task19 task25 ...)"
    )
    export_parser.add_argument(
        "--min-score", type=int, help="Минимальный балл для включения"
    )
    export_parser.add_argument(
        "--val-split", type=float, default=0.1, help="Доля валидации (0.0-1.0)"
    )

    # train
    train_parser = subparsers.add_parser("train", help="Запуск дообучения")
    train_parser.add_argument("--train-file", required=True, help="JSONL или S3 URI")
    train_parser.add_argument("--val-file", help="Валидационный JSONL или S3 URI")
    train_parser.add_argument(
        "--base-model", default="yandexgpt", help="Базовая модель"
    )
    train_parser.add_argument(
        "--learning-rate", type=float, default=1e-5, help="Скорость обучения"
    )
    train_parser.add_argument("--epochs", type=int, default=3, help="Число эпох")
    train_parser.add_argument("--batch-size", type=int, default=8, help="Размер батча")
    train_parser.add_argument(
        "--wait", action="store_true", help="Ждать завершения"
    )
    train_parser.add_argument(
        "--poll-interval", type=int, default=30, help="Интервал опроса (сек)"
    )

    # status
    status_parser = subparsers.add_parser("status", help="Статус задачи дообучения")
    status_parser.add_argument("--job-id", required=True, help="ID задачи")

    args = parser.parse_args()

    commands = {
        "template": cmd_template,
        "import": cmd_import,
        "stats": cmd_stats,
        "export": cmd_export,
        "train": cmd_train,
        "status": cmd_status,
    }

    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
