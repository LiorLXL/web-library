FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    WEB_LIBRARY_DATA_DIR=/app/app-data \
    WEB_LIBRARY_HOST=0.0.0.0 \
    WEB_LIBRARY_PORT=5088 \
    WEB_LIBRARY_DEBUG=0

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

COPY demo-data /opt/demo-data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 5088

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "zotero_web_library.web"]
