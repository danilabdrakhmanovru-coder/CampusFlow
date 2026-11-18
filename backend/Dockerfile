FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/campusflow
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10001 campusflow
COPY alembic.ini .
COPY migrations migrations/
COPY app app/
USER campusflow
CMD ["sh", "-c", "alembic upgrade head && python -m app.v1.demo && exec uvicorn app.v1.main:app --host 0.0.0.0 --port 8000 --no-access-log --proxy-headers --forwarded-allow-ips '*'"]
