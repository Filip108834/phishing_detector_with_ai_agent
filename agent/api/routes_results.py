"""
Router: historia predykcji i statystyki.

Endpointy:
    GET /results              - paginowana lista predykcji
    GET /results/stats        - agregowane statystyki
    GET /results/{id}         - szczegóły pojedynczej predykcji
    GET /results/campaign/{n} - predykcje dla danej kampanii
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func

from agent.api.schemas import ResultItem, ResultListResponse, StatsResponse
from agent.db import Prediction, SessionLocal

router = APIRouter(prefix="/results", tags=["results"])


@router.get("", response_model=ResultListResponse)
def list_results(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    label: Optional[str] = Query(default=None, description="Filtr: 'phishing' | 'legit'"),
    model_used: Optional[str] = Query(default=None, description="Filtr: 'ml' | 'heuristic'"),
    campaign: Optional[str] = Query(default=None, description="Filtr: nazwa kampanii"),
) -> ResultListResponse:
    """Zwraca paginowaną listę predykcji z opcjonalnym filtrowaniem."""
    db = SessionLocal()
    try:
        q = db.query(Prediction)
        if label:
            q = q.filter(Prediction.label == label)
        if model_used:
            q = q.filter(Prediction.model_used == model_used)
        if campaign:
            q = q.filter(Prediction.campaign == campaign)

        total = q.count()
        items = (
            q.order_by(Prediction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return ResultListResponse(total=total, items=items)
    finally:
        db.close()


@router.get("/stats", response_model=StatsResponse)
def get_stats() -> StatsResponse:
    """Zwraca zagregowane statystyki wszystkich predykcji."""
    db = SessionLocal()
    try:
        total = db.query(Prediction).count()
        phishing = db.query(Prediction).filter(Prediction.label == "phishing").count()
        legit = db.query(Prediction).filter(Prediction.label == "legit").count()
        ml_count = db.query(Prediction).filter(Prediction.model_used == "ml").count()
        heuristic_count = db.query(Prediction).filter(Prediction.model_used == "heuristic").count()

        campaigns_raw = (
            db.query(Prediction.campaign)
            .filter(Prediction.campaign.isnot(None))
            .distinct()
            .all()
        )
        campaigns = sorted({row[0] for row in campaigns_raw})

        return StatsResponse(
            total_predictions=total,
            phishing_count=phishing,
            legit_count=legit,
            phishing_ratio=round(phishing / max(total, 1), 4),
            ml_predictions=ml_count,
            heuristic_predictions=heuristic_count,
            campaigns=campaigns,
        )
    finally:
        db.close()


@router.get("/campaign/{name}", response_model=ResultListResponse)
def results_by_campaign(
    name: str,
    limit: int = Query(default=200, ge=1, le=500),
) -> ResultListResponse:
    """Zwraca wszystkie predykcje dla podanej kampanii."""
    db = SessionLocal()
    try:
        q = db.query(Prediction).filter(Prediction.campaign == name)
        total = q.count()
        items = q.order_by(Prediction.created_at.desc()).limit(limit).all()
        return ResultListResponse(total=total, items=items)
    finally:
        db.close()


@router.get("/{result_id}", response_model=ResultItem)
def get_result(result_id: int) -> ResultItem:
    """Zwraca szczegóły pojedynczej predykcji."""
    db = SessionLocal()
    try:
        row = db.query(Prediction).filter(Prediction.id == result_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Predykcja {result_id} nie istnieje.")
        return row
    finally:
        db.close()
