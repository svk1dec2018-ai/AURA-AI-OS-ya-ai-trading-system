FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 aura

WORKDIR /app

COPY pyproject.toml README.md ./
COPY aura ./aura
COPY examples ./examples

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && mkdir -p /app/runtime \
    && chown -R aura:aura /app/runtime

USER aura

VOLUME ["/app/runtime"]

CMD ["python", "examples/run_public_crypto_live.py"]
