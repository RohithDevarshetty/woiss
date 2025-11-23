#!/bin/bash

###
# Setup script for Real-Time Transcription Platform
###

set -e

echo "===================================="
echo "Real-Time Transcription Setup"
echo "===================================="
echo ""

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

echo "✅ Docker found"

# Check for Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker Compose found"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file and set your configuration (especially HF_AUTH_TOKEN for diarization)"
else
    echo "✅ .env file already exists"
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data/postgres data/redis data/rabbitmq data/minio data/models

# Initialize database schema
echo "🗄️  Starting PostgreSQL..."
docker-compose up -d postgres

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
sleep 10

# Run database migrations
echo "🔧 Initializing database schema..."
docker-compose run --rm api python -c "
import sys
sys.path.insert(0, '/app')
from shared.database import init_db
init_db()
print('✅ Database initialized')
"

# Start infrastructure services
echo "🚀 Starting infrastructure services..."
docker-compose up -d postgres redis rabbitmq minio

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 15

# Initialize RabbitMQ topology
echo "🔧 Setting up RabbitMQ topology..."
docker-compose run --rm ingestion python -c "
import sys
sys.path.insert(0, '/app')
from shared.messaging import mq_client, setup_topology
mq_client.connect()
setup_topology(mq_client)
mq_client.disconnect()
print('✅ RabbitMQ topology configured')
"

# Initialize storage buckets
echo "🗄️  Initializing storage buckets..."
docker-compose run --rm ingestion python -c "
import sys
sys.path.insert(0, '/app')
from shared.storage import initialize_storage
initialize_storage()
print('✅ Storage buckets created')
"

echo ""
echo "===================================="
echo "✅ Setup Complete!"
echo "===================================="
echo ""
echo "Next steps:"
echo "1. Edit .env file to configure your settings"
echo "2. For speaker diarization, get a Hugging Face token:"
echo "   - Visit https://huggingface.co/settings/tokens"
echo "   - Accept pyannote model license at https://huggingface.co/pyannote/speaker-diarization"
echo "   - Add token to .env: HF_AUTH_TOKEN=your_token"
echo "3. Start all services: ./scripts/start.sh"
echo "4. Create a user and API key: ./scripts/create-user.sh your@email.com"
echo "5. Open web client: http://localhost:8080"
echo ""
echo "Services will be available at:"
echo "  - WebSocket Gateway: ws://localhost:8000"
echo "  - REST API: http://localhost:8001"
echo "  - RabbitMQ Management: http://localhost:15672 (guest/guest)"
echo "  - MinIO Console: http://localhost:9001 (minioadmin/minioadmin)"
echo ""
