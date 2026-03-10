FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime libs required by HEIC/HEIF decoder.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libheif1 libde265-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1} --backlog ${UVICORN_BACKLOG:-2048} --timeout-keep-alive ${UVICORN_TIMEOUT_KEEP_ALIVE:-5}"]
