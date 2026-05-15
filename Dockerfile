# =========================================================
# Stage 1: builder  -  kompilacja zależności C/C++ (lxml itp.)
# =========================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modele NLP pobrane raz w warstwie buildera (cache-friendly)
RUN python -m spacy download en_core_web_sm \
    && python -c "import nltk; [nltk.download(r, quiet=True) for r in ('punkt', 'punkt_tab', 'stopwords')]"

# =========================================================
# Stage 2: runtime  -  minimalny obraz produkcyjny
# =========================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Runtime libs dla lxml (bez build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Venv + modele NLP z buildera
COPY --from=builder /opt/venv /opt/venv

# Użytkownik bez uprawnień roota
RUN groupadd --system appgroup \
    && useradd --system --uid 1000 --gid appgroup --no-create-home appuser

WORKDIR /app

# Tylko kod aplikacji (reszta wykluczona przez .dockerignore)
COPY agent/ agent/

# Punkty montowania dla wolumenów (dane + model ML)
RUN mkdir -p data/raw data/processed data/datasets models \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=4s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
