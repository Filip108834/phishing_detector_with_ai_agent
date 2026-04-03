"""
Główny conftest – ustawiany PRZED importem jakichkolwiek modułów agenta.

Kolejność działania:
    1. os.environ ustawiony zanim cokolwiek z agent.* zostanie załadowane
    2. engine SQLite (in-memory + StaticPool) zastępuje engine PostgreSQL
    3. SessionLocal we wszystkich modułach routerów jest patchowany
    4. Tabele tworzone jeden raz dla całej sesji testowej
"""
from __future__ import annotations

import os

# ── Musi być PRZED każdym importem z agent.* ─────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MAILHOG_POLLER_ENABLED", "false")
os.environ.setdefault("MODEL_PATH", "models/nonexistent.joblib")
# ─────────────────────────────────────────────────────────────────────────────

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import modułów agenta po ustawieniu env vars
import agent.db as _db
import agent.api.routes_predict as _routes_predict
import agent.api.routes_results as _routes_results
import agent.main as _main

from agent.db import Base
from agent.ingestion.email_parser import ParsedEmail

# ── Testowy engine SQLite (in-memory, współdzielony przez StaticPool) ─────────
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False)

# ── Podmiana referencji we wszystkich modułach ────────────────────────────────
_db.engine = _test_engine
_db.SessionLocal = _TestSession
_routes_predict.SessionLocal = _TestSession
_routes_results.SessionLocal = _TestSession
_main.engine = _test_engine

# ── Tworzenie tabel (raz na sesję testową) ────────────────────────────────────
Base.metadata.create_all(bind=_test_engine)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures współdzielone
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient – lifespan uruchamiany raz na całą sesję testową."""
    from starlette.testclient import TestClient
    from agent.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def db_session():
    """Sesja SQLAlchemy dla bezpośrednich operacji na testowej bazie."""
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_predictions():
    """Czyści tabelę predictions przed każdym testem."""
    from agent.db import Prediction
    db = _TestSession()
    try:
        db.query(Prediction).delete()
        db.commit()
    finally:
        db.close()
    yield


# ─────────────────────────────────────────────────────────────────────────────
# Fabryki e-maili do wielokrotnego użytku
# ─────────────────────────────────────────────────────────────────────────────

def make_phishing_eml(
    from_addr: str = "security@evil.xyz",
    subject: str = "URGENT: Verify your account immediately!",
    reply_to: str = "attacker@gmail.com",
    body: str | None = None,
) -> str:
    if body is None:
        body = (
            "Click here to verify: http://192.168.1.100/login\n"
            "Your account has been suspended. Action required.\n"
            "Confirm your credentials now or account will be disabled."
        )
    return (
        f"From: {from_addr}\r\n"
        f"To: victim@lab.local\r\n"
        f"Subject: {subject}\r\n"
        f"Reply-To: {reply_to}\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}"
    )


def make_legit_eml(
    from_addr: str = "hr@company.com",
    subject: str = "Team meeting tomorrow at 10:00",
    body: str | None = None,
) -> str:
    if body is None:
        body = (
            "Hi team,\n\n"
            "Please join the sprint review meeting tomorrow at 10:00 in room A2.\n\n"
            "Agenda:\n1. Sprint results\n2. Next iteration planning\n\nBest,\nAnna"
        )
    return (
        f"From: {from_addr}\r\n"
        f"To: employee@company.com\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}"
    )


@pytest.fixture()
def phishing_parsed() -> ParsedEmail:
    return ParsedEmail.from_string(make_phishing_eml())


@pytest.fixture()
def legit_parsed() -> ParsedEmail:
    return ParsedEmail.from_string(make_legit_eml())
