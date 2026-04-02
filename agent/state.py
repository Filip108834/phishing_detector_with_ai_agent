"""
Współdzielony stan aplikacji (singleton).

Przechowuje załadowany model ML i referencję do pollera MailHog.
Importowany przez moduły API i ingestion bez ryzyka circular imports,
ponieważ nie importuje nic z pozostałych modułów agenta.
"""
from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Stan modelu ML
# ---------------------------------------------------------------------------

model: dict[str, Any] = {
    "pipeline": None,    # sklearn Pipeline lub None
    "type":     "heuristic",   # "ml" | "heuristic"
    "path":     None,          # str – ścieżka do pliku .joblib
}


def is_ml_active() -> bool:
    return model["pipeline"] is not None


# ---------------------------------------------------------------------------
# Referencja do MailHog pollera (ustawiana w lifespan)
# ---------------------------------------------------------------------------

poller: Optional[Any] = None   # MailHogPoller instance
