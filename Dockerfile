FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production

WORKDIR /app

COPY requirements-prod.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements-prod.txt

RUN groupadd --system --gid 10001 stockflow \
    && useradd --system --uid 10001 --gid stockflow --home-dir /app stockflow \
    && mkdir -p /app/instance \
    && chown stockflow:stockflow /app /app/instance

COPY --chown=stockflow:stockflow app.py ./
COPY --chown=stockflow:stockflow stockflow/ ./stockflow/
COPY --chown=stockflow:stockflow migrations/ ./migrations/

USER stockflow

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/ready', timeout=3)"]

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
