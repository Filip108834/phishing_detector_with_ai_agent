# Agent AI do detekcji phishingu

## Projekt pracy inżynierskiej

**Autor:** Filip Pich
**Środowisko:** Windows 10 / Windows 11 + Visual Studio Code
**Język programowania:** Python 3.10+

---

## Opis projektu

Repozytorium zawiera implementację systemu opracowywanego w ramach pracy inżynierskiej pt.:

**„Wykorzystanie agenta AI do detekcji phishingu – symulacja ataków i badanie skuteczności mechanizmów obronnych”**

Celem projektu jest zaprojektowanie oraz implementacja środowiska umożliwiającego:

* symulację ataków phishingowych w kontrolowanych warunkach,
* analizę treści wiadomości e-mail z wykorzystaniem technik NLP,
* klasyfikację wiadomości jako phishingowe lub bezpieczne,
* ocenę skuteczności mechanizmów detekcji przy użyciu metod uczenia maszynowego.

System integruje narzędzia do symulacji phishingu z pipeline’em analitycznym opartym na sztucznej inteligencji.

**Projekt znajduje się w trakcie aktywnego rozwoju w ramach pracy inżynierskiej.**

---

## Główne komponenty systemu

Architektura rozwiązania obejmuje następujące moduły:

* **Moduł symulacji phishingu** – generowanie kampanii testowych (np. Gophish),
* **Moduł pozyskiwania wiadomości** – pobieranie i parsowanie e-maili,
* **Agent AI** – analiza treści, ekstrakcja cech oraz klasyfikacja,
* **Warstwa przechowywania danych** – zapisywanie wyników i predykcji,
* **Moduł ewaluacji** – analiza skuteczności modeli.

---

## Wykorzystane technologie

### Język i środowisko

* Python 3.10+
* Windows 11
* Visual Studio Code
* Git

### Machine Learning i NLP

* scikit-learn
* pandas
* numpy
* spaCy
* NLTK

### Symulacja phishingu

* Gophish
* MailHog lub testowy serwer SMTP

### Analiza danych i eksperymenty

* Jupyter Notebook
* matplotlib
* seaborn

### Konteneryzacja

* Docker
* Docker Compose

### Baza danych

* SQLite (domyślnie)
* PostgreSQL (opcjonalnie)

---

## Struktura projektu

```
project-root/
│
├── agent/              # Implementacja agenta AI
├── data/               # Zbiory danych (raw / processed / sample)
├── experiments/        # Skrypty eksperymentalne
├── notebooks/          # Notebooki Jupyter
├── docker/             # Konfiguracja kontenerów
├── models/             # Wytrenowane modele (ignorowane w Git)
├── docs/               # Dokumentacja techniczna
│
├── requirements.txt
├── docker-compose.yml
├── README.md
└── .gitignore
```

---

## Instalacja (Windows)

### 1. Klonowanie repozytorium

```bash
git clone https://github.com/twoj-login/twoje-repo.git
cd twoje-repo
```

---

### 2. Utworzenie środowiska wirtualnego

```bash
python -m venv .venv
source .venv\Scripts\activate
```

---

### 3. Instalacja zależności (wymagane dodatkowe kroki dla wybranego modelu języka 3.1 lub 3.2)

```bash
pip install -r requirements.txt
```

#### 3.1 Model językowy dla spyCy (polski)

```bash
python -m spacy download en_core_web_sm
```

---

#### 3.2 Model językowy dla spyCy (angielski)

```bash
python -m spacy download en_core_web_sm
```

---

### 4. Uruchomienie Jupyter Notebook (opcjonalnie)

```bash
jupyter notebook
```

---

## Uruchomienie z użyciem Dockera (opcjonalnie)

Po zainstalowaniu **Docker Desktop**:

```bash
docker-compose up --build
```

---

## Uruchamianie eksperymentów

Przykład trenowania modelu:

```bash
python experiments/train_model.py
```

Przykład ewaluacji:

```bash
python experiments/evaluate.py
```

---

## Metryki oceny modeli

Skuteczność systemu oceniana jest z wykorzystaniem standardowych metryk klasyfikacyjnych:

* Accuracy
* Precision
* Recall
* F1-score
* Confusion Matrix

---

## Informacja dotycząca bezpieczeństwa

Projekt wykorzystuje symulację ataków phishingowych wyłącznie w kontrolowanym środowisku badawczym i służy celom edukacyjnym oraz naukowym.

**Zabrania się używania tego oprogramowania do działań niezgodnych z prawem.**

---

## Licencja

Projekt udostępniony jest na licencji **MIT**.
Szczegóły znajdują się w pliku `LICENSE`.

---

## Kontekst pracy dyplomowej

Repozytorium zawiera część implementacyjną pracy inżynierskiej.
Podstawy teoretyczne, metodologia badań oraz analiza wyników zostały opisane w pracy pisemnej.

---

## Możliwe kierunki dalszego rozwoju

* zastosowanie modeli deep learning (np. Transformer),
* integracja z bramą pocztową w czasie rzeczywistym,
* rozwój modułu Explainable AI,
* wdrożenie w architekturze mikroserwisowej,
* stworzenie interfejsu webowego do zarządzania eksperymentami.
