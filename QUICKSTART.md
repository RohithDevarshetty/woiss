# Quick Start Guide

Get up and running with Real-Time Transcription in under 5 minutes!

## Prerequisites

- Docker & Docker Compose installed
- 8GB RAM minimum (16GB recommended)
- Microphone access in your browser

## Step 1: Clone and Setup (1 minute)

```bash
# Clone repository
git clone <repository-url>
cd woiss

# Run automated setup
chmod +x scripts/*.sh
./scripts/setup.sh
```

This will:
- Create configuration files
- Start PostgreSQL
- Initialize database
- Configure RabbitMQ
- Set up storage buckets

## Step 2: Configure (1 minute)

### For Basic Transcription (No Diarization)

You can skip this step and use defaults!

### For Speaker Diarization (Optional)

1. Get a Hugging Face token:
   - Visit https://huggingface.co/settings/tokens
   - Create a new token
   - Accept license at https://huggingface.co/pyannote/speaker-diarization

2. Add to `.env`:
   ```bash
   HF_AUTH_TOKEN=your_token_here
   ```

## Step 3: Start Services (2 minutes)

```bash
./scripts/start.sh
```

This starts all services. First run will download ML models (~5GB), which takes a few minutes.

## Step 4: Create User & API Key (30 seconds)

```bash
./scripts/create-user.sh your@email.com
```

**Save the API key** that's displayed - you'll need it!

## Step 5: Start Transcribing! (30 seconds)

### Option A: Web Browser (Easiest)

1. Open `web-client/index.html` in your browser
2. Paste your API key
3. Click "Start Recording"
4. Speak into your microphone
5. Watch real-time transcription!

### Option B: Serve Web Client

```bash
cd web-client
python -m http.server 8080
```

Open http://localhost:8080 in your browser.

## Verify Everything Works

### Check Services

```bash
# All services should be running
docker-compose ps

# View logs
docker-compose logs -f gateway asr
```

### Test REST API

```bash
# Health check
curl http://localhost:8001/health

# List sessions
curl "http://localhost:8001/v1/sessions?limit=5"
```

### Access Management UIs

- **RabbitMQ:** http://localhost:15672 (guest/guest)
- **MinIO:** http://localhost:9001 (minioadmin/minioadmin)
- **API Docs:** http://localhost:8001/docs

## Common Issues

### "Cannot connect to WebSocket"

**Solution:** Wait for services to fully start (1-2 minutes on first run)

```bash
# Check gateway is ready
docker-compose logs gateway | grep "started"
```

### "No transcription appearing"

**Solution:** Check ASR service is running and models are downloaded

```bash
# View ASR logs
docker-compose logs asr

# Models should be downloading/loaded
```

### "Diarization not working"

**Solution:** Ensure HF_AUTH_TOKEN is set in `.env` and license is accepted

```bash
# Check diarization logs
docker-compose logs diarization
```

### Out of Memory

**Solution:** Use a smaller Whisper model

Edit `.env`:
```bash
WHISPER_MODEL=medium  # or 'small' or 'base'
```

Then restart:
```bash
./scripts/stop.sh
./scripts/start.sh
```

## Performance Tips

### For Faster Transcription

1. **Use GPU** (if available)
   - Uncomment GPU sections in `docker-compose.yml`
   - Install NVIDIA Container Toolkit
   - Restart services

2. **Use Smaller Models**
   - `small` - Fast, good quality
   - `medium` - Balanced
   - `large-v3` - Best quality, slower

3. **Disable Diarization**
   - Uncheck "Speaker Diarization" in web client
   - Or remove diarization service from docker-compose.yml

### For Better Accuracy

1. **Use Larger Models**
   ```bash
   WHISPER_MODEL=large-v3
   ```

2. **Specify Language**
   - Select correct language in web client
   - Improves accuracy significantly

3. **Good Audio Quality**
   - Use quality microphone
   - Quiet environment
   - Speak clearly

## Next Steps

Now that you're up and running:

1. **Read Full Documentation:** See README.md
2. **Explore REST API:** http://localhost:8001/docs
3. **Build Custom Clients:** See API documentation
4. **Deploy to Production:** See Kubernetes guides in `k8s/`
5. **Monitor Performance:** Access Prometheus metrics at `/metrics`

## Clean Up

To stop all services:

```bash
./scripts/stop.sh
```

To remove all data (including models):

```bash
docker-compose down -v
```

## Support

- **Documentation:** README.md and ARCHITECTURE.md
- **Issues:** GitHub Issues
- **Examples:** See `docs/` directory

---

**Happy Transcribing! 🎙️**
