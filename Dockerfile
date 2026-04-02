FROM python:3.11-slim

# Lepsze logi i brak .pyc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Zależności systemowe pod lxml // parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalacja zależności Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kod
COPY . .

#TBD
EXPOSE 8000

#TBD
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
 