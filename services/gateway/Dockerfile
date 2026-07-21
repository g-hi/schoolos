# ─────────────────────────────────────────────────────────────────────────────
# SchoolOS Gateway – Dockerfile
#
# Uses a slim Python 3.11 base to keep the image small.
# In production, remove --reload from the CMD.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Prevents Python from writing .pyc files and enables unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (cached layer — only re-runs if pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

# Copy the rest of the source code
COPY . .

# Expose the port FastAPI listens on
EXPOSE 8000

# Run Alembic before starting the local development gateway so the database
# revision stays aligned with the runtime schema.
CMD ["sh", "-c", "alembic upgrade head && python scripts/reset_demo_passwords.py && uvicorn services.gateway.main:app --host 0.0.0.0 --port 8000 --reload"]
