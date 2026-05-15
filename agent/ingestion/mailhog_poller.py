"""
Background poller - automatyczna klasyfikacja nowych e-maili z MailHog.

Uruchamiany jako asyncio task w FastAPI lifespan.
Co `interval` sekund pobiera wiadomości z MailHog i klasyfikuje nowe
(niewidziane wcześniej, identyfikowane po msg_id).

Zależności:
    - simulation.mailhog_client.MailHogClient (sync, wywoływany przez executor)
    - agent.state                             (dostęp do pipeline ML)
    - agent.api.routes_predict.classify_parsed
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class MailHogPoller:
    """
    Asynchroniczny poller skrzynki MailHog.

    Parametry:
        mailhog_url:  bazowy URL MailHog API (np. "http://mailhog:8025")
        interval:     interwał odpytywania w sekundach (domyślnie 15)
        campaign_tag: opcjonalna nazwa kampanii zapisywana w DB
    """

    def __init__(
        self,
        mailhog_url: str,
        interval: int = 15,
        campaign_tag: Optional[str] = None,
    ) -> None:
        self.mailhog_url = mailhog_url
        self.interval = interval
        self.campaign_tag = campaign_tag or "poller_auto"

        self._processed_ids: set[str] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Uruchamia background task. Wywoływać z lifespan FastAPI."""
        if self._task is not None and not self._task.done():
            logger.warning("Poller już działa.")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="mailhog_poller")
        logger.info(
            "MailHog poller uruchomiony (URL=%s, interwał=%ds).",
            self.mailhog_url, self.interval,
        )

    def stop(self) -> None:
        """Zatrzymuje background task. Wywoływać przy zamknięciu aplikacji."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("MailHog poller zatrzymany.")

    # ------------------------------------------------------------------
    # Główna pętla
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.interval)
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Błąd pollera: %s", e, exc_info=True)

    async def _poll_once(self) -> None:
        """Jednorazowe sprawdzenie MailHog i klasyfikacja nowych wiadomości."""
        loop = asyncio.get_running_loop()

        # Wywołanie synchronicznego klienta przez executor (nie blokuje event loop)
        messages = await loop.run_in_executor(None, self._fetch_messages)
        if not messages:
            return

        new_msgs = [m for m in messages if m.msg_id not in self._processed_ids]
        if not new_msgs:
            return

        logger.info("Poller: %d nowych wiadomości.", len(new_msgs))

        for msg in new_msgs:
            try:
                await loop.run_in_executor(None, self._classify_one, msg)
                self._processed_ids.add(msg.msg_id)
            except Exception as e:
                logger.warning("Błąd klasyfikacji %s: %s", msg.msg_id, e)

    # ------------------------------------------------------------------
    # Synchroniczne helpery (wykonywane w thread executor)
    # ------------------------------------------------------------------

    def _fetch_messages(self):
        """Pobiera wiadomości z MailHog (sync) bez zależności od simulation."""
        import requests
        from dataclasses import dataclass

        @dataclass
        class _Msg:
            msg_id: str
            raw_mime: str

        base = self.mailhog_url.rstrip("/")
        try:
            r = requests.get(f"{base}/api/v2/messages", params={"start": 0, "limit": 50}, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning("Nie można pobrać wiadomości z MailHog: %s", e)
            return []

        msgs: list[_Msg] = []
        for item in data.get("items", []):
            msg_id = item.get("ID", "")
            headers: dict = item.get("Content", {}).get("Headers", {})
            body: str = item.get("Content", {}).get("Body", "")
            raw_parts: list[str] = []
            for key, values in headers.items():
                for val in values:
                    raw_parts.append(f"{key}: {val}")
            raw_parts.append("")
            raw_parts.append(body)
            msgs.append(_Msg(msg_id=msg_id, raw_mime="\r\n".join(raw_parts)))

        return msgs

    def _classify_one(self, msg) -> None:
        """Klasyfikuje pojedynczą wiadomość i zapisuje do DB (sync)."""
        from agent.api.routes_predict import classify_parsed
        from agent.ingestion.email_parser import ParsedEmail

        parsed = ParsedEmail.from_string(msg.raw_mime)
        result = classify_parsed(parsed, campaign=self.campaign_tag)
        logger.debug(
            "Poller: sklasyfikowano %s → %s (score=%.3f)",
            msg.msg_id[:16], result["label"], result["score"],
        )

    # ------------------------------------------------------------------
    # Diagnostyka
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "running": self._running,
            "interval_s": self.interval,
            "processed_count": len(self._processed_ids),
            "mailhog_url": self.mailhog_url,
        }
