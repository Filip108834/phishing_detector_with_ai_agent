"""
Ekstrakcja wektora cech z ParsedEmail.

Zwraca słownik cech gotowy do wrzucenia w pandas DataFrame:
    {
      "text":   str,    # temat + treść (wejście do TF-IDF)
      "feat_*": float,  # cechy numeryczne (URL, nagłówki, styl tekstu)
    }

Podział cech:
    Tekstowe  (1 kolumna)  -> TF-IDF wewnątrz sklearn Pipeline
    Numeryczne (N kolumn)  -> StandardScaler wewnątrz ColumnTransformer
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from agent.features.nlp_analyzer import NLP_FEATURE_COLS, analyze_text
from agent.features.url_analyzer import analyze_urls
from agent.ingestion.email_parser import ParsedEmail

# Znane narzędzia do wysyłania phishingu / masowej poczty
# identyfikowane przez nagłówek X-Mailer.
_KNOWN_PHISH_MAILERS = frozenset([
    "gophish", "goPhish", "mass mailer", "phpmailer", "sendblaster",
    "atomic mail sender", "dark mailer", "interspire",
])

# Słowa wskazujące pilność / presję czasową
_URGENCY_WORDS = frozenset([
    "urgent", "immediately", "verify", "confirm", "suspended", "blocked",
    "action required", "account disabled", "click here", "limited time",
    "pilne", "natychmiast", "zablokowane", "weryfikacja", "potwierdź",
    "kliknij", "hasło", "konto", "ważne", "zagrożenie",
])

# Darmowe domeny pocztowe
_FREEMAIL_DOMAINS = frozenset([
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "wp.pl", "onet.pl", "interia.pl", "o2.pl", "aol.com",
])

# Kolumny numeryczne (używane w ColumnTransformer)
# Uwaga: NLP_FEATURE_COLS są zawsze obecne w wektorze (wartość 0.0 gdy spaCy niedostępny)
NUMERICAL_FEATURE_COLS: list[str] = [
    # --- URL ---
    "feat_url_count",
    "feat_has_ip_url",
    "feat_has_suspicious_tld",
    "feat_has_url_keyword",
    "feat_has_at_in_url",
    "feat_has_redirect_param",
    "feat_max_url_length",
    "feat_avg_url_length",
    "feat_max_subdomain_depth",
    "feat_avg_url_entropy",
    "feat_url_domain_diversity",
    # --- Nagłówki ---
    "feat_from_reply_to_mismatch",
    "feat_subject_urgency_score",
    "feat_subject_is_empty",
    "feat_subject_exclamation",
    "feat_from_is_freemail",
    "feat_has_html",
    "feat_has_attachments",
    "feat_spf_fail",
    "feat_received_hops",
    "feat_xmailer_known_phish_tool",
    "feat_has_dkim",
    # --- Stylistyczne ---
    "feat_text_length",
    "feat_exclamation_density",
    "feat_caps_ratio",
    # --- NLP (spaCy) ---
    *NLP_FEATURE_COLS,
]


def extract(parsed: ParsedEmail) -> dict[str, Any]:
    """
    Zwraca płaski słownik z kolumną 'text' i cechami 'feat_*'.
    Można bezpośrednio przekazać do pd.DataFrame([extract(p), ...]).
    """
    features: dict[str, Any] = {}

    # ----------------------------------------------------------------
    # 1. Pole tekstowe dla TF-IDF
    # ----------------------------------------------------------------
    body = parsed.plain_text or parsed.html_text
    features["text"] = f"{parsed.subject} {body}".strip()

    # ----------------------------------------------------------------
    # 2. Cechy URL
    # ----------------------------------------------------------------
    url_feats = analyze_urls(parsed.urls)
    for key, val in url_feats.items():
        features[f"feat_{key}"] = val

    # ----------------------------------------------------------------
    # 3. Cechy nagłówkowe
    # ----------------------------------------------------------------
    from_domain = _extract_domain(parsed.from_addr)
    reply_domain = _extract_domain(parsed.reply_to)

    # Niezgodność From vs Reply-To (klasyczna technika phishingu)
    features["feat_from_reply_to_mismatch"] = float(
        bool(reply_domain) and from_domain != reply_domain
    )

    # Pilność w temacie
    subject_lower = parsed.subject.lower()
    urgency_hits = sum(1 for w in _URGENCY_WORDS if w in subject_lower)
    features["feat_subject_urgency_score"] = float(urgency_hits)
    features["feat_subject_is_empty"] = float(not parsed.subject.strip())
    features["feat_subject_exclamation"] = float(parsed.subject.count("!"))

    # Darmowa skrzynka jako nadawca
    features["feat_from_is_freemail"] = float(from_domain in _FREEMAIL_DOMAINS)

    # Flagi struktury
    features["feat_has_html"] = float(parsed.has_html)
    features["feat_has_attachments"] = float(parsed.has_attachments)

    # SPF fail / brak (0 = pass/neutral/brak info, 1 = fail/softfail)
    features["feat_spf_fail"] = float(parsed.spf_result in ("fail", "softfail"))

    # Liczba przeskoków Received (bardzo duża = podejrzana)
    features["feat_received_hops"] = float(min(parsed.received_hops, 20))

    # X-Mailer: znane narzędzie phishingowe / masowej poczty
    xmailer = parsed.extra_headers.get("x-mailer", "").lower()
    features["feat_xmailer_known_phish_tool"] = float(
        any(tool.lower() in xmailer for tool in _KNOWN_PHISH_MAILERS)
    )

    # DKIM: brak podpisu DKIM to słaby sygnał phishingu
    # Authentication-Results jest parsowany do extra_headers przez email_parser
    auth_results = parsed.extra_headers.get("authentication-results", "").lower()
    dkim_header  = parsed.extra_headers.get("dkim-signature", "").lower()
    features["feat_has_dkim"] = float(
        "dkim=pass" in auth_results or bool(dkim_header)
    )

    # ----------------------------------------------------------------
    # 4. Cechy stylistyczne treści
    # ----------------------------------------------------------------
    full_text = features["text"]
    text_len = max(len(full_text), 1)

    features["feat_text_length"] = float(text_len)
    features["feat_exclamation_density"] = float(full_text.count("!") / text_len)

    # Stosunek wielkich liter (CAPS lock -> presja / alarm)
    upper_count = sum(1 for c in full_text if c.isupper())
    alpha_count = sum(1 for c in full_text if c.isalpha())
    features["feat_caps_ratio"] = float(upper_count / max(alpha_count, 1))

    # ----------------------------------------------------------------
    # 5. Cechy NLP (spaCy) - fallback 0.0 gdy model niedostępny
    # ----------------------------------------------------------------
    nlp_feats = analyze_text(full_text)
    features.update(nlp_feats)

    return features


def extract_batch(parsed_emails: list[ParsedEmail]) -> pd.DataFrame:
    """Wyciąga cechy z listy ParsedEmail i zwraca DataFrame."""
    rows = [extract(p) for p in parsed_emails]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_domain(addr: str) -> str:
    """Wyciąga domenę z adresu e-mail (np. 'phish@evil.com' -> 'evil.com')."""
    if not addr:
        return ""
    match = re.search(r"@([\w.\-]+)", addr)
    return match.group(1).lower() if match else ""
