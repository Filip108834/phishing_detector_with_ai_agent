"""
Ładowanie zbiorów danych do trenowania klasyfikatora.

Obsługiwane źródła:
  - SpamAssassin Public Corpus (data/datasets/spamassassin/)
  - Kampanie Gophish/MailHog    (data/raw/*/  z metadata.json)
  - Enron email dataset         (data/datasets/enron/emails.csv)

Zwracany DataFrame ma zawsze kolumny:
    raw_eml  : str   - surowa treść MIME (lub syntetyczna dla API-input)
    label    : int   - 0 = legit, 1 = phishing/spam
    source   : str   - identyfikator zbioru danych
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Katalogi domyślne (względem CWD projektu)
SPAMASSASSIN_DIR = Path("data/datasets/spamassassin")
CAMPAIGNS_DIR = Path("data/raw")
ENRON_CSV = Path("data/datasets/enron/emails.csv")

# Mapowanie podkatalogów SpamAssassin → etykieta
_SA_LABEL_MAP: dict[str, int] = {
    "easy_ham":   0,
    "easy_ham_2": 0,
    "hard_ham":   0,
    "spam":       1,
    "spam_2":     1,
}


# ---------------------------------------------------------------------------
# Publiczne funkcje ładowania
# ---------------------------------------------------------------------------

def load_spamassassin(base_dir: Path = SPAMASSASSIN_DIR, max_per_class: int | None = None) -> pd.DataFrame:
    """
    Wczytuje SpamAssassin Public Corpus.

    Args:
        base_dir:       ścieżka do katalogu ze zbiorami SA
        max_per_class:  opcjonalne ograniczenie liczby przykładów na klasę
    """
    if not base_dir.exists():
        logger.warning("SpamAssassin dir not found: %s", base_dir)
        return _empty_df()

    records: list[dict] = []
    class_counts: dict[int, int] = {0: 0, 1: 0}

    for subset_name, label in _SA_LABEL_MAP.items():
        subset_dir = base_dir / subset_name
        if not subset_dir.exists():
            continue

        files = sorted(subset_dir.iterdir())
        for path in tqdm(files, desc=f"SpamAssassin/{subset_name}", unit="msg", leave=False):
            if not path.is_file():
                continue
            if max_per_class and class_counts[label] >= max_per_class:
                break
            raw = _safe_read(path)
            if raw:
                records.append({"raw_eml": raw, "label": label, "source": f"spamassassin/{subset_name}"})
                class_counts[label] += 1

    df = pd.DataFrame(records)
    logger.info("SpamAssassin: %d legit, %d spam/phishing", class_counts[0], class_counts[1])
    return df


def load_campaigns(base_dir: Path = CAMPAIGNS_DIR) -> pd.DataFrame:
    """
    Wczytuje e-maile z lokalnych kampanii Gophish/MailHog.
    Etykieta pochodzi z pliku metadata.json w katalogu kampanii.
    """
    if not base_dir.exists():
        return _empty_df()

    records: list[dict] = []

    for campaign_dir in sorted(base_dir.iterdir()):
        if not campaign_dir.is_dir():
            continue

        meta_path = campaign_dir / "metadata.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Błąd odczytu %s: %s", meta_path, e)
            continue

        raw_label = meta.get("label", "unknown").lower()
        label = 1 if raw_label == "phishing" else 0
        source = f"campaign/{campaign_dir.name}"

        for eml_path in sorted(campaign_dir.glob("*.eml")):
            raw = _safe_read(eml_path)
            if raw:
                records.append({"raw_eml": raw, "label": label, "source": source})

    df = pd.DataFrame(records)
    if not df.empty:
        logger.info("Kampanie: %d legit, %d phishing",
                    (df["label"] == 0).sum(), (df["label"] == 1).sum())
    return df


def load_enron(csv_path: Path = ENRON_CSV, max_rows: int = 20_000) -> pd.DataFrame:
    """
    Wczytuje Enron dataset (emails.csv z Kaggle).
    Enron zawiera wyłącznie legit e-maile (etykieta = 0).

    Kolumny CSV: file, message
    """
    if not csv_path.exists():
        logger.info("Enron CSV nie znaleziony (%s) - pomijam.", csv_path)
        return _empty_df()

    df_raw = pd.read_csv(
        csv_path,
        usecols=["message"],
        nrows=max_rows,
        on_bad_lines="skip",
    )
    df_raw = df_raw.dropna(subset=["message"])
    df = pd.DataFrame({
        "raw_eml": df_raw["message"].astype(str),
        "label": 0,
        "source": "enron",
    })
    logger.info("Enron: %d wiadomości (wszystkie legit)", len(df))
    return df


def load_all(
    include_spamassassin: bool = True,
    include_campaigns: bool = True,
    include_enron: bool = True,
    max_per_class: int | None = None,
) -> pd.DataFrame:
    """
    Ładuje i łączy wszystkie dostępne datasety.
    Przetasowuje wiersze i resetuje indeks.
    """
    parts: list[pd.DataFrame] = []

    if include_spamassassin:
        parts.append(load_spamassassin(max_per_class=max_per_class))

    if include_campaigns:
        parts.append(load_campaigns())

    if include_enron:
        parts.append(load_enron())

    if not parts:
        return _empty_df()

    df = pd.concat(parts, ignore_index=True)
    df = df.dropna(subset=["raw_eml", "label"])
    df = df[df["raw_eml"].str.strip().astype(bool)]   # usuń puste
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    logger.info(
        "Łącznie: %d wiadomości | legit=%d (%.1f%%) | phishing/spam=%d (%.1f%%)",
        len(df),
        (df["label"] == 0).sum(), (df["label"] == 0).mean() * 100,
        (df["label"] == 1).sum(), (df["label"] == 1).mean() * 100,
    )
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_read(path: Path) -> str:
    """Wczytuje plik z obsługą różnych kodowań."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, PermissionError):
            continue
    return ""


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["raw_eml", "label", "source"])
