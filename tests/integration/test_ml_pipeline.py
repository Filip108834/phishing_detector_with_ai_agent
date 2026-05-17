"""
Testy integracyjne: agent/ml/pipeline.py

Weryfikują pełny cykl ML:
    build_pipeline -> train -> predict -> evaluate -> save -> load

Używa minimalnego zbioru danych (20 próbek) i prostego modelu "lr"
(LogisticRegression), żeby testy były szybkie.
"""
import pandas as pd
import pytest

from agent.features.extractor import NUMERICAL_FEATURE_COLS, extract
from agent.ingestion.email_parser import ParsedEmail
from agent.ml import pipeline as ml


# -----------------------------------------------------------------------------
# Helpersy
# -----------------------------------------------------------------------------

PHISHING_TEXTS = [
    "URGENT: verify your account login password suspended click now",
    "Your account has been blocked. Verify credentials immediately.",
    "Click here to confirm: http://192.168.1.1/verify account disabled",
    "ACTION REQUIRED: update your password now or lose access",
    "Security alert: suspicious activity detected. Confirm identity.",
    "Your Microsoft password expired. Reset now: http://reset.tk/login",
    "ALERT! Bank account suspended. Verify login credentials now!",
    "Confirm your PayPal details or account will be permanently blocked",
    "Limited time: verify your Amazon account. Sign in immediately.",
    "Your account will be disabled. Click to verify: http://evil.xyz/update",
]

LEGIT_TEXTS = [
    "Hi team, sprint review is tomorrow at 10am in room A2. See you there.",
    "Monthly IT newsletter: new server migration completed successfully.",
    "Meeting invite: product planning session on Friday at 2pm.",
    "Reminder: submit your timesheets by end of day Friday.",
    "Please find attached the Q1 report for your review.",
    "Team lunch is scheduled for Thursday at 12pm at the usual place.",
    "New wiki article published: deployment guide for production.",
    "HR update: new vacation policy effective from next month.",
    "Congratulations on completing the training module successfully.",
    "Weekly standup notes are now available in the shared folder.",
]


def _make_feature_df(phishing_texts: list[str], legit_texts: list[str]):
    """Tworzy minimalny DataFrame cech z podanych tekstów."""
    rows = []
    labels = []

    for text in phishing_texts:
        parsed = ParsedEmail.from_request(sender="s@s.com", subject="", body=text)
        rows.append(extract(parsed))
        labels.append(1)

    for text in legit_texts:
        parsed = ParsedEmail.from_request(sender="s@s.com", subject="", body=text)
        rows.append(extract(parsed))
        labels.append(0)

    X = pd.DataFrame(rows)
    y = pd.Series(labels)

    # Wypełnij brakujące wartości numeryczne
    num_cols = [c for c in X.columns if c.startswith("feat_")]
    X[num_cols] = X[num_cols].fillna(0.0)
    X["text"] = X["text"].fillna("").astype(str)
    return X, y


# -----------------------------------------------------------------------------
# Testy: budowanie pipeline'u
# -----------------------------------------------------------------------------

class TestBuildPipeline:
    def test_build_returns_pipeline(self):
        pipe = ml.build_pipeline("lr")
        assert pipe is not None

    def test_pipeline_has_preprocessor(self):
        pipe = ml.build_pipeline("lr")
        assert "preprocessor" in pipe.named_steps

    def test_pipeline_has_classifier(self):
        pipe = ml.build_pipeline("lr")
        assert "classifier" in pipe.named_steps

    @pytest.mark.parametrize("model_name", ["lr", "rf", "gb", "ensemble"])
    def test_all_model_variants_build(self, model_name):
        pipe = ml.build_pipeline(model_name)
        assert pipe is not None

    def test_invalid_model_raises_value_error(self):
        with pytest.raises(ValueError, match="Nieznany model"):
            ml.build_pipeline("invalid_model_name")


# -----------------------------------------------------------------------------
# Testy: trening i predykcja
# -----------------------------------------------------------------------------

class TestTrainAndPredict:
    @pytest.fixture(scope="class")
    def trained_pipeline(self):
        """Pipeline wytrenowany raz na wszystkie testy w klasie."""
        X, y = _make_feature_df(PHISHING_TEXTS, LEGIT_TEXTS)
        pipe = ml.build_pipeline("lr")
        return ml.train(pipe, X, y)

    def test_train_returns_pipeline(self):
        X, y = _make_feature_df(PHISHING_TEXTS[:5], LEGIT_TEXTS[:5])
        pipe = ml.build_pipeline("lr")
        result = ml.train(pipe, X, y)
        assert result is pipe

    def test_predict_email_returns_tuple(self, trained_pipeline):
        parsed = ParsedEmail.from_request(
            sender="s@s.com",
            subject="",
            body="URGENT: verify your account now!",
        )
        label, score, reasons = ml.predict_email(trained_pipeline, parsed)
        assert label in ("phishing", "legit")
        assert 0.0 <= score <= 1.0
        assert isinstance(reasons, list)
        assert len(reasons) >= 1

    def test_phishing_email_high_score(self, trained_pipeline):
        parsed = ParsedEmail.from_request(
            sender="s@s.com",
            subject="",
            body="URGENT: verify your account login credentials now suspended",
        )
        _, score, _ = ml.predict_email(trained_pipeline, parsed)
        # Wytrenowany model powinien dawać wyższy score dla phishingu
        assert score > 0.3  # luźny próg - mały zbiór treningowy

    def test_legit_email_low_score(self, trained_pipeline):
        parsed = ParsedEmail.from_request(
            sender="hr@company.com",
            subject="",
            body="Hi team, sprint review is tomorrow at 10am. See you there.",
        )
        _, score, _ = ml.predict_email(trained_pipeline, parsed)
        assert score < 0.8  # luźny próg

    def test_predict_reasons_is_list_of_strings(self, trained_pipeline):
        parsed = ParsedEmail.from_request(
            sender="s@s.com", subject="", body="test"
        )
        _, _, reasons = ml.predict_email(trained_pipeline, parsed)
        assert all(isinstance(r, str) for r in reasons)


# -----------------------------------------------------------------------------
# Testy: ewaluacja
# -----------------------------------------------------------------------------

class TestEvaluate:
    @pytest.fixture(scope="class")
    def eval_metrics(self):
        """Pipeline wytrenowany raz; metryki obliczone raz dla całej klasy."""
        X, y = _make_feature_df(PHISHING_TEXTS, LEGIT_TEXTS)
        pipe = ml.build_pipeline("lr")
        ml.train(pipe, X, y)
        return ml.evaluate(pipe, X, y)

    def test_evaluate_returns_required_metrics(self, eval_metrics):
        required = {"accuracy", "precision", "recall", "f1", "roc_auc",
                    "confusion_matrix", "classification_report"}
        assert required.issubset(eval_metrics.keys())

    def test_evaluate_accuracy_in_range(self, eval_metrics):
        assert 0.0 <= eval_metrics["accuracy"] <= 1.0

    def test_evaluate_confusion_matrix_shape(self, eval_metrics):
        cm = eval_metrics["confusion_matrix"]
        assert len(cm) == 2
        assert len(cm[0]) == 2


# -----------------------------------------------------------------------------
# Testy: zapis i odczyt modelu
# -----------------------------------------------------------------------------

class TestSaveLoad:
    def test_save_creates_file(self, tmp_path):
        X, y = _make_feature_df(PHISHING_TEXTS[:5], LEGIT_TEXTS[:5])
        pipe = ml.build_pipeline("lr")
        ml.train(pipe, X, y)
        path = tmp_path / "test_model.joblib"
        ml.save(pipe, path)
        assert path.exists()

    def test_load_returns_none_for_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.joblib"
        result = ml.load(path)
        assert result is None

    def test_save_then_load_preserves_predictions(self, tmp_path):
        X, y = _make_feature_df(PHISHING_TEXTS, LEGIT_TEXTS)
        pipe = ml.build_pipeline("lr")
        ml.train(pipe, X, y)

        path = tmp_path / "roundtrip.joblib"
        ml.save(pipe, path)
        loaded = ml.load(path)

        assert loaded is not None

        # Predykcje przed i po save/load powinny być identyczne
        parsed = ParsedEmail.from_request(
            sender="s@s.com",
            subject="URGENT verify",
            body="Click to confirm account suspended",
        )
        label_orig, score_orig, _ = ml.predict_email(pipe, parsed)
        label_load, score_load, _ = ml.predict_email(loaded, parsed)
        assert label_orig == label_load
        assert abs(score_orig - score_load) < 1e-6
