import os
from dataclasses import dataclass


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, parsed)


def _float_env(name: str, default: float, minimum: float = 0.1) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(minimum, parsed)


@dataclass(frozen=True)
class Settings:
    worker_count: int
    queue_maxsize: int
    enqueue_timeout_sec: float
    job_timeout_sec: float
    jpeg_quality: int
    max_upload_bytes: int


def load_settings() -> Settings:
    default_workers = os.cpu_count() or 4
    max_upload_mb = _int_env("CONVERTER_MAX_UPLOAD_MB", 50)
    return Settings(
        worker_count=_int_env("CONVERTER_WORKERS", default_workers),
        queue_maxsize=_int_env("CONVERTER_QUEUE_MAXSIZE", 512),
        enqueue_timeout_sec=_float_env("CONVERTER_ENQUEUE_TIMEOUT_SEC", 2.0),
        job_timeout_sec=_float_env("CONVERTER_JOB_TIMEOUT_SEC", 30.0),
        jpeg_quality=_int_env("CONVERTER_JPEG_QUALITY", 100),
        max_upload_bytes=max_upload_mb * 1024 * 1024,
    )


settings = load_settings()
