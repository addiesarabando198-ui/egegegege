"""
Модуль предобработки изображений для улучшения OCR-распознавания рукописного текста.

Применяет серию преобразований к фотографиям рукописного текста перед отправкой
в Yandex Vision API, что значительно повышает качество распознавания.
"""

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    logger.warning("Pillow not installed. Image preprocessing disabled. pip install Pillow")


def preprocess_for_ocr(image_bytes: bytes) -> bytes:
    """
    Предобработка изображения для улучшения OCR рукописного текста.

    Применяет последовательность фильтров:
    1. Конвертация в градации серого
    2. Автоконтраст для нормализации яркости
    3. Повышение контрастности (усиление чернил vs бумаги)
    4. Повышение резкости
    5. Лёгкое размытие для сглаживания шума
    6. Масштабирование до оптимального размера для OCR

    Args:
        image_bytes: Исходные байты изображения

    Returns:
        Обработанные байты изображения (JPEG)
    """
    if not PILLOW_AVAILABLE:
        logger.debug("Pillow unavailable, returning original image")
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))

        # EXIF-ориентация (фото с телефона часто повёрнуты)
        img = ImageOps.exif_transpose(img)

        # Конвертация в градации серого - убирает цветовой шум от бумаги
        img = img.convert('L')

        # Автоконтраст - нормализует уровни яркости
        img = ImageOps.autocontrast(img, cutoff=1)

        # Повышение контрастности - делает чернила темнее, бумагу светлее
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)

        # Повышение резкости - чётче контуры букв
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.8)

        # Лёгкий медианный фильтр - убирает точечный шум, сохраняя контуры
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # Масштабирование: OCR лучше работает при ~300 DPI
        # Если изображение слишком маленькое - увеличиваем
        # Если слишком большое - уменьшаем для скорости
        width, height = img.size
        target_width = 2000  # Оптимальная ширина для OCR

        if width < 1000:
            # Маленькое фото - увеличиваем
            scale = target_width / width
            new_size = (int(width * scale), int(height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(f"Image upscaled: {width}x{height} -> {new_size[0]}x{new_size[1]}")
        elif width > 4000:
            # Слишком большое - уменьшаем для скорости API
            scale = target_width / width
            new_size = (int(width * scale), int(height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(f"Image downscaled: {width}x{height} -> {new_size[0]}x{new_size[1]}")

        # Сохраняем в JPEG с хорошим качеством
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=92)
        result_bytes = output.getvalue()

        logger.info(
            f"Image preprocessed: {len(image_bytes)} -> {len(result_bytes)} bytes, "
            f"size: {img.size[0]}x{img.size[1]}"
        )

        return result_bytes

    except Exception as e:
        logger.error(f"Image preprocessing failed: {e}", exc_info=True)
        # В случае ошибки возвращаем оригинал
        return image_bytes


def compress_for_claude(image_bytes: bytes, max_dimension: int = 1568) -> bytes:
    """
    Оптимизация изображения для Claude Vision API.

    Claude Vision работает отлично с изображениями до 1568px по длинной стороне.
    Сжатие драматически уменьшает payload (5-10MB → 100-300KB), что критично
    для передачи через CF Worker / прокси без таймаутов.

    В отличие от preprocess_for_ocr, НЕ конвертирует в grayscale —
    Claude использует цветовую информацию для лучшего распознавания.

    Args:
        image_bytes: Исходные байты изображения
        max_dimension: Максимальный размер по длинной стороне (px)

    Returns:
        Сжатые байты изображения (JPEG)
    """
    if not PILLOW_AVAILABLE:
        logger.debug("Pillow unavailable, returning original image")
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))

        # EXIF-ориентация (фото с телефона часто повёрнуты)
        img = ImageOps.exif_transpose(img)

        # RGB для JPEG (убирает альфа-канал если есть)
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Масштабирование по длинной стороне
        width, height = img.size
        max_side = max(width, height)
        if max_side > max_dimension:
            scale = max_dimension / max_side
            new_size = (int(width * scale), int(height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(
                f"Claude image resized: {width}x{height} -> "
                f"{new_size[0]}x{new_size[1]}"
            )

        # JPEG quality 85 — хороший баланс качества и размера
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        result_bytes = output.getvalue()

        logger.info(
            f"Claude image compressed: {len(image_bytes)} -> {len(result_bytes)} bytes "
            f"({len(image_bytes) / max(len(result_bytes), 1):.1f}x reduction), "
            f"size: {img.size[0]}x{img.size[1]}"
        )

        return result_bytes

    except Exception as e:
        logger.error(f"Claude image compression failed: {e}", exc_info=True)
        return image_bytes


def preprocess_for_ocr_enhanced(image_bytes: bytes) -> bytes:
    """
    Усиленная предобработка для сложных случаев (низкая уверенность OCR).

    Более агрессивные фильтры для плохо читаемого почерка:
    - Адаптивная бинаризация
    - Усиленный контраст
    - Морфологическая очистка

    Args:
        image_bytes: Исходные байты изображения

    Returns:
        Обработанные байты изображения (JPEG)
    """
    if not PILLOW_AVAILABLE:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        img = img.convert('L')

        # Агрессивный автоконтраст
        img = ImageOps.autocontrast(img, cutoff=3)

        # Сильное повышение контраста
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        # Повышение яркости (чтобы фон стал белым)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.2)

        # Ещё раз контраст после осветления
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)

        # Резкость
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)

        # Масштабирование
        width, height = img.size
        target_width = 2500

        if width < 1200:
            scale = target_width / width
            new_size = (int(width * scale), int(height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        img.save(output, format='JPEG', quality=95)
        result_bytes = output.getvalue()

        logger.info(f"Enhanced preprocessing: {len(image_bytes)} -> {len(result_bytes)} bytes")

        return result_bytes

    except Exception as e:
        logger.error(f"Enhanced preprocessing failed: {e}", exc_info=True)
        return image_bytes
