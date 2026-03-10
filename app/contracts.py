from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from fastapi import HTTPException, UploadFile


class FileExtension(str, Enum):
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"
    HEIC = "heic"
    HEIF = "heif"
    JFIF = "jfif"
    PDF = "pdf"


DEFAULT_QUALITY = 100
SUPPORTED_REQUEST_EXTENSIONS = {
    FileExtension.JPG,
    FileExtension.JPEG,
    FileExtension.PNG,
    FileExtension.HEIC,
    FileExtension.HEIF,
    FileExtension.JFIF,
    FileExtension.PDF,
}
SUPPORTED_TARGET_EXTENSIONS = {FileExtension.JPG, FileExtension.JPEG}
SUPPORTED_CONVERSION_SOURCE_EXTENSIONS = {FileExtension.HEIC, FileExtension.HEIF}
SUPPORTED_CONTENT_TYPES = {"image/heic", "image/heif"}


@dataclass(slots=True)
class ConversionRequest:
    file: UploadFile
    source_extension: FileExtension | None
    target_extension: FileExtension
    quality: int


def build_conversion_request(
    *,
    file: UploadFile | None,
    target_extension_value: str | None,
    quality_value: str | None,
) -> ConversionRequest:
    if file is None:
        raise HTTPException(status_code=400, detail="File is required.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    source_extension = parse_extension(file.filename)
    content_type = (file.content_type or "").lower()
    if content_type not in SUPPORTED_CONTENT_TYPES and source_extension not in SUPPORTED_CONVERSION_SOURCE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Only HEIC/HEIF files are supported.")

    target_extension = parse_target_extension(target_extension_value)
    quality = parse_quality(quality_value)

    return ConversionRequest(
        file=file,
        source_extension=source_extension,
        target_extension=target_extension,
        quality=quality,
    )


def parse_extension(filename: str) -> FileExtension | None:
    suffix = Path(filename).suffix.strip().lower().lstrip(".")
    if not suffix:
        return None

    try:
        extension = FileExtension(suffix)
    except ValueError:
        return None

    if extension not in SUPPORTED_REQUEST_EXTENSIONS:
        return None
    return extension


def parse_quality(raw_value: str | None) -> int:
    if raw_value is None or raw_value == "":
        return DEFAULT_QUALITY

    try:
        quality = int(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Quality must be an integer between 1 and 100.") from exc

    if not 1 <= quality <= 100:
        raise HTTPException(status_code=400, detail="Quality must be an integer between 1 and 100.")

    return quality


def parse_target_extension(raw_value: str | None) -> FileExtension:
    if raw_value is None or raw_value == "":
        raise HTTPException(status_code=400, detail="targetExtension is required.")

    normalized = raw_value.strip().lower().lstrip(".")
    try:
        target_extension = FileExtension(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported targetExtension value.") from exc

    if target_extension not in SUPPORTED_TARGET_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Only JPG/JPEG output is supported.")

    return target_extension
