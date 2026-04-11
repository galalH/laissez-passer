"""World Bank Job Scraper - extracts Bearer token from page HTML, then calls CSOD API."""

import requests
import json
import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

AGENCY = "World Bank"
AGENCY_NAME = "World Bank Group"
JOBS_URL = "https://worldbankgroup.csod.com/ux/ats/careersite/1/home?c=worldbankgroup"
SEARCH_URL = "https://us.api.csod.com/rec-job-search/external/jobs"
DETAIL_URL = "https://worldbankgroup.csod.com/Services/API/ATS/CareerSite/1/JobRequisitions/{id}?useMobileAd=false&cultureId=1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _parse_deadline(s):
    """Convert M/D/YYYY or M/D/YYYY (...) format to YYYY-MM-DD."""
    if not s:
        return None
    date_part = s.strip().split(" ")[0]
    parts = date_part.split("/")
    if len(parts) == 3:
        month, day, year = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None


def _fetch_detail(session, req_id):
    """Fetch grade, full location, and deadline from the job detail ad HTML table."""
    try:
        resp = session.get(DETAIL_URL.format(id=req_id), timeout=30)
        resp.raise_for_status()
        fields = resp.json()["data"][0]["items"][0]["fields"]
        ad = fields.get("ad", "")
        soup = BeautifulSoup(ad, "html.parser")
        rows = soup.find_all("tr")
        table = {}
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) == 2:
                table[cells[0].rstrip(":")] = cells[1]

        grade = table.get("Grade") or None

        # Use top-level location field (primary location, no multi-location noise)
        location_str = fields.get("location", "")
        city, country = None, None
        if location_str:
            # Format: "City,Country"
            parts = location_str.split(",")
            if len(parts) >= 2:
                city = parts[0].strip() or None
                country = parts[-1].strip() or None
            else:
                city = location_str.strip() or None

        closing = table.get("Closing Date")
        deadline = _parse_deadline(closing)

        # Description: ad HTML minus the metadata table
        ad_soup = BeautifulSoup(ad, "html.parser")
        for t in ad_soup.find_all("table"):
            t.decompose()
        description = trim(html_to_md(str(ad_soup)) or None, after="WBG Culture Attributes:")

        return grade, city, country, deadline, description
    except Exception:
        return None, None, None, None, None


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    # Get token from page HTML (embedded as csod.context={...})
    r = session.get(JOBS_URL, timeout=30)
    r.raise_for_status()
    m = re.search(r'csod\.context\s*=\s*(\{.*?\})\s*;', r.text)
    if not m:
        raise ValueError("csod.context token not found in page HTML")
    token = json.loads(m.group(1))["token"]

    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": JOBS_URL,
        "Origin": "https://worldbankgroup.csod.com",
    })

    stubs = []
    seen = set()
    page = 1
    page_size = 25
    total = None

    while True:
        payload = {
            "careerSiteId": 1,
            "careerSitePageId": 1,
            "pageNumber": page,
            "pageSize": page_size,
            "cultureId": 1,
            "searchText": "",
            "cultureName": "en-US",
            "states": [],
            "countryCodes": [],
            "cities": [],
            "placeID": "",
            "radius": None,
            "postingsWithinDays": None,
            "customFieldCheckboxKeys": [],
            "customFieldDropdowns": [],
            "customFieldRadios": [],
        }

        resp = session.post(SEARCH_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "Success":
            break

        if total is None:
            total = data["data"]["totalCount"]

        requisitions = data["data"].get("requisitions", [])
        if not requisitions:
            break

        for req in requisitions:
            req_id = req.get("requisitionId")
            if req_id in seen:
                continue
            seen.add(req_id)

            job_title = req.get("displayJobTitle", "")
            if not job_title:
                continue

            job_url = f"https://worldbankgroup.csod.com/ux/ats/careersite/1/home/requisition/{req_id}?c=worldbankgroup"
            stubs.append({"_id": req_id, "agency": AGENCY, "agency_name": AGENCY_NAME,
                          "job_title": job_title, "url": job_url})

        if len(stubs) >= total or len(requisitions) < page_size:
            break
        page += 1

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_detail, session, s.pop("_id"))) for s in stubs]

    jobs = []
    for stub, fut in futures:
        grade, city, country, deadline, description = fut.result()
        jobs.append({**stub, "grade": grade, "city": city, "country": country,
                     "deadline": deadline, "description": description})
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
