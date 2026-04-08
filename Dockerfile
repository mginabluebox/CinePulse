FROM python:3.12-slim

WORKDIR /app

# Use psycopg2-binary in Docker (avoids compiling from source on slim image)
# Swap the source package for the binary wheel before installing everything else
COPY requirements.txt .
RUN sed 's/^psycopg2==/psycopg2-binary==/' requirements.txt \
    | pip install --no-cache-dir -r /dev/stdin

# Copy application source
COPY src/ ./src/

# Run from the src directory so relative imports (database.*, bots.*) resolve
WORKDIR /app/src

EXPOSE 8080

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60"]
