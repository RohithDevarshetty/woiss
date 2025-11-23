FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy shared modules
COPY shared/ /app/shared/

# Copy service files
COPY services/postprocessing/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/postprocessing/ /app/

# Run service
CMD ["python", "main.py"]
