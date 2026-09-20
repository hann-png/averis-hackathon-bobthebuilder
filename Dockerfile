#Multi-stage production Dockerfile for Shipping Document Verification Service
FROM python:3.11-slim as base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Run the validation pipeline to pre-populate submission.json if data is present
RUN python -c "import os; os.system('python run_pipeline.py --data data --output submission.json') if os.path.exists('data') else None"

EXPOSE 8080

# Optionally run the idempotent PostgreSQL import before starting FastAPI.
# Set SDOC_AUTO_MIGRATE=true for one Railway deployment, verify it, then set it false.
CMD ["sh", "-c", "if [ \"$SDOC_AUTO_MIGRATE\" = \"true\" ]; then python scripts/migrate_to_postgres.py; fi; exec uvicorn api.main:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
