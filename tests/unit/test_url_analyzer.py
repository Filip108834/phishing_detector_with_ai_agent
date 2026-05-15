"""
Testy jednostkowe: agent/features/url_analyzer.py

Testowane komponenty:
    - analyze_urls()     - agregacja cech z listy URL-i
    - _char_entropy()    - entropia Shannona
    - _analyze_single()  - analiza pojedynczego URL-a
"""
from __future__ import annotations

import math

import pytest

from agent.features.url_analyzer import analyze_urls, _char_entropy


# ─────────────────────────────────────────────────────────────────────────────
# Testy: pusta lista URL-i
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptyUrls:
    def test_empty_list_returns_zero_dict(self):
        result = analyze_urls([])
        assert isinstance(result, dict)
        assert all(v == 0.0 for v in result.values())

    def test_empty_list_has_all_expected_keys(self):
        result = analyze_urls([])
        expected_keys = {
            "url_count", "has_ip_url", "has_suspicious_tld",
            "has_url_keyword", "has_at_in_url", "has_redirect_param",
            "max_url_length", "avg_url_length", "max_subdomain_depth",
            "avg_url_entropy", "url_domain_diversity",
        }
        assert expected_keys == set(result.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Testy: wykrywanie wskaźników phishingu
# ─────────────────────────────────────────────────────────────────────────────

class TestPhishingIndicators:
    def test_ip_url_detected(self):
        result = analyze_urls(["http://192.168.1.100/login"])
        assert result["has_ip_url"] == 1.0

    def test_normal_url_not_flagged_as_ip(self):
        result = analyze_urls(["https://www.google.com/search?q=test"])
        assert result["has_ip_url"] == 0.0

    def test_suspicious_tld_xyz(self):
        result = analyze_urls(["http://phishing.xyz/page"])
        assert result["has_suspicious_tld"] == 1.0

    def test_suspicious_tld_tk(self):
        result = analyze_urls(["http://evil.tk/verify"])
        assert result["has_suspicious_tld"] == 1.0

    def test_normal_tld_not_suspicious(self):
        result = analyze_urls(["https://company.com/page"])
        assert result["has_suspicious_tld"] == 0.0

    def test_phishing_keyword_login(self):
        result = analyze_urls(["https://secure-bank.net/login?user=test"])
        assert result["has_url_keyword"] == 1.0

    def test_phishing_keyword_verify(self):
        result = analyze_urls(["https://example.com/verify-account"])
        assert result["has_url_keyword"] == 1.0

    def test_normal_url_no_keyword(self):
        result = analyze_urls(["https://example.com/about-us"])
        assert result["has_url_keyword"] == 0.0

    def test_at_in_url_netloc(self):
        result = analyze_urls(["http://legit.com@evil.com/page"])
        assert result["has_at_in_url"] == 1.0

    def test_redirect_param_url_detected(self):
        result = analyze_urls(["https://tracker.com/click?redirect=http://evil.com"])
        assert result["has_redirect_param"] == 1.0

    def test_redirect_param_next_detected(self):
        result = analyze_urls(["https://sso.example.com/login?next=/dashboard"])
        assert result["has_redirect_param"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Testy: metryki liczbowe
# ─────────────────────────────────────────────────────────────────────────────

class TestNumericMetrics:
    def test_url_count(self):
        urls = ["https://a.com", "https://b.com", "https://c.com"]
        result = analyze_urls(urls)
        assert result["url_count"] == 3.0

    def test_max_url_length(self):
        urls = ["http://a.com", "http://b.com/very/long/path/with/many/segments"]
        result = analyze_urls(urls)
        assert result["max_url_length"] == float(max(len(u) for u in urls))

    def test_avg_url_length(self):
        urls = ["http://a.com", "http://bb.com"]
        result = analyze_urls(urls)
        expected = (len(urls[0]) + len(urls[1])) / 2
        assert result["avg_url_length"] == pytest.approx(expected)

    def test_subdomain_depth_zero_for_no_subdomain(self):
        result = analyze_urls(["http://example.com/page"])
        assert result["max_subdomain_depth"] == 0.0

    def test_subdomain_depth_counted(self):
        result = analyze_urls(["http://login.secure.evil.com/page"])
        assert result["max_subdomain_depth"] >= 1.0

    def test_domain_diversity_all_unique(self):
        urls = ["http://a.com", "http://b.com", "http://c.com"]
        result = analyze_urls(urls)
        assert result["url_domain_diversity"] == pytest.approx(1.0)

    def test_domain_diversity_all_same(self):
        urls = ["http://evil.com/p1", "http://evil.com/p2", "http://evil.com/p3"]
        result = analyze_urls(urls)
        assert result["url_domain_diversity"] == pytest.approx(1 / 3)

    def test_avg_entropy_positive_for_urls(self):
        result = analyze_urls(["https://example.com/path"])
        assert result["avg_url_entropy"] > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Testy: _char_entropy
# ─────────────────────────────────────────────────────────────────────────────

class TestCharEntropy:
    def test_empty_string_returns_zero(self):
        assert _char_entropy("") == 0.0

    def test_single_char_returns_zero(self):
        assert _char_entropy("aaaa") == pytest.approx(0.0)

    def test_two_equal_chars_returns_one_bit(self):
        assert _char_entropy("ab") == pytest.approx(1.0)

    def test_entropy_increases_with_randomness(self):
        low = _char_entropy("aaabbbccc")
        high = _char_entropy("aB3!xQ7#mZ")
        assert high > low

    def test_entropy_non_negative(self):
        for s in ["hello", "world", "phishing", "http://evil.xyz/verify"]:
            assert _char_entropy(s) >= 0.0
