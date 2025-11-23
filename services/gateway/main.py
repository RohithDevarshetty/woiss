"""
WebSocket Gateway Service
Entry point for real-time audio streaming from clients
"""
import os
import sys
import asyncio
import logging
import uuid
import json
from datetime import datetime
from typing import Dict, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
import uvicorn

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logging_config import setup_logging
from shared.utils.redis_client import redis_client
from shared.utils.metrics import (
    websocket_connections_active,
    websocket_messages_total,
    audio_chunks_processed_total,
    sessions_created_total,
    sessions_active,
    errors_total,
    track_duration,
    http_request_duration_seconds
)
from shared.messaging import mq_client
from shared.database import get_db, Session as DBSession, User, APIKey
from shared.utils.auth import hash_api_key

# Setup logging
setup_logging(service_name='gateway')
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Real-Time Transcription Gateway",
    description="WebSocket gateway for real-time audio streaming",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Connection manager
class ConnectionManager:
    """Manages active WebSocket connections"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.session_connections: Dict[str, str] = {}  # session_id -> connection_id

    async def connect(self, connection_id: str, session_id: str, websocket: WebSocket):
        """Register new WebSocket connection"""
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        self.session_connections[session_id] = connection_id

        # Register in Redis
        redis_client.register_connection(connection_id, session_id)

        # Update metrics
        websocket_connections_active.labels(service='gateway').inc()

        logger.info(f"WebSocket connected: connection_id={connection_id}, session_id={session_id}")

    def disconnect(self, connection_id: str, session_id: str):
        """Unregister WebSocket connection"""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]

        if session_id in self.session_connections:
            del self.session_connections[session_id]

        # Unregister from Redis
        redis_client.unregister_connection(connection_id)

        # Update metrics
        websocket_connections_active.labels(service='gateway').dec()

        logger.info(f"WebSocket disconnected: connection_id={connection_id}, session_id={session_id}")

    async def send_message(self, session_id: str, message: dict):
        """Send message to client by session ID"""
        connection_id = self.session_connections.get(session_id)
        if connection_id and connection_id in self.active_connections:
            websocket = self.active_connections[connection_id]
            try:
                await websocket.send_json(message)
                websocket_messages_total.labels(
                    service='gateway',
                    direction='outbound',
                    message_type=message.get('type', 'unknown')
                ).inc()
            except Exception as e:
                logger.error(f"Failed to send message to session {session_id}: {e}")

    async def broadcast_to_session(self, session_id: str, event_type: str, data: dict):
        """Broadcast event to session"""
        message = {
            'type': event_type,
            'timestamp': datetime.utcnow().isoformat(),
            'data': data
        }
        await self.send_message(session_id, message)


manager = ConnectionManager()


async def verify_api_key(api_key: str, db: DBSession) -> Dict:
    """
    Verify API key and return user info

    Args:
        api_key: API key from query param
        db: Database session

    Returns:
        User info dict

    Raises:
        HTTPException: If API key is invalid
    """
    key_hash = hash_api_key(api_key)

    api_key_obj = db.query(APIKey).filter(
        APIKey.key_hash == key_hash,
        APIKey.is_active == True
    ).first()

    if not api_key_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    # Check rate limit
    if not redis_client.check_rate_limit(
        str(api_key_obj.user_id),
        limit=api_key_obj.rate_limit,
        window=60
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )

    # Update last used
    api_key_obj.last_used_at = datetime.utcnow()
    db.commit()

    # Get user
    user = db.query(User).filter(User.id == api_key_obj.user_id).first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not active"
        )

    return {
        'user_id': str(user.id),
        'email': user.email,
        'tier': user.tier,
        'rate_limit': api_key_obj.rate_limit
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    with track_duration(http_request_duration_seconds, 'gateway', 'GET', '/health'):
        # Check Redis
        redis_ok = redis_client.health_check()

        # Check RabbitMQ
        mq_ok = mq_client.health_check()

        if not redis_ok or not mq_ok:
            return {
                'status': 'degraded',
                'redis': redis_ok,
                'rabbitmq': mq_ok
            }

        return {
            'status': 'healthy',
            'redis': redis_ok,
            'rabbitmq': mq_ok
        }


@app.get("/stats")
async def get_stats():
    """Get connection statistics"""
    return {
        'active_connections': len(manager.active_connections),
        'active_sessions': len(manager.session_connections)
    }


@app.websocket("/v1/stream")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: str = Query(..., description="API key for authentication"),
    language: str = Query('en', description="Audio language code"),
    model: str = Query('large-v3', description="ASR model"),
    enable_diarization: bool = Query(True, description="Enable speaker diarization"),
    db: DBSession = Depends(get_db)
):
    """
    WebSocket endpoint for real-time audio streaming

    Protocol:
        Client -> Server: Binary audio chunks (WebM, WAV, etc.)
        Server -> Client: JSON events (interim, final, speaker, error)

    Event types:
        - session_started: Session initiated
        - interim: Interim transcript
        - final: Final transcript with timestamps
        - speaker: Speaker label update
        - error: Error message
        - session_ended: Session completed
    """
    connection_id = str(uuid.uuid4())
    session_id = None

    try:
        # Verify API key
        user_info = await verify_api_key(api_key, db)
        user_id = user_info['user_id']
        tier = user_info['tier']

        # Create new session
        session_id = str(uuid.uuid4())

        # Store session in Redis
        session_data = {
            'user_id': user_id,
            'status': 'active',
            'connection_id': connection_id,
            'started_at': datetime.utcnow().isoformat(),
            'config': {
                'language': language,
                'model': model,
                'enable_diarization': enable_diarization
            }
        }
        redis_client.set_session(session_id, session_data, ttl=7200)  # 2 hours

        # Accept WebSocket connection
        await manager.connect(connection_id, session_id, websocket)

        # Update metrics
        sessions_created_total.labels(tier=tier).inc()
        sessions_active.labels(tier=tier).inc()

        # Send session_started event
        await manager.broadcast_to_session(session_id, 'session_started', {
            'session_id': session_id,
            'config': session_data['config']
        })

        logger.info(f"Session started: session_id={session_id}, user_id={user_id}")

        # Main message loop
        chunk_count = 0
        while True:
            try:
                # Receive audio data (binary)
                data = await websocket.receive_bytes()

                chunk_count += 1
                websocket_messages_total.labels(
                    service='gateway',
                    direction='inbound',
                    message_type='audio'
                ).inc()

                # Publish audio chunk to RabbitMQ for processing
                message = {
                    'session_id': session_id,
                    'user_id': user_id,
                    'chunk_number': chunk_count,
                    'timestamp': datetime.utcnow().isoformat(),
                    'config': session_data['config'],
                    'audio_data_size': len(data)
                }

                # Publish metadata
                mq_client.publish(
                    exchange='audio.input',
                    routing_key='',
                    message=message
                )

                # Publish audio data separately (binary)
                mq_client.publish_binary(
                    exchange='audio.input',
                    routing_key='',
                    data=data
                )

                audio_chunks_processed_total.labels(
                    service='gateway',
                    status='sent'
                ).inc()

                logger.debug(f"Audio chunk received: session_id={session_id}, chunk={chunk_count}, size={len(data)}")

            except WebSocketDisconnect:
                logger.info(f"Client disconnected: session_id={session_id}")
                break

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                errors_total.labels(service='gateway', error_type=type(e).__name__).inc()
                await manager.broadcast_to_session(session_id, 'error', {
                    'message': str(e)
                })

    except HTTPException as e:
        # Authentication/authorization error
        logger.warning(f"WebSocket auth failed: {e.detail}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=e.detail)

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        errors_total.labels(service='gateway', error_type=type(e).__name__).inc()
        if websocket.client_state.name == 'CONNECTED':
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

    finally:
        # Cleanup
        if session_id:
            # Update session status in Redis
            session_data = redis_client.get_session(session_id)
            if session_data:
                session_data['status'] = 'ended'
                session_data['ended_at'] = datetime.utcnow().isoformat()
                session_data['total_chunks'] = chunk_count
                redis_client.set_session(session_id, session_data, ttl=3600)

            # Disconnect
            manager.disconnect(connection_id, session_id)

            # Update metrics
            if user_info:
                sessions_active.labels(tier=user_info.get('tier', 'unknown')).dec()

            # Send session_ended event
            await manager.broadcast_to_session(session_id, 'session_ended', {
                'session_id': session_id,
                'total_chunks': chunk_count
            })

            logger.info(f"Session ended: session_id={session_id}, chunks={chunk_count}")


# Background task to process transcript results from RabbitMQ
async def process_transcript_results():
    """
    Consume transcript results from RabbitMQ and push to WebSocket clients
    Runs in background
    """
    logger.info("Starting transcript result processor")

    def callback(ch, method, properties, body):
        """RabbitMQ callback for transcript results"""
        try:
            message = json.loads(body)
            session_id = message.get('session_id')
            event_type = message.get('event_type')
            data = message.get('data')

            if session_id:
                # Send to WebSocket client asynchronously
                asyncio.create_task(
                    manager.broadcast_to_session(session_id, event_type, data)
                )

                logger.debug(f"Sent {event_type} to session {session_id}")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.error(f"Error processing transcript result: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    try:
        # Declare queue for results (if not exists)
        mq_client.declare_queue('gateway.results')
        mq_client.bind_queue('gateway.results', 'processing.output', routing_key='#')

        # Start consuming
        mq_client.consume('gateway.results', callback, prefetch_count=10)

    except KeyboardInterrupt:
        logger.info("Transcript result processor stopped")
    except Exception as e:
        logger.error(f"Transcript result processor failed: {e}")


@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("Gateway service starting up")

    # Connect to RabbitMQ
    mq_client.connect()

    # Start background task for processing results
    # Note: This is simplified; in production, use a separate consumer process
    # asyncio.create_task(process_transcript_results())


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Gateway service shutting down")
    mq_client.disconnect()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )
