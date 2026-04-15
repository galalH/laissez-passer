"""WFP Job Scraper - iterates Management_Level grade facet for authoritative grades."""

import requests
import json
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim, load_cached_jobs

AGENCY = "WFP"
AGENCY_NAME = "World Food Programme"
JOBS_URL = "https://wd3.myworkdaysite.com/recruiting/wfp/job_openings"
API_URL = "https://wd3.myworkdaysite.com/wday/cxs/wfp/job_openings/jobs"
DETAIL_BASE = "https://wd3.myworkdaysite.com/wday/cxs/wfp/job_openings"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": JOBS_URL,
}


def _split_location(s):
    if not s or not isinstance(s, str):
        return None, None
    s = s.strip()
    if "," not in s:
        return None, s
    parts = s.split(",", 1)
    return parts[0].strip() or None, parts[1].strip() or None


def _fetch_detail(session, external_path):
    try:
        detail = session.get(f"{DETAIL_BASE}{external_path}", headers=HEADERS, timeout=30)
        detail.raise_for_status()
        info = detail.json().get("jobPostingInfo", {})
        end_date = info.get("endDate")
        deadline = end_date[:10] if end_date else None
        start_date = info.get("startDate")
        pubdate = start_date[:10] if start_date else None
        description = html_to_md(info.get("jobDescription", ""))
        description = trim(
            description,
            before="Terms and Conditions** section of this vacancy announcement).\n\n",
            after="**WFP LEADERSHIP FRAMEWORK**",
        )
        return deadline, pubdate, description
    except Exception:
        return None, None, None


def _fetch_grade_facets(session):
    try:
        payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
        resp = session.post(API_URL, json=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        facets = resp.json().get("facets", [])
        for facet in facets:
            if facet.get("facetParameter") == "Management_Level":
                return [(v["descriptor"], v["id"]) for v in facet.get("values", [])]
    except Exception:
        pass
    return []


def _collect_stubs_for_grade(session, grade_descriptor, grade_id):
    """Collect job stubs (without description/deadline) for a given grade."""
    stubs = []
    offset = 0
    limit = 20
    while True:
        try:
            payload = {
                "appliedFacets": {"Management_Level": [grade_id]},
                "limit": limit, "offset": offset, "searchText": "",
            }
            resp = session.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for job in postings:
            external_path = job.get("externalPath", "")
            if not external_path:
                continue
            slug = external_path.rstrip("/").split("/")[-1]
            url = f"https://wd3.myworkdaysite.com/en-US/recruiting/wfp/job_openings/details/{slug}"
            city, country = _split_location(job.get("locationsText"))
            stubs.append({
                "_path": external_path,
                "agency": AGENCY, "agency_name": AGENCY_NAME,
                "job_title": job.get("title", ""),
                "grade": grade_descriptor,
                "city": city, "country": country, "url": url,
            })
        total = data.get("total", 0)
        if offset + limit >= total:
            break
        offset += limit
    return stubs


def scrape() -> list[dict]:
    session = requests.Session()
    all_stubs = []

    grade_facets = _fetch_grade_facets(session)
    for descriptor, grade_id in grade_facets:
        all_stubs.extend(_collect_stubs_for_grade(session, descriptor, grade_id))

    cache = load_cached_jobs()
    futures = []
    jobs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for s in all_stubs:
            path = s.pop("_path")
            if s["url"] in cache:
                c = cache[s["url"]]
                s["deadline"] = c.get("deadline")
                s["pubdate"] = c.get("pubdate")
                s["description"] = c.get("description")
                jobs.append(s)
            else:
                futures.append((s, ex.submit(_fetch_detail, session, path)))
    for stub, fut in futures:
        deadline, pubdate, description = fut.result()
        stub["deadline"] = deadline
        stub["pubdate"] = pubdate
        stub["description"] = description
        jobs.append(stub)
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
