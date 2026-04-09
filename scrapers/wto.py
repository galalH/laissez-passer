"""WTO Job Scraper - uses the Workday CXS JSON API."""

import requests
import json
import re

AGENCY = "WTO"
AGENCY_NAME = "World Trade Organization"
JOBS_URL = "https://wto.wd103.myworkdayjobs.com/External"

API_URL = "https://wto.wd103.myworkdayjobs.com/wday/cxs/wto/External/jobs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": JOBS_URL,
}


def _parse_deadline(s):
    """Extract deadline in YYYY-MM-DD format from text containing DD-MM-YYYY."""
    if not s:
        return None
    m = re.search(r'\b(\d{2})-(\d{2})-(\d{4})\b', s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def scrape() -> list[dict]:
    jobs = []
    offset = 0
    limit = 20

    while True:
        try:
            payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
            resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for job in postings:
                title = job.get("title", "")
                location = job.get("locationsText") or None

                deadline = None
                bullet = job.get("bulletFields", [])
                if len(bullet) > 1:
                    deadline = bullet[1]

                external_path = job.get("externalPath", "")
                if not external_path:
                    continue
                slug = external_path.rstrip("/").split("/")[-1]
                url = f"https://wto.wd103.myworkdayjobs.com/en-US/External/details/{slug}"

                jobs.append({
                    "agency": AGENCY,
                    "agency_name": AGENCY_NAME,
                    "job_title": title,
                    "grade": None,
                    "city": "Geneva",
                    "country": "Switzerland",
                    "deadline": _parse_deadline(deadline),
                    "url": url,
                })

            total = data.get("total", 0)
            if offset + limit >= total:
                break
            offset += limit

        except Exception:
            break

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
