"""
Klient MailHog API v2.

MailHog przechwytuje e-maile wysłane przez Gophish (SMTP :1025)
i udostępnia je przez REST API (:8025).

API reference: https://github.com/mailhog/MailHog/blob/master/docs/APIv2.md

Użycie:
    client = MailHogClient("http://localhost:8025")
    msgs = client.fetch_all()
    client.export_to_eml_dir(msgs, "data/raw/campaign_01")
    client.delete_all()
"""
from __future__ import annotations

import email
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import requests


@dataclass
class MailHogMessage:
    msg_id: str          # Gophish/MailHog ID
    from_addr: str
    to_addrs: list[str]
    subject: str
    raw_mime: str        # pełna wiadomość MIME jako string


class MailHogClient:
    """Wrapper nad MailHog API v2."""

    def __init__(self, api_url: str = "http://localhost:8025") -> None:
        self.base = api_url.rstrip("/")

    # ------------------------------------------------------------------
    # Pobieranie wiadomości
    # ------------------------------------------------------------------

    def fetch_all(self, limit: int = 500) -> list[MailHogMessage]:
        """Zwraca wszystkie wiadomości z inbox MailHog."""
        messages: list[MailHogMessage] = []
        start = 0

        while True:
            batch = self._fetch_page(start=start, limit=min(limit, 50))
            messages.extend(batch)
            if len(batch) < 50 or len(messages) >= limit:
                break
            start += len(batch)

        return messages[:limit]

    def fetch_by_recipient(self, email_addr: str) -> list[MailHogMessage]:
        """Filtruje wiadomości po adresie odbiorcy."""
        all_msgs = self.fetch_all()
        return [m for m in all_msgs if email_addr.lower() in [a.lower() for a in m.to_addrs]]

    def _fetch_page(self, start: int = 0, limit: int = 50) -> list[MailHogMessage]:
        url = f"{self.base}/api/v2/messages"
        r = requests.get(url, params={"start": start, "limit": limit}, timeout=10)
        r.raise_for_status()
        data = r.json()

        result: list[MailHogMessage] = []
        for item in data.get("items", []):
            result.append(_parse_mailhog_item(item))
        return result

    # ------------------------------------------------------------------
    # Eksport do plików .eml
    # ------------------------------------------------------------------

    def export_to_eml_dir(self, messages: list[MailHogMessage], output_dir: str | Path) -> list[Path]:
        """Zapisuje każdą wiadomość jako plik .eml, zwraca listę ścieżek."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        paths: list[Path] = []
        for i, msg in enumerate(messages):
            safe_id = msg.msg_id.replace("/", "_").replace("\\", "_")
            path = out / f"{i:04d}_{safe_id[:16]}.eml"
            path.write_text(msg.raw_mime, encoding="utf-8", errors="replace")
            paths.append(path)

        return paths

    # ------------------------------------------------------------------
    # Zarządzanie inbox
    # ------------------------------------------------------------------

    def delete_all(self) -> None:
        """Czyści całą skrzynkę MailHog."""
        r = requests.delete(f"{self.base}/api/v1/messages", timeout=10)
        r.raise_for_status()

    def count(self) -> int:
        r = requests.get(f"{self.base}/api/v2/messages", params={"limit": 1}, timeout=10)
        r.raise_for_status()
        return int(r.json().get("total", 0))


# ---------------------------------------------------------------------------
# Parsowanie odpowiedzi MailHog
# ---------------------------------------------------------------------------

def _parse_mailhog_item(item: dict) -> MailHogMessage:
    """Konwertuje surowy JSON z MailHog API na MailHogMessage."""
    msg_id = item.get("ID", "")

    # Nagłówki
    headers: dict[str, list[str]] = item.get("Content", {}).get("Headers", {})
    from_addr = _first_header(headers, "From")
    subject = _first_header(headers, "Subject")

    # Odbiorcy
    to_raw = headers.get("To", [])
    to_addrs: list[str] = []
    for entry in to_raw:
        to_addrs.extend([a.strip() for a in entry.split(",") if a.strip()])

    # Rekonstrukcja surowego MIME
    raw_parts: list[str] = []

    # Nagłówki → string
    for key, values in headers.items():
        for val in values:
            raw_parts.append(f"{key}: {val}")
    raw_parts.append("")  # pusta linia = koniec nagłówków

    # Ciało
    body = item.get("Content", {}).get("Body", "")
    raw_parts.append(body)

    raw_mime = "\r\n".join(raw_parts)

    return MailHogMessage(
        msg_id=msg_id,
        from_addr=from_addr,
        to_addrs=to_addrs,
        subject=subject,
        raw_mime=raw_mime,
    )


def _first_header(headers: dict[str, list[str]], key: str) -> str:
    values = headers.get(key, [])
    return values[0] if values else ""
