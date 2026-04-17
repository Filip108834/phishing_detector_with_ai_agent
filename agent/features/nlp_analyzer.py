"""
Analiza NLP tekstu e-maila przy użyciu spaCy.

Cechy wyciągane z modelu en_core_web_sm:
  NER  - liczba encji typów ORG, MONEY, DATE, CARDINAL
  POS  - gęstość czasowników i rzeczowników, liczba czasowników rozkazujących
  Zdania - liczba zdań, średnia długość zdania, stosunek zdań z wykrzyknikiem
  Leksykalne - unikalność tokenów (TTR), współczynnik słów funkcyjnych

Moduł ładuje model spaCy leniwie (raz, przy pierwszym wywołaniu).
Jeśli model jest niedostępny, zwraca wektor zerowy - cały pipeline ML
działa nadal poprawnie, tylko bez tych cech.

Instalacja modelu:
    python -m spacy download en_core_web_sm
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy loading modelu spaCy
# ---------------------------------------------------------------------------

_nlp = None          # globalny singleton modelu
_spacy_ok = False    # czy model udało się załadować


def _get_nlp():
    """Ładuje model spaCy przy pierwszym wywołaniu; cache'uje wynik."""
    global _nlp, _spacy_ok
    # Zwróć wynik z cache jeśli już próbowaliśmy załadować model
    # (niezależnie od tego czy się udało, czy nie).
    # Poprzednia wersja: `_nlp is not None or _spacy_ok is False and _nlp is None`
    # - przez pierwszeństwo `and` > `or` warunek był True przy pierwszym wywołaniu
    # (_spacy_ok=False, _nlp=None), więc model nigdy nie był ładowany.
    if _nlp is not None or _spacy_ok is False:
        return _nlp

    try:
        import spacy
        _nlp = spacy.load(
            "en_core_web_sm",
            # Wyłączamy parser zależności - używamy lekkiego sentence segmentera
            # Zostawiamy: tok2vec, tagger, senter, ner, attribute_ruler, lemmatizer
            exclude=["parser"],
        )
        # Dodaj sentencizer jako alternatywę dla parsera
        if "senter" not in _nlp.pipe_names:
            _nlp.add_pipe("sentencizer")
        _spacy_ok = True
        logger.info("spaCy 'en_core_web_sm' załadowany. Pipes: %s", _nlp.pipe_names)
    except OSError:
        logger.warning(
            "Model spaCy 'en_core_web_sm' nie jest zainstalowany. "
            "Uruchom: python -m spacy download en_core_web_sm"
        )
        _spacy_ok = False
    except ImportError:
        logger.warning("spaCy nie jest zainstalowany. Uruchom: pip install spacy")
        _spacy_ok = False

    return _nlp


# ---------------------------------------------------------------------------
# Nazwy kolumn NLP (prefix feat_nlp_)
# ---------------------------------------------------------------------------

NLP_FEATURE_COLS: list[str] = [
    "feat_nlp_ner_org_count",
    "feat_nlp_ner_money_count",
    "feat_nlp_ner_date_count",
    "feat_nlp_ner_cardinal_count",
    "feat_nlp_imperative_count",
    "feat_nlp_sentence_count",
    "feat_nlp_avg_sentence_len",
    "feat_nlp_exclaim_sentence_ratio",
    "feat_nlp_unique_token_ratio",
    "feat_nlp_verb_density",
    "feat_nlp_noun_density",
    "feat_nlp_function_word_ratio",
]


def analyze_text(text: str, max_chars: int = 8_000) -> dict[str, float]:
    """
    Wyciąga cechy NLP z podanego tekstu.

    Args:
        text:      surowy tekst (subject + body)
        max_chars: limit znaków przekazywanych do spaCy (wydajność)

    Returns:
        Słownik z kluczami z NLP_FEATURE_COLS; wartości = 0.0 gdy brak modelu.
    """
    nlp = _get_nlp()
    if nlp is None:
        return _zero_features()

    # Ogranicz długość tekstu
    text = text[:max_chars].strip()
    if not text:
        return _zero_features()

    doc = nlp(text)
    return _extract_from_doc(doc)


def analyze_texts_batch(texts: list[str], max_chars: int = 8_000) -> list[dict[str, float]]:
    """
    Wersja wsadowa - wydajniejsza przy trenowaniu na dużym zbiorze.
    Używa nlp.pipe() dla lepszej wydajności.
    """
    nlp = _get_nlp()
    if nlp is None:
        return [_zero_features() for _ in texts]

    truncated = [t[:max_chars].strip() for t in texts]
    return [_extract_from_doc(doc) for doc in nlp.pipe(truncated, batch_size=64)]


# ---------------------------------------------------------------------------
# Ekstrakcja cech z doc spaCy
# ---------------------------------------------------------------------------

# Typy POS uznawane za słowa funkcyjne (spójniki, przyimki, zaimki, partykuły)
_FUNCTION_POS = frozenset(["ADP", "AUX", "CCONJ", "DET", "PART", "PRON", "SCONJ"])

# Czasowniki mogące być rozkazem (POS=VERB, dep=ROOT, lemma w słowniku).
# Lista dwujęzyczna: en_core_web_sm lematyzuje angielskie lematy poprawnie;
# polskie formy rozkazujące (bez fleksji) trafiają tu jako fallback gdy
# sentencizer przekaże je jako ROOT - spaCy nie lematyzuje PL idealnie,
# ale wykrywa podstawowe formy czasownikowe.
_IMPERATIVE_LEMMAS = frozenset([
    # --- Angielskie ---
    "click", "verify", "confirm", "update", "login", "sign", "enter",
    "provide", "send", "call", "contact", "access", "download", "open",
    "submit", "fill", "check", "visit", "review",
    # --- Polskie ---
    "kliknij", "zweryfikuj", "potwierdź", "zaktualizuj", "zaloguj",
    "podaj", "wyślij", "zadzwoń", "skontaktuj", "pobierz", "otwórz",
    "wypełnij", "sprawdź", "odwiedź", "przejdź", "wprowadź", "zapłać",
    "opłać", "wpisz", "aktywuj", "odblokuj", "zarejestruj",
])


def _extract_from_doc(doc) -> dict[str, float]:
    tokens = [t for t in doc if not t.is_space]
    n_tokens = max(len(tokens), 1)

    # --- NER ---
    ner_org      = sum(1 for e in doc.ents if e.label_ == "ORG")
    ner_money    = sum(1 for e in doc.ents if e.label_ == "MONEY")
    ner_date     = sum(1 for e in doc.ents if e.label_ == "DATE")
    ner_cardinal = sum(1 for e in doc.ents if e.label_ == "CARDINAL")

    # --- POS ---
    pos_counts: dict[str, int] = {}
    for t in tokens:
        pos_counts[t.pos_] = pos_counts.get(t.pos_, 0) + 1

    verb_count  = pos_counts.get("VERB", 0) + pos_counts.get("AUX", 0)
    noun_count  = pos_counts.get("NOUN", 0) + pos_counts.get("PROPN", 0)
    func_count  = sum(pos_counts.get(p, 0) for p in _FUNCTION_POS)

    # Zlicz czasowniki rozkazujące (ROOT VERB z lematem w słowniku)
    imperative_count = sum(
        1 for t in tokens
        if t.pos_ == "VERB"
        and t.dep_ == "ROOT"
        and t.lemma_.lower() in _IMPERATIVE_LEMMAS
    )

    # --- Zdania ---
    sentences = list(doc.sents)
    n_sents = max(len(sentences), 1)

    sent_lengths = [len([t for t in s if not t.is_space]) for s in sentences]
    avg_sent_len = sum(sent_lengths) / n_sents

    exclaim_sents = sum(1 for s in sentences if s.text.rstrip().endswith("!"))
    exclaim_ratio = exclaim_sents / n_sents

    # --- Leksykalne ---
    lemmas = [t.lemma_.lower() for t in tokens if t.is_alpha]
    unique_ratio = len(set(lemmas)) / max(len(lemmas), 1)

    return {
        "feat_nlp_ner_org_count":          float(ner_org),
        "feat_nlp_ner_money_count":         float(ner_money),
        "feat_nlp_ner_date_count":          float(ner_date),
        "feat_nlp_ner_cardinal_count":      float(ner_cardinal),
        "feat_nlp_imperative_count":        float(imperative_count),
        "feat_nlp_sentence_count":          float(n_sents),
        "feat_nlp_avg_sentence_len":        float(avg_sent_len),
        "feat_nlp_exclaim_sentence_ratio":  float(exclaim_ratio),
        "feat_nlp_unique_token_ratio":      float(unique_ratio),
        "feat_nlp_verb_density":            float(verb_count / n_tokens),
        "feat_nlp_noun_density":            float(noun_count / n_tokens),
        "feat_nlp_function_word_ratio":     float(func_count / n_tokens),
    }


def _zero_features() -> dict[str, float]:
    return {col: 0.0 for col in NLP_FEATURE_COLS}
