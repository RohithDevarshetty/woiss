"""
Authentication and authorization utilities
"""
import os
import hashlib
import secrets
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta
import jwt
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# JWT configuration
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-secret-change-in-production')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))


def generate_api_key() -> Tuple[str, str]:
    """
    Generate a new API key

    Returns:
        Tuple of (api_key, key_hash)
    """
    # Generate 32-byte random key
    api_key = f"rtk_{secrets.token_urlsafe(32)}"

    # Hash for storage
    key_hash = hash_api_key(api_key)

    return api_key, key_hash


def hash_api_key(api_key: str) -> str:
    """
    Hash API key using SHA-256

    Args:
        api_key: Plain API key

    Returns:
        Hashed API key
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(db: Session, api_key: str) -> Optional[dict]:
    """
    Verify API key and return associated user

    Args:
        db: Database session
        api_key: API key to verify

    Returns:
        User dict if valid, None otherwise
    """
    from shared.database import APIKey, User

    key_hash = hash_api_key(api_key)

    try:
        api_key_obj = db.query(APIKey).filter(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True
        ).first()

        if not api_key_obj:
            return None

        # Update last_used_at
        api_key_obj.last_used_at = datetime.utcnow()
        db.commit()

        # Get user
        user = db.query(User).filter(User.id == api_key_obj.user_id).first()

        if not user or not user.is_active:
            return None

        return {
            'user_id': str(user.id),
            'email': user.email,
            'tier': user.tier,
            'api_key_id': str(api_key_obj.id),
            'rate_limit': api_key_obj.rate_limit
        }

    except Exception as e:
        logger.error(f"Error verifying API key: {e}")
        return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token

    Args:
        data: Data to encode in token
        expires_delta: Optional expiration delta

    Returns:
        JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)

    to_encode.update({'exp': expire})

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_access_token(token: str) -> Optional[dict]:
    """
    Verify JWT access token

    Args:
        token: JWT token

    Returns:
        Decoded payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        return None
    except jwt.JWTError as e:
        logger.warning(f"Token verification failed: {e}")
        return None


def create_session_token(session_id: str, user_id: str) -> str:
    """
    Create a session-specific JWT token

    Args:
        session_id: Session ID
        user_id: User ID

    Returns:
        JWT token
    """
    data = {
        'session_id': session_id,
        'user_id': user_id,
        'type': 'session'
    }
    return create_access_token(data)


def verify_session_token(token: str) -> Optional[Tuple[str, str]]:
    """
    Verify session token and extract session_id and user_id

    Args:
        token: JWT session token

    Returns:
        Tuple of (session_id, user_id) if valid, None otherwise
    """
    payload = verify_access_token(token)
    if payload and payload.get('type') == 'session':
        return payload.get('session_id'), payload.get('user_id')
    return None
