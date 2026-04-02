# Agent AI do detekcji phishingu

## Projekt pracy inżynierskiej

**Autor:** Filip Pich
**Środowisko:** Windows 11 + Visual Studio Code
**Język programowania:** Python 3.11

---

## Opis projektu

Repozytorium zawiera implementację systemu opracowywanego w ramach pracy inżynierskiej pt.:

**„Wykorzystanie agenta AI do detekcji phishingu – symulacja ataków i badanie skuteczności mechanizmów obronnych"**

Celem projektu jest zaprojektowanie oraz implementacja środowiska umożliwiającego:

* symulację ataków phishingowych w kontrolowanych warunkach,
* analizę treści wiadomości e-mail z wykorzystaniem technik NLP,
* klasyfikację wiadomości jako phishingowe lub bezpieczne,
* ocenę skuteczności mechanizmów detekcji przy użyciu metod uczenia maszynowego.

System integruje narzędzia do symulacji phishingu z pipeline'em analitycznym opartym na sztucznej inteligencji.

**Projekt znajduje się w trakcie aktywnego rozwoju w ramach pracy inżynierskiej.**

---

## Główne komponenty systemu

| Moduł | Opis |
|---|---|
| `simulation/` | Generowanie kampanii phishingowych (Gophish + MailHog) |
| `agent/` | API klasyfikatora (FastAPI) + logika ML |
| `data/` | Surowe e-maile, przetworzone cechy, datasety publiczne |
| `experiments/` | Skrypty trenowania i ewaluacji modeli |
| `notebooks/` | Eksploracyjna analiza danych (EDA) |
| `models/` | Wytrenowane modele (wykluczone z Git) |
| `scripts/` | Skrypty pomocnicze (pobieranie datasetów) |
| `docs/` | Dokumentacja techniczna |

---

## Wykorzystane technologie

### Język i środowisko

* Python 3.11
* Docker + Docker Compose
* Visual Studio Code

### API agenta

* FastAPI + uvicorn
* pydantic v2

### Machine Learning i NLP

* scikit-learn
* pandas, numpy, scipy
* spaCy (`en_core_web_sm`)
* NLTK

### Parsowanie e-maili i analiza URL

* beautifulsoup4, lxml
* tldextract
* requests

### Symulacja phishingu

* Gophish (kampanie phishingowe)
* MailHog (testowy serwer SMTP/inbox)

### Analiza danych i eksperymenty

* Jupyter Notebook
* matplotlib, seaborn

### Baza danych

* PostgreSQL 16 (główna)
* SQLite (Gophish – wewnętrzna)

---

## Struktura projektu

```
phishing_detector_with_ai_agent/
│
├── agent/                      # Agent AI – FastAPI + logika klasyfikatora
│   ├── __init__.py
│   └── main.py                 # Endpointy /predict, /health + model baseline
│
├── simulation/                 # Moduł symulacji phishingu
│   ├── gophish_client.py       # Wrapper Gophish REST API
│   ├── mailhog_client.py       # Klient MailHog API (fetch + eksport .eml)
│   └── campaign_generator.py   # Skrypt generujący kampanie end-to-end
│
├── data/
│   ├── raw/                    # E-maile z kampanii Gophish (.eml) [git-ignored]
│   ├── processed/              # Wektory cech gotowe do trenowania [git-ignored]
│   └── datasets/               # Publiczne datasety (SpamAssassin, Enron) [git-ignored]
│
├── experiments/                # Skrypty trenowania i ewaluacji modeli
├── notebooks/                  # Notebooki Jupyter (EDA, wizualizacje)
├── models/                     # Wytrenowane modele (.pkl, .joblib) [git-ignored]
├── docs/                       # Dokumentacja techniczna
│
├── scripts/
│   └── fetch_datasets.py       # Pobieranie SpamAssassin + instrukcja Enron
│
├── docker/
│   └── gophish/
│       └── config.json         # Konfiguracja Gophish (porty, brak TLS)
│
├── .env.example                # Szablon zmiennych środowiskowych
├── docker-compose.yml          # Orkiestracja: MailHog, Gophish, PostgreSQL, agent
├── Dockerfile                  # Obraz agenta AI
└── requirements.txt
```

---

## Szybki start

### 1. Klonowanie repozytorium

```bash
git clone <url-repozytorium>
cd phishing_detector_with_ai_agent
```

### 2. Konfiguracja zmiennych środowiskowych

```bash
cp .env.example .env
# Edytuj .env – uzupełnij GOPHISH_API_KEY po pierwszym uruchomieniu (krok 4)
```

### 3. Uruchomienie środowiska laboratoryjnego

```bash
docker compose up -d
```

Serwisy dostępne po starcie:

| Serwis | URL | Opis |
|---|---|---|
| Gophish (admin) | http://localhost:3333 | Panel zarządzania kampaniami |
| MailHog | http://localhost:8025 | Podgląd przechwyconych e-maili |
| Agent AI | http://localhost:8000/docs | Swagger UI klasyfikatora |

### 4. Pobranie klucza API Gophish

Przy pierwszym uruchomieniu Gophish losuje hasło admina i wypisuje je do logów:

```bash
docker compose logs gophish | grep "Please login"
```

Zaloguj się na http://localhost:3333, przejdź do **Account Settings** i skopiuj **API Key** do `.env`:

```
GOPHISH_API_KEY=<skopiowany_klucz>
```

### 5. Pobranie publicznych datasetów

```bash
python scripts/fetch_datasets.py
```

Pobiera SpamAssassin Public Corpus (~3700 wiadomości) do `data/datasets/`.
Instrukcja pobrania datasetu Enron wyświetlona w terminalu.

### 6. Generowanie danych z kampanii

```bash
# Aktywuj środowisko wirtualne (lokalnie)
python -m venv .venv
.venv\Scripts\activate      # Windows CMD
# lub: source .venv/Scripts/activate  # Git Bash / WSL

pip install -r requirements.txt

# Wygeneruj kampanie phishingowe i legit e-maile
python -m simulation.campaign_generator --mode all
```

Wiadomości trafiają do `data/raw/<nazwa_kampanii>/` wraz z `metadata.json` (etykiety).

---

## Lokalna instalacja (bez Dockera)

Wymagana tylko dla uruchamiania skryptów ML / notebooków poza kontenerem.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows CMD
# lub: source .venv/Scripts/activate  # Git Bash / WSL

pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

Jupyter Notebook:

```bash
jupyter notebook
```

---

## Endpointy API agenta

| Metoda | Endpoint | Opis |
|---|---|---|
| `GET` | `/health` | Sprawdzenie stanu serwisu i połączenia z DB |
| `POST` | `/predict` | Klasyfikacja wiadomości e-mail |
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

## Metryki oceny modeli

Skuteczność systemu oceniana jest z wykorzystaniem standardowych metryk klasyfikacyjnych:

* Accuracy, Precision, Recall, F1-score (macro + weighted)
* ROC AUC, Precision-Recall curve
* Confusion Matrix
* False Positive Rate (kluczowe w systemach bezpieczeństwa)

---

## Informacja dotycząca bezpieczeństwa

Projekt wykorzystuje symulację ataków phishingowych wyłącznie w kontrolowanym środowisku badawczym i służy celom edukacyjnym oraz naukowym.

Środowisko laboratoryjne działa w izolowanej sieci Docker (`lab_internal`) bez dostępu do internetu. Wszystkie porty bindowane są na `127.0.0.1`.

**Zabrania się używania tego oprogramowania do działań niezgodnych z prawem.**

---

## Licencja

Projekt udostępniony jest na licencji **MIT**.
Szczegóły znajdują się w pliku `LICENSE`.
