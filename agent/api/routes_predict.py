"""
Router: klasyfikacja wiadomości e-mail.

Endpointy:
    POST /predict      – klasyfikacja z JSON (sender, subject, body, urls, headers)
    POST /predict/raw  – klasyfikacja z surowego MIME (.eml string)
    GET  /model/info   – informacje o aktywnym modelu
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, HTTPException

from agent import state
from agent.api.schemas import (
    ModelInfoResponse,
    PredictRawRequest,
    PredictRequest,
    PredictResponse,
)
from agent.db import Prediction, SessionLocal
from agent.features.extractor import NUMERICAL_FEATURE_COLS, extract
from agent.ingestion.email_parser import ParsedEmail
from agent.ml import pipeline as ml

router = APIRouter(tags=["predict"])

# ---------------------------------------------------------------------------
# Endpointy
# ---------------------------------------------------------------------------

@router.get("/model/info", response_model=ModelInfoResponse)
def model_info() -> ModelInfoResponse:
    n_features = None
    if state.is_ml_active():
        try:
            n_features = len(NUMERICAL_FEATURE_COLS)
        except Exception:
            pass
    return ModelInfoResponse(
        model_type=state.model["type"],
        model_path=state.model["path"],
        is_ml_active=state.is_ml_active(),
        feature_count=n_features,
    )


@router.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest) -> PredictResponse:
    """Klasyfikuje e-mail z danych strukturyzowanych."""
    parsed = ParsedEmail.from_request(
        sender=payload.sender,
        subject=payload.subject,
        body=payload.body,
        urls=payload.urls,
        headers=payload.headers,
    )
    return _classify_and_save(parsed, snippet=(payload.body or "")[:1000])


@router.post("/predict/raw", response_model=PredictResponse)
def predict_raw(payload: PredictRawRequest) -> PredictResponse:
    """Klasyfikuje e-mail z surowego stringa MIME."""
    try:
        parsed = ParsedEmail.from_string(payload.raw_eml)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Błąd parsowania MIME: {e}")
    snippet = (parsed.plain_text or parsed.html_text or "")[:1000]
    return _classify_and_save(parsed, snippet=snippet)


# ---------------------------------------------------------------------------
# Wewnętrzna logika (reużywana przez poller i ingest)
# ---------------------------------------------------------------------------

def classify_parsed(parsed: ParsedEmail, campaign: Optional[str] = None) -> dict:
    """
    Klasyfikuje ParsedEmail i zapisuje do DB.

    Returns:
        dict z kluczami: label, score, reasons, model_used, saved_id
    """
    if state.is_ml_active():
        label, score, reasons = ml.predict_email(state.model["pipeline"], parsed)
        model_used = "ml"
    else:
        score, reasons = _heuristic_score(parsed)
        label = "phishing" if score >= 0.5 else "legit"
        model_used = "heuristic"

    snippet = (parsed.plain_text or parsed.html_text or "")[:1000]
    saved_id = _save_to_db(parsed, snippet, score, label, reasons, model_used, campaign)

    return {
        "label": label,
        "score": score,
        "reasons": reasons,
        "model_used": model_used,
        "saved_id": saved_id,
    }


def _classify_and_save(parsed: ParsedEmail, snippet: str) -> PredictResponse:
    result = classify_parsed(parsed)
    return PredictResponse(**result)


def _save_to_db(
    parsed: ParsedEmail,
    snippet: str,
    score: float,
    label: str,
    reasons: list[str],
    model_used: str,
    campaign: Optional[str],
) -> int:
    db = SessionLocal()
    try:
        row = Prediction(
            sender=parsed.from_addr or None,
            subject=parsed.subject or None,
            body_snippet=snippet.strip().replace("\n", " ") or None,
            score=score,
            label=label,
            reasons=str(reasons),
            model_used=model_used,
            campaign=campaign,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Błąd zapisu do DB: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Heurystyczny baseline (fallback)
# ---------------------------------------------------------------------------

_PHISH_KEYWORDS = [
    "pilne", "natychmiast", "zablokowane", "weryfikacja", "potwierdź",
    "hasło", "login", "konto", "płatność", "faktura", "dopłata",
    "przelew", "bank", "paypal", "apple id", "microsoft", "office",
    "security alert", "verify", "password", "urgent", "suspended",
]
_SUSPICIOUS_TLDS = [".zip", ".top", ".xyz", ".tk", ".click", ".lol"]
_IP_RE = re.compile(r"https?://(\d{1,3}\.){3}\d{1,3}(:\d+)?(/|$)")


def _heuristic_score(parsed: ParsedEmail) -> tuple[float, list[str]]:
    reasons: list[str] = []
    text = f"{parsed.subject} {parsed.plain_text} {parsed.html_text}".lower()

    kw_hits = [kw for kw in _PHISH_KEYWORDS if kw in text]
    if kw_hits:
        reasons.append(f"Wykryto słowa-klucze: {', '.join(kw_hits[:8])}")
    if text.count("!") >= 3:
        reasons.append("Wysoka liczba wykrzykników (presja/pilność).")

    bad_urls = [
        u for u in parsed.urls
        if _IP_RE.search(u.lower())
        or any(u.lower().endswith(t) or f"{t}/" in u.lower() for t in _SUSPICIOUS_TLDS)
    ]
    if bad_urls:
        reasons.append(f"Podejrzane URL: {', '.join(bad_urls[:3])}")

    score = min(1.0, 0.15 + 0.05 * len(kw_hits)
                + (0.15 if text.count("!") >= 3 else 0.0)
                + (0.25 if bad_urls else 0.0))

    if not reasons:
        reasons.append("Brak silnych sygnałów phishingu (heurystyka).")
    return score, reasons
