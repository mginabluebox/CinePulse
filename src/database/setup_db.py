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
    """
    Create a SQLAlchemy engine.
    """
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')
    db_host = os.getenv('DB_HOST')
    db_name = os.getenv('DB_NAME')
    db_port = os.getenv('DB_PORT')

    host = f"{db_host}:{db_port}" if db_port else db_host
    db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{host}/{db_name}"
    return create_engine(db_url)

# Create a session factory
def get_session(engine=None):
    """Return a DB session. If an engine is supplied, use it; otherwise create one from env."""
    if engine is None:
        engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

# # Initialize database (for migrations or creating tables)
# def setup_database():
#     engine = get_engine()
#     Base.metadata.create_all(engine)
