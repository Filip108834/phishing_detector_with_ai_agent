"""
Testy komponentowe: GET /results, GET /results/stats, GET /results/{id}

Używa prawdziwego TestClient + SQLite. Dane są wstawiane bezpośrednio przez
ORM lub przez endpoint /predict.
"""
import pytest

from agent.db import Prediction


def _insert_prediction(db_session, label="phishing", model="heuristic", campaign=None):
    """Pomocnik: wstawia rekord Prediction do bazy testowej."""
    pred = Prediction(
        sender="test@example.com",
        subject="Test",
        body_snippet="Test body",
        score=0.85 if label == "phishing" else 0.1,
        label=label,
        reasons="[]",
        model_used=model,
        campaign=campaign,
    )
    db_session.add(pred)
    db_session.commit()
    db_session.refresh(pred)
    return pred


# -----------------------------------------------------------------------------
# Testy: GET /results
# -----------------------------------------------------------------------------

class TestResultsList:
    def test_empty_db_returns_empty_list(self, client):
        resp = client.get("/results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_returns_inserted_predictions(self, client, db_session):
        _insert_prediction(db_session, label="phishing")
        _insert_prediction(db_session, label="legit")
        resp = client.get("/results")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_response_schema(self, client, db_session):
        _insert_prediction(db_session)
        resp = client.get("/results")
        item = resp.json()["items"][0]
        assert "id" in item
        assert "label" in item
        assert "score" in item
        assert "model_used" in item
        assert "created_at" in item

    def test_filter_by_label_phishing(self, client, db_session):
        _insert_prediction(db_session, label="phishing")
        _insert_prediction(db_session, label="legit")
        resp = client.get("/results?label=phishing")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["label"] == "phishing"

    def test_filter_by_label_legit(self, client, db_session):
        _insert_prediction(db_session, label="phishing")
        _insert_prediction(db_session, label="legit")
        resp = client.get("/results?label=legit")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["label"] == "legit"

    def test_filter_by_model_used(self, client, db_session):
        _insert_prediction(db_session, model="heuristic")
        _insert_prediction(db_session, model="ml")
        resp = client.get("/results?model_used=ml")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["model_used"] == "ml"

    def test_filter_by_campaign(self, client, db_session):
        _insert_prediction(db_session, campaign="campaign_01")
        _insert_prediction(db_session, campaign="campaign_02")
        resp = client.get("/results?campaign=campaign_01")
        data = resp.json()
        assert data["total"] == 1

    def test_pagination_limit(self, client, db_session):
        for _ in range(5):
            _insert_prediction(db_session)
        resp = client.get("/results?limit=3")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 3

    def test_pagination_offset(self, client, db_session):
        for _ in range(5):
            _insert_prediction(db_session)
        resp = client.get("/results?limit=3&offset=3")
        data = resp.json()
        assert len(data["items"]) == 2  # pozostałe 2

    def test_limit_too_large_returns_422(self, client):
        resp = client.get("/results?limit=999")
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client):
        resp = client.get("/results?limit=0")
        assert resp.status_code == 422


# -----------------------------------------------------------------------------
# Testy: GET /results/stats
# -----------------------------------------------------------------------------

class TestResultsStats:
    def test_stats_empty_db(self, client):
        resp = client.get("/results/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_predictions"] == 0
        assert data["phishing_count"] == 0
        assert data["legit_count"] == 0
        assert data["phishing_ratio"] == 0.0

    def test_stats_with_data(self, client, db_session):
        _insert_prediction(db_session, label="phishing")
        _insert_prediction(db_session, label="phishing")
        _insert_prediction(db_session, label="legit")
        resp = client.get("/results/stats")
        data = resp.json()
        assert data["total_predictions"] == 3
        assert data["phishing_count"] == 2
        assert data["legit_count"] == 1
        assert abs(data["phishing_ratio"] - 2 / 3) < 0.001

    def test_stats_campaigns_listed(self, client, db_session):
        _insert_prediction(db_session, campaign="alpha")
        _insert_prediction(db_session, campaign="beta")
        _insert_prediction(db_session, campaign=None)
        resp = client.get("/results/stats")
        data = resp.json()
        assert "alpha" in data["campaigns"]
        assert "beta" in data["campaigns"]
        assert None not in data["campaigns"]

    def test_stats_model_counts(self, client, db_session):
        _insert_prediction(db_session, model="heuristic")
        _insert_prediction(db_session, model="heuristic")
        _insert_prediction(db_session, model="ml")
        resp = client.get("/results/stats")
        data = resp.json()
        assert data["heuristic_predictions"] == 2
        assert data["ml_predictions"] == 1


# -----------------------------------------------------------------------------
# Testy: GET /results/{id}
# -----------------------------------------------------------------------------

class TestResultById:
    def test_get_existing_prediction(self, client, db_session):
        pred = _insert_prediction(db_session, label="phishing")
        resp = client.get(f"/results/{pred.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == pred.id
        assert data["label"] == "phishing"

    def test_get_missing_prediction_returns_404(self, client):
        resp = client.get("/results/999999")
        assert resp.status_code == 404

    def test_get_by_id_schema(self, client, db_session):
        pred = _insert_prediction(db_session)
        resp = client.get(f"/results/{pred.id}")
        data = resp.json()
        required_keys = {"id", "label", "score", "model_used", "created_at"}
        assert required_keys.issubset(data.keys())


# -----------------------------------------------------------------------------
# Testy: GET /results/campaign/{name}
# -----------------------------------------------------------------------------

class TestResultsByCampaign:
    def test_campaign_results_found(self, client, db_session):
        _insert_prediction(db_session, campaign="test_campaign")
        _insert_prediction(db_session, campaign="test_campaign")
        _insert_prediction(db_session, campaign="other_campaign")
        resp = client.get("/results/campaign/test_campaign")
        data = resp.json()
        assert data["total"] == 2

    def test_empty_campaign_returns_zero(self, client):
        resp = client.get("/results/campaign/nonexistent")
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []
