"""
Database connection management for PostgreSQL
"""
import os
from typing import Generator
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, QueuePool
from .models import Base

# Database URL from environment
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://transcribe:transcribe@localhost:5432/realtime_transcribe'
)


class DatabaseManager:
    """Manages database connections and sessions"""

    def __init__(
        self,
        database_url: str = DATABASE_URL,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: int = 30,
        echo: bool = False
    ):
        """
        Initialize database manager

        Args:
            database_url: PostgreSQL connection URL
            pool_size: Number of connections to keep in pool
            max_overflow: Maximum overflow connections
            pool_timeout: Timeout for getting connection from pool
            echo: Enable SQL query logging
        """
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_pre_ping=True,  # Enable connection health checks
            echo=echo,
        )

        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

        # Register connection event listeners
        self._setup_listeners()

    def _setup_listeners(self):
        """Setup SQLAlchemy event listeners for monitoring"""

        @event.listens_for(self.engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            """Called when connection is created"""
            # Set session parameters
            cursor = dbapi_conn.cursor()
            cursor.execute("SET TIME ZONE 'UTC'")
            cursor.close()

        @event.listens_for(self.engine, "checkout")
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            """Called when connection is checked out from pool"""
            pass  # Add metrics collection here

        @event.listens_for(self.engine, "checkin")
        def receive_checkin(dbapi_conn, connection_record):
            """Called when connection is returned to pool"""
            pass  # Add metrics collection here

    def create_tables(self):
        """Create all database tables"""
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """Drop all database tables (DANGER!)"""
        Base.metadata.drop_all(bind=self.engine)

    def get_session(self) -> Session:
        """
        Get a new database session

        Returns:
            SQLAlchemy session
        """
        return self.SessionLocal()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions with automatic commit/rollback

        Usage:
            with db.session_scope() as session:
                user = session.query(User).first()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def health_check(self) -> bool:
        """
        Check database connectivity

        Returns:
            True if database is accessible, False otherwise
        """
        try:
            with self.engine.connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def dispose(self):
        """Dispose of connection pool"""
        self.engine.dispose()


# Global database instance
db_manager = DatabaseManager()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI to get database session

    Usage:
        @app.get("/users")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()
    """
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()


def init_db():
    """Initialize database (create tables)"""
    db_manager.create_tables()


def reset_db():
    """Reset database (drop and recreate tables) - USE WITH CAUTION"""
    db_manager.drop_tables()
    db_manager.create_tables()
