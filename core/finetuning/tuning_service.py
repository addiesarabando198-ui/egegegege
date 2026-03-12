"""
Сервис дообучения YandexGPT через Foundation Models API.

Управляет полным циклом дообучения:
1. Загрузка обучающих данных в Yandex Object Storage
2. Запуск задачи дообучения через API
3. Мониторинг статуса задачи
4. Получение URI дообученной модели
"""

import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)


class TuningStatus(Enum):
    """Статусы задачи дообучения."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TuningJobConfig:
    """Конфигурация задачи дообучения."""
    base_model: str = "yandexgpt"
    learning_rate: float = 1e-5
    num_epochs: int = 3
    batch_size: int = 8
    warmup_ratio: float = 0.1
    seed: int = 42
    additional_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TuningJobResult:
    """Результат задачи дообучения."""
    job_id: str
    status: TuningStatus
    model_uri: Optional[str] = None
    metrics: Optional[Dict[str, float]] = None
    error: Optional[str] = None


class YandexGPTTuningService:
    """Сервис для дообучения YandexGPT через API."""

    TUNING_API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/tuning"
    TUNING_STATUS_URL = "https://llm.api.cloud.yandex.net/operations"
    S3_ENDPOINT = "https://storage.yandexcloud.net"

    def __init__(
        self,
        api_key: Optional[str] = None,
        folder_id: Optional[str] = None,
        s3_access_key: Optional[str] = None,
        s3_secret_key: Optional[str] = None,
        s3_bucket: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("YANDEX_GPT_API_KEY")
        self.folder_id = folder_id or os.getenv("YANDEX_GPT_FOLDER_ID")
        self.s3_access_key = s3_access_key or os.getenv("YANDEX_S3_ACCESS_KEY")
        self.s3_secret_key = s3_secret_key or os.getenv("YANDEX_S3_SECRET_KEY")
        self.s3_bucket = s3_bucket or os.getenv(
            "YANDEX_S3_BUCKET", "ege-superbot-training"
        )

        if not self.api_key or not self.folder_id:
            raise ValueError(
                "Необходимо установить YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID"
            )

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

    async def upload_training_data(
        self,
        train_path: str,
        val_path: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Загружает обучающие данные в Yandex Object Storage.

        Args:
            train_path: Путь к файлу обучающей выборки (JSONL)
            val_path: Путь к файлу валидационной выборки (JSONL)

        Returns:
            Словарь с URI загруженных файлов:
                - train_uri: S3 URI обучающих данных
                - val_uri: S3 URI валидационных данных (если указан)
        """
        if not self.s3_access_key or not self.s3_secret_key:
            raise ValueError(
                "Для загрузки данных в Object Storage необходимо установить "
                "YANDEX_S3_ACCESS_KEY и YANDEX_S3_SECRET_KEY. "
                "Также можно загрузить файлы вручную через консоль Yandex Cloud."
            )

        try:
            import boto3
        except ImportError:
            raise ImportError(
                "Для загрузки данных в Object Storage установите boto3: "
                "pip install boto3"
            )

        session = boto3.session.Session()
        s3 = session.client(
            service_name="s3",
            endpoint_url=self.S3_ENDPOINT,
            aws_access_key_id=self.s3_access_key,
            aws_secret_access_key=self.s3_secret_key,
        )

        result = {}

        # Загружаем обучающие данные
        train_key = f"training/{os.path.basename(train_path)}"
        s3.upload_file(train_path, self.s3_bucket, train_key)
        result["train_uri"] = f"s3://{self.s3_bucket}/{train_key}"
        logger.info(f"Обучающие данные загружены: {result['train_uri']}")

        # Загружаем валидационные данные
        if val_path:
            val_key = f"training/{os.path.basename(val_path)}"
            s3.upload_file(val_path, self.s3_bucket, val_key)
            result["val_uri"] = f"s3://{self.s3_bucket}/{val_key}"
            logger.info(f"Валидационные данные загружены: {result['val_uri']}")

        return result

    async def start_tuning(
        self,
        train_uri: str,
        val_uri: Optional[str] = None,
        config: Optional[TuningJobConfig] = None,
    ) -> TuningJobResult:
        """
        Запускает задачу дообучения YandexGPT.

        Args:
            train_uri: S3 URI обучающих данных
            val_uri: S3 URI валидационных данных
            config: Конфигурация дообучения

        Returns:
            TuningJobResult с ID задачи и начальным статусом
        """
        if config is None:
            config = TuningJobConfig()

        payload = {
            "baseModelUri": f"gpt://{self.folder_id}/{config.base_model}",
            "trainingDatasets": [
                {"datasetUri": train_uri, "weight": 1.0}
            ],
            "completionOptions": {
                "maxTokens": "2000",
            },
            "hyperparameters": {
                "learningRate": str(config.learning_rate),
                "numEpochs": str(config.num_epochs),
                "batchSize": str(config.batch_size),
                "warmupRatio": str(config.warmup_ratio),
                "seed": str(config.seed),
            },
        }

        if val_uri:
            payload["validationDatasets"] = [
                {"datasetUri": val_uri, "weight": 1.0}
            ]

        # Добавляем дополнительные параметры
        payload["hyperparameters"].update(
            {k: str(v) for k, v in config.additional_params.items()}
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.TUNING_API_URL,
                json=payload,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get("message", str(data))
                    logger.error(f"Ошибка запуска дообучения: {error_msg}")
                    return TuningJobResult(
                        job_id="",
                        status=TuningStatus.FAILED,
                        error=error_msg,
                    )

                job_id = data.get("id", "")
                logger.info(f"Задача дообучения запущена: {job_id}")

                return TuningJobResult(
                    job_id=job_id,
                    status=TuningStatus.PENDING,
                )

    async def get_tuning_status(self, job_id: str) -> TuningJobResult:
        """
        Проверяет статус задачи дообучения.

        Args:
            job_id: ID задачи

        Returns:
            TuningJobResult с текущим статусом
        """
        url = f"{self.TUNING_STATUS_URL}/{job_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    return TuningJobResult(
                        job_id=job_id,
                        status=TuningStatus.FAILED,
                        error=data.get("message", str(data)),
                    )

                done = data.get("done", False)
                error = data.get("error")

                if error:
                    return TuningJobResult(
                        job_id=job_id,
                        status=TuningStatus.FAILED,
                        error=error.get("message", str(error)),
                    )

                if done:
                    response = data.get("response", {})
                    model_uri = response.get("modelUri", "")
                    metrics = response.get("metrics", {})

                    return TuningJobResult(
                        job_id=job_id,
                        status=TuningStatus.COMPLETED,
                        model_uri=model_uri,
                        metrics=metrics,
                    )

                return TuningJobResult(
                    job_id=job_id,
                    status=TuningStatus.RUNNING,
                )

    async def wait_for_completion(
        self,
        job_id: str,
        poll_interval: int = 30,
        max_wait: int = 7200,
    ) -> TuningJobResult:
        """
        Ожидает завершения задачи дообучения.

        Args:
            job_id: ID задачи
            poll_interval: Интервал опроса в секундах
            max_wait: Максимальное время ожидания в секундах

        Returns:
            TuningJobResult с финальным статусом
        """
        elapsed = 0

        while elapsed < max_wait:
            result = await self.get_tuning_status(job_id)

            if result.status in (TuningStatus.COMPLETED, TuningStatus.FAILED):
                return result

            logger.info(
                f"Дообучение в процессе... ({elapsed}с прошло, "
                f"статус: {result.status.value})"
            )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return TuningJobResult(
            job_id=job_id,
            status=TuningStatus.FAILED,
            error=f"Превышено максимальное время ожидания ({max_wait}с)",
        )

    def get_finetuned_model_uri(self, job_id: str) -> str:
        """
        Возвращает URI дообученной модели для использования в запросах.

        Args:
            job_id: ID завершённой задачи дообучения

        Returns:
            URI модели в формате ds://<job_id>
        """
        return f"ds://{job_id}"
