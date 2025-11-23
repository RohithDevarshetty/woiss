"""
REST API Service
Provides HTTP APIs for session management, transcripts, and user operations
"""
import os
import sys
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session as DBSession
from prometheus_client import make_asgi_app
import uvicorn

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logging_config import setup_logging
from shared.utils.auth import generate_api_key, verify_api_key
from shared.database import get_db, User, APIKey, Session, Transcript, UsageRecord
from shared.utils.redis_client import redis_client
from shared.utils.metrics import http_requests_total, track_duration, http_request_duration_seconds

# Setup logging
setup_logging(service_name='api')
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Real-Time Transcription API",
    description="REST API for real-time transcription platform",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# Pydantic models
class UserCreate(BaseModel):
    email: EmailStr
    tier: str = 'free'


class APIKeyCreate(BaseModel):
    name: str


class SessionResponse(BaseModel):
    id: str
    user_id: str
    status: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]
    total_words: int
    average_confidence: Optional[float]

    class Config:
        from_attributes = True


class TranscriptSegment(BaseModel):
    start: float
    end: float
    speaker: Optional[str]
    text: str
    confidence: float


class TranscriptResponse(BaseModel):
    session_id: str
    segments: List[dict]
    created_at: datetime
    updated_at: datetime


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    with track_duration(http_request_duration_seconds, 'api', 'GET', '/health'):
        redis_ok = redis_client.health_check()

        return {
            'status': 'healthy' if redis_ok else 'degraded',
            'redis': redis_ok
        }


# User endpoints
@app.post("/v1/users", status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, db: DBSession = Depends(get_db)):
    """Create a new user"""
    with track_duration(http_request_duration_seconds, 'api', 'POST', '/v1/users'):
        # Check if user exists
        existing = db.query(User).filter(User.email == user.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already exists"
            )

        # Create user
        new_user = User(email=user.email, tier=user.tier)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        http_requests_total.labels(service='api', method='POST', endpoint='/v1/users', status='201').inc()

        return {
            'id': str(new_user.id),
            'email': new_user.email,
            'tier': new_user.tier,
            'created_at': new_user.created_at
        }


# API Key endpoints
@app.post("/v1/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: APIKeyCreate,
    user_id: str,
    db: DBSession = Depends(get_db)
):
    """Create a new API key for a user"""
    with track_duration(http_request_duration_seconds, 'api', 'POST', '/v1/api-keys'):
        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Generate API key
        api_key, key_hash = generate_api_key()

        # Store in database
        new_key = APIKey(
            user_id=user.id,
            key_hash=key_hash,
            name=key_data.name
        )
        db.add(new_key)
        db.commit()

        http_requests_total.labels(service='api', method='POST', endpoint='/v1/api-keys', status='201').inc()

        return {
            'id': str(new_key.id),
            'api_key': api_key,  # Only returned once!
            'name': new_key.name,
            'created_at': new_key.created_at
        }


# Session endpoints
@app.get("/v1/sessions", response_model=List[SessionResponse])
async def list_sessions(
    user_id: Optional[str] = None,
    limit: int = 20,
    db: DBSession = Depends(get_db)
):
    """List sessions"""
    with track_duration(http_request_duration_seconds, 'api', 'GET', '/v1/sessions'):
        query = db.query(Session)

        if user_id:
            query = query.filter(Session.user_id == user_id)

        sessions = query.order_by(Session.started_at.desc()).limit(limit).all()

        http_requests_total.labels(service='api', method='GET', endpoint='/v1/sessions', status='200').inc()

        return sessions


@app.get("/v1/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: DBSession = Depends(get_db)):
    """Get session details"""
    with track_duration(http_request_duration_seconds, 'api', 'GET', f'/v1/sessions/{session_id}'):
        session = db.query(Session).filter(Session.id == session_id).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )

        http_requests_total.labels(service='api', method='GET', endpoint='/v1/sessions/:id', status='200').inc()

        return session


@app.delete("/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, db: DBSession = Depends(get_db)):
    """Delete a session"""
    with track_duration(http_request_duration_seconds, 'api', 'DELETE', f'/v1/sessions/{session_id}'):
        session = db.query(Session).filter(Session.id == session_id).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )

        db.delete(session)
        db.commit()

        # Clean up Redis
        redis_client.delete_session(session_id)

        http_requests_total.labels(service='api', method='DELETE', endpoint='/v1/sessions/:id', status='204').inc()


# Transcript endpoints
@app.get("/v1/sessions/{session_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(session_id: str, db: DBSession = Depends(get_db)):
    """Get full transcript for a session"""
    with track_duration(http_request_duration_seconds, 'api', 'GET', f'/v1/sessions/{session_id}/transcript'):
        transcript = db.query(Transcript).filter(
            Transcript.session_id == session_id
        ).first()

        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transcript not found"
            )

        http_requests_total.labels(service='api', method='GET', endpoint='/v1/sessions/:id/transcript', status='200').inc()

        return transcript


# Usage endpoints
@app.get("/v1/usage")
async def get_usage(
    user_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: DBSession = Depends(get_db)
):
    """Get usage statistics"""
    with track_duration(http_request_duration_seconds, 'api', 'GET', '/v1/usage'):
        query = db.query(UsageRecord).filter(UsageRecord.user_id == user_id)

        if start_date:
            query = query.filter(UsageRecord.timestamp >= start_date)
        if end_date:
            query = query.filter(UsageRecord.timestamp <= end_date)

        records = query.all()

        # Aggregate statistics
        total_minutes = sum(r.duration_seconds or 0 for r in records) / 60.0
        total_words = sum(r.word_count or 0 for r in records)
        total_cost = sum(r.cost_cents or 0 for r in records) / 100.0  # Convert to dollars

        http_requests_total.labels(service='api', method='GET', endpoint='/v1/usage', status='200').inc()

        return {
            'user_id': user_id,
            'total_minutes': total_minutes,
            'total_words': total_words,
            'total_cost_usd': total_cost,
            'record_count': len(records)
        }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )
