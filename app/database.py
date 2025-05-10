import os
import logging
from urllib.parse import urlparse
from databases import Database
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import AsyncGenerator
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER_NAME = os.getenv("DB_USER_NAME", "graduation_thesis")
DB_PASSWORD = os.getenv("DB_PASSWORD", "z9hr8d2uFTvsBqg")
DB_NAME = os.getenv("DB_NAME", "university_ems_db")
DATABASE_URL = f"postgresql://{DB_USER_NAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def validate_database_url(url: str) -> None:
    """
    Validate the DATABASE_URL format and ensure port is a valid integer.
    
    Args:
        url (str): Database URL to validate.
        
    Raises:
        ValueError: If the URL is invalid or port is not an integer.
    """
    if not url:
        raise ValueError("DATABASE_URL is not set in environment variables")
    
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid DATABASE_URL format: {url}")
    
    if parsed.port:
        try:
            int(parsed.port)
        except ValueError:
            raise ValueError(f"Invalid port in DATABASE_URL: {parsed.port}")

try:
    validate_database_url(DATABASE_URL)
except ValueError as e:
    logger.error(str(e))
    raise

database = Database(DATABASE_URL)
engine = create_engine(DATABASE_URL, echo=False)   
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

async def get_db() -> AsyncGenerator:
    """
    Provide a database connection for async FastAPI endpoints.
    
    Yields:
        Database: An active database connection.
        
    Raises:
        Exception: If connection fails.
    """
    try:
        await database.connect()
        yield database
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise
    finally:
        await database.disconnect()

def get_db_session():
    """
    Provide a SQLAlchemy session for sync operations.
    
    Yields:
        Session: An active SQLAlchemy session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()