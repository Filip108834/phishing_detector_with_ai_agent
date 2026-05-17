"""
Definicja pipeline'u ML oraz funkcje trenowania, ewaluacji i persystencji modelu.

Architektura pipeline'u:
    raw_eml (str)
        ↓  EmailParser + FeatureExtractor (+ spaCy NLP)
    DataFrame { "text": str, "feat_*": float, ... }
        ↓  ColumnTransformer
    [NLTKPreprocessor -> TF-IDF(text) | StandardScaler(feat_*)]  ->  sparse+dense concat
        ↓  Classifier
    label: 0/1  +  proba: float

Dostępne warianty klasyfikatora (argument `model_name`):
    "lr"        - Logistic Regression (szybki baseline)
    "rf"        - Random Forest
    "gb"        - Gradient Boosting
    "ensemble"  - VotingClassifier(lr + rf + gb, soft voting)  [domyślny]
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    VotingClassifier,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from agent.features.extractor import NUMERICAL_FEATURE_COLS, extract
from agent.features.text_preprocessor import NLTKTextPreprocessor
from agent.ingestion.email_parser import ParsedEmail

logger = logging.getLogger(__name__)

# Ścieżka domyślna dla zapisywanego modelu
DEFAULT_MODEL_PATH = Path("models/classifier.joblib")


# ---------------------------------------------------------------------------
# Budowanie pipeline'u
# ---------------------------------------------------------------------------

def build_pipeline(model_name: str = "ensemble") -> Pipeline:
    """
    Zwraca niewnytrenowany sklearn Pipeline.

    Args:
        model_name: "lr" | "rf" | "gb" | "ensemble"
    """
    # Gałąź tekstowa: NLTK preprocessing -> TF-IDF (unigrams + bigrams).
    # language=None wyłącza stemmer angielski, który zniekształcałby polskie tokeny.
    # strip_accents usunięto - polskie znaki diakrytyczne (ą, ę, ó…) są cechami
    # semantycznymi i nie powinny być sprowadzane do ich ASCII-odpowiedników.
    text_pipeline = Pipeline([
        ("nltk_prep", NLTKTextPreprocessor(language=None)),
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=8_000,
            sublinear_tf=True,
            min_df=2,
            analyzer="word",
        )),
    ])

    preprocessor = ColumnTransformer(
        transformers=[
            ("text", text_pipeline, "text"),
            ("num",  StandardScaler(), NUMERICAL_FEATURE_COLS),
        ],
        remainder="drop",
        # sparse_threshold=0: zawsze gęsta macierz wyjściowa.
        # HistGradientBoostingClassifier nie akceptuje macierzy rzadkich
        # (scipy.sparse), więc wymuszamy dense aby pipeline działał dla
        # wszystkich wariantów klasyfikatora (lr, rf, gb, ensemble).
        sparse_threshold=0.0,
    )

    classifier = _build_classifier(model_name)

    return Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", classifier),
    ])


def _build_classifier(model_name: str) -> Any:
    lr = LogisticRegression(
        C=1.0,
        max_iter=1_000,
        class_weight="balanced",
        solver="lbfgs",
        random_state=42,
    )
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=20,
        class_weight="balanced",
        n_jobs=-1,
        random_state=42,
    )
    # HistGradientBoostingClassifier zastępuje GradientBoostingClassifier:
    # - obsługuje class_weight="balanced" (GBC nie ma tego parametru)
    # - znacząco szybszy na dużych zbiorach (histogram-based binning)
    gb = HistGradientBoostingClassifier(
        max_iter=150,
        max_depth=5,
        learning_rate=0.1,
        class_weight="balanced",
        random_state=42,
    )

    if model_name == "lr":
        return lr
    if model_name == "rf":
        return rf
    if model_name == "gb":
        return gb
    if model_name == "ensemble":
        return VotingClassifier(
            estimators=[("lr", lr), ("rf", rf), ("gb", gb)],
            voting="soft",
            n_jobs=-1,
        )
    raise ValueError(f"Nieznany model: '{model_name}'. Dostępne: lr, rf, gb, ensemble")


# ---------------------------------------------------------------------------
# Trenowanie
# ---------------------------------------------------------------------------

def train(
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    y_train: pd.Series,
) -> Pipeline:
    """Trenuje pipeline i zwraca go (in-place)."""
    logger.info("Trenowanie na %d próbkach …", len(X_train))
    pipeline.fit(X_train, y_train)
    logger.info("Trenowanie zakończone.")
    return pipeline


def cross_validate_pipeline(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
) -> dict[str, float]:
    """
    Walidacja krzyżowa (stratified k-fold).
    Zwraca słownik ze średnimi metrykami.
    """
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    scoring = ["accuracy", "precision_weighted", "recall_weighted", "f1_weighted", "roc_auc"]

    logger.info("Cross-validation (%d-fold) …", n_splits)
    cv_results = cross_validate(pipeline, X, y, cv=cv, scoring=scoring, n_jobs=-1)

    summary = {
        metric: float(np.mean(cv_results[f"test_{metric}"]))
        for metric in scoring
    }
    for metric, val in summary.items():
        logger.info("  CV %s: %.4f", metric, val)

    return summary


# ---------------------------------------------------------------------------
# Ewaluacja
# ---------------------------------------------------------------------------

def evaluate(
    pipeline: Pipeline,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> dict[str, Any]:
    """
    Ewaluuje wytrenowany pipeline na zbiorze testowym.
    Zwraca słownik z wszystkimi metrykami.
    """
    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy":         float(accuracy_score(y_test, y_pred)),
        "precision":        float(precision_score(y_test, y_pred, zero_division=0)),
        "recall":           float(recall_score(y_test, y_pred, zero_division=0)),
        "f1":               float(f1_score(y_test, y_pred, zero_division=0)),
        "roc_auc":          float(roc_auc_score(y_test, y_proba)),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "classification_report": classification_report(
            y_test, y_pred, target_names=["legit", "phishing"], zero_division=0
        ),
    }

    logger.info("Ewaluacja: acc=%.4f  prec=%.4f  rec=%.4f  f1=%.4f  auc=%.4f",
                metrics["accuracy"], metrics["precision"],
                metrics["recall"], metrics["f1"], metrics["roc_auc"])
    return metrics


# ---------------------------------------------------------------------------
# Predykcja pojedynczego e-maila
# ---------------------------------------------------------------------------

def predict_email(pipeline: Pipeline, parsed: ParsedEmail) -> tuple[str, float, list[str]]:
    """
    Klasyfikuje ParsedEmail za pomocą wytrenowanego pipeline'u.

    Returns:
        (label, score, reasons)
        label:   "phishing" | "legit"
        score:   prawdopodobieństwo phishingu (0..1)
        reasons: lista opisowych powodów (z cech numerycznych)
    """
    feats = extract(parsed)
    df = pd.DataFrame([feats])

    proba = pipeline.predict_proba(df)[0]
    score = float(proba[1])
    threshold = float(os.getenv("PHISHING_THRESHOLD", "0.5"))
    label = "phishing" if score >= threshold else "legit"

    reasons = _explain(feats, score)
    return label, score, reasons


def _explain(feats: dict, score: float) -> list[str]:
    """Generuje czytelne powody na podstawie wartości cech."""
    reasons: list[str] = []

    if feats.get("feat_has_ip_url"):
        reasons.append("URL z adresem IP zamiast domeny.")
    if feats.get("feat_has_suspicious_tld"):
        reasons.append("Podejrzane TLD w URL (.xyz, .tk, .click itp.).")
    if feats.get("feat_has_url_keyword"):
        reasons.append("URL zawiera słowa kluczowe phishingu (login, verify, account…).")
    if feats.get("feat_from_reply_to_mismatch"):
        reasons.append("Niezgodność domeny From i Reply-To.")
    if feats.get("feat_spf_fail"):
        reasons.append("SPF fail/softfail - wiadomość mogła zostać sfałszowana.")
    urgency = feats.get("feat_subject_urgency_score", 0)
    if urgency >= 2:
        reasons.append(f"Temat zawiera {int(urgency)} słów wskazujących pilność/presję.")
    if feats.get("feat_subject_exclamation", 0) >= 2:
        reasons.append("Wiele wykrzykników w temacie.")
    if feats.get("feat_caps_ratio", 0) > 0.3:
        reasons.append("Wysoki udział wielkich liter w treści.")
    if feats.get("feat_has_redirect_param"):
        reasons.append("URL zawiera parametr przekierowania.")
    if feats.get("feat_has_at_in_url"):
        reasons.append("URL zawiera znak @ (technika maskowania domeny).")

    if not reasons:
        threshold = float(os.getenv("PHISHING_THRESHOLD", "0.5"))
        if score >= threshold:
            reasons.append("Model ML zaklasyfikował jako phishing (sygnały tekstowe).")
        else:
            reasons.append("Brak wyraźnych sygnałów phishingu.")

    return reasons


# ---------------------------------------------------------------------------
# Persystencja
# ---------------------------------------------------------------------------

def save(pipeline: Pipeline, path: Path = DEFAULT_MODEL_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, path)
    logger.info("Model zapisany -> %s", path)


def load(path: Path = DEFAULT_MODEL_PATH) -> Pipeline | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        model = joblib.load(path)
        logger.info("Model wczytany ← %s", path)
        return model
    except Exception as e:
        logger.error("Błąd wczytania modelu %s: %s", path, e)
        return None
