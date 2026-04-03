"""
Testy komponentowe: POST /ingest/mailhog, POST /ingest/campaign/{name},
                    DELETE /ingest/mailhog/purge

Zewnętrzne zależności (MailHog, pliki .eml) są mockowane lub tworzone
tymczasowo (tmp_path).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpersy
# ─────────────────────────────────────────────────────────────────────────────

PHISHING_EML = """\
From: phisher@evil.xyz\r
To: victim@lab.local\r
Subject: URGENT: Verify your account\r
Reply-To: attacker@gmail.com\r
MIME-Version: 1.0\r
Content-Type: text/plain; charset=utf-8\r
\r
Click here to verify: http://192.168.1.100/login\r
Your account has been suspended. Action required.\
"""

LEGIT_EML = """\
From: hr@company.com\r
To: employee@company.com\r
Subject: Team meeting tomorrow\r
MIME-Version: 1.0\r
Content-Type: text/plain; charset=utf-8\r
\r
Hi, please join the sprint review meeting tomorrow at 10am in room A2.\
"""


def _write_campaign(tmp_path: Path, name: str, emls: list[str], label: str = "phishing") -> Path:
    """Tworzy katalog kampanii z plikami .eml i metadata.json."""
    campaign_dir = tmp_path / name
    campaign_dir.mkdir()
    for i, eml in enumerate(emls):
        (campaign_dir / f"{i:04d}.eml").write_text(eml, encoding="utf-8")
    metadata = {"label": label, "campaign_name": name}
    (campaign_dir / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    return campaign_dir


# ─────────────────────────────────────────────────────────────────────────────
# Testy: POST /ingest/campaign/{name}
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestCampaign:
    def test_missing_campaign_returns_404(self, client, tmp_path, monkeypatch):
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        resp = client.post("/ingest/campaign/nonexistent")
        assert resp.status_code == 404

    def test_empty_campaign_dir_returns_422(self, client, tmp_path, monkeypatch):
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        (tmp_path / "empty_campaign").mkdir()
        resp = client.post("/ingest/campaign/empty_campaign")
        assert resp.status_code == 422

    def test_phishing_campaign_classified(self, client, tmp_path, monkeypatch):
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        _write_campaign(tmp_path, "phish_01", [PHISHING_EML, PHISHING_EML], label="phishing")
        resp = client.post("/ingest/campaign/phish_01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["campaign"] == "phish_01"
        assert data["classified"] == 2
        assert data["errors"] == 0

    def test_legit_campaign_classified(self, client, tmp_path, monkeypatch):
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        _write_campaign(tmp_path, "legit_01", [LEGIT_EML, LEGIT_EML], label="legit")
        resp = client.post("/ingest/campaign/legit_01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["classified"] == 2

    def test_accuracy_computed_when_metadata_present(self, client, tmp_path, monkeypatch):
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        # Wiadomość phishingowa → model heurystyczny powinien sklasyfikować jako phishing
        _write_campaign(tmp_path, "acc_test", [PHISHING_EML], label="phishing")
        resp = client.post("/ingest/campaign/acc_test")
        data = resp.json()
        assert data["ground_truth_available"] is True
        assert data["accuracy"] is not None
        assert 0.0 <= data["accuracy"] <= 1.0

    def test_no_metadata_no_accuracy(self, client, tmp_path, monkeypatch):
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        campaign_dir = tmp_path / "no_meta"
        campaign_dir.mkdir()
        (campaign_dir / "0000.eml").write_text(LEGIT_EML, encoding="utf-8")
        resp = client.post("/ingest/campaign/no_meta")
        data = resp.json()
        assert data["ground_truth_available"] is False
        assert data["accuracy"] is None

    def test_mixed_campaign_counts_legit_and_phishing(self, client, tmp_path, monkeypatch):
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        campaign_dir = tmp_path / "mixed"
        campaign_dir.mkdir()
        (campaign_dir / "phish.eml").write_text(PHISHING_EML, encoding="utf-8")
        (campaign_dir / "legit.eml").write_text(LEGIT_EML, encoding="utf-8")
        resp = client.post("/ingest/campaign/mixed")
        data = resp.json()
        assert data["classified"] == 2
        assert data["phishing"] + data["legit"] == 2

    def test_ingest_saves_to_db(self, client, tmp_path, monkeypatch, db_session):
        from agent.db import Prediction
        import agent.api.routes_ingest as ri
        monkeypatch.setattr(ri, "RAW_DATA_DIR", tmp_path)
        _write_campaign(tmp_path, "db_test", [PHISHING_EML], label="phishing")
        client.post("/ingest/campaign/db_test")
        preds = db_session.query(Prediction).filter(
            Prediction.campaign == "db_test"
        ).all()
        assert len(preds) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Testy: DELETE /ingest/mailhog/purge
# ─────────────────────────────────────────────────────────────────────────────

class TestPurgeMailhog:
    def test_purge_calls_delete_all(self, client):
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            resp = client.delete("/ingest/mailhog/purge")
        assert resp.status_code == 200
        mock_instance.delete_all.assert_called_once()

    def test_purge_response_schema(self, client):
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            MockClient.return_value = MagicMock()
            resp = client.delete("/ingest/mailhog/purge")
        data = resp.json()
        assert data["status"] == "ok"

    def test_purge_503_when_mailhog_down(self, client):
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.delete_all.side_effect = ConnectionError("MailHog down")
            MockClient.return_value = mock_instance
            resp = client.delete("/ingest/mailhog/purge")
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# Testy: POST /ingest/mailhog
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestMailhog:
    def _make_mailhog_message(self, msg_id: str, raw_mime: str):
        """Tworzy mock MailHogMessage."""
        msg = MagicMock()
        msg.msg_id = msg_id
        msg.raw_mime = raw_mime
        return msg

    def test_ingest_empty_inbox(self, client):
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.fetch_all.return_value = []
            MockClient.return_value = mock_instance
            resp = client.post("/ingest/mailhog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fetched"] == 0
        assert data["classified"] == 0

    def test_ingest_classifies_messages(self, client):
        msgs = [
            self._make_mailhog_message("id1", PHISHING_EML),
            self._make_mailhog_message("id2", LEGIT_EML),
        ]
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.fetch_all.return_value = msgs
            MockClient.return_value = mock_instance
            resp = client.post("/ingest/mailhog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fetched"] == 2
        assert data["classified"] == 2
        assert data["errors"] == 0

    def test_ingest_clear_after_calls_delete(self, client):
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.fetch_all.return_value = []
            MockClient.return_value = mock_instance
            resp = client.post("/ingest/mailhog?clear_after=true")
        assert resp.status_code == 200
        mock_instance.delete_all.assert_called_once()

    def test_ingest_503_when_mailhog_unreachable(self, client):
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.fetch_all.side_effect = ConnectionError("unreachable")
            MockClient.return_value = mock_instance
            resp = client.post("/ingest/mailhog")
        assert resp.status_code == 503

    def test_ingest_response_schema(self, client):
        with patch("simulation.mailhog_client.MailHogClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.fetch_all.return_value = []
            MockClient.return_value = mock_instance
            resp = client.post("/ingest/mailhog")
        data = resp.json()
        assert {"fetched", "classified", "phishing", "legit", "errors"}.issubset(data.keys())
