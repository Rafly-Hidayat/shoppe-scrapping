# Render (dan Docker lain): Chromium + lib sistem dipasang saat build image.
# Tanpa ini, runtime tidak punya browser — error sama seperti di lokal tanpa `playwright install`.
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT} --timeout 120"]
