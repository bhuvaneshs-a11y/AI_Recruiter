import re
from urllib.parse import urlparse

import requests

import config

GITHUB_API = "https://api.github.com"


def classify_link(url):
    host = urlparse(url).netloc.lower()
    if "github.com" in host:
        return "github"
    if "linkedin.com" in host:
        return "linkedin"
    return "portfolio"


def _github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return headers


def _parse_owner_repo(url):
    path = urlparse(url).path.strip("/")
    if not path:
        return None, None
    parts = path.split("/")
    owner = parts[0] or None
    repo = parts[1] if len(parts) > 1 and parts[1] else None
    return owner, repo


def verify_github(url, candidate_name=""):
    owner, repo = _parse_owner_repo(url)
    if not owner:
        return {"url": url, "type": "github", "valid_url": False}

    result = {
        "url": url, "type": "github", "owner": owner, "repo": repo,
        "exists": False, "is_fork": None, "stars": None,
        "owner_is_contributor": None, "owner_commit_count_approx": None,
        "owner_pr_count": None, "owner_name_matches_candidate": None,
    }

    if not repo:
        # Profile link only (github.com/{owner}) - check user exists, compare display name
        resp = requests.get(f"{GITHUB_API}/users/{owner}", headers=_github_headers(), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            result["exists"] = True
            display_name = (data.get("name") or "").lower()
            result["owner_name_matches_candidate"] = bool(
                candidate_name and display_name and
                any(part in display_name for part in candidate_name.lower().split() if len(part) > 2)
            )
        return result

    repo_resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_github_headers(), timeout=15)
    if repo_resp.status_code != 200:
        return result
    repo_data = repo_resp.json()
    result["exists"] = True
    result["is_fork"] = repo_data.get("fork")
    result["stars"] = repo_data.get("stargazers_count")

    contrib_resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contributors",
        headers=_github_headers(), params={"per_page": 100}, timeout=15,
    )
    if contrib_resp.status_code == 200:
        contributors = [c.get("login", "").lower() for c in contrib_resp.json()]
        result["owner_is_contributor"] = owner.lower() in contributors

    commits_resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits",
        headers=_github_headers(), params={"author": owner, "per_page": 1}, timeout=15,
    )
    if commits_resp.status_code == 200:
        link = commits_resp.headers.get("Link", "")
        match = re.search(r'page=(\d+)>; rel="last"', link)
        result["owner_commit_count_approx"] = int(match.group(1)) if match else len(commits_resp.json())

    search_resp = requests.get(
        f"{GITHUB_API}/search/issues",
        headers=_github_headers(),
        params={"q": f"repo:{owner}/{repo} type:pr author:{owner}"},
        timeout=15,
    )
    if search_resp.status_code == 200:
        result["owner_pr_count"] = search_resp.json().get("total_count")

    user_resp = requests.get(f"{GITHUB_API}/users/{owner}", headers=_github_headers(), timeout=15)
    if user_resp.status_code == 200:
        display_name = (user_resp.json().get("name") or "").lower()
        result["owner_name_matches_candidate"] = bool(
            candidate_name and display_name and
            any(part in display_name for part in candidate_name.lower().split() if len(part) > 2)
        )

    return result


def verify_portfolio(url):
    result = {"url": url, "type": "portfolio", "reachable": False, "status_code": None}
    try:
        resp = requests.get(url, timeout=15, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        result["reachable"] = resp.ok
        result["status_code"] = resp.status_code
        if resp.ok:
            text = re.sub(r"<[^>]+>", " ", resp.text)
            result["content_snippet"] = re.sub(r"\s+", " ", text).strip()[:1000]
    except requests.RequestException as e:
        result["error"] = str(e)
    return result


def verify_linkedin(url):
    result = {"url": url, "type": "linkedin", "reachable": False, "status_code": None,
              "note": "LinkedIn has no public verification API; only URL reachability was checked."}
    try:
        resp = requests.head(url, timeout=15, allow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0"})
        result["reachable"] = resp.status_code < 400
        result["status_code"] = resp.status_code
    except requests.RequestException as e:
        result["error"] = str(e)
    return result


def verify_link(url, candidate_name=""):
    if not url.startswith(("http://", "https://")):
        return {"url": url, "type": "unsupported", "reachable": False,
                "note": "Not an http(s) URL (e.g. mailto:, tel:) - not verifiable."}

    link_type = classify_link(url)
    if link_type == "github":
        return verify_github(url, candidate_name)
    if link_type == "linkedin":
        return verify_linkedin(url)
    return verify_portfolio(url)
