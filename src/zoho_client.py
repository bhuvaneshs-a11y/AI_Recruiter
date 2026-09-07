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

    def get_associated_job_openings(self, record_id):
        """Job Openings a candidate has applied to/is associated with."""
        resp = requests.get(
            f"{config.ZOHO_API_DOMAIN}/recruit/v2/Candidates/{record_id}/associate",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_applications_for_job(self, job_opening_id, job_title):
        """Applications (i.e. candidates) for a specific Job Opening.

        NOTE: `/JobOpenings/{id}/associate` (the docs-suggested reverse of
        get_associated_job_openings) returns 400 "the relation name given seems
        to be invalid" in practice, despite docs claiming symmetry with the
        Candidates-side endpoint - confirmed live, not a guess.

        Instead, this searches the Applications module directly. Zoho's search
        API silently ignores criteria on `$Job_Opening_Id` (a computed reference
        field - returns 200 with unfiltered results, not an error), but filtering
        by the job's title (`Job_Opening_Name`) does work server-side. Since two
        different job openings could in theory share the same title, this then
        double-checks the exact job_opening_id client-side on the (much smaller)
        returned set for correctness.
        """
        all_apps = []
        page = 1
        while True:
            resp = requests.get(
                f"{config.ZOHO_API_DOMAIN}/recruit/v2/Applications/search",
                headers=self._headers(),
                params={
                    "criteria": f"(Job_Opening_Name:equals:{job_title})",
                    "page": page, "per_page": 200,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            all_apps.extend(data.get("data", []))
            if not data.get("info", {}).get("more_records"):
                break
            page += 1
        return [a for a in all_apps if a.get("$Job_Opening_Id") == job_opening_id]

    def get_job_opening(self, job_opening_id, fields=None):
        resp = requests.get(
            f"{config.ZOHO_API_DOMAIN}/recruit/v2/JobOpenings/{job_opening_id}",
            headers=self._headers(),
            params={"fields": fields} if fields else None,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_job_openings(self, page=1, per_page=200,
                          fields="id,Job_Opening_Name,Posting_Title,Job_Opening_Status,"
                                 "Number_of_Positions,Job_Description,Required_Skills,"
                                 "Work_Experience,Industry,Job_Type,Remote_Job,Target_Date"):
        resp = requests.get(
            f"{config.ZOHO_API_DOMAIN}/recruit/v2/JobOpenings",
            headers=self._headers(),
            params={"page": page, "per_page": per_page, "fields": fields},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_all_job_openings(self, fields=None):
        """Auto-paginated: returns every Job Opening record as a single list."""
        all_records = []
        page = 1
        while True:
            kwargs = {"page": page}
            if fields:
                kwargs["fields"] = fields
            result = self.get_job_openings(**kwargs)
            records = result.get("data", [])
            all_records.extend(records)
            if not result.get("info", {}).get("more_records"):
                break
            page += 1
        return all_records


_shared_client = None


def get_shared_client():
    """One ZohoClient reused for the process lifetime - critical in the FastAPI
    server, where a fresh ZohoClient() per request would refresh the access
    token on every single request instead of caching it until it expires.
    Zoho actively rate-limits the token-refresh endpoint itself, separately
    from normal API calls."""
    global _shared_client
    if _shared_client is None:
        _shared_client = ZohoClient()
    return _shared_client
