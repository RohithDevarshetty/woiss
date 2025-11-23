#!/bin/bash

###
# Start all services
###

set -e

echo "🚀 Starting Real-Time Transcription Platform..."
echo ""

# Start infrastructure first
echo "Starting infrastructure services..."
docker-compose up -d postgres redis rabbitmq minio

echo "⏳ Waiting for infrastructure to be ready..."
sleep 10

# Start application services
echo "Starting application services..."
docker-compose up -d gateway api ingestion postprocessing

# Start ML services (ASR, Diarization, Voice Imitation)
echo "Starting ML services (this may take a while on first run)..."
docker-compose up -d asr diarization voice-imitation

echo ""
echo "✅ All services started!"
echo ""
echo "View logs: docker-compose logs -f"
echo "Stop services: ./scripts/stop.sh"
echo ""
echo "Services:"
echo "  - Gateway (WebSocket): ws://localhost:8000"
echo "  - API (REST): http://localhost:8001"
echo "  - Voice Imitation API: http://localhost:8002"
echo "  - Web Client (Transcription): file://$(pwd)/web-client/index.html"
echo "  - Web Client (Voice Synthesis): file://$(pwd)/web-client/voice-synthesis.html"
echo ""
echo "Management UIs:"
echo "  - RabbitMQ: http://localhost:15672 (guest/guest)"
echo "  - MinIO: http://localhost:9001 (minioadmin/minioadmin)"
echo ""
