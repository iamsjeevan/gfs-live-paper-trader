FROM python:3.11-slim

WORKDIR /app

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY database/ ./database/
COPY reports/ ./reports/
COPY tests/ ./tests/
COPY .env.example .env

# Expose web dashboard port
EXPOSE 8080

# Run continuous paper trading engine with embedded web dashboard
CMD ["python", "-m", "app.main", "--run-continuous"]
