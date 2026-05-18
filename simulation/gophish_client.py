"""
Klient REST API Gophish.

Dokumentacja API: https://docs.getgophish.com/api-documentation
Autoryzacja: nagłówek  Authorization: Bearer <api_key>

Użycie:
    client = GophishClient(api_url="http://localhost:3333", api_key="...")
    profiles = client.list_sending_profiles()
"""
from dataclasses import dataclass, field
from typing import Any

import requests
from requests import Response

### Modele danych (proste dataclassy - wystarczające na potrzeby skryptów)

@dataclass
class SendingProfile:
    name: str
    host: str          ### np. "mailhog:1025"
    from_address: str  ### np. "phishing-test@lab.local"
    username: str = ""
    password: str = ""
    ignore_cert_errors: bool = True
    id: int | None = None


@dataclass
class EmailTemplate:
    name: str
    subject: str
    html: str
    text: str = ""
    id: int | None = None


@dataclass
class LandingPage:
    name: str
    html: str
    capture_credentials: bool = False
    capture_passwords: bool = False
    redirect_url: str = ""
    id: int | None = None


@dataclass
class TargetUser:
    first_name: str
    last_name: str
    email: str
    position: str = ""


@dataclass
class UserGroup:
    name: str
    targets: list[TargetUser] = field(default_factory=list)
    id: int | None = None


@dataclass
class Campaign:
    name: str
    template_name: str
    page_name: str
    smtp_name: str
    group_names: list[str]
    url: str = "http://localhost:8080"
    id: int | None = None
    status: str = ""


### Klient

class GophishClient:
    """Wrapper nad Gophish REST API v1."""

    def __init__(self, api_url: str, api_key: str, verify_ssl: bool = False) -> None:
        self.base = api_url.rstrip("/") + "/api"
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
        self._session.verify = verify_ssl

    ### Helpers

    def _get(self, path: str) -> Any:
        r = self._session.get(f"{self.base}{path}")
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict) -> Any:
        r = self._session.post(f"{self.base}{path}", json=payload)
        _raise_gophish(r)
        return r.json()

    def _delete(self, path: str) -> Any:
        r = self._session.delete(f"{self.base}{path}")
        r.raise_for_status()
        return r.json()

    ### Sending Profiles (SMTP)

    def list_sending_profiles(self) -> list[dict]:
        return self._get("/smtp/")

    def create_sending_profile(self, profile: SendingProfile) -> int:
        """Tworzy profil wysyłkowy i zwraca nadane ID."""
        payload = {
            "name": profile.name,
            "host": profile.host,
            "from_address": profile.from_address,
            "username": profile.username,
            "password": profile.password,
            "ignore_cert_errors": profile.ignore_cert_errors,
        }
        result = self._post("/smtp/", payload)
        return int(result["id"])

    def delete_sending_profile(self, profile_id: int) -> None:
        self._delete(f"/smtp/{profile_id}")

    ### Email Templates

    def list_templates(self) -> list[dict]:
        return self._get("/templates/")

    def create_template(self, template: EmailTemplate) -> int:
        payload = {
            "name": template.name,
            "subject": template.subject,
            "html": template.html,
            "text": template.text,
        }
        result = self._post("/templates/", payload)
        return int(result["id"])

    def delete_template(self, template_id: int) -> None:
        self._delete(f"/templates/{template_id}")

    ### Landing Pages

    def list_pages(self) -> list[dict]:
        return self._get("/pages/")

    def create_page(self, page: LandingPage) -> int:
        payload = {
            "name": page.name,
            "html": page.html,
            "capture_credentials": page.capture_credentials,
            "capture_passwords": page.capture_passwords,
            "redirect_url": page.redirect_url,
        }
        result = self._post("/pages/", payload)
        return int(result["id"])

    def delete_page(self, page_id: int) -> None:
        self._delete(f"/pages/{page_id}")

    ### User Groups

    def list_groups(self) -> list[dict]:
        return self._get("/groups/")

    def create_group(self, group: UserGroup) -> int:
        payload = {
            "name": group.name,
            "targets": [
                {
                    "first_name": t.first_name,
                    "last_name": t.last_name,
                    "email": t.email,
                    "position": t.position,
                }
                for t in group.targets
            ],
        }
        result = self._post("/groups/", payload)
        return int(result["id"])

    def delete_group(self, group_id: int) -> None:
        self._delete(f"/groups/{group_id}")

    ### Campaigns

    def list_campaigns(self) -> list[dict]:
        return self._get("/campaigns/")

    def create_campaign(self, campaign: Campaign) -> int:
        payload = {
            "name": campaign.name,
            "template": {"name": campaign.template_name},
            "page": {"name": campaign.page_name},
            "smtp": {"name": campaign.smtp_name},
            "groups": [{"name": n} for n in campaign.group_names],
            "url": campaign.url,
        }
        result = self._post("/campaigns/", payload)
        return int(result["id"])

    def get_campaign_results(self, campaign_id: int) -> dict:
        return self._get(f"/campaigns/{campaign_id}/results")

    def delete_campaign(self, campaign_id: int) -> None:
        self._delete(f"/campaigns/{campaign_id}")

    ### Cleanup - usuwa wszystkie zasoby stworzone na potrzeby kampanii

    def teardown(
        self,
        campaign_id: int | None = None,
        template_id: int | None = None,
        page_id: int | None = None,
        smtp_id: int | None = None,
        group_id: int | None = None,
    ) -> None:
        if campaign_id:
            self.delete_campaign(campaign_id)
        if template_id:
            self.delete_template(template_id)
        if page_id:
            self.delete_page(page_id)
        if smtp_id:
            self.delete_sending_profile(smtp_id)
        if group_id:
            self.delete_group(group_id)


### Helper

def _raise_gophish(r: Response) -> None:
    """Gophish zwraca HTTP 200 nawet przy błędach - sprawdzamy pole 'success'."""
    try:
        body = r.json()
    except Exception:
        r.raise_for_status()
        return

    if isinstance(body, dict) and body.get("success") is False:
        msg = body.get("message", "Nieznany błąd Gophish")
        raise RuntimeError(f"Gophish API error: {msg}")

    r.raise_for_status()
