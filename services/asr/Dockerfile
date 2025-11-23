FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

# Install Python and system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    gcc \
    g++ \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Copy shared modules
COPY shared/ /app/shared/

# Copy service files
COPY services/asr/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/asr/ /app/

# Create model cache directory
RUN mkdir -p /models

# Set environment variables
ENV MODEL_CACHE_DIR=/models
ENV DEVICE=cuda
ENV COMPUTE_TYPE=float16

# Run service
CMD ["python", "main.py"]
