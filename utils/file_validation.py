"""Validación de archivos subidos: magic bytes, tamaño máximo.

Uso recomendado en rutas que aceptan uploads:

    from utils.file_validation import validate_image_upload, UnsafeUploadError
    try:
        validate_image_upload(foto)
    except UnsafeUploadError as e:
        abort(400, description=str(e))
"""

from werkzeug.datastructures import FileStorage

# Magic bytes oficiales de formatos de imagen comunes
IMAGE_SIGNATURES = {
    b'\xff\xd8\xff': 'JPEG',
    b'\x89PNG\r\n\x1a\n': 'PNG',
    b'GIF87a': 'GIF',
    b'GIF89a': 'GIF',
}

# WebP es 'RIFF????WEBP' (? = size), se valida aparte
WEBP_HEAD = b'RIFF'
WEBP_FORMAT = b'WEBP'

# HEIC/HEIF (iPhone): bytes 4-7 = 'ftyp', bytes 8-11 = brand
HEIC_BRANDS = {b'heic', b'heix', b'mif1', b'msf1', b'hevc', b'hevx', b'heim', b'heis'}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB por archivo


class UnsafeUploadError(ValueError):
    """Archivo subido no pasa validación de formato/tamaño."""


def _read_head(file_stream: FileStorage, n: int = 12) -> bytes:
    """Lee los primeros `n` bytes sin consumir el stream."""
    pos = file_stream.tell()
    head = file_stream.read(n)
    file_stream.seek(pos)
    return head


def _detect_image_format(head: bytes) -> str | None:
    """Retorna el nombre del formato detectado o None si no es imagen reconocida."""
    for sig, name in IMAGE_SIGNATURES.items():
        if head.startswith(sig):
            return name
    # WebP: 'RIFF' + 4 bytes size + 'WEBP'
    if head[:4] == WEBP_HEAD and head[8:12] == WEBP_FORMAT:
        return 'WEBP'
    # HEIC/HEIF: 'ftyp' en pos 4-8, brand en pos 8-12
    if head[4:8] == b'ftyp' and head[8:12] in HEIC_BRANDS:
        return 'HEIC'
    return None


def validate_image_upload(
    file_storage: FileStorage,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> str:
    """Valida que un upload sea una imagen real (magic bytes) y no exceda tamaño.

    Retorna el nombre del formato detectado (JPEG/PNG/GIF/WEBP).
    Lanza UnsafeUploadError si no es válida.

    No consume el stream (seek vuelve a la posición inicial).
    """
    if file_storage is None or not file_storage.filename:
        raise UnsafeUploadError("Archivo vacío o sin nombre.")

    # Tamaño: preferir content_length si viene del header; si no, medir stream
    size = file_storage.content_length
    if size is None or size == 0:
        pos = file_storage.tell()
        file_storage.seek(0, 2)  # seek to end
        size = file_storage.tell()
        file_storage.seek(pos)

    if size > max_bytes:
        raise UnsafeUploadError(
            f"Archivo excede tamaño máximo ({size:,} > {max_bytes:,} bytes)."
        )

    head = _read_head(file_storage, 12)
    fmt = _detect_image_format(head)
    if fmt is None:
        raise UnsafeUploadError(
            "Formato de imagen no soportado. "
            "Solo se aceptan JPEG, PNG, GIF y WebP."
        )
    return fmt
