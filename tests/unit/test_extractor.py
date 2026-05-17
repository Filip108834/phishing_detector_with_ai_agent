"""
Testy jednostkowe: agent/features/extractor.py

Testowane komponenty:
    - extract()              - wektor cech z ParsedEmail
    - NUMERICAL_FEATURE_COLS - kompletność listy kolumn
    - _extract_domain()      - wyciąganie domeny z adresu e-mail
"""
from __future__ import annotations

import pytest

from agent.features.extractor import NUMERICAL_FEATURE_COLS, extract
from agent.ingestion.email_parser import ParsedEmail


# -----------------------------------------------------------------------------
# Helpersy
# -----------------------------------------------------------------------------

def _parsed(**kwargs) -> ParsedEmail:
    """Tworzy ParsedEmail z minimalnym zestawem pól; resztę wypełnia defaults."""
    defaults = dict(
        message_id="<test@test>",
        date="",
        from_addr=kwargs.pop("from_addr", "sender@example.com"),
        reply_to=kwargs.pop("reply_to", ""),
        return_path="",
        to_addr="",
        subject=kwargs.pop("subject", "Test subject"),
        plain_text=kwargs.pop("plain_text", "Some body text"),
        html_text=kwargs.pop("html_text", ""),
        urls=kwargs.pop("urls", []),
        has_html=kwargs.pop("has_html", False),
        has_attachments=kwargs.pop("has_attachments", False),
        raw_size=100,
        extra_headers={},
        received_hops=kwargs.pop("received_hops", 1),
        spf_result=kwargs.pop("spf_result", "none"),
    )
    return ParsedEmail(**defaults)


# -----------------------------------------------------------------------------
# Testy: struktura wektora cech
# -----------------------------------------------------------------------------

class TestExtractStructure:
    def test_text_key_present(self):
        feats = extract(_parsed())
        assert "text" in feats

    def test_all_numerical_cols_present(self):
        feats = extract(_parsed())
        for col in NUMERICAL_FEATURE_COLS:
            assert col in feats, f"Brak kolumny: {col}"

    def test_all_values_are_numeric(self):
        feats = extract(_parsed())
        for col in NUMERICAL_FEATURE_COLS:
            assert isinstance(feats[col], float), f"{col} nie jest float"

    def test_text_is_subject_plus_body(self):
        feats = extract(_parsed(subject="Hello", plain_text="World"))
        assert "Hello" in feats["text"]
        assert "World" in feats["text"]

    def test_numerical_feature_cols_count(self):
        # 11 URL + 9 nagłówkowe + 3 stylistyczne + 12 NLP = 35
        assert len(NUMERICAL_FEATURE_COLS) == 35


# -----------------------------------------------------------------------------
# Testy: cechy nagłówkowe
# -----------------------------------------------------------------------------

class TestHeaderFeatures:
    def test_from_reply_to_mismatch_detected(self):
        feats = extract(_parsed(
            from_addr="bank@real-bank.com",
            reply_to="attacker@gmail.com",
        ))
        assert feats["feat_from_reply_to_mismatch"] == 1.0

    def test_from_reply_to_match_not_flagged(self):
        feats = extract(_parsed(
            from_addr="info@company.com",
            reply_to="info@company.com",
        ))
        assert feats["feat_from_reply_to_mismatch"] == 0.0

    def test_no_reply_to_not_flagged(self):
        feats = extract(_parsed(from_addr="sender@example.com", reply_to=""))
        assert feats["feat_from_reply_to_mismatch"] == 0.0

    def test_spf_fail_flagged(self):
        feats = extract(_parsed(spf_result="fail"))
        assert feats["feat_spf_fail"] == 1.0

    def test_spf_softfail_flagged(self):
        feats = extract(_parsed(spf_result="softfail"))
        assert feats["feat_spf_fail"] == 1.0

    def test_spf_pass_not_flagged(self):
        feats = extract(_parsed(spf_result="pass"))
        assert feats["feat_spf_fail"] == 0.0

    def test_freemail_from_detected(self):
        feats = extract(_parsed(from_addr="attacker@gmail.com"))
        assert feats["feat_from_is_freemail"] == 1.0

    def test_corporate_from_not_freemail(self):
        feats = extract(_parsed(from_addr="hr@company.com"))
        assert feats["feat_from_is_freemail"] == 0.0

    def test_has_html_flag(self):
        feats = extract(_parsed(has_html=True))
        assert feats["feat_has_html"] == 1.0

    def test_has_attachments_flag(self):
        feats = extract(_parsed(has_attachments=True))
        assert feats["feat_has_attachments"] == 1.0

    def test_received_hops_capped_at_20(self):
        feats = extract(_parsed(received_hops=50))
        assert feats["feat_received_hops"] == 20.0

    def test_received_hops_below_20_preserved(self):
        feats = extract(_parsed(received_hops=5))
        assert feats["feat_received_hops"] == 5.0


# -----------------------------------------------------------------------------
# Testy: cechy tematu
# -----------------------------------------------------------------------------

class TestSubjectFeatures:
    def test_urgency_score_from_subject(self):
        feats = extract(_parsed(subject="URGENT: verify your account immediately!"))
        assert feats["feat_subject_urgency_score"] >= 1.0

    def test_no_urgency_for_normal_subject(self):
        feats = extract(_parsed(subject="Team meeting tomorrow"))
        assert feats["feat_subject_urgency_score"] == 0.0

    def test_empty_subject_flag(self):
        feats = extract(_parsed(subject=""))
        assert feats["feat_subject_is_empty"] == 1.0

    def test_non_empty_subject_not_flagged(self):
        feats = extract(_parsed(subject="Hello"))
        assert feats["feat_subject_is_empty"] == 0.0

    def test_exclamation_count_in_subject(self):
        feats = extract(_parsed(subject="ALERT!! Act now!!!"))
        assert feats["feat_subject_exclamation"] >= 2.0


# -----------------------------------------------------------------------------
# Testy: cechy stylistyczne
# -----------------------------------------------------------------------------

class TestStyleFeatures:
    def test_caps_ratio_all_upper(self):
        # subject="" żeby full_text = tylko body (same wielkie litery)
        feats = extract(_parsed(subject="", plain_text="CLICK NOW VERIFY ACCOUNT"))
        assert feats["feat_caps_ratio"] > 0.8

    def test_caps_ratio_all_lower(self):
        feats = extract(_parsed(plain_text="hello world this is normal"))
        assert feats["feat_caps_ratio"] < 0.1

    def test_exclamation_density_high(self):
        feats = extract(_parsed(plain_text="Act now! Verify! Click! Hurry!"))
        assert feats["feat_exclamation_density"] > 0.0

    def test_exclamation_density_zero_for_no_exclamation(self):
        feats = extract(_parsed(plain_text="Hello. How are you. Fine."))
        assert feats["feat_exclamation_density"] == 0.0

    def test_text_length_positive(self):
        feats = extract(_parsed(plain_text="Some content here"))
        assert feats["feat_text_length"] > 0.0
