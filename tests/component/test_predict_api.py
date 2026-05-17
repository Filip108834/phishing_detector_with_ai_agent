"""
Testy komponentowe: POST /predict, GET /model/info, GET /health

Używa prawdziwego FastAPI TestClient + SQLite in-memory (patchowanego w conftest).
Model ML nie jest załadowany -> klasyfikator heurystyczny.
"""
import pytest


# -----------------------------------------------------------------------------
# Testy: /health
# -----------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_status_ok(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_reports_model_type(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "model" in data
        assert data["model"] in ("heuristic", "ml")

    def test_health_no_poller_when_disabled(self, client):
        resp = client.get("/health")
        data = resp.json()
        # Poller wyłączony przez MAILHOG_POLLER_ENABLED=false w conftest
        assert "poller" not in data


# -----------------------------------------------------------------------------
# Testy: /predict
# -----------------------------------------------------------------------------

class TestPredict:
    def test_predict_returns_200(self, client):
        resp = client.post("/predict", json={"body": "Hello, this is a test email."})
        assert resp.status_code == 200

    def test_predict_response_schema(self, client):
        resp = client.post("/predict", json={"body": "Some email body"})
        data = resp.json()
        assert "label" in data
        assert "score" in data
        assert "reasons" in data
        assert "model_used" in data
        assert data["label"] in ("phishing", "legit")

    def test_predict_score_in_range(self, client):
        resp = client.post("/predict", json={"body": "Some email body"})
        data = resp.json()
        assert 0.0 <= data["score"] <= 1.0

    def test_predict_with_phishing_ip_url(self, client):
        # score = 0.15 (base) + 0.25 (IP URL) + 0.05*2 (verify+suspended) = 0.50 -> phishing
        resp = client.post("/predict", json={
            "body": "verify account suspended",
            "urls": ["http://192.168.1.100/verify"],
        })
        data = resp.json()
        assert data["label"] == "phishing"
        assert data["score"] >= 0.5

    def test_predict_phishing_keyword_in_subject(self, client):
        resp = client.post("/predict", json={
            "subject": "URGENT: Verify your account immediately!",
            "body": "Your account has been suspended. Action required.",
        })
        data = resp.json()
        assert data["score"] > 0.15  # przynajmniej wyżej niż baseline

    def test_predict_with_all_optional_fields(self, client):
        resp = client.post("/predict", json={
            "sender": "phisher@evil.xyz",
            "subject": "Account suspended",
            "body": "Verify now",
            "urls": ["http://192.168.0.1/login"],
            "headers": {"X-Mailer": "PhishKit/1.0"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] in ("phishing", "legit")

    def test_predict_saves_to_db(self, client, db_session):
        from agent.db import Prediction
        resp = client.post("/predict", json={
            "sender": "test@example.com",
            "subject": "DB test",
            "body": "Test body for DB saving",
        })
        assert resp.status_code == 200
        data = resp.json()
        # saved_id powinno być ustawione
        assert data.get("saved_id") is not None
        # Sprawdź że rekord istnieje w DB
        pred = db_session.query(Prediction).filter(
            Prediction.id == data["saved_id"]
        ).first()
        assert pred is not None
        assert pred.label in ("phishing", "legit")

    def test_predict_missing_body_returns_422(self, client):
        resp = client.post("/predict", json={"subject": "No body here"})
        assert resp.status_code == 422

    def test_predict_empty_body_accepted(self, client):
        # Puste body jest technicznie poprawne (walidacja nie wymaga min length)
        resp = client.post("/predict", json={"body": ""})
        assert resp.status_code == 200

    def test_predict_model_used_is_heuristic(self, client):
        resp = client.post("/predict", json={"body": "Test"})
        data = resp.json()
        # Model ML nie jest załadowany w testach
        assert data["model_used"] == "heuristic"

    def test_predict_reasons_is_list(self, client):
        resp = client.post("/predict", json={"body": "Some email"})
        data = resp.json()
        assert isinstance(data["reasons"], list)
        assert len(data["reasons"]) >= 1


# -----------------------------------------------------------------------------
# Testy: /model/info
# -----------------------------------------------------------------------------

class TestModelInfo:
    def test_model_info_returns_200(self, client):
        resp = client.get("/model/info")
        assert resp.status_code == 200

    def test_model_info_schema(self, client):
        resp = client.get("/model/info")
        data = resp.json()
        assert "model_type" in data
        assert "model_path" in data
        assert "is_ml_active" in data

    def test_model_info_ml_not_active(self, client):
        resp = client.get("/model/info")
        data = resp.json()
        # Model nie jest załadowany w testach
        assert data["is_ml_active"] is False
        assert data["model_type"] == "heuristic"
