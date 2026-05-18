"""
Modele Pydantic używane przez endpointy API.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


### Predykcja

class PredictRequest(BaseModel):
    sender: Optional[str] = Field(default=None, description="Adres nadawcy (From)")
    subject: Optional[str] = Field(default=None, description="Temat wiadomości")
    body: str = Field(..., description="Treść wiadomości (plain text lub HTML)")
    urls: Optional[List[str]] = Field(default=None, description="Linki z treści")
    headers: Optional[Dict[str, Any]] = Field(default=None, description="Nagłówki MIME")


class PredictRawRequest(BaseModel):
    raw_eml: str = Field(..., description="Pełna wiadomość MIME (zawartość .eml)")


class PredictResponse(BaseModel):
    label: str
    score: float
    reasons: List[str]
    model_used: str
    saved_id: int


### Wyniki / historia

class ResultItem(BaseModel):
    id: int
    created_at: datetime
    sender: Optional[str]
    subject: Optional[str]
    score: float
    label: str
    model_used: str
    campaign: Optional[str]

    class Config:
        from_attributes = True


class ResultListResponse(BaseModel):
    total: int
    items: List[ResultItem]


class StatsResponse(BaseModel):
    total_predictions: int
    phishing_count: int
    legit_count: int
    phishing_ratio: float
    ml_predictions: int
    heuristic_predictions: int
    campaigns: List[str]


### Ingestion

class IngestMailhogResponse(BaseModel):
    fetched: int
    classified: int
    phishing: int
    legit: int
    errors: int


class IngestCampaignResponse(BaseModel):
    campaign: str
    classified: int
    phishing: int
    legit: int
    errors: int
    # Jeśli dostępna etykieta z metadata.json - zwraca metryki
    accuracy: Optional[float] = None
    ground_truth_available: bool = False


### Informacja o modelu

class ModelInfoResponse(BaseModel):
    model_type: str
    model_path: Optional[str]
    is_ml_active: bool
    feature_count: Optional[int] = None
