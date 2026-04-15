"""UNHCR Job Scraper - uses the Workday CXS JSON API."""

import re
import requests
import json
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim, load_cached_jobs

AGENCY = "UNHCR"
AGENCY_NAME = "United Nations High Commissioner for Refugees"
JOBS_URL = "https://unhcr.wd3.myworkdayjobs.com/External"
API_URL = "https://unhcr.wd3.myworkdayjobs.com/wday/cxs/unhcr/External/jobs"
DETAIL_BASE = "https://unhcr.wd3.myworkdayjobs.com/wday/cxs/unhcr/External"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": JOBS_URL,
}


def _split_location(location_str):
    if location_str is None:
        return None, None
    if "," not in location_str:
        return location_str.strip(), None
    parts = location_str.rsplit(",", 1)
    return parts[0].strip(), parts[1].strip()


def _fetch_detail(external_path):
    try:
        detail = requests.get(f"{DETAIL_BASE}{external_path}", headers=HEADERS, timeout=30)
        detail.raise_for_status()
        info = detail.json().get("jobPostingInfo", {})
        end_date = info.get("endDate")
        deadline = end_date[:10] if end_date else None
        start_date = info.get("startDate")
        pubdate = start_date[:10] if start_date else None
        description = html_to_md(info.get("jobDescription") or "")
        description = trim(
            description,
            before=[re.compile(r"Terms of Reference\**"), re.compile(r"Standard Job Description\**")],
            after=re.compile(r"\**\s*UNHCR Salary Calculator"),
        )
        return deadline, pubdate, description
    except Exception:
        return None, None, None


def scrape() -> list[dict]:
    stubs = []
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
                location_str = job.get("locationsText") or None
                city, country = _split_location(location_str)
                grade = None
                bullet = job.get("bulletFields", [])
                if len(bullet) > 1:
                    grade = bullet[1]
                external_path = job.get("externalPath", "")
                if not external_path:
                    continue
                slug = external_path.rstrip("/").split("/")[-1]
                url = f"https://unhcr.wd3.myworkdayjobs.com/en-US/External/details/{slug}"
                stubs.append({
                    "_path": external_path,
                    "agency": AGENCY, "agency_name": AGENCY_NAME,
                    "job_title": title, "grade": grade,
                    "city": city, "country": country, "url": url,
                })

            total = data.get("total", 0)
            if offset + limit >= total:
                break
            offset += limit
        except Exception:
            break

    cache = load_cached_jobs()
    futures = []
    jobs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for s in stubs:
            path = s.pop("_path")
            if s["url"] in cache:
                c = cache[s["url"]]
                s["deadline"] = c.get("deadline")
                s["pubdate"] = c.get("pubdate")
                s["description"] = c.get("description")
                jobs.append(s)
            else:
                futures.append((s, ex.submit(_fetch_detail, path)))
    for stub, fut in futures:
        deadline, pubdate, description = fut.result()
        stub["deadline"] = deadline
        stub["pubdate"] = pubdate
        stub["description"] = description
        jobs.append(stub)
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
