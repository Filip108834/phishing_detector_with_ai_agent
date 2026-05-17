"""
Agent AI - punkt wejścia FastAPI.

Odpowiedzialność tego modułu jest celowo ograniczona do:
    1. Konfiguracji aplikacji i lifecycle (lifespan)
    2. Rejestracji routerów
    3. Endpointu /health

Logika biznesowa, schematy i dostęp do DB żyją w osobnych modułach:
    agent/db.py             - SQLAlchemy engine, SessionLocal, Prediction
    agent/state.py          - współdzielony stan modelu i pollera
    agent/api/schemas.py    - modele Pydantic
    agent/api/routes_*.py   - endpointy pogrupowane tematycznie
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException

from agent import state
from agent.api.routes_ingest import router as ingest_router
from agent.api.routes_predict import router as predict_router
from agent.api.routes_results import router as results_router
from agent.db import Base, engine
from agent.ingestion.mailhog_poller import MailHogPoller
from agent.ml import pipeline as ml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Utwórz tabele (idempotentne)
    Base.metadata.create_all(bind=engine)

    # 2. Wczytaj model ML
    model_path = Path(os.getenv("MODEL_PATH", "models/classifier.joblib"))
    loaded = ml.load(model_path)
    if loaded is not None:
        state.model["pipeline"] = loaded
        state.model["type"] = "ml"
        state.model["path"] = str(model_path)
        logger.info("Model ML załadowany: %s", model_path)
    else:
        logger.warning(
            "Brak modelu ML (%s). Aktywny: heurystyczny baseline. "
            "Uruchom: python -m experiments.train_model",
            model_path,
        )

    # 3. Uruchom MailHog poller (jeśli skonfigurowany)
    poller_enabled = os.getenv("MAILHOG_POLLER_ENABLED", "true").lower() == "true"
    if poller_enabled:
        mailhog_url = os.getenv("MAILHOG_API_URL", "http://localhost:8025")
        interval = int(os.getenv("MAILHOG_POLL_INTERVAL", "15"))
        state.poller = MailHogPoller(mailhog_url=mailhog_url, interval=interval)
        state.poller.start()

    yield

    # Cleanup
    if state.poller:
        state.poller.stop()


# ---------------------------------------------------------------------------
# Aplikacja
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Agent - Detekcja phishingu",
    version="0.3.0",
    description=(
        "System klasyfikacji wiadomości e-mail jako phishing lub legit. "
        "Używa ML pipeline (spaCy + TF-IDF + ensemble) lub heurystycznego baseline."
    ),
    lifespan=lifespan,
)

app.include_router(predict_router)
app.include_router(results_router)
app.include_router(ingest_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
def health() -> Dict[str, str]:
    """Sprawdza połączenie z DB i raportuje aktywny tryb klasyfikacji."""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1;")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB not ready: {e}")

    result: Dict[str, str] = {"status": "ok", "model": state.model["type"]}
    if state.poller:
        result["poller"] = "running" if state.poller._running else "stopped"
    return result


@app.get("/poller/status", tags=["system"])
def poller_status() -> dict:
    """Zwraca stan background pollera MailHog."""
    if state.poller is None:
        return {"enabled": False}
    return {"enabled": True, **state.poller.status()}
