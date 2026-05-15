"""
Preprocessor tekstu oparty na NLTK - kompatybilny ze sklearn.

Wykonuje:
    1. Zamiana na małe litery
    2. Usunięcie znaków niealfanumerycznych
    3. Tokenizacja (NLTK word_tokenize)
    4. Usunięcie stopwords (angielskie + polskie)
    5. Stemming (SnowballStemmer: angielski lub domyślny)

Jako sklearn transformer może być wstawiony bezpośrednio do Pipeline
przed TfidfVectorizer:

    Pipeline([
        ("preprocess", NLTKTextPreprocessor()),
        ("tfidf",      TfidfVectorizer(...)),
    ])

Jeśli NLTK lub wymagane zasoby są niedostępne, transformer zwraca
oryginalny tekst po lowercase (bezpieczny fallback).
"""
from __future__ import annotations

import logging
import re
import string
from typing import Iterable

from sklearn.base import BaseEstimator, TransformerMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Polskie stopwords (NLTK nie ma ich wbudowanych)
# ---------------------------------------------------------------------------

_POLISH_STOPWORDS = frozenset([
    "i", "w", "z", "na", "do", "się", "nie", "to", "że", "a", "jak",
    "o", "ale", "po", "tak", "jest", "co", "ze", "już", "czy", "przez",
    "jego", "jej", "ich", "ten", "ta", "te", "tego", "tej", "tych",
    "być", "mieć", "pan", "pani", "więc", "oraz", "też", "tylko",
    "może", "tu", "go", "mu", "ci", "im", "nas", "was",
    "który", "która", "które", "lecz", "lub",
])

# ---------------------------------------------------------------------------
# Lazy loading zasobów NLTK
# ---------------------------------------------------------------------------

_nltk_ready = False


def _ensure_nltk() -> bool:
    """Pobiera wymagane zasoby NLTK jeśli jeszcze nie ma; zwraca True jeśli OK."""
    global _nltk_ready
    if _nltk_ready:
        return True

    try:
        import nltk
        for resource in ("punkt", "punkt_tab", "stopwords"):
            try:
                nltk.data.find(f"tokenizers/{resource}" if "punkt" in resource
                               else f"corpora/{resource}")
            except LookupError:
                logger.info("Pobieranie zasobu NLTK: %s", resource)
                nltk.download(resource, quiet=True)

        _nltk_ready = True
        return True

    except ImportError:
        logger.warning("NLTK nie jest zainstalowany. Preprocessor używa fallbacku.")
        return False


# ---------------------------------------------------------------------------
# Transformer
# ---------------------------------------------------------------------------

class NLTKTextPreprocessor(BaseEstimator, TransformerMixin):
    """
    sklearn-kompatybilny transformer tokenizujący i (opcjonalnie) stemujący tekst.

    Parametry:
        language:      język dla stemmera i stopwords ('english' domyślnie).
                       Przekaż None aby wyłączyć stemming - właściwe dla treści
                       wielojęzycznych (np. mieszanina PL/EN), gdzie stemmer
                       angielski zniekształcałby polskie tokeny.
        min_token_len: minimalna długość tokenu po przetworzeniu.
    """

    def __init__(self, language: str | None = "english", min_token_len: int = 2) -> None:
        self.language = language
        self.min_token_len = min_token_len

    def fit(self, X: Iterable[str], y=None) -> "NLTKTextPreprocessor":
        _ensure_nltk()
        return self

    def transform(self, X: Iterable[str]) -> list[str]:
        return [self._process(text) for text in X]

    def _process(self, text: str) -> str:
        if not _ensure_nltk():
            return text.lower()

        import nltk
        from nltk.corpus import stopwords
        from nltk.stem import SnowballStemmer

        # Wczytaj stopwords (angielskie + polskie)
        try:
            en_stops = set(stopwords.words("english"))
        except Exception:
            en_stops = set()

        all_stops = en_stops | _POLISH_STOPWORDS

        # Stemmer - pomijany gdy language=None (tryb wielojęzyczny)
        stemmer = None
        if self.language is not None:
            try:
                stemmer = SnowballStemmer(self.language)
            except Exception:
                pass

        # Normalizacja
        text = text.lower()
        text = re.sub(r"https?://\S+", " urltoken ", text)   # zamień URL na token
        text = re.sub(r"\S+@\S+", " emailtoken ", text)      # zamień e-mail na token
        text = re.sub(r"\d+", " numtoken ", text)             # zamień liczby na token
        text = text.translate(str.maketrans("", "", string.punctuation))

        # Tokenizacja
        try:
            tokens = nltk.word_tokenize(text)
        except Exception:
            tokens = text.split()

        # Filtrowanie i stemming
        result_tokens: list[str] = []
        for tok in tokens:
            if len(tok) < self.min_token_len:
                continue
            if tok in all_stops:
                continue
            if stemmer:
                tok = stemmer.stem(tok)
            if len(tok) >= self.min_token_len:
                result_tokens.append(tok)

        return " ".join(result_tokens)
