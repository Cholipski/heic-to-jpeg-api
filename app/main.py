from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.config import settings
from app.contracts import ConversionRequest, build_conversion_request
from app.converter import (
    ConversionFailedError,
    JpegConversionQueue,
    QueueFullError,
    UnsupportedFormatError,
)

app = FastAPI(
    title="File Converter",
    description="FastAPI service accepting the legacy conversion request contract for HEIC/HEIF to JPEG.",
    version="1.1.0",
)

converter = JpegConversionQueue(
    worker_count=settings.worker_count,
    queue_maxsize=settings.queue_maxsize,
    enqueue_timeout_sec=settings.enqueue_timeout_sec,
    default_jpeg_quality=settings.jpeg_quality,
)

CONVERT_RESPONSES = {
    200: {"description": "Converted JPEG stream"},
    400: {"description": "Invalid request"},
    413: {"description": "Upload too large"},
    415: {"description": "Unsupported file type"},
    422: {"description": "Conversion failed"},
    503: {"description": "Queue is full"},
    504: {"description": "Processing timeout"},
}


@app.on_event("shutdown")
def shutdown_converter() -> None:
    converter.shutdown()


@app.get("/health")
def health() -> dict[str, int | float | str]:
    return {
        "status": "ok",
        "pending_jobs": converter.pending_jobs(),
        "workers": converter.worker_count(),
        "estimated_wait_sec": round(converter.estimated_wait_seconds(), 3),
    }


async def _convert(conversion_request: ConversionRequest) -> Response:
    if converter.is_queue_full():
        raise HTTPException(status_code=503, detail="Conversion queue is full, try again shortly.")

    if converter.estimated_wait_seconds() >= settings.job_timeout_sec:
        raise HTTPException(status_code=503, detail="Service is overloaded, try again shortly.")

    try:
        payload = await conversion_request.file.read(settings.max_upload_bytes + 1)
    finally:
        await conversion_request.file.close()

    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded file is too large.")

    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        future = converter.submit(payload=payload, quality=conversion_request.quality)
    except QueueFullError:
        raise HTTPException(status_code=503, detail="Conversion queue is full, try again shortly.") from None

    try:
        jpeg_bytes = await asyncio.wait_for(asyncio.wrap_future(future), timeout=settings.job_timeout_sec)
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail="Timed out waiting for conversion.") from None
    except UnsupportedFormatError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ConversionFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    output_name = f"{Path(conversion_request.file.filename or '').stem or 'converted'}.{conversion_request.target_extension.value}"
    headers = {
        "Content-Disposition": f'attachment; filename="{output_name}"',
        "X-Queue-Pending": str(converter.pending_jobs()),
    }
    return Response(content=jpeg_bytes, media_type="image/jpeg", headers=headers)


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _resolve_field(
    field_name: str,
    *values: str | None,
    normalizer: Callable[[str], str] | None = None,
) -> str | None:
    resolved_value: str | None = None
    resolved_normalized: str | None = None

    for value in values:
        candidate = _normalize_optional(value)
        if candidate is None:
            continue

        candidate_normalized = normalizer(candidate) if normalizer is not None else candidate
        if resolved_normalized is not None and candidate_normalized != resolved_normalized:
            raise HTTPException(status_code=400, detail=f"Conflicting {field_name} values.")

        if resolved_value is None:
            resolved_value = candidate
            resolved_normalized = candidate_normalized

    return resolved_value


def _resolve_target_extension(
    *,
    path_value: str | None,
    form_value: str | None,
    query_value: str | None,
    fallback_value: str | None = None,
) -> str | None:
    resolved = _resolve_field(
        "targetExtension",
        path_value,
        form_value,
        query_value,
        normalizer=lambda value: value.lower().lstrip("."),
    )
    return resolved if resolved is not None else fallback_value


def _resolve_quality(*, form_value: str | None, query_value: str | None) -> str | None:
    return _resolve_field("quality", form_value, query_value)


@app.post("/convert", responses=CONVERT_RESPONSES)
async def convert(
    file: UploadFile | None = File(None),
    target_extension_form: str | None = Form(None, alias="targetExtension"),
    target_extension_query: str | None = Query(None, alias="targetExtension"),
    quality_form: str | None = Form(None, alias="quality"),
    quality_query: str | None = Query(None, alias="quality"),
) -> Response:
    conversion_request = build_conversion_request(
        file=file,
        target_extension_value=_resolve_target_extension(
            path_value=None,
            form_value=target_extension_form,
            query_value=target_extension_query,
        ),
        quality_value=_resolve_quality(form_value=quality_form, query_value=quality_query),
    )
    return await _convert(conversion_request)


@app.post("/convert/{path_target_extension}", responses=CONVERT_RESPONSES)
async def convert_to_target(
    path_target_extension: str,
    file: UploadFile | None = File(None),
    target_extension_form: str | None = Form(None, alias="targetExtension"),
    target_extension_query: str | None = Query(None, alias="targetExtension"),
    quality_form: str | None = Form(None, alias="quality"),
    quality_query: str | None = Query(None, alias="quality"),
) -> Response:
    conversion_request = build_conversion_request(
        file=file,
        target_extension_value=_resolve_target_extension(
            path_value=path_target_extension,
            form_value=target_extension_form,
            query_value=target_extension_query,
        ),
        quality_value=_resolve_quality(form_value=quality_form, query_value=quality_query),
    )
    return await _convert(conversion_request)


@app.post("/convert-to-jpeg", responses=CONVERT_RESPONSES)
async def convert_to_jpeg(
    file: UploadFile | None = File(None),
    target_extension_form: str | None = Form(None, alias="targetExtension"),
    target_extension_query: str | None = Query(None, alias="targetExtension"),
    quality_form: str | None = Form(None, alias="quality"),
    quality_query: str | None = Query(None, alias="quality"),
) -> Response:
    conversion_request = build_conversion_request(
        file=file,
        target_extension_value=_resolve_target_extension(
            path_value=None,
            form_value=target_extension_form,
            query_value=target_extension_query,
            fallback_value="jpg",
        ),
        quality_value=_resolve_quality(form_value=quality_form, query_value=quality_query),
    )
    return await _convert(conversion_request)
