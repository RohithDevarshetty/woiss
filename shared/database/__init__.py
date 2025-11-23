"""
Database module for Real-Time Transcription Platform
"""
from .models import (
    Base,
    User,
    APIKey,
    Session,
    Transcript,
    UsageRecord,
    SpeakerProfile,
    Webhook
)
from .connection import (
    DatabaseManager,
    db_manager,
    get_db,
    init_db,
    reset_db
)

__all__ = [
    'Base',
    'User',
    'APIKey',
    'Session',
    'Transcript',
    'UsageRecord',
    'SpeakerProfile',
    'Webhook',
    'DatabaseManager',
    'db_manager',
    'get_db',
    'init_db',
    'reset_db',
]
