from __future__ import annotations

import io
import queue
import threading
import time
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

_SENTINEL = object()


class QueueFullError(Exception):
    pass


class UnsupportedFormatError(Exception):
    pass


class ConversionFailedError(Exception):
    pass


@dataclass(slots=True)
class ConversionJob:
    payload: bytes
    quality: int
    result: Future[bytes]


class JpegConversionQueue:
    def __init__(
        self,
        worker_count: int,
        queue_maxsize: int,
        enqueue_timeout_sec: float,
        default_jpeg_quality: int,
    ) -> None:
        pillow_heif.register_heif_opener()

        self._queue: queue.Queue[ConversionJob | object] = queue.Queue(maxsize=queue_maxsize)
        self._enqueue_timeout_sec = enqueue_timeout_sec
        self._default_jpeg_quality = max(1, min(default_jpeg_quality, 100))
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._metrics_lock = threading.Lock()
        self._avg_task_sec = 0.8

        thread_count = max(1, worker_count)
        for i in range(thread_count):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"converter-worker-{i + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def submit(self, payload: bytes, quality: int | None = None) -> Future[bytes]:
        if not payload:
            raise UnsupportedFormatError("Uploaded file is empty.")

        future: Future[bytes] = Future()
        normalized_quality = self._default_jpeg_quality if quality is None else max(1, min(quality, 100))
        job = ConversionJob(payload=payload, quality=normalized_quality, result=future)
        try:
            # Never block the FastAPI event loop when overloaded.
            self._queue.put_nowait(job)
        except queue.Full as exc:
            raise QueueFullError("Conversion queue is full.") from exc
        return future

    def pending_jobs(self) -> int:
        return self._queue.qsize()

    def is_queue_full(self) -> bool:
        return self._queue.full()

    def worker_count(self) -> int:
        return len(self._workers)

    def estimated_wait_seconds(self) -> float:
        workers = max(1, len(self._workers))
        pending = self._queue.qsize()
        with self._metrics_lock:
            avg = self._avg_task_sec
        return (pending / workers) * avg

    def shutdown(self, join_timeout_sec: float = 2.0) -> None:
        self._stop_event.set()
        for _ in self._workers:
            try:
                self._queue.put_nowait(_SENTINEL)
            except queue.Full:
                break
        for worker in self._workers:
            worker.join(timeout=join_timeout_sec)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_or_sentinel = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if job_or_sentinel is _SENTINEL:
                self._queue.task_done()
                break

            job = job_or_sentinel
            if not isinstance(job, ConversionJob):
                self._queue.task_done()
                continue

            started_at = time.perf_counter()
            try:
                converted = self._convert_to_jpeg(job.payload, quality=job.quality)
                if not job.result.done():
                    try:
                        job.result.set_result(converted)
                    except InvalidStateError:
                        pass
            except Exception as exc:
                if not job.result.done():
                    try:
                        job.result.set_exception(exc)
                    except InvalidStateError:
                        pass
            finally:
                duration = max(0.001, time.perf_counter() - started_at)
                with self._metrics_lock:
                    self._avg_task_sec = (self._avg_task_sec * 0.9) + (duration * 0.1)
                self._queue.task_done()

    def _convert_to_jpeg(self, payload: bytes, *, quality: int) -> bytes:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                prepared = self._prepare_image_for_jpeg(image)
                converted = prepared
                if prepared.mode not in {"RGB", "L"}:
                    converted = prepared.convert("RGB")

                try:
                    buffer = io.BytesIO()
                    save_kwargs: dict[str, object] = {
                        "format": "JPEG",
                        "quality": quality,
                        "optimize": False,
                        "progressive": False,
                        "subsampling": 2,
                    }

                    exif_bytes = self._extract_exif_bytes(prepared, image)
                    if exif_bytes:
                        save_kwargs["exif"] = exif_bytes

                    icc_profile = self._extract_icc_profile(prepared, image)
                    if icc_profile:
                        save_kwargs["icc_profile"] = icc_profile

                    dpi = self._extract_dpi(prepared, image)
                    if dpi:
                        save_kwargs["dpi"] = dpi

                    converted.save(buffer, **save_kwargs)
                    return buffer.getvalue()
                finally:
                    if converted is not prepared:
                        converted.close()
                    if prepared is not image:
                        prepared.close()
        except UnidentifiedImageError as exc:
            raise UnsupportedFormatError("Only HEIC/HEIF images are supported.") from exc
        except OSError as exc:
            raise ConversionFailedError("Image conversion failed.") from exc

    @staticmethod
    def _prepare_image_for_jpeg(image: Image.Image) -> Image.Image:
        try:
            orientation = image.getexif().get(274, 1)
        except (AttributeError, ValueError, TypeError, OSError):
            orientation = 1
        if orientation not in {1, None}:
            return ImageOps.exif_transpose(image)
        return image

    @staticmethod
    def _extract_exif_bytes(primary: Image.Image, fallback: Image.Image) -> bytes | None:
        checked: set[int] = set()
        for candidate in (primary, fallback):
            marker = id(candidate)
            if marker in checked:
                continue
            checked.add(marker)

            try:
                exif = candidate.getexif()
                if exif:
                    exif_bytes = exif.tobytes()
                    if exif_bytes:
                        return exif_bytes
            except (AttributeError, ValueError, TypeError, OSError):
                pass

            info_exif = candidate.info.get("exif")
            if isinstance(info_exif, bytes) and info_exif:
                return info_exif
        return None

    @staticmethod
    def _extract_icc_profile(primary: Image.Image, fallback: Image.Image) -> bytes | None:
        checked: set[int] = set()
        for candidate in (primary, fallback):
            marker = id(candidate)
            if marker in checked:
                continue
            checked.add(marker)

            icc_profile = candidate.info.get("icc_profile")
            if isinstance(icc_profile, bytes) and icc_profile:
                return icc_profile
        return None

    @staticmethod
    def _extract_dpi(primary: Image.Image, fallback: Image.Image) -> tuple[int | float, int | float] | None:
        checked: set[int] = set()
        for candidate in (primary, fallback):
            marker = id(candidate)
            if marker in checked:
                continue
            checked.add(marker)

            dpi = candidate.info.get("dpi")
            if (
                isinstance(dpi, tuple)
                and len(dpi) == 2
                and all(isinstance(value, (int, float)) and value > 0 for value in dpi)
            ):
                return dpi
        return None
