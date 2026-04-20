"""Validación robusta de imágenes — magic bytes + tamaño."""
import os
import logging
from PIL import Image
from io import BytesIO

logger = logging.getLogger(__name__)

MAX_IMAGE_WIDTH = 8000
MAX_IMAGE_HEIGHT = 8000
MAX_IMAGE_PIXELS = 50_000_000  # 50MP
MAX_IMAGE_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def validate_image_file(file_obj, max_size_bytes=MAX_IMAGE_FILE_SIZE) -> tuple:
    """
    Valida imagen: magic bytes, dimensiones, tamaño.
    Retorna (válido: bool, mensaje: str)

    Sube file_obj hasta max_size_bytes para no cargar archivos enormes.
    """
    try:
        # Validación 1: Tamaño de archivo
        file_obj.seek(0, 2)  # Ir al final
        file_size = file_obj.tell()
        file_obj.seek(0)  # Volver al inicio

        if file_size > max_size_bytes:
            return False, f"Archivo muy grande ({file_size // 1024} KB, máx {max_size_bytes // 1024} KB)"

        if file_size == 0:
            return False, "Archivo vacío"

        # Validación 2: Validar que sea imagen real (magic bytes + PIL)
        try:
            img = Image.open(file_obj)
            img.load()  # Fuerza lectura completa para validar integridad
        except Exception as e:
            return False, f"Archivo no es imagen válida: {str(e)}"

        # Validación 3: Dimensiones
        width, height = img.size
        if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
            return False, f"Imagen muy grande ({width}x{height}, máx {MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT})"

        if width * height > MAX_IMAGE_PIXELS:
            return False, f"Imagen excede píxeles máx ({width * height} > {MAX_IMAGE_PIXELS})"

        if width < 100 or height < 100:
            return False, f"Imagen muy pequeña ({width}x{height}, mín 100x100)"

        return True, "OK"

    except Exception as e:
        logger.error(f"Error validando imagen: {e}")
        return False, f"Error interno: {str(e)}"
