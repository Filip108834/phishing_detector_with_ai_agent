"""
Parser wiadomości e-mail.

Wejście:  surowy string MIME (zawartość pliku .eml) lub ścieżka do pliku.
Wyjście:  ParsedEmail - ustrukturyzowany obiekt gotowy do ekstrakcji cech.

Moduł używa wyłącznie bibliotek standardowych + beautifulsoup4/lxml,
bez żadnych wywołań sieciowych.
"""
from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

# Regex do wykrywania URL w plain-text
_URL_RE = re.compile(
    r"https?://[^\s\"'<>)\]]+",
    re.IGNORECASE,
)

# Nagłówki które ekstrakcja zachowuje (poza standardowymi)
_EXTRA_HEADERS = (
    "x-mailer",
    "x-originating-ip",
    "x-spam-status",
    "x-spam-score",
    "authentication-results",   # zawiera wyniki DKIM/SPF/DMARC
    "dkim-signature",           # obecność = własny podpis DKIM
)


@dataclass
class ParsedEmail:
    # --- Identyfikatory ---
    message_id: str = ""
    date: str = ""

    # --- Adresy ---
    from_addr: str = ""
    reply_to: str = ""
    return_path: str = ""
    to_addr: str = ""

    # --- Treść ---
    subject: str = ""
    plain_text: str = ""
    html_text: str = ""   # tekst po wystrippowaniu HTML

    # --- Linki ---
    urls: list[str] = field(default_factory=list)

    # --- Flagi ---
    has_html: bool = False
    has_attachments: bool = False

    # --- Metadane ---
    raw_size: int = 0
    extra_headers: dict[str, str] = field(default_factory=dict)
    received_hops: int = 0       # liczba wpisów Received:
    spf_result: str = ""         # "pass" / "fail" / "softfail" / ""

    @classmethod
    def from_string(cls, raw: str) -> "ParsedEmail":
        """Parsuje surowy string MIME."""
        msg = email.message_from_string(raw, policy=email.policy.compat32)
        return _parse_message(msg, raw_size=len(raw.encode("utf-8", errors="replace")))

    @classmethod
    def from_file(cls, path: str | Path) -> "ParsedEmail":
        """Wczytuje i parsuje plik .eml."""
        data = Path(path).read_bytes()
        msg = email.message_from_bytes(data, policy=email.policy.compat32)
        return _parse_message(msg, raw_size=len(data))

    @classmethod
    def from_request(
        cls,
        *,
        sender: Optional[str] = None,
        subject: Optional[str] = None,
        body: str = "",
        urls: Optional[list[str]] = None,
        headers: Optional[dict] = None,
    ) -> "ParsedEmail":
        """Tworzy ParsedEmail ze strukturyzowanego żądania API (bez parsowania MIME)."""
        hdrs = headers or {}
        obj = cls(
            from_addr=sender or "",
            reply_to=str(hdrs.get("Reply-To", "")),
            return_path=str(hdrs.get("Return-Path", "")),
            subject=subject or "",
            plain_text=body,
            urls=list(urls or []) + _extract_urls(body),
            has_html="<html" in body.lower() or "<body" in body.lower(),
            raw_size=len(body.encode("utf-8", errors="replace")),
        )
        obj.urls = list(dict.fromkeys(obj.urls))   # deduplikacja z zachowaniem kolejności
        return obj


# ---------------------------------------------------------------------------
# Prywatna logika parsowania
# ---------------------------------------------------------------------------

def _parse_message(msg: Message, raw_size: int) -> ParsedEmail:
    parsed = ParsedEmail(raw_size=raw_size)

    # Nagłówki podstawowe
    parsed.message_id = _hdr(msg, "Message-ID")
    parsed.date = _hdr(msg, "Date")
    parsed.from_addr = _hdr(msg, "From")
    parsed.reply_to = _hdr(msg, "Reply-To")
    parsed.return_path = _hdr(msg, "Return-Path")
    parsed.to_addr = _hdr(msg, "To")
    parsed.subject = _hdr(msg, "Subject")

    # Nagłówki dodatkowe
    for key in _EXTRA_HEADERS:
        val = _hdr(msg, key)
        if val:
            parsed.extra_headers[key] = val

    # Liczba przeskoków Received:
    parsed.received_hops = len(msg.get_all("Received") or [])

    # Wynik SPF z nagłówków Authentication-Results / Received-SPF
    parsed.spf_result = _extract_spf(msg)

    # Ciało wiadomości
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in msg.walk():
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition") or "").lower()

        if "attachment" in disp:
            parsed.has_attachments = True
            continue

        if ctype == "text/plain":
            plain_parts.append(_decode_part(part))
        elif ctype == "text/html":
            parsed.has_html = True
            raw_html = _decode_part(part)
            html_parts.append(_strip_html(raw_html))
            # Wyciągnij URL-e z HTML przed strippowaniem
            parsed.urls.extend(_extract_urls_from_html(raw_html))

    parsed.plain_text = "\n".join(plain_parts).strip()
    parsed.html_text = "\n".join(html_parts).strip()

    # URL-e z plain-text
    combined_text = parsed.plain_text + " " + parsed.html_text
    parsed.urls.extend(_extract_urls(combined_text))
    parsed.urls = list(dict.fromkeys(parsed.urls))   # deduplikacja

    return parsed


def _hdr(msg: Message, key: str) -> str:
    """Bezpiecznie pobiera i dekoduje nagłówek."""
    val = msg.get(key, "")
    if not val:
        return ""
    try:
        decoded_parts = email.header.decode_header(val)
        parts = []
        for fragment, charset in decoded_parts:
            if isinstance(fragment, bytes):
                parts.append(fragment.decode(charset or "utf-8", errors="replace"))
            else:
                parts.append(str(fragment))
        return "".join(parts).strip()
    except Exception:
        return str(val).strip()


def _decode_part(part: Message) -> str:
    """Dekoduje payload MIME part do stringa."""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    """Usuwa tagi HTML i zwraca czysty tekst."""
    try:
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        # Fallback: prosta regexpowa ekstrakcja
        return re.sub(r"<[^>]+>", " ", html)


def _extract_urls(text: str) -> list[str]:
    """Wyciąga URL-e z plain textu."""
    return _URL_RE.findall(text)


def _extract_urls_from_html(html: str) -> list[str]:
    """Wyciąga URL-e z atrybutów href/src w HTML."""
    urls: list[str] = []
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(href=True):
            href = tag["href"].strip()
            if href.startswith(("http://", "https://")):
                urls.append(href)
        for tag in soup.find_all(src=True):
            src = tag["src"].strip()
            if src.startswith(("http://", "https://")):
                urls.append(src)
    except Exception:
        pass
    return urls


def _extract_spf(msg: Message) -> str:
    """Wyciąga wynik SPF z nagłówków Authentication-Results lub Received-SPF."""
    auth = _hdr(msg, "Authentication-Results").lower()
    if "spf=pass" in auth:
        return "pass"
    if "spf=fail" in auth:
        return "fail"
    if "spf=softfail" in auth:
        return "softfail"
    if "spf=neutral" in auth:
        return "neutral"

    spf_hdr = _hdr(msg, "Received-SPF").lower()
    for result in ("pass", "fail", "softfail", "neutral"):
        if result in spf_hdr:
            return result

    return ""
