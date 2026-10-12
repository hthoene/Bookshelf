FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BOOKSHELF_DATA_DIR=/data \
    BOOKSHELF_PORT=8080 \
    # Trust X-Forwarded-* headers so URLs are correct behind a reverse proxy.
    FORWARDED_ALLOW_IPS=*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bookshelf ./bookshelf
RUN pip install . \
    && useradd --system --uid 1000 --home-dir /data bookshelf \
    && mkdir -p /data \
    && chown bookshelf:bookshelf /data

USER bookshelf
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthcheck', timeout=4)"

CMD ["python", "-m", "bookshelf", "serve"]
