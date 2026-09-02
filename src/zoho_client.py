import time

import requests

import config


class ZohoAuthError(RuntimeError):
    pass


class ZohoClient:
    """Minimal Zoho Recruit v2 client: token refresh, candidate listing, attachment download."""

    def __init__(self):
        self._access_token = None
        self._expires_at = 0

    def _refresh_access_token(self):
        if not (config.ZOHO_CLIENT_ID and config.ZOHO_CLIENT_SECRET and config.ZOHO_REFRESH_TOKEN):
            raise ZohoAuthError(
                "Missing ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN in .env"
            )
        resp = requests.post(
            f"{config.ZOHO_ACCOUNTS_URL}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": config.ZOHO_CLIENT_ID,
                "client_secret": config.ZOHO_CLIENT_SECRET,
                "refresh_token": config.ZOHO_REFRESH_TOKEN,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "access_token" not in payload:
            raise ZohoAuthError(f"Zoho token refresh failed: {payload}")
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + payload.get("expires_in", 3600) - 60

    def _headers(self):
        if not self._access_token or time.time() >= self._expires_at:
            self._refresh_access_token()
        return {"Authorization": f"Zoho-oauthtoken {self._access_token}"}

    def get_candidates(self, page=1, per_page=200, fields="id,Full_Name,Email"):
        resp = requests.get(
            f"{config.ZOHO_API_DOMAIN}/recruit/v2/Candidates",
            headers=self._headers(),
            params={"page": page, "per_page": per_page, "fields": fields},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def list_attachments(self, record_id, module="Candidates"):
        resp = requests.get(
            f"{config.ZOHO_API_DOMAIN}/recruit/v2/{module}/{record_id}/Attachments",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def download_attachment(self, record_id, attachment_id, save_path, module="Candidates"):
        resp = requests.get(
            f"{config.ZOHO_API_DOMAIN}/recruit/v2/{module}/{record_id}/Attachments/{attachment_id}",
            headers=self._headers(),
            timeout=60,
            stream=True,
        )
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return save_path
