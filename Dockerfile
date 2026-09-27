FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    DATABASE_PATH=/app/data/inbox-classifier.db

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY app ./app

RUN python -m pip install --no-cache-dir . \
    && addgroup --system app \
    && adduser --system --ingroup app --home /app app \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
