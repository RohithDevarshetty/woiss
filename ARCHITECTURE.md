# Real-Time Transcription Platform - System Architecture

## Executive Summary

Production-grade, low-latency real-time speech-to-text platform with speaker diarization, voice imitation, and flexible deployment options.

**Target Performance:**
- First word latency: <800ms
- Finalized sentence latency: <2s
- Throughput: 100-150 concurrent streams per low-end GPU
- Accuracy: >95% WER on clean audio, >90% on noisy environments

---

## System Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Client Layer                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │   Browser    │  │   iOS SDK    │  │  Android SDK │              │
│  │  (WebRTC)    │  │              │  │              │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                  │                       │
└─────────┼─────────────────┼──────────────────┼───────────────────────┘
          │                 │                  │
          └─────────────────┴──────────────────┘
                            │
                    ┌───────▼────────┐
                    │  Load Balancer │
                    │   (nginx/HAProxy)│
                    └───────┬────────┘
                            │
          ┌─────────────────┴─────────────────┐
          │                                   │
┌─────────▼──────────┐            ┌──────────▼──────────┐
│  WebSocket Gateway │            │    REST API         │
│   (FastAPI/Python) │            │   (FastAPI/Python)  │
│  - Connection mgmt │            │  - Session mgmt     │
│  - Auth/validation │            │  - Transcript query │
│  - Real-time push  │            │  - User management  │
└─────────┬──────────┘            └──────────┬──────────┘
          │                                   │
          │         ┌──────────────┐          │
          └────────►│    Redis     │◄─────────┘
                    │ Session State│
                    └──────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          │                                   │
┌─────────▼──────────┐            ┌──────────▼──────────┐
│ Audio Ingestion    │            │   Message Queue     │
│  Service (Python)  │───────────►│   (RabbitMQ)        │
│  - Audio buffering │            │                     │
│  - Format conversion│            └──────────┬──────────┘
│  - Stream routing  │                       │
└────────────────────┘                       │
                                             │
                    ┌────────────────────────┴────────────────────────┐
                    │                                                 │
          ┌─────────▼──────────┐            ┌──────────▼──────────┐  │
          │   ASR Service      │            │  Diarization Service│  │
          │  (Python/CUDA)     │            │   (Python/CUDA)     │  │
          │  - faster-whisper  │            │  - pyannote.audio   │  │
          │  - Real-time mode  │            │  - Speaker embeddings│ │
          │  - Batch processing│            │  - Clustering       │  │
          └─────────┬──────────┘            └──────────┬──────────┘  │
                    │                                   │             │
                    └────────────────┬──────────────────┘             │
                                     │                                │
                           ┌─────────▼──────────┐                     │
                           │ Post-Processing    │◄────────────────────┘
                           │  Service (Python)  │
                           │  - Punctuation     │
                           │  - Capitalization  │
                           │  - Formatting      │
                           │  - Confidence calc │
                           └─────────┬──────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
          ┌─────────▼──────────┐          ┌─────────▼──────────┐
          │   PostgreSQL       │          │   S3 Storage       │
          │  - Sessions        │          │  - Audio recordings│
          │  - Transcripts     │          │  - Models          │
          │  - Users           │          │  - Artifacts       │
          │  - Analytics       │          └────────────────────┘
          └────────────────────┘
                    │
          ┌─────────▼──────────┐
          │  Monitoring Stack  │
          │  - Prometheus      │
          │  - Grafana         │
          │  - Jaeger (traces) │
          └────────────────────┘
```

### Voice Imitation Pipeline (Phase 2)

```
┌──────────────┐
│ Speaker Audio│
│   Sample     │
└──────┬───────┘
       │
┌──────▼───────────┐
│  ECAPA-TDNN      │
│ Speaker Encoder  │
│  (CPU/GPU)       │
└──────┬───────────┘
       │
       │  Speaker Embedding
       │
       ├──────────────────────────┐
       │                          │
┌──────▼───────────┐    ┌─────────▼──────────┐
│   FastSpeech2    │    │  Embedding Store   │
│ Multi-Speaker TTS│    │     (Redis)        │
│   (GPU/CPU)      │    └────────────────────┘
└──────┬───────────┘
       │
       │  Mel-spectrogram
       │
┌──────▼───────────┐
│   HiFi-GAN       │
│    Vocoder       │
│   (GPU/CPU)      │
└──────┬───────────┘
       │
┌──────▼───────────┐
│  Cloned Voice    │
│     Output       │
└──────────────────┘
```

---

## Technology Stack

### Backend Services
- **Language**: Python 3.11+
- **Framework**: FastAPI (async, WebSocket support, automatic OpenAPI docs)
- **ASGI Server**: Uvicorn with Gunicorn workers
- **Message Queue**: RabbitMQ (reliable, battle-tested)
- **Cache/State**: Redis (session state, rate limiting, speaker embeddings)
- **Database**: PostgreSQL 15+ (JSONB support for flexible schema)
- **Storage**: MinIO (S3-compatible, self-hosted) or AWS S3

### ML/ASR Stack
- **ASR Engine**: faster-whisper (optimized Whisper with CTranslate2)
- **Diarization**: pyannote.audio (state-of-the-art speaker diarization)
- **Speaker Encoding**: ECAPA-TDNN (speechbrain)
- **TTS**: FastSpeech2 (multi-speaker)
- **Vocoder**: HiFi-GAN
- **Acceleration**: CUDA 11.8+, cuDNN, TensorRT

### Infrastructure
- **Containerization**: Docker
- **Orchestration**: Kubernetes (production), Docker Compose (dev)
- **Load Balancer**: nginx or HAProxy
- **Monitoring**: Prometheus, Grafana, Jaeger
- **Logging**: ELK Stack (Elasticsearch, Logstash, Kibana) or Loki

### Frontend
- **Browser Client**: Vanilla JS (minimal dependencies)
- **Audio Capture**: WebRTC MediaRecorder API
- **WebSocket**: Native WebSocket API
- **Future SDKs**: Swift (iOS), Kotlin (Android)

---

## Service Specifications

### 1. WebSocket Gateway Service

**Responsibilities:**
- Accept WebSocket connections from clients
- Authenticate via API keys
- Manage session lifecycle
- Push real-time transcript events to clients
- Handle backpressure and reconnection

**Tech Stack:**
- FastAPI with WebSocket support
- Redis for connection registry
- JWT for session tokens

**API:**
```
WS /v1/stream?api_key=xxx
  → Client sends: binary audio chunks
  ← Server sends: JSON events (interim, final, speaker, error)
```

**Scaling:**
- Stateless (session state in Redis)
- Horizontal scaling via load balancer
- WebSocket sticky sessions

---

### 2. Audio Ingestion Service

**Responsibilities:**
- Receive audio streams from gateway
- Buffer and chunk audio (configurable window)
- Convert formats (WebM → PCM/WAV)
- Publish audio chunks to RabbitMQ for ASR processing
- Store raw audio to S3 (optional, compliance)

**Tech Stack:**
- Python with pydub/ffmpeg for conversion
- RabbitMQ producer
- S3 client (boto3 or MinIO SDK)

**Performance:**
- Async I/O with asyncio
- Batch processing for efficiency
- Stream-based conversion (no full buffering)

---

### 3. ASR Service (Speech Recognition)

**Responsibilities:**
- Consume audio chunks from RabbitMQ
- Perform real-time transcription with faster-whisper
- Generate interim and final transcripts
- Compute word-level timestamps and confidence scores
- Publish results to post-processing queue

**Tech Stack:**
- faster-whisper (CTranslate2-optimized Whisper)
- CUDA for GPU acceleration
- Model: Whisper large-v3 (best accuracy) or medium (lower latency)

**Optimizations:**
- Beam size: 1-3 for low latency
- VAD (Voice Activity Detection) pre-filtering
- Model quantization (INT8) for edge deployment
- Batch processing for throughput

**Latency Targets:**
- 300-600ms per 3-second chunk
- Streaming mode: incremental decoding

---

### 4. Speaker Diarization Service

**Responsibilities:**
- Identify "who spoke when"
- Assign speaker labels to transcript segments
- Cluster speaker embeddings
- Handle overlapping speech (best-effort)

**Tech Stack:**
- pyannote.audio (pre-trained pipelines)
- ECAPA-TDNN for speaker embeddings
- Agglomerative clustering

**Processing Modes:**
- **Real-time (sliding window)**: 5-10s latency, incremental updates
- **Post-hoc (full session)**: Higher accuracy, after session ends

**Challenges:**
- Overlapping speech
- Unknown number of speakers
- Cold-start (no pre-enrollment)

---

### 5. Post-Processing Service

**Responsibilities:**
- Add punctuation (deepmultilingual punctuation or custom models)
- Capitalize proper nouns
- Format numbers, dates, times
- Merge speaker labels with transcripts
- Calculate final confidence scores
- Profanity filtering (optional)

**Tech Stack:**
- Python NLP libraries (spaCy, transformers)
- Rule-based + ML hybrid approach

**Output:**
```json
{
  "session_id": "abc123",
  "segments": [
    {
      "start": 0.5,
      "end": 3.2,
      "speaker": "SPEAKER_01",
      "text": "Hello, how are you?",
      "confidence": 0.94,
      "words": [
        {"word": "Hello", "start": 0.5, "end": 0.8, "confidence": 0.96},
        ...
      ]
    }
  ]
}
```

---

### 6. REST API Service

**Responsibilities:**
- Session management (create, list, delete)
- Transcript retrieval (full, by time range)
- User/API key management
- Usage metrics and billing data
- Webhook configuration

**Endpoints:**
```
POST   /v1/sessions                 # Create session
GET    /v1/sessions/:id             # Get session details
GET    /v1/sessions/:id/transcript  # Get full transcript
DELETE /v1/sessions/:id             # Delete session
GET    /v1/usage                    # Usage stats
POST   /v1/webhooks                 # Configure webhooks
```

---

### 7. Storage Service

**Responsibilities:**
- Store audio recordings (compliance, replay)
- Store ML model artifacts
- Versioned model storage
- Efficient retrieval for playback

**Tech Stack:**
- S3-compatible storage (MinIO or AWS S3)
- Lifecycle policies (auto-delete after N days)
- Presigned URLs for secure download

---

## Data Models

### PostgreSQL Schema

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    tier VARCHAR(50) DEFAULT 'free'
);

-- API Keys table
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Sessions table
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'active',
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    audio_url TEXT,
    config JSONB,
    metadata JSONB
);

-- Transcripts table
CREATE TABLE transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    segments JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Usage tracking
CREATE TABLE usage_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id),
    event_type VARCHAR(50),
    duration_seconds INTEGER,
    cost_cents INTEGER,
    timestamp TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_usage_user_timestamp ON usage_records(user_id, timestamp);
```

### Redis Data Structures

```python
# Session state
session:{session_id} → {
    "user_id": "...",
    "status": "active",
    "connection_id": "...",
    "started_at": "...",
    "last_activity": "...",
    "config": {...}
}

# Connection registry
connection:{connection_id} → session_id

# Rate limiting
ratelimit:{user_id}:{window} → count

# Speaker embeddings (voice imitation)
speaker:{speaker_id}:embedding → binary (512-dim vector)
```

---

## Message Queue Architecture

### RabbitMQ Topology

**Exchanges:**
- `audio.input` (fanout) - Raw audio chunks
- `transcription.output` (topic) - ASR results
- `processing.output` (topic) - Post-processed results

**Queues:**
- `audio.chunks.high_priority` - Low-latency tier
- `audio.chunks.standard` - Standard tier
- `asr.results` - ASR output
- `diarization.tasks` - Speaker diarization jobs
- `postprocessing.tasks` - Final formatting

**Routing:**
```
audio.input → audio.chunks.{priority} → ASR Service
ASR Service → transcription.output → Post-Processing
Post-Processing → processing.output → WebSocket Gateway
```

---

## Deployment Architecture

### Development (Docker Compose)

```yaml
services:
  gateway:
    image: realtime-transcribe/gateway:latest
    ports: ["8000:8000"]

  asr:
    image: realtime-transcribe/asr:latest
    runtime: nvidia
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

  postgres:
    image: postgres:15

  redis:
    image: redis:7

  rabbitmq:
    image: rabbitmq:3-management

  minio:
    image: minio/minio
```

### Production (Kubernetes)

**Namespaces:**
- `rt-prod` - Production services
- `rt-monitoring` - Prometheus, Grafana
- `rt-infra` - PostgreSQL, Redis, RabbitMQ

**Key Resources:**
- **Deployments**: gateway, api, ingestion, asr, diarization, postprocessing
- **StatefulSets**: PostgreSQL, Redis, RabbitMQ
- **Services**: ClusterIP for internal, LoadBalancer for gateway
- **HPA**: Horizontal Pod Autoscaler for gateway, ASR
- **PVC**: Persistent volumes for DB, model storage

**GPU Node Pool:**
- Dedicated node pool with NVIDIA GPUs (T4/A10)
- Taints/tolerations for ASR/Diarization pods
- GPU resource requests/limits

---

## Monitoring & Observability

### Metrics (Prometheus)

**Service Metrics:**
- `http_requests_total` - Request count by endpoint
- `websocket_connections_active` - Active WebSocket connections
- `audio_chunks_processed_total` - Audio processing throughput
- `asr_latency_seconds` - ASR processing time histogram
- `transcript_words_total` - Total words transcribed

**Business Metrics:**
- `sessions_created_total` - Sessions by tier
- `usage_minutes_total` - Billable minutes
- `error_rate` - Error rate by service

### Tracing (Jaeger)

Distributed tracing for request flow:
```
WebSocket → Gateway → Ingestion → RabbitMQ → ASR → Post-Processing → Gateway
```

### Logging (Structured JSON)

```json
{
  "timestamp": "2025-11-23T...",
  "level": "INFO",
  "service": "asr",
  "session_id": "abc123",
  "message": "Transcription completed",
  "latency_ms": 450,
  "words": 12,
  "model": "whisper-large-v3"
}
```

---

## Security & Compliance

### Authentication
- API key authentication (SHA-256 hashed)
- JWT tokens for session authorization
- Rate limiting per user/tier

### Data Privacy
- Optional audio deletion after transcription
- Encryption at rest (S3, PostgreSQL)
- Encryption in transit (TLS 1.3)
- GDPR compliance (data export, deletion)

### HIPAA Compliance (Enterprise)
- BAA agreements
- Audit logging
- Private cloud deployment
- PHI data handling procedures

---

## Scaling Strategy

### Horizontal Scaling
- **Gateway**: Scale based on WebSocket connections (target: 1000/pod)
- **ASR**: Scale based on queue depth and GPU utilization
- **Ingestion/Post-processing**: Scale based on CPU/memory

### Vertical Scaling
- ASR service: GPU memory (larger models)
- PostgreSQL: CPU/RAM for query performance

### Caching
- Redis for hot session data
- CDN for static assets (web client)
- Model caching in GPU memory

### Load Balancing
- Geographic routing (edge locations)
- Sticky sessions for WebSocket
- Queue-based load leveling

---

## Cost Optimization

### Compute
- **CPU instances**: t3.medium for stateless services ($0.04/hr)
- **GPU instances**: g4dn.xlarge (T4 GPU, $0.526/hr)
- Spot instances for batch processing (70% savings)
- Auto-scaling to zero during low usage

### Storage
- S3 Intelligent-Tiering for audio archives
- Lifecycle policies (delete after 30 days)
- Compression (Opus for audio, gzip for transcripts)

### Network
- CloudFront/CDN for static content
- VPC endpoints to avoid data transfer costs
- Regional deployments to reduce cross-region traffic

---

## Disaster Recovery

### Backup Strategy
- PostgreSQL: Daily automated backups, 7-day retention
- Redis: RDB snapshots every 6 hours
- S3: Versioning enabled, cross-region replication

### High Availability
- Multi-AZ deployments for databases
- Active-active gateway nodes
- Queue persistence (RabbitMQ durable queues)

### Incident Response
- Automated health checks
- Graceful degradation (lower accuracy models during high load)
- Circuit breakers for external dependencies

---

## Future Enhancements

### Phase 2: Voice Imitation
- ECAPA-TDNN speaker encoder service
- FastSpeech2 TTS service
- HiFi-GAN vocoder service
- Voice consent and watermarking

### Phase 3: Advanced Features
- Custom vocabulary and domain adaptation
- Multi-language support (100+ languages)
- Real-time translation
- Sentiment analysis
- PII redaction

### Phase 4: Platform Expansion
- Mobile SDKs (iOS, Android)
- Desktop SDKs (Electron)
- Zapier/Make.com integrations
- Marketplace (Zoom, Teams, Slack apps)

---

## Performance Benchmarks (Target)

| Metric | Target | Measurement |
|--------|--------|-------------|
| First word latency | <800ms | Time from audio start to first transcript |
| Finalized sentence latency | <2s | Time from sentence end to final transcript |
| WER (clean audio) | <5% | Word Error Rate on LibriSpeech test-clean |
| WER (noisy audio) | <10% | Word Error Rate on CHiME-5 |
| Concurrent streams (1 GPU) | 100-150 | T4 GPU, Whisper medium model |
| Diarization accuracy | >90% DER | Diarization Error Rate |
| Uptime | 99.9% | Monthly uptime SLA |
| API latency (REST) | <100ms p95 | Session/transcript APIs |

---

This architecture is designed for:
- **Low latency** (sub-second transcription)
- **High accuracy** (>95% WER)
- **Scalability** (1000s of concurrent streams)
- **Reliability** (99.9% uptime)
- **Cost efficiency** ($0.50-$1 per streaming hour)
- **Privacy** (on-device, private cloud options)

Next: Detailed implementation of each service.
