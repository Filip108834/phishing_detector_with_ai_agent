"""
Skrypt generujący kampanie phishingowe w środowisku laboratoryjnym.

Uruchomienie:
    python -m simulation.campaign_generator

Wymagania:
    - Gophish: http://localhost:3333  (GOPHISH_API_URL)
    - MailHog:  http://localhost:8025 (MAILHOG_API_URL)
    - Klucz API Gophish w zmiennej środowiskowej GOPHISH_API_KEY

Kroki skryptu:
    1. Weryfikacja połączeń
    2. Tworzenie profilu wysyłkowego (SMTP ->MailHog)
    3. Tworzenie szablonów e-mail (phishing x3 + legit x2)
    4. Tworzenie landing page
    5. Tworzenie grupy testowych odbiorców
    6. Uruchomienie kampanii
    7. Eksport wiadomości z MailHog do data/raw/<campaign_name>/
    8. Zapis metadanych kampanii do data/raw/<campaign_name>/metadata.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from simulation.gophish_client import (
    Campaign,
    EmailTemplate,
    GophishClient,
    LandingPage,
    SendingProfile,
    TargetUser,
    UserGroup,
)
from simulation.mailhog_client import MailHogClient

load_dotenv()

# ---------------------------------------------------------------------------
# Konfiguracja ze zmiennych środowiskowych
# ---------------------------------------------------------------------------

GOPHISH_API_URL = os.getenv("GOPHISH_API_URL", "http://localhost:3333")
GOPHISH_API_KEY = os.getenv("GOPHISH_API_KEY", "")
MAILHOG_API_URL = os.getenv("MAILHOG_API_URL", "http://localhost:8025")

OUTPUT_BASE = Path("data/raw")

# ---------------------------------------------------------------------------
# Szablony e-mail
# ---------------------------------------------------------------------------

PHISHING_TEMPLATES: list[dict] = [
    {
        "name": "lab_phish_bank_alert",
        "subject": "PILNE: Zablokowano Twoje konto bankowe",
        "text": (
            "Szanowny Kliencie,\n\n"
            "Wykryliśmy podejrzaną aktywność na Twoim koncie. "
            "Aby odblokować dostęp, kliknij poniższy link i potwierdź swoje dane:\n\n"
            "{{.URL}}\n\n"
            "Jeśli nie zrealizujesz weryfikacji w ciągu 24 godzin, konto zostanie trwale zablokowane.\n\n"
            "Zespół Bezpieczeństwa"
        ),
        "html": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:#c0392b;padding:16px;color:white;text-align:center">
    <h2>&#9888; ALERT BEZPIECZEŃSTWA</h2>
  </div>
  <div style="padding:24px;border:1px solid #ddd">
    <p>Szanowny Kliencie,</p>
    <p>Wykryliśmy <strong>podejrzaną aktywność</strong> na Twoim koncie.</p>
    <p>Aby uniknąć trwałego zablokowania, natychmiast potwierdź swoje dane:</p>
    <p style="text-align:center;margin:32px 0">
      <a href="{{.URL}}" style="background:#c0392b;color:white;padding:14px 28px;
         text-decoration:none;border-radius:4px;font-weight:bold">
        ZWERYFIKUJ KONTO TERAZ
      </a>
    </p>
    <p style="color:#888;font-size:12px">
      Masz 24 godziny na potwierdzenie. Brak akcji = trwała blokada konta.
    </p>
  </div>
  <div style="background:#f5f5f5;padding:12px;text-align:center;font-size:11px;color:#aaa">
    Wiadomość wygenerowana automatycznie. Nie odpowiadaj na ten e-mail.<br>
    Kliknij <a href="{{.URL}}">tutaj</a> aby wypisać się z powiadomień.
  </div>
</body>
</html>""",
    },
    {
        "name": "lab_phish_password_reset",
        "subject": "Twoje hasło wygasło - wymagana zmiana",
        "text": (
            "Drogi użytkowniku,\n\n"
            "Twoje hasło do konta Microsoft wygasło. "
            "Aby kontynuować korzystanie z usług, ustaw nowe hasło:\n\n"
            "{{.URL}}\n\n"
            "Link jest ważny przez 1 godzinę.\n\n"
            "Dział IT"
        ),
        "html": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:#0078d4;padding:20px;color:white">
    <h3 style="margin:0">Microsoft Account</h3>
  </div>
  <div style="padding:24px">
    <p>Drogi użytkowniku,</p>
    <p>Twoje hasło do konta Microsoft <strong>wygasło</strong>.</p>
    <p>Kliknij poniżej, aby ustawić nowe hasło i odzyskać dostęp do swoich plików i aplikacji.</p>
    <p style="text-align:center;margin:28px 0">
      <a href="{{.URL}}" style="background:#0078d4;color:white;padding:12px 24px;
         text-decoration:none;border-radius:2px">
        Zmień hasło teraz
      </a>
    </p>
    <p style="font-size:12px;color:#666">Link wygasa za <strong>1 godzinę</strong>.</p>
  </div>
</body>
</html>""",
    },
    {
        "name": "lab_phish_package_delivery",
        "subject": "Nie mogliśmy dostarczyć Twojej paczki - wymagana opłata",
        "text": (
            "Twoja paczka czeka na odbiór.\n\n"
            "Numer przesyłki: PL82746512\n"
            "Status: Wstrzymana - wymagana dopłata 3,99 PLN\n\n"
            "Aby zwolnić przesyłkę i ustalić termin dostawy, kliknij:\n"
            "{{.URL}}\n\n"
            "Paczka zostanie zwrócona po 3 dniach roboczych."
        ),
        "html": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:#f90;padding:16px;text-align:center">
    <h2 style="margin:0;color:white">Informacja o przesyłce</h2>
  </div>
  <div style="padding:24px;border:1px solid #eee">
    <p>Twoja paczka <strong>czeka na odbiór</strong>.</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0">
      <tr><td style="padding:8px;background:#f9f9f9"><strong>Numer:</strong></td>
          <td style="padding:8px">PL82746512</td></tr>
      <tr><td style="padding:8px;background:#f9f9f9"><strong>Status:</strong></td>
          <td style="padding:8px;color:#c0392b">Wstrzymana</td></tr>
      <tr><td style="padding:8px;background:#f9f9f9"><strong>Dopłata:</strong></td>
          <td style="padding:8px">3,99 PLN</td></tr>
    </table>
    <p style="text-align:center;margin:24px 0">
      <a href="{{.URL}}" style="background:#f90;color:white;padding:12px 24px;
         text-decoration:none;border-radius:4px;font-weight:bold">
        Opłać i zaplanuj dostawę
      </a>
    </p>
  </div>
</body>
</html>""",
    },
]

LEGIT_TEMPLATES: list[dict] = [
    {
        "name": "lab_legit_newsletter",
        "subject": "Miesięczny newsletter działu IT - kwiecień 2025",
        "text": (
            "Witajcie,\n\n"
            "W tym miesiącu zakończyliśmy migrację serwerów do nowej infrastruktury. "
            "Planowane prace serwisowe odbędą się w sobotę od 2:00 do 4:00.\n\n"
            "Nowe zasoby w intranecie: http://intranet.lab.local/wiki\n\n"
            "Pozdrawiamy,\nDział IT"
        ),
        "html": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:#2c3e50;padding:16px;color:white">
    <h3 style="margin:0">Newsletter Działu IT | Kwiecień 2025</h3>
  </div>
  <div style="padding:24px">
    <h4>Zakończona migracja infrastruktury</h4>
    <p>Zakończyliśmy migrację serwerów aplikacyjnych do nowej infrastruktury.
       Wszystkie usługi działają stabilnie.</p>
    <h4>Planowane prace serwisowe</h4>
    <p>Sobota, 5 kwietnia, godz. <strong>2:00-4:00</strong>. Przerwa w dostępie do poczty.</p>
    <h4>Nowe zasoby w intranecie</h4>
    <p>Dokumentacja techniczna dostępna pod adresem
       <a href="http://intranet.lab.local/wiki">intranet.lab.local/wiki</a>.</p>
    <p>Pozdrawiamy,<br>Dział IT</p>
  </div>
</body>
</html>""",
    },
    {
        "name": "lab_legit_meeting_invite",
        "subject": "Zaproszenie na spotkanie zespołu - piątek 10:00",
        "text": (
            "Cześć,\n\n"
            "Zapraszam na spotkanie podsumowujące sprint w piątek o 10:00 w sali konferencyjnej A2.\n\n"
            "Agenda:\n"
            "1. Omówienie wyników sprintu\n"
            "2. Planowanie kolejnej iteracji\n"
            "3. Sprawy bieżące\n\n"
            "Proszę o potwierdzenie obecności.\n\n"
            "Anna Kowalska\nProduct Owner"
        ),
        "html": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="padding:24px">
    <p>Cześć,</p>
    <p>Zapraszam na <strong>spotkanie podsumowujące sprint</strong>:</p>
    <ul>
      <li><strong>Kiedy:</strong> Piątek, godz. 10:00</li>
      <li><strong>Gdzie:</strong> Sala konferencyjna A2</li>
    </ul>
    <p><strong>Agenda:</strong></p>
    <ol>
      <li>Omówienie wyników sprintu</li>
      <li>Planowanie kolejnej iteracji</li>
      <li>Sprawy bieżące</li>
    </ol>
    <p>Proszę o potwierdzenie obecności przez odpowiedź na ten e-mail.</p>
    <p>Pozdrawiam,<br><strong>Anna Kowalska</strong><br>Product Owner</p>
  </div>
</body>
</html>""",
    },
]

LANDING_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Weryfikacja konta</title>
  <style>
    body { font-family: Arial, sans-serif; display: flex; justify-content: center;
           align-items: center; min-height: 100vh; margin: 0; background: #f0f0f0; }
    .box { background: white; padding: 40px; border-radius: 8px;
           box-shadow: 0 2px 10px rgba(0,0,0,.1); max-width: 400px; width: 100%; }
    h2 { color: #c0392b; }
    input { width: 100%; padding: 10px; margin: 8px 0; box-sizing: border-box;
            border: 1px solid #ddd; border-radius: 4px; }
    button { width: 100%; padding: 12px; background: #c0392b; color: white;
             border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
  </style>
</head>
<body>
  <div class="box">
    <h2>Weryfikacja tożsamości</h2>
    <p>Wprowadź swoje dane, aby potwierdzić tożsamość.</p>
    <form method="POST">
      <input type="text"     name="username" placeholder="Login / e-mail">
      <input type="password" name="password" placeholder="Hasło">
      <button type="submit">Potwierdź</button>
    </form>
    <!-- STRONA TESTOWA - ŚRODOWISKO LABORATORYJNE -->
  </div>
</body>
</html>"""

TEST_TARGETS: list[TargetUser] = [
    TargetUser("Jan",     "Kowalski",   "jan.kowalski@lab.local",   "Pracownik"),
    TargetUser("Anna",    "Nowak",      "anna.nowak@lab.local",     "Manager"),
    TargetUser("Piotr",   "Wiśniewski", "piotr.wisniewski@lab.local","Analityk"),
    TargetUser("Katarzyna","Dąbrowska", "k.dabrowska@lab.local",    "Pracownik"),
    TargetUser("Marek",   "Lewandowski","m.lewandowski@lab.local",  "Pracownik"),
]


# ---------------------------------------------------------------------------
# Główna funkcja
# ---------------------------------------------------------------------------

def run_campaign(campaign_name: str, template_key: str = "lab_phish_bank_alert") -> None:
    """
    Tworzy i uruchamia pojedynczą kampanię phishingową.

    Args:
        campaign_name: unikalna nazwa kampanii (folder wyjściowy w data/raw/)
        template_key:  nazwa szablonu z PHISHING_TEMPLATES
    """
    if not GOPHISH_API_KEY:
        print("[BŁĄD] Brak GOPHISH_API_KEY - uzupełnij plik .env i spróbuj ponownie.")
        print("       Klucz API znajdziesz w Gophish UI: http://localhost:3333 -> Account Settings")
        sys.exit(1)

    gophish = GophishClient(GOPHISH_API_URL, GOPHISH_API_KEY)
    mailhog = MailHogClient(MAILHOG_API_URL)

    # Sprawdzenie połączeń
    _check_gophish(gophish)
    _check_mailhog(mailhog)

    # Wyszukanie szablonu
    tpl_data = next((t for t in PHISHING_TEMPLATES if t["name"] == template_key), None)
    if tpl_data is None:
        print(f"[BŁĄD] Szablon '{template_key}' nie istnieje.")
        sys.exit(1)

    print(f"\n[*] Tworzenie kampanii: {campaign_name}")

    # 1. Profil wysyłkowy ->MailHog
    smtp_id = gophish.create_sending_profile(SendingProfile(
        name=f"{campaign_name}_smtp",
        host="mailhog:1025",
        from_address="security-alert@lab.local",
    ))
    print(f"    [+] Profil SMTP ID={smtp_id}")

    # 2. Szablon phishingowy - unikalna nazwa per kampania, aby uniknąć kolizji
    tpl_name = f"{campaign_name}_{tpl_data['name']}"
    tpl_id = gophish.create_template(EmailTemplate(
        name=tpl_name,
        subject=tpl_data["subject"],
        html=tpl_data["html"],
        text=tpl_data["text"],
    ))
    print(f"    [+] Szablon e-mail ID={tpl_id}")

    # 3. Landing page
    page_id = gophish.create_page(LandingPage(
        name=f"{campaign_name}_page",
        html=LANDING_PAGE_HTML,
        capture_credentials=True,
        capture_passwords=False,   # nie zbieramy haseł nawet w labie
    ))
    print(f"    [+] Landing page ID={page_id}")

    # 4. Grupa odbiorców
    group_id = gophish.create_group(UserGroup(
        name=f"{campaign_name}_targets",
        targets=TEST_TARGETS,
    ))
    print(f"    [+] Grupa odbiorców ID={group_id} ({len(TEST_TARGETS)} osób)")

    # 5. Kampania
    campaign_id = gophish.create_campaign(Campaign(
        name=campaign_name,
        template_name=tpl_name,
        page_name=f"{campaign_name}_page",
        smtp_name=f"{campaign_name}_smtp",
        group_names=[f"{campaign_name}_targets"],
        url="http://gophish:8080",
    ))
    print(f"    [+] Kampania uruchomiona ID={campaign_id}")

    # 6. Czekaj na wysyłkę
    print("\n[*] Czekam na dostarczenie e-maili do MailHog (max 30s)...")
    _wait_for_delivery(mailhog, expected=len(TEST_TARGETS), timeout=30)

    # 7. Eksport z MailHog
    output_dir = OUTPUT_BASE / campaign_name
    messages = mailhog.fetch_all()
    paths = mailhog.export_to_eml_dir(messages, output_dir)
    print(f"[+] Wyeksportowano {len(paths)} wiadomości ->{output_dir}/")

    # 8. Metadane kampanii
    metadata = {
        "campaign_name": campaign_name,
        "template": template_key,
        "label": "phishing",
        "created_at": datetime.utcnow().isoformat(),
        "targets": [t.email for t in TEST_TARGETS],
        "gophish_campaign_id": campaign_id,
        "message_count": len(paths),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[+] Zapisano metadata.json")

    # 9. Podsumowanie wyników z Gophish
    results = gophish.get_campaign_results(campaign_id)
    sent = sum(1 for r in results.get("results", []) if r.get("status") != "Error")
    print(f"\n[=] Podsumowanie kampanii '{campaign_name}':")
    print(f"    Wysłane: {sent}/{len(TEST_TARGETS)}")
    print(f"    Wyniki:  {GOPHISH_API_URL}/campaigns/{campaign_id}")


def generate_legit_emails() -> None:
    """Generuje przykładowe legit e-maile przez MailHog SMTP."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_host = os.getenv("SMTP_HOST", "localhost")
    smtp_port = int(os.getenv("SMTP_PORT", "1025"))

    output_dir = OUTPUT_BASE / "legit_batch_01"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[*] Wysyłam legit e-maile przez SMTP {smtp_host}:{smtp_port}")

    for tpl in LEGIT_TEMPLATES:
        for target in TEST_TARGETS:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = tpl["subject"]
            msg["From"] = "it-team@lab.local"
            msg["To"] = target.email

            msg.attach(MIMEText(tpl["text"], "plain", "utf-8"))
            msg.attach(MIMEText(tpl["html"], "html", "utf-8"))

            try:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=5) as s:
                    s.sendmail("it-team@lab.local", [target.email], msg.as_string())
            except Exception as e:
                print(f"    [!] Błąd wysyłki do {target.email}: {e}")

    # Eksportuj z MailHog
    mailhog = MailHogClient(MAILHOG_API_URL)
    _wait_for_delivery(mailhog, expected=len(LEGIT_TEMPLATES) * len(TEST_TARGETS), timeout=15)

    messages = mailhog.fetch_all()
    paths = mailhog.export_to_eml_dir(messages, output_dir)

    metadata = {
        "batch": "legit_batch_01",
        "label": "legit",
        "created_at": datetime.utcnow().isoformat(),
        "message_count": len(paths),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[+] Wyeksportowano {len(paths)} legit e-maili ->{output_dir}/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_gophish(client: GophishClient) -> None:
    try:
        client.list_campaigns()
        print("[+] Połączenie z Gophish OK")
    except Exception as e:
        print(f"[BŁĄD] Nie można połączyć się z Gophish ({GOPHISH_API_URL}): {e}")
        print("       Upewnij się, że kontenery działają: docker compose up -d")
        sys.exit(1)


def _check_mailhog(client: MailHogClient) -> None:
    try:
        client.count()
        print("[+] Połączenie z MailHog OK")
    except Exception as e:
        print(f"[BŁĄD] Nie można połączyć się z MailHog ({MAILHOG_API_URL}): {e}")
        sys.exit(1)


def _wait_for_delivery(client: MailHogClient, expected: int, timeout: int = 30) -> None:
    # Zapamiętaj stan skrzynki PRZED wysyłką, żeby liczyć tylko nowe wiadomości.
    # Poprzednia wersja porównywała client.count() z `expected`, co powodowało
    # natychmiastowe wyjście jeśli w skrzynce pozostały wiadomości z poprzedniej
    # kampanii (wyścig czasowy / false-positive).
    count_before = client.count()
    deadline = time.time() + timeout
    while time.time() < deadline:
        new_count = client.count() - count_before
        if new_count >= expected:
            print(f"    [+] Odebrano {new_count} nowych wiadomości.")
            return
        time.sleep(1)
    delivered = client.count() - count_before
    print(f"    [!] Timeout - odebrano {delivered}/{expected} nowych wiadomości.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generator kampanii phishingowych (lab)")
    parser.add_argument(
        "--mode",
        choices=["phishing", "legit", "all"],
        default="all",
        help="Rodzaj generowanych danych (domyślnie: all)",
    )
    parser.add_argument(
        "--template",
        default="lab_phish_bank_alert",
        choices=[t["name"] for t in PHISHING_TEMPLATES],
        help="Szablon phishingowy do użycia",
    )
    parser.add_argument(
        "--name",
        default=f"campaign_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        help="Nazwa kampanii (domyślnie: campaign_<timestamp>)",
    )
    args = parser.parse_args()

    if args.mode in ("phishing", "all"):
        run_campaign(args.name, args.template)

    if args.mode in ("legit", "all"):
        generate_legit_emails()
