"""
Database models for Real-Time Transcription Platform
"""
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime,
    ForeignKey, JSON, Text, Float
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """User account model"""
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    tier = Column(String(50), default='free', nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    metadata = Column(JSONB, default=dict)

    # Relationships
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, tier={self.tier})>"


class APIKey(Base):
    """API key model for authentication"""
    __tablename__ = 'api_keys'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)
    rate_limit = Column(Integer, default=100)  # requests per minute
    metadata = Column(JSONB, default=dict)

    # Relationships
    user = relationship("User", back_populates="api_keys")

    def __repr__(self):
        return f"<APIKey(id={self.id}, user_id={self.user_id}, name={self.name})>"


class Session(Base):
    """Transcription session model"""
    __tablename__ = 'sessions'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(50), default='active', nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    ended_at = Column(DateTime)
    duration_seconds = Column(Integer)
    audio_url = Column(Text)

    # Configuration
    config = Column(JSONB, default=dict)  # model, language, features, etc.

    # Metadata
    metadata = Column(JSONB, default=dict)

    # Stats
    total_words = Column(Integer, default=0)
    total_speakers = Column(Integer)
    average_confidence = Column(Float)

    # Relationships
    user = relationship("User", back_populates="sessions")
    transcripts = relationship("Transcript", back_populates="session", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id}, status={self.status})>"


class Transcript(Base):
    """Transcript storage model"""
    __tablename__ = 'transcripts'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)

    # Transcript segments in JSONB format
    # Structure: [{"start": 0.5, "end": 3.2, "speaker": "SPEAKER_01", "text": "...", "words": [...]}]
    segments = Column(JSONB, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Version for optimistic locking
    version = Column(Integer, default=1, nullable=False)

    # Relationships
    session = relationship("Session", back_populates="transcripts")

    def __repr__(self):
        return f"<Transcript(id={self.id}, session_id={self.session_id}, version={self.version})>"


class UsageRecord(Base):
    """Usage tracking for billing and analytics"""
    __tablename__ = 'usage_records'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id', ondelete='SET NULL'))

    event_type = Column(String(50), nullable=False)  # 'transcription', 'diarization', 'voice_clone', etc.
    duration_seconds = Column(Integer)
    word_count = Column(Integer)
    cost_cents = Column(Integer)  # Cost in cents

    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    metadata = Column(JSONB, default=dict)

    # Relationships
    user = relationship("User", back_populates="usage_records")
    session = relationship("Session", back_populates="usage_records")

    def __repr__(self):
        return f"<UsageRecord(id={self.id}, user_id={self.user_id}, event_type={self.event_type})>"


class SpeakerProfile(Base):
    """Speaker voice profile for voice imitation (Phase 2)"""
    __tablename__ = 'speaker_profiles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Speaker embedding stored as binary in Redis, reference here
    embedding_key = Column(String(255), unique=True, index=True)

    # Sample audio reference
    sample_audio_url = Column(Text)

    # Consent and verification
    consent_verified = Column(Boolean, default=False, nullable=False)
    consent_timestamp = Column(DateTime)
    consent_signature = Column(Text)  # Cryptographic signature

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    is_active = Column(Boolean, default=True, nullable=False)
    metadata = Column(JSONB, default=dict)

    def __repr__(self):
        return f"<SpeakerProfile(id={self.id}, name={self.name}, consent_verified={self.consent_verified})>"


class Webhook(Base):
    """Webhook configuration for event notifications"""
    __tablename__ = 'webhooks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    url = Column(Text, nullable=False)
    events = Column(JSONB, nullable=False)  # List of event types to subscribe to
    secret = Column(String(255))  # For HMAC signature verification

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Stats
    total_deliveries = Column(Integer, default=0)
    failed_deliveries = Column(Integer, default=0)
    last_delivery_at = Column(DateTime)
    last_failure_at = Column(DateTime)

    def __repr__(self):
        return f"<Webhook(id={self.id}, user_id={self.user_id}, url={self.url})>"
