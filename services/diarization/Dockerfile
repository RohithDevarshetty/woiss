FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Copy shared modules
COPY shared/ /app/shared/

# Copy service files
COPY services/diarization/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/diarization/ /app/

# Environment
ENV DEVICE=cuda

# Run service
CMD ["python", "main.py"]
