FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (including ffmpeg for audio processing)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy shared modules
COPY shared/ /app/shared/

# Copy service files
COPY services/ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ingestion/ /app/

# Run service
CMD ["python", "main.py"]
