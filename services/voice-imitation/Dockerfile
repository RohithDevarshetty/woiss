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
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Copy shared modules
COPY shared/ /app/shared/

# Copy service files
COPY services/voice-imitation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/voice-imitation/ /app/

# Create model cache directories
RUN mkdir -p /models/ecapa-tdnn /models/fastspeech2 /models/hifigan

# Set environment variables
ENV DEVICE=cuda
ENV MODEL_CACHE_DIR=/models

# Expose port
EXPOSE 8002

# Run service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
