FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

COPY . .

EXPOSE 8000

# Run Alembic migrations then start the gateway.
# Migration failure stops the container — preventing a mismatched-schema startup.
# In development / local Docker Compose, create_all in the lifespan is still
# active as a convenience layer; Alembic is authoritative for production.
CMD ["sh", "-c", "alembic upgrade head && python scripts/reset_demo_passwords.py && uvicorn services.gateway.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
