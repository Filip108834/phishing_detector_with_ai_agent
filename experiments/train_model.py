"""
Skrypt trenowania i ewaluacji klasyfikatora phishingu.

Uruchomienie:
    python -m experiments.train_model [opcje]

Przykłady:
    # Trenuj ensemble na wszystkich dostępnych danych
    python -m experiments.train_model

    # Trenuj tylko Logistic Regression, bez Enrona
    python -m experiments.train_model --model lr --no-enron

    # Porównaj wszystkie modele (bez zapisywania)
    python -m experiments.train_model --compare

    # Ogranicz liczebność klas (szybki test)
    python -m experiments.train_model --max-per-class 500
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

# Upewnij się że projekt jest w sys.path przy uruchomieniu jako skrypt
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.features.extractor import extract
from agent.ingestion.dataset_loader import load_all
from agent.ingestion.email_parser import ParsedEmail
from agent.ml import pipeline as ml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

RESULTS_DIR = Path("experiments/results")
MODEL_PATH = Path("models/classifier.joblib")


# ---------------------------------------------------------------------------
# Pipeline danych: raw_eml -> DataFrame cech
# ---------------------------------------------------------------------------

def build_feature_matrix(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Parsuje e-maile i wyciąga cechy.

    Args:
        df_raw: DataFrame z kolumnami [raw_eml, label]

    Returns:
        X: DataFrame cech (text + feat_*)
        y: Series etykiet (0/1)
    """
    logger.info("Parsowanie %d e-maili i ekstrakcja cech …", len(df_raw))

    rows: list[dict] = []
    errors = 0

    for _, row in df_raw.iterrows():
        try:
            parsed = ParsedEmail.from_string(row["raw_eml"])
            feats = extract(parsed)
            rows.append(feats)
        except Exception as e:
            logger.debug("Błąd parsowania: %s", e)
            errors += 1
            # Fallback: puste cechy
            rows.append({"text": str(row["raw_eml"])[:500]})

    if errors:
        logger.warning("Nie udało się sparsować %d/%d wiadomości.", errors, len(df_raw))

    X = pd.DataFrame(rows)
    # pd.concat różnych źródeł może zmieniać dtype kolumny label na object/float.
    # Wymuszone rzutowanie na int zapobiega błędowi sklearn "Unknown label type: unknown".
    y = df_raw["label"].reset_index(drop=True).astype(int)

    # Wypełnij brakujące wartości numeryczne zerem (dla wiadomości które się nie sparsowały)
    num_cols = [c for c in X.columns if c.startswith("feat_")]
    X[num_cols] = X[num_cols].fillna(0.0)
    X["text"] = X["text"].fillna("").astype(str)

    logger.info("Macierz cech: %d próbek × %d kolumn", *X.shape)
    logger.info("Rozkład klas: legit=%d (%.1f%%)  phishing=%d (%.1f%%)",
                (y == 0).sum(), (y == 0).mean() * 100,
                (y == 1).sum(), (y == 1).mean() * 100)
    return X, y


# ---------------------------------------------------------------------------
# Trenowanie jednego modelu
# ---------------------------------------------------------------------------

def run_training(
    model_name: str = "ensemble",
    include_enron: bool = True,
    max_per_class: int | None = None,
    cv: bool = True,
    save_model: bool = True,
) -> dict:
    """Pełny cykl: ładowanie danych -> cechy -> train/test split -> trening -> ewaluacja."""

    # 1. Dane
    df_raw = load_all(
        include_enron=include_enron,
        max_per_class=max_per_class,
    )
    if df_raw.empty:
        logger.error("Brak danych! Uruchom najpierw: python scripts/fetch_datasets.py")
        sys.exit(1)

    # 2. Cechy
    X, y = build_feature_matrix(df_raw)

    # 3. Podział train/test (stratified)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    logger.info("Train: %d  |  Test: %d", len(X_train), len(X_test))

    # 4. Buduj i trenuj pipeline
    pipe = ml.build_pipeline(model_name)
    ml.train(pipe, X_train, y_train)

    # 5. Opcjonalna walidacja krzyżowa (na całym zbiorze, bez testu)
    cv_metrics: dict = {}
    if cv:
        # Użyj podzbioru dla CV (max 5000 próbek) żeby nie trwało wiecznie
        n_cv = min(len(X), 5_000)
        cv_metrics = ml.cross_validate_pipeline(pipe, X.iloc[:n_cv], y.iloc[:n_cv])

    # 6. Ewaluacja na test set
    test_metrics = ml.evaluate(pipe, X_test, y_test)

    # 7. Wydruk raportu
    _print_report(model_name, test_metrics, cv_metrics)

    # 8. Zapis modelu
    if save_model:
        ml.save(pipe, MODEL_PATH)

    # 9. Zapis wyników do pliku JSON
    result = {
        "model": model_name,
        "trained_at": datetime.utcnow().isoformat(),
        "dataset_size": len(df_raw),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "test_metrics": {k: v for k, v in test_metrics.items()
                         if k not in ("confusion_matrix", "classification_report")},
        "cv_metrics": cv_metrics,
    }
    _save_results(result, model_name)

    return result


# ---------------------------------------------------------------------------
# Porównanie modeli
# ---------------------------------------------------------------------------

def run_comparison(max_per_class: int | None = 1_000) -> None:
    """Trenuje i porównuje wszystkie warianty klasyfikatora."""
    df_raw = load_all(max_per_class=max_per_class)
    if df_raw.empty:
        logger.error("Brak danych!")
        sys.exit(1)

    X, y = build_feature_matrix(df_raw)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    summary_rows: list[dict] = []

    for model_name in ("lr", "rf", "gb", "ensemble"):
        logger.info("\n%s  Trenuję: %s  %s", "=" * 20, model_name, "=" * 20)
        pipe = ml.build_pipeline(model_name)
        ml.train(pipe, X_train, y_train)
        m = ml.evaluate(pipe, X_test, y_test)
        summary_rows.append({
            "model":     model_name,
            "accuracy":  m["accuracy"],
            "precision": m["precision"],
            "recall":    m["recall"],
            "f1":        m["f1"],
            "roc_auc":   m["roc_auc"],
        })

    df_summary = pd.DataFrame(summary_rows).set_index("model")
    print("\n" + "=" * 60)
    print("PORÓWNANIE MODELI")
    print("=" * 60)
    print(df_summary.to_string(float_format="{:.4f}".format))
    print("=" * 60)

    best = df_summary["f1"].idxmax()
    print(f"\nNajlepszy model (F1): {best}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_report(model_name: str, test_metrics: dict, cv_metrics: dict) -> None:
    print("\n" + "=" * 60)
    print(f"MODEL: {model_name.upper()}")
    print("=" * 60)
    print("\n[Test set]")
    for k in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        print(f"  {k:<12} {test_metrics[k]:.4f}")
    print()
    print(test_metrics["classification_report"])
    if cv_metrics:
        print("[Cross-validation (5-fold)]")
        for k, v in cv_metrics.items():
            print(f"  {k:<25} {v:.4f}")
    print("=" * 60)


def _save_results(result: dict, model_name: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"{model_name}_{ts}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wyniki zapisane -> %s", path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trenowanie klasyfikatora phishingu")
    parser.add_argument(
        "--model",
        choices=["lr", "rf", "gb", "ensemble"],
        default="ensemble",
        help="Wariant klasyfikatora (domyślnie: ensemble)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Porównaj wszystkie modele zamiast trenować jeden",
    )
    parser.add_argument(
        "--no-enron",
        action="store_true",
        help="Wyklucz dataset Enron",
    )
    parser.add_argument(
        "--no-cv",
        action="store_true",
        help="Pomiń walidację krzyżową (szybszy tryb)",
    )
    parser.add_argument(
        "--max-per-class",
        type=int,
        default=None,
        metavar="N",
        help="Ogranicz liczbę próbek na klasę (przydatne do szybkich testów)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Nie zapisuj wytrenowanego modelu",
    )
    args = parser.parse_args()

    if args.compare:
        run_comparison(max_per_class=args.max_per_class or 1_000)
    else:
        run_training(
            model_name=args.model,
            include_enron=not args.no_enron,
            max_per_class=args.max_per_class,
            cv=not args.no_cv,
            save_model=not args.no_save,
        )
