import os
import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("uvicorn")  
logger.setLevel(logging.DEBUG)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER_NAME = os.getenv("DB_USER_NAME", "graduation_thesis")
DB_PASSWORD = os.getenv("DB_PASSWORD", "z9hr8d2uFTvsBqg")
DB_NAME = os.getenv("DB_NAME", "university_ems_db")

ASYNC_DATABASE_URL = f"postgresql+asyncpg://{DB_USER_NAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"[DB] Error during session: {e}")
            raise
        finally:
            await session.close()

async def test_connection():
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            logger.info(f"[DB] Connection test successful: {result.scalar()}")
    except Exception as e:
        logger.error(f"[DB] Connection test failed: {e}")
        raise


