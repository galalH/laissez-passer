"""WTO Job Scraper - uses the Workday CXS JSON API."""

import requests
import json
import re
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

AGENCY = "WTO"
AGENCY_NAME = "World Trade Organization"
JOBS_URL = "https://wto.wd103.myworkdayjobs.com/External"
API_URL = "https://wto.wd103.myworkdayjobs.com/wday/cxs/wto/External/jobs"
DETAIL_BASE = "https://wto.wd103.myworkdayjobs.com/wday/cxs/wto/External"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": JOBS_URL,
}


def _fetch_detail(session, external_path):
    try:
        detail = session.get(f"{DETAIL_BASE}{external_path}", headers=HEADERS, timeout=30)
        detail.raise_for_status()
        desc_html = detail.json().get("jobPostingInfo", {}).get("jobDescription", "")
        description = html_to_md(desc_html)
        _PREAMBLE_END = "are particularly encouraged for all positions.\n\n"
        if description and _PREAMBLE_END in description:
            description = description.split(_PREAMBLE_END, 1)[1]
            if description.startswith(".\n"):
                description = description.lstrip(".\n").strip() or None
        return description
    except Exception:
        return None


def _parse_deadline(s):
    if not s:
        return None
    m = re.search(r'\b(\d{2})-(\d{2})-(\d{4})\b', s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def scrape() -> list[dict]:
    stubs = []
    offset = 0
    limit = 20
    session = requests.Session()

    while True:
        try:
            payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
            resp = session.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for job in postings:
                title = job.get("title", "")
                deadline = None
                bullet = job.get("bulletFields", [])
                if len(bullet) > 1:
                    deadline = bullet[1]
                external_path = job.get("externalPath", "")
                if not external_path:
                    continue
                slug = external_path.rstrip("/").split("/")[-1]
                url = f"https://wto.wd103.myworkdayjobs.com/en-US/External/details/{slug}"
                stubs.append({
                    "_path": external_path,
                    "agency": AGENCY, "agency_name": AGENCY_NAME,
                    "job_title": title, "grade": None,
                    "city": "Geneva", "country": "Switzerland",
                    "deadline": _parse_deadline(deadline), "url": url,
                })

            total = data.get("total", 0)
            if offset + limit >= total:
                break
            offset += limit
        except Exception:
            break

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_detail, session, s.pop("_path"))) for s in stubs]

    jobs = []
    for stub, fut in futures:
        stub["description"] = fut.result()
        jobs.append(stub)
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
