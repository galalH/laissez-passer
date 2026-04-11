import requests
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

from scrapers._utils import html_to_md

_ORACLE_BASE = "https://estm.fa.em2.oraclecloud.com"
_DETAIL_API = f"{_ORACLE_BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
_DESC_FIELDS = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")


def _fetch_description(session: requests.Session, job_url: str) -> str | None:
    try:
        job_id = job_url.rstrip("/").split("/")[-1]
        params = {"onlyData": "true", "finder": f'ById;Id="{job_id}",siteNumber=CX_1'}
        resp = session.get(_DETAIL_API, params=params, timeout=30)
        resp.raise_for_status()
        item = (resp.json().get("items") or [{}])[0]
        parts = [html_to_md(item.get(f) or "") or "" for f in _DESC_FIELDS]
        return "\n\n".join(p for p in parts if p) or None
    except Exception:
        return None

AGENCY = "ICAO"
AGENCY_NAME = "International Civil Aviation Organization"
JOBS_URL = "https://icaocareers.icao.int/careers/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _parse_deadline(s: str | None) -> str | None:
    if not s:
        return None
    try:
        day, month, year = s.split("/")
        return f"{year}-{month}-{day}"
    except (ValueError, IndexError):
        return None


def _split_location(s: str | None) -> tuple[str | None, str | None]:
    if not s:
        return None, None
    if "," not in s:
        return s, None
    last_comma_idx = s.rfind(",")
    return s[:last_comma_idx].strip(), s[last_comma_idx + 1:].strip()


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(JOBS_URL, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="tablePag")
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []

    stubs = []
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 5:
            continue
        link = cells[0].find("a")
        if not link:
            continue
        job_title = link.get_text(strip=True)
        url = link.get("href", "").strip()
        if not job_title or not url:
            continue
        if url.startswith("/"):
            url = "https://icaocareers.icao.int" + url
        stubs.append({
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": job_title,
            "grade": cells[1].get_text(strip=True) or None,
            "city": _split_location(cells[3].get_text(strip=True) or None)[0],
            "country": _split_location(cells[3].get_text(strip=True) or None)[1],
            "deadline": _parse_deadline(cells[4].get_text(strip=True) or None),
            "url": url,
        })

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_fetch_description, session, s["url"]) for s in stubs]
    for stub, fut in zip(stubs, futures):
        stub["description"] = fut.result()

    return stubs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
