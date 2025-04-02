import os
from sqlalchemy import Column, Integer, String, DateTime, Text, create_engine
from .setup_db import Base

# Define the Showtime model
class Showtime(Base):
    __tablename__ = 'showtimes'

    id = Column(Integer, primary_key=True)
    crawled_at = Column(DateTime, nullable=False)
    title = Column(String(255), nullable=False)
    show_time = Column(DateTime, nullable=False)
    show_day = Column(String(20), nullable=False)
    ticket_link = Column(Text)
    director1 = Column(String(255))
    director2 = Column(String(255))
    year = Column(Integer)
    runtime = Column(Integer)
    format = Column(String(50))
    synopsis = Column(Text)
    cinema = Column(String)
