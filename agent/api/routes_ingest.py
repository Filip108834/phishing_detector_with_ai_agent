"""
Router: masowe pobieranie i klasyfikacja wiadomości.

Endpointy:
    POST /ingest/mailhog              - pobierz wszystkie e-maile z MailHog i sklasyfikuj
    POST /ingest/campaign/{name}      - sklasyfikuj e-maile z lokalnej kampanii (data/raw/)
    DELETE /ingest/mailhog/purge      - wyczyść skrzynkę MailHog
"""
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from agent.api.routes_predict import classify_parsed
from agent.api.schemas import IngestCampaignResponse, IngestMailhogResponse
from agent.ingestion.email_parser import ParsedEmail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

RAW_DATA_DIR = Path("data/raw")


# ---------------------------------------------------------------------------
# MailHog ingestion
# ---------------------------------------------------------------------------

def _mailhog_fetch_all(mailhog_url: str) -> list[dict]:
    """Pobiera wszystkie wiadomości z MailHog i zwraca listę dict {msg_id, raw_mime}."""
    import requests as _req

    base = mailhog_url.rstrip("/")
    messages: list[dict] = []
    start = 0
    while True:
        r = _req.get(f"{base}/api/v2/messages", params={"start": start, "limit": 50}, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        for item in items:
            msg_id = item.get("ID", "")
            headers: dict = item.get("Content", {}).get("Headers", {})
            body: str = item.get("Content", {}).get("Body", "")
            raw_parts: list[str] = []
            for key, vals in headers.items():
                for v in vals:
                    raw_parts.append(f"{key}: {v}")
            raw_parts.append("")
            raw_parts.append(body)
            messages.append({"msg_id": msg_id, "raw_mime": "\r\n".join(raw_parts)})
        if len(items) < 50:
            break
        start += len(items)
    return messages


def _mailhog_delete_all(mailhog_url: str) -> None:
    import requests as _req
    _req.delete(f"{mailhog_url.rstrip('/')}/api/v1/messages", timeout=10).raise_for_status()


@router.post("/mailhog", response_model=IngestMailhogResponse)
def ingest_mailhog(clear_after: bool = False) -> IngestMailhogResponse:
    """
    Pobiera wszystkie wiadomości z MailHog, klasyfikuje je i zapisuje do DB.

    Args:
        clear_after: jeśli True, czyści inbox MailHog po przetworzeniu
    """
    mailhog_url = os.getenv("MAILHOG_API_URL", "http://mailhog:8025")

    try:
        messages = _mailhog_fetch_all(mailhog_url)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Błąd połączenia z MailHog: {e}")

    fetched = len(messages)
    classified = phishing = legit = errors = 0

    for msg in messages:
        try:
            parsed = ParsedEmail.from_string(msg["raw_mime"])
            result = classify_parsed(parsed, campaign="mailhog_ingest")
            classified += 1
            if result["label"] == "phishing":
                phishing += 1
            else:
                legit += 1
        except Exception as e:
            logger.warning("Błąd klasyfikacji wiadomości %s: %s", msg.get("msg_id"), e)
            errors += 1

    if clear_after:
        try:
            _mailhog_delete_all(mailhog_url)
            logger.info("Inbox MailHog wyczyszczony po ingestion.")
        except Exception as e:
            logger.warning("Nie udało się wyczyścić MailHog: %s", e)

    logger.info("Ingest MailHog: pobrano=%d sklasyfikowano=%d phishing=%d legit=%d błędy=%d",
                fetched, classified, phishing, legit, errors)

    return IngestMailhogResponse(
        fetched=fetched,
        classified=classified,
        phishing=phishing,
        legit=legit,
        errors=errors,
    )


@router.delete("/mailhog/purge")
def purge_mailhog() -> dict:
    """Czyści wszystkie wiadomości z inbox MailHog."""
    mailhog_url = os.getenv("MAILHOG_API_URL", "http://mailhog:8025")
    try:
        _mailhog_delete_all(mailhog_url)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Błąd MailHog: {e}")
    return {"status": "ok", "message": "Inbox MailHog wyczyszczony."}


# ---------------------------------------------------------------------------
# Campaign ingestion
# ---------------------------------------------------------------------------

@router.post("/campaign/{campaign_name}", response_model=IngestCampaignResponse)
def ingest_campaign(campaign_name: str) -> IngestCampaignResponse:
    """
    Klasyfikuje wszystkie pliki .eml z lokalnego katalogu kampanii.

    Katalog: data/raw/<campaign_name>/
    Metadane: data/raw/<campaign_name>/metadata.json  (opcjonalnie - ground truth)
    """
    campaign_dir = RAW_DATA_DIR / campaign_name
    if not campaign_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Katalog kampanii nie istnieje: {campaign_dir}",
        )

    eml_files = sorted(campaign_dir.glob("*.eml"))
    if not eml_files:
        raise HTTPException(
            status_code=422,
            detail=f"Brak plików .eml w katalogu: {campaign_dir}",
        )

    # Opcjonalne metadane (ground truth label)
    ground_truth_label: str | None = None
    meta_path = campaign_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ground_truth_label = meta.get("label", "").lower()
        except Exception as e:
            logger.warning("Nie udało się odczytać metadata.json: %s", e)

    classified = phishing = legit = errors = 0
    correct = 0

    for eml_path in eml_files:
        try:
            raw = eml_path.read_text(encoding="utf-8", errors="replace")
            parsed = ParsedEmail.from_string(raw)
            result = classify_parsed(parsed, campaign=campaign_name)
            classified += 1

            if result["label"] == "phishing":
                phishing += 1
            else:
                legit += 1

            # Porównanie z ground truth (jeśli dostępne)
            if ground_truth_label:
                expected = 1 if ground_truth_label == "phishing" else 0
                predicted = 1 if result["label"] == "phishing" else 0
                if expected == predicted:
                    correct += 1

        except Exception as e:
            logger.warning("Błąd przetwarzania %s: %s", eml_path.name, e)
            errors += 1

    accuracy = None
    if ground_truth_label and classified > 0:
        accuracy = round(correct / classified, 4)

    logger.info("Ingest kampanii '%s': %d plików, phishing=%d, legit=%d, acc=%s",
                campaign_name, classified, phishing, legit, accuracy)

    return IngestCampaignResponse(
        campaign=campaign_name,
        classified=classified,
        phishing=phishing,
        legit=legit,
        errors=errors,
        accuracy=accuracy,
        ground_truth_available=ground_truth_label is not None,
    )
