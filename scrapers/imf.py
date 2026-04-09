"""IMF Job Scraper - uses the Workday CXS JSON API."""

import re
import requests
import json
from bs4 import BeautifulSoup

AGENCY = "IMF"
AGENCY_NAME = "International Monetary Fund"
JOBS_URL = "https://imf.wd5.myworkdayjobs.com/IMF"
API_URL = "https://imf.wd5.myworkdayjobs.com/wday/cxs/imf/IMF/jobs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": JOBS_URL,
}


def _split_location(location_str):
    """Split IMF locationsText into (city, country).

    Format is 'Country, City' (e.g. 'USA, Washington DC') or just 'Country'.
    Strip 'LTX-' prefixes used for some country codes.
    """
    if not location_str:
        return None, None
    s = re.sub(r'^LTX-', '', location_str.strip())
    if "," not in s:
        return None, s
    idx = s.index(",")
    country = s[:idx].strip()
    city = s[idx + 1:].strip()
    return city, country


def _parse_deadline(bullet_fields):
    """Extract deadline date from bulletFields list (MM/DD/YYYY -> YYYY-MM-DD)."""
    for field in bullet_fields:
        m = re.search(r'(\d{2})/(\d{2})/(\d{4})', field)
        if m:
            month, day, year = m.group(1), m.group(2), m.group(3)
            return f"{year}-{month}-{day}"
    return None


def _fetch_grade(session, external_path):
    """Fetch job detail page and extract 'Hiring For' grade(s)."""
    try:
        url = f"https://imf.wd5.myworkdayjobs.com/wday/cxs/imf/IMF{external_path}"
        data = session.get(url, headers=HEADERS, timeout=30).json()
        desc = data.get("jobPostingInfo", {}).get("jobDescription", "")
        text = BeautifulSoup(desc, "html.parser").get_text(separator="\n", strip=True)
        m = re.search(r'Hiring For[:\s]*\n(.+)', text)
        if not m:
            return None
        grade = m.group(1).strip()
        if "," in grade:
            grade = grade.split(",")[-1].strip()
        return grade
    except Exception:
        return None


def scrape() -> list[dict]:
    session = requests.Session()
    jobs = []
    offset = 0
    limit = 20

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
                location_str = job.get("locationsText") or None
                external_path = job.get("externalPath", "")
                if not external_path:
                    continue
                job_slug = external_path.rstrip("/").split("/")[-1]
                url = f"https://imf.wd5.myworkdayjobs.com/en-US/IMF/details/{job_slug}"
                city, country = _split_location(location_str)
                deadline = _parse_deadline(job.get("bulletFields", []))
                grade = _fetch_grade(session, external_path)
                jobs.append({
                    "agency": AGENCY,
                    "agency_name": AGENCY_NAME,
                    "job_title": title,
                    "grade": grade,
                    "city": city,
                    "country": country,
                    "deadline": deadline,
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
