"""
Konfiguracja bazy danych - SQLAlchemy engine, session, modele ORM.

Importuj stąd: engine, SessionLocal, Base, Prediction
"""
import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Brak zmiennej środowiskowej DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sender = Column(String(320), nullable=True)
    subject = Column(String(512), nullable=True)
    body_snippet = Column(String(1000), nullable=True)
    score = Column(Float, nullable=False)
    label = Column(String(32), nullable=False)
    reasons = Column(Text, nullable=True)
    model_used = Column(String(32), nullable=False, default="heuristic")
    ### Opcjonalne pole kampanii (wypełniane przez /ingest/campaign)
    campaign = Column(String(128), nullable=True)
