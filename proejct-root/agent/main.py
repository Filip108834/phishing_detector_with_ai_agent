from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
)
from sqlalchemy.orm import declarative_base, sessionmaker


# =========================
# Konfiguracja DB
# =========================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Brak zmiennej środowiskowej DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    sender = Column(String(320), nullable=True)
    subject = Column(String(512), nullable=True)
    body_snippet = Column(String(1000), nullable=True)

    score = Column(Float, nullable=False)
    label = Column(String(32), nullable=False)
    reasons = Column(Text, nullable=True)  # JSON-like string (na start)


# Utworzenie tabel (na start bez migracji)
Base.metadata.create_all(bind=engine)


# =========================
# API
# =========================
app = FastAPI(
    title="AI Agent – Detekcja phishingu",
    version="0.1.0",
    description="Minimalny szkielet agenta AI (FastAPI) z /predict i zapisem do Postgres.",
)


class PredictRequest(BaseModel):
    sender: Optional[str] = Field(default=None, description="Adres nadawcy, np. from")
    subject: Optional[str] = Field(default=None, description="Temat wiadomości")
    body: str = Field(..., description="Treść wiadomości (plain lub z HTML po ekstrakcji)")
    urls: Optional[List[str]] = Field(default=None, description="Lista linków wyodrębnionych z treści")
    headers: Optional[Dict[str, Any]] = Field(default=None, description="Wybrane nagłówki/metadata")


class PredictResponse(BaseModel):
    label: str
    score: float
    reasons: List[str]
    saved_id: int


# =========================
# Minimalna logika "baseline"
# (żeby endpoint działał zanim podepniesz ML)
# =========================
PHISH_KEYWORDS = [
    "pilne", "natychmiast", "zablokowane", "weryfikacja", "potwierdź",
    "hasło", "login", "konto", "płatność", "faktura", "dopłata",
    "przelew", "bank", "paypal", "apple id", "microsoft", "office",
    "security alert", "verify", "password",
]

SUSPICIOUS_TLDS = [".zip", ".top", ".xyz", ".tk", ".click", ".lol"]


def _basic_score(sender: Optional[str], subject: Optional[str], body: str, urls: Optional[List[str]]) -> Tuple[float, List[str]]:
    """Prosty scoring heurystyczny: 0..1 + powody. Do podmiany na ML."""
    reasons: List[str] = []
    text = " ".join([subject or "", body or ""]).lower()

    kw_hits = [kw for kw in PHISH_KEYWORDS if kw in text]
    if kw_hits:
        reasons.append(f"Wykryto słowa-klucze: {', '.join(kw_hits[:8])}{'…' if len(kw_hits) > 8 else ''}")

    # dużo wykrzykników / presja czasu
    if text.count("!") >= 3:
        reasons.append("Wysoka liczba wykrzykników (presja / pilność).")

    # linki: IP lub podejrzane TLD
    url_list = urls or []
    ip_regex = re.compile(r"https?://(\d{1,3}\.){3}\d{1,3}(:\d+)?(/|$)")
    bad_urls = []
    for u in url_list:
        u_low = u.lower()
        if ip_regex.search(u_low):
            bad_urls.append(u)
        if any(u_low.endswith(tld) or f"{tld}/" in u_low for tld in SUSPICIOUS_TLDS):
            bad_urls.append(u)

    if bad_urls:
        reasons.append(f"Podejrzane URL (IP / TLD): {', '.join(bad_urls[:3])}{'…' if len(bad_urls) > 3 else ''}")

    # brak/krótki temat i długi body — często w spam/phish
    if (subject is None or len(subject.strip()) < 3) and len(body) > 500:
        reasons.append("Brak/krótki temat przy dłuższej treści.")

    # wynik: prosta normalizacja
    score = 0.15
    score += min(0.45, 0.05 * len(kw_hits))
    score += 0.15 if text.count("!") >= 3 else 0.0
    score += 0.25 if bad_urls else 0.0
    score += 0.1 if (subject is None or len(subject.strip()) < 3) and len(body) > 500 else 0.0
    score = max(0.0, min(1.0, score))

    if not reasons:
        reasons.append("Brak silnych sygnałów phishingu w baseline (heurystyka).")

    return score, reasons


@app.get("/health")
def health() -> Dict[str, str]:
    # szybki check DB
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1;")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB not ready: {e}")
    return {"status": "ok"}


@app.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest) -> PredictResponse:
    score, reasons = _basic_score(payload.sender, payload.subject, payload.body, payload.urls)

    label = "phishing" if score >= 0.5 else "legit"
    snippet = (payload.body or "").strip().replace("\n", " ")
    snippet = snippet[:1000] if snippet else None

    # zapis do DB
    db = SessionLocal()
    try:
        row = Prediction(
            sender=payload.sender,
            subject=payload.subject,
            body_snippet=snippet,
            score=float(score),
            label=label,
            reasons=str(reasons),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        saved_id = int(row.id)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Błąd zapisu do DB: {e}")
    finally:
        db.close()

    return PredictResponse(label=label, score=float(score), reasons=reasons, saved_id=saved_id)
