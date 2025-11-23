"""
Redis client for session state management and caching
"""
import os
import json
import logging
from typing import Optional, Dict, Any, Union
import redis
from redis.exceptions import RedisError, ConnectionError

logger = logging.getLogger(__name__)

# Redis configuration from environment
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_DB = int(os.getenv('REDIS_DB', '0'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
REDIS_MAX_CONNECTIONS = int(os.getenv('REDIS_MAX_CONNECTIONS', '50'))


class RedisClient:
    """Redis client for session state and caching"""

    def __init__(
        self,
        host: str = REDIS_HOST,
        port: int = REDIS_PORT,
        db: int = REDIS_DB,
        password: Optional[str] = REDIS_PASSWORD,
        max_connections: int = REDIS_MAX_CONNECTIONS,
        decode_responses: bool = True
    ):
        """
        Initialize Redis client

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password (optional)
            max_connections: Maximum connections in pool
            decode_responses: Decode responses to strings
        """
        self.pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            max_connections=max_connections,
            decode_responses=decode_responses
        )
        self.client = redis.Redis(connection_pool=self.pool)

    # Session management
    def set_session(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        ttl: int = 3600
    ):
        """
        Store session data

        Args:
            session_id: Unique session identifier
            session_data: Session data dictionary
            ttl: Time to live in seconds (default 1 hour)
        """
        key = f"session:{session_id}"
        try:
            self.client.setex(
                key,
                ttl,
                json.dumps(session_data)
            )
            logger.debug(f"Set session: {session_id}")
        except RedisError as e:
            logger.error(f"Failed to set session {session_id}: {e}")
            raise

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session data

        Args:
            session_id: Unique session identifier

        Returns:
            Session data dict or None if not found
        """
        key = f"session:{session_id}"
        try:
            data = self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except RedisError as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            raise

    def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any],
        ttl: Optional[int] = None
    ):
        """
        Update session data (merge with existing)

        Args:
            session_id: Unique session identifier
            updates: Dictionary of updates to apply
            ttl: Optional new TTL in seconds
        """
        session_data = self.get_session(session_id)
        if session_data:
            session_data.update(updates)
            if ttl is None:
                # Preserve existing TTL
                ttl = self.client.ttl(f"session:{session_id}")
                if ttl == -1:  # No expiration
                    ttl = 3600  # Default to 1 hour
            self.set_session(session_id, session_data, ttl)
        else:
            # Create new session
            self.set_session(session_id, updates, ttl or 3600)

    def delete_session(self, session_id: str):
        """
        Delete session data

        Args:
            session_id: Unique session identifier
        """
        key = f"session:{session_id}"
        try:
            self.client.delete(key)
            logger.debug(f"Deleted session: {session_id}")
        except RedisError as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            raise

    def session_exists(self, session_id: str) -> bool:
        """
        Check if session exists

        Args:
            session_id: Unique session identifier

        Returns:
            True if session exists, False otherwise
        """
        return bool(self.client.exists(f"session:{session_id}"))

    # Connection registry
    def register_connection(
        self,
        connection_id: str,
        session_id: str,
        ttl: int = 3600
    ):
        """
        Register WebSocket connection

        Args:
            connection_id: Unique connection identifier
            session_id: Associated session ID
            ttl: Time to live in seconds
        """
        key = f"connection:{connection_id}"
        try:
            self.client.setex(key, ttl, session_id)
            logger.debug(f"Registered connection: {connection_id} -> {session_id}")
        except RedisError as e:
            logger.error(f"Failed to register connection {connection_id}: {e}")
            raise

    def get_session_for_connection(self, connection_id: str) -> Optional[str]:
        """
        Get session ID for connection

        Args:
            connection_id: Unique connection identifier

        Returns:
            Session ID or None
        """
        key = f"connection:{connection_id}"
        try:
            return self.client.get(key)
        except RedisError as e:
            logger.error(f"Failed to get session for connection {connection_id}: {e}")
            raise

    def unregister_connection(self, connection_id: str):
        """
        Unregister WebSocket connection

        Args:
            connection_id: Unique connection identifier
        """
        key = f"connection:{connection_id}"
        try:
            self.client.delete(key)
            logger.debug(f"Unregistered connection: {connection_id}")
        except RedisError as e:
            logger.error(f"Failed to unregister connection {connection_id}: {e}")
            raise

    # Rate limiting
    def check_rate_limit(
        self,
        user_id: str,
        limit: int = 100,
        window: int = 60
    ) -> bool:
        """
        Check if user has exceeded rate limit

        Args:
            user_id: User identifier
            limit: Maximum requests allowed
            window: Time window in seconds

        Returns:
            True if under limit, False if exceeded
        """
        key = f"ratelimit:{user_id}:{window}"
        try:
            current = self.client.get(key)
            if current is None:
                # First request in window
                self.client.setex(key, window, 1)
                return True
            elif int(current) < limit:
                # Increment counter
                self.client.incr(key)
                return True
            else:
                # Rate limit exceeded
                logger.warning(f"Rate limit exceeded for user {user_id}")
                return False
        except RedisError as e:
            logger.error(f"Rate limit check failed for user {user_id}: {e}")
            # Fail open (allow request) on error
            return True

    # Speaker embeddings (for voice imitation)
    def set_speaker_embedding(
        self,
        speaker_id: str,
        embedding: bytes,
        ttl: Optional[int] = None
    ):
        """
        Store speaker embedding vector

        Args:
            speaker_id: Speaker identifier
            embedding: Binary embedding vector
            ttl: Time to live in seconds (None = no expiration)
        """
        key = f"speaker:{speaker_id}:embedding"
        try:
            if ttl:
                self.client.setex(key, ttl, embedding)
            else:
                self.client.set(key, embedding)
            logger.debug(f"Set speaker embedding: {speaker_id}")
        except RedisError as e:
            logger.error(f"Failed to set speaker embedding {speaker_id}: {e}")
            raise

    def get_speaker_embedding(self, speaker_id: str) -> Optional[bytes]:
        """
        Retrieve speaker embedding vector

        Args:
            speaker_id: Speaker identifier

        Returns:
            Binary embedding vector or None
        """
        key = f"speaker:{speaker_id}:embedding"
        try:
            return self.client.get(key)
        except RedisError as e:
            logger.error(f"Failed to get speaker embedding {speaker_id}: {e}")
            raise

    # Generic key-value operations
    def set(self, key: str, value: Union[str, bytes, int, float], ttl: Optional[int] = None):
        """
        Set a key-value pair

        Args:
            key: Redis key
            value: Value to store
            ttl: Time to live in seconds (None = no expiration)
        """
        try:
            if ttl:
                self.client.setex(key, ttl, value)
            else:
                self.client.set(key, value)
        except RedisError as e:
            logger.error(f"Failed to set key {key}: {e}")
            raise

    def get(self, key: str) -> Optional[Any]:
        """
        Get value for key

        Args:
            key: Redis key

        Returns:
            Value or None
        """
        try:
            return self.client.get(key)
        except RedisError as e:
            logger.error(f"Failed to get key {key}: {e}")
            raise

    def delete(self, key: str):
        """
        Delete a key

        Args:
            key: Redis key
        """
        try:
            self.client.delete(key)
        except RedisError as e:
            logger.error(f"Failed to delete key {key}: {e}")
            raise

    def exists(self, key: str) -> bool:
        """
        Check if key exists

        Args:
            key: Redis key

        Returns:
            True if key exists, False otherwise
        """
        return bool(self.client.exists(key))

    def expire(self, key: str, ttl: int):
        """
        Set expiration on key

        Args:
            key: Redis key
            ttl: Time to live in seconds
        """
        try:
            self.client.expire(key, ttl)
        except RedisError as e:
            logger.error(f"Failed to set expiration on key {key}: {e}")
            raise

    # Cache operations with JSON serialization
    def cache_set(
        self,
        key: str,
        data: Dict[str, Any],
        ttl: int = 300
    ):
        """
        Cache data with JSON serialization

        Args:
            key: Cache key
            data: Data to cache
            ttl: Time to live in seconds (default 5 minutes)
        """
        try:
            self.client.setex(key, ttl, json.dumps(data))
        except RedisError as e:
            logger.error(f"Failed to cache data for key {key}: {e}")
            raise

    def cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached data

        Args:
            key: Cache key

        Returns:
            Cached data or None
        """
        try:
            data = self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except RedisError as e:
            logger.error(f"Failed to retrieve cache for key {key}: {e}")
            raise

    def flush_all(self):
        """Flush all keys from current database (USE WITH CAUTION)"""
        try:
            self.client.flushdb()
            logger.warning("Flushed all keys from Redis database")
        except RedisError as e:
            logger.error(f"Failed to flush database: {e}")
            raise

    def health_check(self) -> bool:
        """
        Check Redis connectivity

        Returns:
            True if Redis is accessible, False otherwise
        """
        try:
            return self.client.ping()
        except (RedisError, ConnectionError) as e:
            logger.error(f"Redis health check failed: {e}")
            return False


# Global Redis client instance
redis_client = RedisClient()
