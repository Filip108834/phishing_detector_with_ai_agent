"""
Testy jednostkowe: agent/features/text_preprocessor.py

Testowane komponenty:
    - NLTKTextPreprocessor.transform() - przetwarzanie tekstu
    - NLTKTextPreprocessor.fit()       - kompatybilność sklearn
    - Normalizacja URL/e-mail/liczb
    - Usuwanie stopwords
    - Stemming
"""
from __future__ import annotations

import string

import pytest

from agent.features.text_preprocessor import NLTKTextPreprocessor


# -----------------------------------------------------------------------------
# Fixture
# -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def preprocessor() -> NLTKTextPreprocessor:
    """Wytrenowany preprocessor (fit wywołuje _ensure_nltk)."""
    p = NLTKTextPreprocessor()
    p.fit(["dummy text"])
    return p


# -----------------------------------------------------------------------------
# Testy: transformacja tekstu
# -----------------------------------------------------------------------------

class TestTransform:
    def test_output_is_lowercase(self, preprocessor):
        result = preprocessor.transform(["HELLO WORLD"])[0]
        assert result == result.lower()

    def test_url_replaced_with_token(self, preprocessor):
        result = preprocessor.transform(["Visit http://evil.xyz/login now"])[0]
        assert "urltoken" in result
        # Oryginalny URL nie powinien pozostać
        assert "evil.xyz" not in result

    def test_https_url_replaced(self, preprocessor):
        result = preprocessor.transform(["See https://secure.com/verify"])[0]
        assert "urltoken" in result

    def test_email_replaced_with_token(self, preprocessor):
        result = preprocessor.transform(["Send to user@example.com now"])[0]
        assert "emailtoken" in result
        assert "user@example.com" not in result

    def test_numbers_replaced_with_token(self, preprocessor):
        result = preprocessor.transform(["Pay 3.99 PLN within 24 hours"])[0]
        assert "numtoken" in result

    def test_punctuation_removed(self, preprocessor):
        result = preprocessor.transform(["Hello, world! How are you?"])[0]
        for ch in string.punctuation:
            assert ch not in result

    def test_stopwords_removed(self, preprocessor):
        # "the", "is", "a" - typowe angielskie stopwords
        result = preprocessor.transform(["the dog is a friend"])[0]
        words = result.split()
        assert "the" not in words
        assert "is" not in words

    def test_empty_string_returns_empty(self, preprocessor):
        result = preprocessor.transform([""])[0]
        assert result == ""

    def test_multiple_texts_processed(self, preprocessor):
        inputs = ["Hello world", "URGENT verify account", "Meeting tomorrow"]
        results = preprocessor.transform(inputs)
        assert len(results) == 3
        assert all(isinstance(r, str) for r in results)

    def test_min_token_length_filters_short_tokens(self, preprocessor):
        # Tokeny krótsze niż min_token_len (domyślnie 2) powinny być usunięte
        result = preprocessor.transform(["I a b in"])[0]
        words = result.split()
        assert all(len(w) >= 2 for w in words)


# -----------------------------------------------------------------------------
# Testy: interfejs sklearn
# -----------------------------------------------------------------------------

class TestSklearnInterface:
    def test_fit_returns_self(self):
        p = NLTKTextPreprocessor()
        result = p.fit(["some text"])
        assert result is p

    def test_fit_transform_equivalent_to_fit_then_transform(self):
        texts = ["Hello world", "URGENT verify account"]
        p1 = NLTKTextPreprocessor()
        p2 = NLTKTextPreprocessor()
        result1 = p1.fit_transform(texts)
        p2.fit(texts)
        result2 = p2.transform(texts)
        assert result1 == result2

    def test_get_params_contains_language(self):
        p = NLTKTextPreprocessor(language="english", min_token_len=3)
        params = p.get_params()
        assert params["language"] == "english"
        assert params["min_token_len"] == 3

    def test_custom_min_token_len(self):
        p = NLTKTextPreprocessor(min_token_len=5)
        p.fit(["dummy"])
        result = p.transform(["the big brown fox jumps"])[0]
        words = result.split()
        assert all(len(w) >= 5 for w in words)
