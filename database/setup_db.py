import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv, find_dotenv

# Load environment variables
load_dotenv(find_dotenv())

# SQLAlchemy Base
Base = declarative_base()

# Database connection setup
def get_engine():
    """Create a SQLAlchemy engine using environment variables."""
    db_url = f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
    return create_engine(db_url)

# Create a session factory
def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

# Initialize database (for migrations or creating tables)
def setup_database():
    engine = get_engine()
    Base.metadata.create_all(engine)
