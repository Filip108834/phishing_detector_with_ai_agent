"""
Pobieranie publicznych zbiorów danych do trenowania klasyfikatora.

Uruchomienie:
    python scripts/fetch_datasets.py [--dataset all|spamassassin|enron]

Obsługiwane datasety:
    1. SpamAssassin Public Corpus (pobierany automatycznie przez HTTP)
       - easy_ham (2500 wiadomości)
       - hard_ham (250 wiadomości)
       - spam     (500 wiadomości)

    2. Enron Email Dataset (wymaga ręcznego pobrania - instrukcja poniżej)

    3. CEAS 2008 (alternatywa: UCI Spam dataset - pobierany automatycznie)

Struktura wyjściowa:
    data/datasets/
    ├── spamassassin/
    │   ├── easy_ham/   *.eml  (label: legit)
    │   ├── hard_ham/   *.eml  (label: legit)
    │   └── spam/       *.eml  (label: spam/phishing)
    ├── enron/          (po ręcznym pobraniu)
    └── manifest.json   (podsumowanie zbiorów)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Konfiguracja datasetów
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("data/datasets")

SPAMASSASSIN_BASE = "https://spamassassin.apache.org/old/publiccorpus"

SPAMASSASSIN_FILES = [
    # (nazwa_pliku, nazwa_katalogu_docelowego, label)
    ("20030228_easy_ham.tar.bz2",  "easy_ham",  "legit"),
    ("20030228_hard_ham.tar.bz2",  "hard_ham",  "legit"),
    ("20030228_spam.tar.bz2",      "spam",      "spam"),
    ("20030228_spam_2.tar.bz2",    "spam_2",    "spam"),
    ("20030228_easy_ham_2.tar.bz2","easy_ham_2","legit"),
]

ENRON_INSTRUCTIONS = """
=== Enron Email Dataset - instrukcja pobierania ===

Dataset jest za duży na automatyczne pobieranie (~430 MB skompresowany, ~2.5 GB rozpakowany).
Dostępny jest na Kaggle:

1. Zainstaluj Kaggle CLI:
       pip install kaggle

2. Skonfiguruj token API (kaggle.com -> Account -> API -> Create New Token):
       mkdir -p ~/.kaggle && cp kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json

3. Pobierz dataset:
       kaggle datasets download -d wcukierski/enron-email-dataset -p data/datasets/

4. Wypakuj:
       cd data/datasets && unzip enron-email-dataset.zip -d enron/

5. Struktura po wypakowaniu:
       data/datasets/enron/
       └── emails.csv   (~517 000 wiadomości)

Alternatywnie: dataset jest dostępny bezpośrednio na CMU:
    https://www.cs.cmu.edu/~enron/

=================================================
"""


# ---------------------------------------------------------------------------
# SpamAssassin
# ---------------------------------------------------------------------------

def fetch_spamassassin(force: bool = False) -> dict[str, int]:
    """Pobiera i rozpakowuje SpamAssassin Public Corpus."""
    out_base = OUTPUT_DIR / "spamassassin"
    out_base.mkdir(parents=True, exist_ok=True)

    tmp_dir = OUTPUT_DIR / "_tmp"
    tmp_dir.mkdir(exist_ok=True)

    counts: dict[str, int] = {}

    for filename, target_dir, label in SPAMASSASSIN_FILES:
        dest_dir = out_base / target_dir

        if dest_dir.exists() and any(dest_dir.iterdir()) and not force:
            n = len(list(dest_dir.glob("*")))
            print(f"  [skip] {target_dir} – już pobrany ({n} plików)")
            counts[target_dir] = n
            continue

        url = f"{SPAMASSASSIN_BASE}/{filename}"
        tmp_path = tmp_dir / filename

        print(f"  [->] Pobieranie {filename} …")
        try:
            _download(url, tmp_path)
        except Exception as e:
            print(f"  [!]  Błąd pobierania {filename}: {e}")
            continue

        print(f"  [->] Rozpakowywanie → {dest_dir}/")
        dest_dir.mkdir(parents=True, exist_ok=True)

        try:
            with tarfile.open(tmp_path, "r:bz2") as tar:
                for member in tar.getmembers():
                    # Pomijamy katalogi i pliki CMDs (indeksy SpamAssassin)
                    if member.isfile() and not member.name.endswith("cmds"):
                        member.name = Path(member.name).name  # spłaszcz ścieżkę
                        tar.extract(member, dest_dir)

            n = len(list(dest_dir.glob("*")))
            counts[target_dir] = n
            print(f"  [+]  {target_dir}: {n} wiadomości (label={label})")
            tmp_path.unlink(missing_ok=True)

        except Exception as e:
            print(f"  [!]  Błąd rozpakowywania {filename}: {e}")

    # Posprzątaj tmp
    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    return counts


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_manifest(spamassassin_counts: dict[str, int]) -> None:
    """Zapisuje podsumowanie zebranych zbiorów do manifest.json."""
    manifest = {
        "generated_at": datetime.utcnow().isoformat(),
        "datasets": {
            "spamassassin": {
                "path": "data/datasets/spamassassin/",
                "source": SPAMASSASSIN_BASE,
                "subsets": [
                    {
                        "name": name,
                        "label": label,
                        "count": spamassassin_counts.get(name, 0),
                    }
                    for _, name, label in SPAMASSASSIN_FILES
                ],
                "total": sum(spamassassin_counts.values()),
            },
            "enron": {
                "path": "data/datasets/enron/",
                "source": "https://www.kaggle.com/datasets/wcukierski/enron-email-dataset",
                "note": "Wymaga ręcznego pobrania - patrz ENRON_INSTRUCTIONS w scripts/fetch_datasets.py",
                "total": _count_enron(),
            },
            "lab_campaigns": {
                "path": "data/raw/",
                "source": "Gophish + MailHog (środowisko laboratoryjne)",
                "note": "Generowane przez simulation/campaign_generator.py",
            },
        },
    }

    path = OUTPUT_DIR / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[+] Manifest zapisany → {path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path, chunk_size: int = 65536) -> None:
    """Pobiera plik z podanego URL z paskiem postępu."""
    req = urllib.request.Request(url, headers={"User-Agent": "PhishingDetector/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r       {pct:5.1f}%  ({downloaded // 1024} KB / {total // 1024} KB)", end="", flush=True)
        print()


def _count_enron() -> int:
    enron_path = OUTPUT_DIR / "enron"
    if not enron_path.exists():
        return 0
    csv_files = list(enron_path.glob("*.csv"))
    if csv_files:
        # Zlicz wiersze w emails.csv (minus nagłówek)
        try:
            with open(csv_files[0], encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f) - 1
        except Exception:
            return 0
    return sum(1 for _ in enron_path.rglob("*") if _.is_file())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pobieranie publicznych datasetów e-mail")
    parser.add_argument(
        "--dataset",
        choices=["all", "spamassassin", "enron"],
        default="all",
        help="Który dataset pobrać (domyślnie: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pobierz ponownie nawet jeśli dane już istnieją",
    )
    args = parser.parse_args()

    print("=" * 55)
    print("  Pobieranie zbiorów danych do trenowania klasyfikatora")
    print("=" * 55)

    sa_counts: dict[str, int] = {}

    if args.dataset in ("all", "spamassassin"):
        print("\n[SpamAssassin Public Corpus]")
        sa_counts = fetch_spamassassin(force=args.force)

    if args.dataset in ("all", "enron"):
        print("\n[Enron Email Dataset]")
        print(ENRON_INSTRUCTIONS)

    write_manifest(sa_counts)

    print("\n[=] Gotowe. Następny krok:")
    print("    python -m simulation.campaign_generator --mode all")
