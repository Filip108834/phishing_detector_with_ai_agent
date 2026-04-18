# Agent AI do detekcji phishingu

## Projekt pracy inżynierskiej

**Autor:** Filip Pich
**Środowisko:** Windows 11 + Visual Studio Code
**Język programowania:** Python 3.11

---

## Opis projektu

Repozytorium zawiera implementację systemu opracowywanego w ramach pracy inżynierskiej pt.:

**„Wykorzystanie agenta AI do detekcji phishingu - symulacja ataków i badanie skuteczności mechanizmów obronnych"**

Celem projektu jest zaprojektowanie i implementacja środowiska umożliwiającego:

- symulację ataków phishingowych w kontrolowanych warunkach laboratoryjnych (Gophish + MailHog),
- parsowanie i analizę treści wiadomości e-mail z wykorzystaniem NLP,
- klasyfikację wiadomości jako phishingowe lub bezpieczne przy użyciu ML,
- ocenę i porównanie skuteczności różnych modeli klasyfikacyjnych.

System integruje narzędzia do symulacji phishingu z pipeline'em analitycznym opartym na uczeniu maszynowym.

---

## Wykorzystane technologie

| Warstwa | Technologia | Wersja / uwagi |
|---|---|---|
| **Język** | Python | 3.11 |
| **API agenta** | FastAPI + Uvicorn | REST API z Swagger UI |
| **Baza danych** | PostgreSQL 16 | SQLAlchemy (psycopg3, dialekt `postgresql+psycopg`) |
| **ML pipeline** | scikit-learn | VotingClassifier (LR + RF + HistGBT), TF-IDF, StandardScaler |
| **Przetwarzanie tekstu** | NLTK | Tokenizacja, stopwords (EN+PL), NLTKTextPreprocessor |
| **NLP** | spaCy `en_core_web_sm` | NER, POS tagging, wykrywanie imperatywów |
| **Parsowanie e-mail** | Python `email` (stdlib) + BeautifulSoup/lxml | Dekodowanie MIME, ekstrakcja HTML |
| **Analiza URL** | tldextract | TLD, subdomen, entropia, reputacja |
| **Persystencja modelu** | joblib | Serializacja sklearn Pipeline |
| **Symulacja phishingu** | Gophish | Zarządzanie kampaniami przez REST API |
| **Przechwytywanie SMTP** | MailHog | Sandbox SMTP + API v2 (pobieranie .eml) |
| **Orkiestracja** | Docker Compose | Izolowane sieci `lab_internal`, `db_internal`, `host_access` |
| **Testowanie** | pytest | Testy jednostkowe, integracyjne, komponentowe |
| **Dane treningowe** | SpamAssassin Public Corpus | ~6000 wiadomości EN (spam + ham) |

---

## Wyniki eksperymentów

### Porównanie modeli (SpamAssassin, 1000 próbek/klasę, n=2050)

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|---|
| Logistic Regression | 0.9561 | 0.9796 | 0.9320 | 0.9552 | 0.9922 |
| Random Forest | 0.9878 | 1.0000 | 0.9757 | 0.9877 | 0.9975 |
| HistGradientBoosting | 0.9902 | 1.0000 | 0.9806 | 0.9902 | 0.9995 |
| **Ensemble (wybrany)** | **0.9902** | **0.9951** | **0.9854** | **0.9902** | **0.9982** |

CV 5-fold (Ensemble): F1=0.9902, AUC=0.9987 - brak oznak overfittingu.

### Klasyfikacja kampanii phishingowych

| Kampania | Model | TPR | TNR | F1 |
|---|---|---|---|---|
| Faza 5 (3 kampanie) | Heurystyczny | 0.0% | 100.0% | 0.000 |
| Faza 6 (3 kampanie) | ML Ensemble | 100.0% | 100.0% | 1.000 |

Raporty szczegółowe: `reports/kampania_01_raport.txt` i `reports/kampania_02_raport.txt`.

---

## Architektura systemu

```
campaign_generator.py
    → Gophish API (tworzy kampanię i wysyła przez SMTP)
    → MailHog (przechwytuje e-maile, eksport .eml)
    → POST /ingest/campaign/<nazwa>
    → Agent AI (FastAPI)
         ├── ParsedEmail (email_parser.py)
         ├── FeatureExtractor → 37 cech numerycznych + tekst TF-IDF
         ├── ML Pipeline: NLTKPreprocessor → TF-IDF + StandardScaler
         │                → VotingClassifier (LR + RF + HistGBT)
         │   lub Heuristic fallback (gdy brak modelu .joblib)
         └── PostgreSQL (zapis predykcji)
```

### Sieć Docker

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   MailHog   │  │   Gophish   │  │ PostgreSQL  │
│  SMTP :1025 │  │ Admin :3333 │  │  :5432      │
│  Web  :8025 │  │ Phish :8080 │  │ (db_intern.)│
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │    lab_internal │                │
       └────────┬────────┘       db_intern│
                │                         │
       ┌────────▼─────────────────────────▼──────┐
       │              AI Agent (FastAPI)          │
       │  :8000  |  lab_internal + db_internal    │
       │  + host_access (port-binding do hosta)  │
       └──────────────────────────────────────────┘
```

---

## Struktura projektu

```
phishing_detector_with_ai_agent/
├── agent/
│   ├── api/
│   │   ├── routes_ingest.py    # POST /ingest/campaign, POST /ingest/mailhog
│   │   ├── routes_predict.py   # POST /predict, POST /predict/raw
│   │   ├── routes_results.py   # GET /results, GET /results/stats
│   │   └── schemas.py          # Modele Pydantic
│   ├── features/
│   │   ├── extractor.py        # Główna ekstrakcja cech (37 feat_* + text)
│   │   ├── url_analyzer.py     # Analiza URL (entropia, TLD, IP, redirecty)
│   │   ├── nlp_analyzer.py     # Cechy spaCy (NER, POS, zdania)
│   │   └── text_preprocessor.py# NLTKTextPreprocessor (sklearn-compatible)
│   ├── ingestion/
│   │   ├── dataset_loader.py   # Ładowanie SpamAssassin / kampanii / Enron
│   │   ├── email_parser.py     # Parsowanie MIME → ParsedEmail
│   │   └── mailhog_poller.py   # Background poller MailHog
│   ├── ml/
│   │   └── pipeline.py         # build/train/evaluate/predict/save/load
│   ├── db.py                   # SQLAlchemy (Prediction model, engine)
│   ├── state.py                # Współdzielony stan modelu i pollera
│   └── main.py                 # FastAPI app, lifespan, /health
│
├── simulation/
│   ├── campaign_generator.py   # Generator kampanii end-to-end
│   ├── gophish_client.py       # Wrapper Gophish REST API
│   └── mailhog_client.py       # Klient MailHog API v2
│
├── experiments/
│   ├── train_model.py          # Trening / porównanie modeli (CLI)
│   └── results/                # JSON z metrykami każdego treningu
│
├── data/
│   ├── raw/                    # E-maile z kampanii (.eml + metadata.json)
│   ├── processed/              # Wektory cech (opcjonalnie)
│   └── datasets/               # SpamAssassin, Enron (git-ignored)
│
├── models/
│   └── classifier.joblib       # Wytrenowany Ensemble (git-ignored)
│
├── reports/
│   ├── kampania_01_raport.txt  # Faza 5: model heurystyczny
│   └── kampania_02_raport.txt  # Faza 6: model ML, wyniki porównawcze
│
├── tests/
│   ├── unit/                   # Testy jednostkowe (parser, extractor, URL)
│   ├── integration/            # Testy pipeline ML
│   └── component/              # Testy endpointów API (FastAPI TestClient)
│
├── scripts/
│   └── fetch_datasets.py       # Pobieranie SpamAssassin + instrukcja Enron
│
├── notebooks/
│   └── 01_eda.ipynb            # Eksploracyjna analiza danych
│
├── docker/
│   └── gophish/config.json     # Konfiguracja Gophish (porty, brak TLS)
│
├── .env.example                # Szablon zmiennych środowiskowych
├── docker-compose.yml          # Orkiestracja: MailHog, Gophish, PostgreSQL, agent
├── Dockerfile                  # Obraz agenta AI (python:3.11-slim)
├── requirements.txt
└── pytest.ini
```

---

## Szybki start

### 1. Klonowanie i konfiguracja

```bash
git clone <url-repozytorium>
cd phishing_detector_with_ai_agent
cp .env.example .env
```

### 2. Uruchomienie infrastruktury Docker

```bash
docker compose up -d
```

Serwisy dostępne z hosta:

| Serwis | URL | Opis |
|---|---|---|
| Agent AI | http://localhost:8000/docs | Swagger UI klasyfikatora |
| MailHog | http://localhost:8025 | Podgląd przechwyconych e-maili |
| Gophish (admin) | http://localhost:3333 | Panel zarządzania kampaniami |

### 3. Pobranie klucza API Gophish

```bash
docker compose logs gophish | grep "Please login"
# Wynik: Please login with the username admin and the password <HASLO>
```

Zaloguj się na http://localhost:3333 → Account Settings → skopiuj API Key do `.env`:

```bash
# Alternatywnie przez SQLite:
docker cp gophish:/opt/gophish/gophish.db /tmp/gophish.db
python -c "import sqlite3; c=sqlite3.connect('/tmp/gophish.db'); print(c.execute('SELECT api_key FROM users').fetchone()[0])"
```

Wklej klucz do `.env`:
```
GOPHISH_API_KEY=<skopiowany_klucz>
```

### 4. Instalacja lokalna (skrypty ML, kampanie)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows CMD
# lub: source .venv/Scripts/activate  # Git Bash / WSL

pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 5. Pobranie datasetów treningowych

```bash
python scripts/fetch_datasets.py --dataset spamassassin
# Pobiera ~6000 wiadomości SpamAssassin do data/datasets/spamassassin/
```

### 6. Generowanie kampanii phishingowych

```bash
# Ustaw zmienne środowiskowe (host łączy się z localhost, nie z wewnętrznymi adresami Docker)
export PYTHONIOENCODING=utf-8
export GOPHISH_API_URL=http://localhost:3333
export GOPHISH_API_KEY=<TWOJ_KLUCZ>
export MAILHOG_API_URL=http://localhost:8025
export SMTP_HOST=localhost
export SMTP_PORT=1025

# Kampanie phishingowe (3 szablony) + legit e-maile
python -m simulation.campaign_generator --mode phishing --template lab_phish_bank_alert --name campaign_bank_alert
curl -X DELETE http://localhost:8025/api/v1/messages

python -m simulation.campaign_generator --mode phishing --template lab_phish_password_reset --name campaign_password_reset
curl -X DELETE http://localhost:8025/api/v1/messages

python -m simulation.campaign_generator --mode phishing --template lab_phish_package_delivery --name campaign_package_delivery
curl -X DELETE http://localhost:8025/api/v1/messages

python -m simulation.campaign_generator --mode legit
```

Dostępne szablony phishingowe: `lab_phish_bank_alert`, `lab_phish_password_reset`, `lab_phish_package_delivery`.

### 7. Trenowanie modelu ML

```bash
# Porównanie wszystkich wariantów (LR, RF, GB, Ensemble)
python -m experiments.train_model --compare --max-per-class 1000

# Trening finalnego modelu z walidacją krzyżową i zapisem
python -m experiments.train_model --model ensemble --max-per-class 1000

# Opcje:
#   --model lr|rf|gb|ensemble   (domyślnie: ensemble)
#   --max-per-class N            (ogranicza próbki/klasę, przydatne do testów)
#   --no-cv                      (pomija walidację krzyżową)
#   --no-enron                   (wyklucza dataset Enron)
#   --no-save                    (nie zapisuje modelu)
```

Model zapisywany do `models/classifier.joblib`. Kontener agenta montuje ten katalog automatycznie.

### 8. Przeładowanie agenta z modelem ML

```bash
docker compose up -d ai-agent
curl http://localhost:8000/health
# Oczekiwane: {"status":"ok","model":"ml","poller":"running"}
```

### 9. Ingestion i klasyfikacja kampanii

```bash
curl -X POST http://localhost:8000/ingest/campaign/campaign_bank_alert
curl -X POST http://localhost:8000/ingest/campaign/campaign_password_reset
curl -X POST http://localhost:8000/ingest/campaign/campaign_package_delivery
curl -X POST http://localhost:8000/ingest/campaign/legit_batch_01

# Statystyki globalne
curl http://localhost:8000/results/stats
```

---

## Endpointy API agenta

| Metoda | Endpoint | Opis |
|---|---|---|
| `GET` | `/health` | Status serwisu (model type, poller) |
| `GET` | `/model/info` | Informacje o aktywnym modelu |
| `POST` | `/predict` | Klasyfikacja z JSON (sender, subject, body, urls) |
| `POST` | `/predict/raw` | Klasyfikacja z surowego MIME (.eml string) |
| `GET` | `/results` | Lista predykcji (filtrowanie po kampanii) |
| `GET` | `/results/stats` | Agregowane statystyki wszystkich predykcji |
| `GET` | `/results/{id}` | Szczegóły pojedynczej predykcji |
| `POST` | `/ingest/campaign/{name}` | Ingestion kampanii z data/raw/ |
| `POST` | `/ingest/mailhog` | Ingestion aktualnych wiadomości z MailHog |
| `DELETE` | `/ingest/mailhog/purge` | Czyszczenie skrzynki MailHog |
| `GET` | `/poller/status` | Stan background pollera MailHog |
| `GET` | `/docs` | Swagger UI |

Przykładowe żądanie:

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "alert@bank-fake.xyz",
    "subject": "PILNE: Zablokowano Twoje konto",
    "body": "Kliknij link aby odblokować konto natychmiast!",
    "urls": ["http://192.168.1.1/login"]
  }'
```

---

## Cechy modelu klasyfikacyjnego

### Cechy numeryczne (37 kolumn `feat_*`)

| Kategoria | Cechy |
|---|---|
| URL (11) | url_count, has_ip_url, has_suspicious_tld, has_url_keyword, has_at_in_url, has_redirect_param, max/avg_url_length, max_subdomain_depth, avg_url_entropy, url_domain_diversity |
| Nagłówki (11) | from_reply_to_mismatch, subject_urgency_score, subject_is_empty, subject_exclamation, from_is_freemail, has_html, has_attachments, spf_fail, received_hops, **xmailer_known_phish_tool**, **has_dkim** |
| Stylistyczne (3) | text_length, exclamation_density, caps_ratio |
| NLP / spaCy (12) | ner_org/money/date/cardinal, imperative_count, sentence_count, avg_sentence_len, exclaim_sentence_ratio, unique_token_ratio, verb/noun_density, function_word_ratio |

### Gałąź tekstowa

`NLTKTextPreprocessor(language=None)` → `TfidfVectorizer(ngram_range=(1,2), max_features=8000)`

Stopwords: angielskie (NLTK) + polskie (wbudowane). Stemming wyłączony (`language=None`) dla poprawnej obsługi języka polskiego.

### Klasyfikator

`VotingClassifier(soft)`:
- `LogisticRegression(C=1.0, class_weight=balanced)`
- `RandomForestClassifier(n_estimators=200, class_weight=balanced)`
- `HistGradientBoostingClassifier(max_iter=150, class_weight=balanced)`

---

## Testy

```bash
# Wszystkie testy
pytest

# Wybrana kategoria
pytest tests/unit/
pytest tests/integration/
pytest tests/component/
```

---

## Zmienne środowiskowe (`.env`)

| Zmienna | Opis | Przykład |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy connection string | `postgresql+psycopg://thesis:thesis@db:5432/phishing_lab` |
| `GOPHISH_API_URL` | URL panelu Gophish | `http://localhost:3333` |
| `GOPHISH_API_KEY` | Klucz API Gophish | `7de2ffe2...` |
| `MAILHOG_API_URL` | URL MailHog API | `http://localhost:8025` |
| `SMTP_HOST` | Host SMTP do wysyłki legit e-maili | `localhost` |
| `SMTP_PORT` | Port SMTP | `1025` |
| `PHISHING_THRESHOLD` | Próg klasyfikacji (domyślnie 0.5) | `0.5` |
| `MODEL_PATH` | Ścieżka do pliku modelu | `models/classifier.joblib` |
| `MAILHOG_POLLER_ENABLED` | Włącz/wyłącz background polling | `true` |
| `MAILHOG_POLL_INTERVAL` | Interwał pollera (sekundy) | `15` |

> **Uwaga dla kontenera Docker:** Używaj dialektu `postgresql+psycopg` (psycopg3), nie `psycopg2`.  
> **Uwaga dla hosta Windows:** Używaj `localhost` jako `GOPHISH_API_URL` i `MAILHOG_API_URL`, nie wewnętrznych nazw Docker.

---

## Znane ograniczenia

- **Domain shift URL-i:** Gophish generuje URL-e w formacie `http://gophish:8080?rid=xxx`, które nie wyzwalają reguł URL analizatora. Model nie uczy się wykrywać phishingu po wzorcach URL typowych dla rzeczywistych ataków.
- **Dominacja danych angielskich:** SpamAssassin to zbiór anglojęzyczny. Polskie kampanie stanowią < 2% zbioru treningowego. Model może niedoszacowywać polskie wzorce phishingu.
- **model spaCy:** `en_core_web_sm` to model angielski. Cechy NLP dla polskich tekstów (NER, POS, rozpoznawanie imperatywów) są ograniczonej jakości.
- **X-Mailer jako cecha dominująca:** Nagłówek `X-Mailer: gophish` jest unikalny dla środowiska laboratoryjnego i nieobecny w rzeczywistych atakach.
- **Brak niezależnej walidacji:** Kampanie laboratoryjne były częścią zbioru treningowego. Walidacja na zewnętrznym zbiorze polskich e-maili phishingowych jest wymagana przed wdrożeniem produkcyjnym.

---

## Informacja dotycząca bezpieczeństwa

Projekt wykorzystuje symulację ataków phishingowych wyłącznie w kontrolowanym środowisku badawczym i służy celom edukacyjnym oraz naukowym.

Środowisko laboratoryjne działa w izolowanej sieci Docker (`lab_internal: internal: true`) bez dostępu do sieci zewnętrznej. Wszystkie porty bindowane są wyłącznie na `127.0.0.1`. Hasła i klucze API nie są commitowane do repozytorium.

**Zabrania się używania tego oprogramowania do działań niezgodnych z prawem.**

---

## Licencja

Projekt udostępniony jest na licencji **MIT**.  
Szczegóły znajdują się w pliku `LICENSE`.
