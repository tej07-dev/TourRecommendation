from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from config.settings import get_settings
from database_models.postgres_model import Base
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy import text
settings = get_settings()

# Async engine for FastAPI
async_engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,
)

# Sync engine for initialization and migrations
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database with PostGIS extension"""
    async with async_engine.begin() as conn:
        # Enable PostGIS extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))           
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections"""
    await async_engine.dispose()

# # database/connection.py
# from sqlalchemy import create_engine, event
# from sqlalchemy.orm import sessionmaker, Session
# from sqlalchemy.pool import QueuePool
# from config.settings import get_settings
# from database_models.postgres_model import Base
# from contextlib import contextmanager
# from typing import Generator
# settings = get_settings()

# # Create PostgreSQL engine with connection pooling
# engine = create_engine(
#     settings.POSTGRES_URI,
#     poolclass=QueuePool,
#     pool_size=20,
#     max_overflow=40,
#     pool_pre_ping=True,
#     pool_recycle=3600,
#     echo=settings.DEBUG
# )

# # Enable PostGIS extension
# @event.listens_for(engine, "connect")
# def receive_connect(dbapi_conn, connection_record):
#     with dbapi_conn.cursor() as cursor:
#         cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
#     dbapi_conn.commit()

# # Create session factory
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# def init_db():
#     """Initialize database tables"""
#     Base.metadata.create_all(bind=engine)

# def get_db() -> Generator[Session, None, None]:
#     """Dependency for FastAPI"""
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

# @contextmanager
# def get_db_context():
#     """Context manager for database sessions"""
#     db = SessionLocal()
#     try:
#         yield db
#         db.commit()
#     except Exception:
#         db.rollback()
#         raise
#     finally:
#         db.close()


