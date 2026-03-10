import os

from locust import FastHttpUser, constant, task

HEIC_FILE = os.getenv("HEIC_FILE", "/loadtest/assets/sample.heic")
REQUEST_TIMEOUT_SEC = float(os.getenv("REQUEST_TIMEOUT_SEC", "60"))

try:
    with open(HEIC_FILE, "rb") as file_handle:
        _HEIC_BYTES = file_handle.read()
except FileNotFoundError as exc:
    raise RuntimeError(f"HEIC test file not found: {HEIC_FILE}") from exc

if not _HEIC_BYTES:
    raise RuntimeError(f"HEIC test file is empty: {HEIC_FILE}")


class ConverterUser(FastHttpUser):
    wait_time = constant(0)
    connection_timeout = REQUEST_TIMEOUT_SEC
    network_timeout = REQUEST_TIMEOUT_SEC

    @task
    def convert(self) -> None:
        files = {"file": ("sample.heic", _HEIC_BYTES, "image/heic")}
        data = {"targetExtension": "jpg", "quality": "100"}
        with self.client.post(
            "/convert",
            files=files,
            data=data,
            name="POST /convert",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")
                return

            content_type = (response.headers.get("Content-Type") or "").lower()
            if not content_type.startswith("image/jpeg"):
                response.failure(f"content_type={content_type}")
                return

            response.success()
