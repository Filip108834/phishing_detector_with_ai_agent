"""
Ekstrakcja cech z listy URL-i znalezionych w wiadomości e-mail.

Wszystkie funkcje są deterministyczne i nie wykonują żadnych zapytań sieciowych.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from urllib.parse import urlparse, parse_qs

import tldextract

# TLD uznawane za podejrzane w kontekście phishingu
_SUSPICIOUS_TLDS = frozenset([
    "xyz", "tk", "ml", "ga", "cf", "gq",   # darmowe / nadużywane
    "click", "link", "top", "zip", "lol",   # nowe TLD często używane w phishingu
    "work", "loan", "online", "site", "gdn",
])

# Słowa kluczowe phishingu w URL-u
_PHISH_URL_KEYWORDS = frozenset([
    "login", "signin", "verify", "secure", "account", "update",
    "confirm", "banking", "paypal", "apple", "microsoft", "amazon",
    "password", "credential", "webscr", "cmd=_",
])

# Regex: adres IP w URL
_IP_RE = re.compile(r"https?://(\d{1,3}\.){3}\d{1,3}(:\d+)?(/|$)")

# Parametry przekierowania w URL
_REDIRECT_PARAMS = frozenset(["url", "redirect", "next", "link", "goto", "return"])


def analyze_urls(urls: list[str]) -> dict[str, float]:
    """
    Przelicza cechy URL-i na płaski słownik wartości liczbowych.

    Zwracane klucze:
        url_count                - liczba URL-i w wiadomości
        has_ip_url               - 1 jeśli jakikolwiek URL używa IP zamiast domeny
        has_suspicious_tld       - 1 jeśli TLD jest na liście podejrzanych
        has_url_keyword          - 1 jeśli URL zawiera słowo kluczowe phishingu
        has_at_in_url            - 1 jeśli URL zawiera @ (technika maskowania)
        has_redirect_param       - 1 jeśli URL ma parametr przekierowania
        max_url_length           - max długość URL-a
        avg_url_length           - średnia długość URL-i
        max_subdomain_depth      - max głębokość subdomen (sugestia ukrywania domeny)
        avg_url_entropy          - średnia entropia znaków URL-i
        url_domain_diversity     - liczba unikalnych domen / liczba URL-i (0..1)
    """
    if not urls:
        return _zero_features()

    results = [_analyze_single(u) for u in urls]

    n = len(urls)
    domains = [r["_domain"] for r in results]

    return {
        "url_count":             float(n),
        "has_ip_url":            float(any(r["is_ip"] for r in results)),
        "has_suspicious_tld":    float(any(r["suspicious_tld"] for r in results)),
        "has_url_keyword":       float(any(r["has_keyword"] for r in results)),
        "has_at_in_url":         float(any(r["has_at"] for r in results)),
        "has_redirect_param":    float(any(r["has_redirect"] for r in results)),
        "max_url_length":        float(max(r["length"] for r in results)),
        "avg_url_length":        float(sum(r["length"] for r in results) / n),
        "max_subdomain_depth":   float(max(r["subdomain_depth"] for r in results)),
        "avg_url_entropy":       float(sum(r["entropy"] for r in results) / n),
        "url_domain_diversity":  float(len(set(domains)) / n),
    }


def _analyze_single(url: str) -> dict:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    url_lower = url.lower()

    # Ekstrakcja TLD
    ext = tldextract.extract(url)
    tld = ext.suffix.lower() if ext.suffix else ""
    domain = ext.domain.lower() if ext.domain else ""

    # Głębokość subdomen (np. a.b.c.malicious.com -> 2 subdomeny)
    subdomain = ext.subdomain.lower() if ext.subdomain else ""
    subdomain_depth = len(subdomain.split(".")) if subdomain else 0

    # Parametry query
    query_params = set(parse_qs(parsed.query).keys())

    return {
        "_domain":        domain,
        "is_ip":          bool(_IP_RE.match(url)),
        "suspicious_tld": tld in _SUSPICIOUS_TLDS,
        "has_keyword":    any(kw in url_lower for kw in _PHISH_URL_KEYWORDS),
        "has_at":         "@" in (parsed.netloc or ""),
        "has_redirect":   bool(query_params & _REDIRECT_PARAMS),
        "length":         len(url),
        "subdomain_depth": subdomain_depth,
        "entropy":        _char_entropy(url),
    }


def _char_entropy(s: str) -> float:
    """Entropia Shannona znaków stringa (mierzy losowość/obfuskację)."""
    if not s:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _zero_features() -> dict[str, float]:
    return {
        "url_count":            0.0,
        "has_ip_url":           0.0,
        "has_suspicious_tld":   0.0,
        "has_url_keyword":      0.0,
        "has_at_in_url":        0.0,
        "has_redirect_param":   0.0,
        "max_url_length":       0.0,
        "avg_url_length":       0.0,
        "max_subdomain_depth":  0.0,
        "avg_url_entropy":      0.0,
        "url_domain_diversity": 0.0,
    }
