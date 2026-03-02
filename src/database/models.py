from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint
from pgvector.sqlalchemy import Vector

from .setup_db import Base

# Define the Showtime model
class Showtime(Base):
    __tablename__ = 'showtimes'

    id = Column(Integer, primary_key=True)
    crawled_at = Column(DateTime, nullable=False)
    
    # Showtime level fields
    show_time = Column(DateTime, nullable=False)
    show_day = Column(String(20))
    cinema = Column(String, nullable=False)
    ticket_link = Column(Text)
    image_url = Column(Text)

    # Movie level fields
    title = Column(String(255), nullable=False)
    director1 = Column(String(255))
    director2 = Column(String(255))
    year = Column(Integer)
    runtime = Column(Integer)
    format = Column(String(50))
    synopsis = Column(Text)

    movie_id = Column(Integer, ForeignKey('movies.id'), nullable=False)


class Movie(Base):
    __tablename__ = 'movies'

    id = Column(Integer, primary_key=True)

    title = Column(String(255), nullable=False)
    year = Column(Integer)

    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    scraped_synopsis = Column(Text)
    scraped_director1 = Column(String(255))
    scraped_cinema = Column(String)
    scraped_image_url = Column(Text)

    embedding = Column(Vector(1536), nullable=True)
    embedding_model = Column(String(255), nullable=True)
    embedding_source_hash = Column(String(64), nullable=True)  # SHA256 hash of the source text used for embedding  
    embedded_at = Column(DateTime, nullable=True)

    # __table_args__ = (
    #     UniqueConstraint('title', 'year', name='uq_movie_title_year'),
    # )