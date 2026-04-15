"""IMO Job Scraper - uses the IMO vacancy portal JSON API."""

import requests
from bs4 import BeautifulSoup

from scrapers._utils import html_to_md

AGENCY = "IMO"
AGENCY_NAME = "International Maritime Organization"
JOBS_URL = "https://recruit.imo.org/"
API_URL = "https://recruit.imo.org/api/CurrentJobVacancies"
JOB_URL_TEMPLATE = "https://recruit.imo.org/vacancies/{job_id}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://recruit.imo.org/",
}


def _parse_deadline(deadline_str):
    """Convert deadline from DD/MM/YYYY format to YYYY-MM-DD format."""
    if not deadline_str:
        return None
    try:
        parts = deadline_str.split("/")
        if len(parts) == 3:
            day, month, year = parts
            return f"{year}-{month}-{day}"
    except Exception:
        pass
    return None


def _normalize_grade(grade):
    """Normalize grade format: remove dots (P.2 -> P2, G.7 -> G7)."""
    if not grade or grade == "N/A":
        return None
    return grade.replace(".", "")


_DESCRIPTION_FIELDS = (
    ("purposeforthepost",           "Purpose of the Post"),
    ("maindutiesandresponsibilities","Main Duties and Responsibilities"),
    ("requiredcompetencies",        "Required Competencies"),
    ("professionalexperience",      "Professional Experience"),
    ("education",                   "Education"),
    ("languageskills",              "Language Skills"),
    ("otherskills",                 "Other Skills"),
)


def _parse_description(job: dict) -> str | None:
    parts = []
    for field, label in _DESCRIPTION_FIELDS:
        md = html_to_md(job.get(field) or "")
        if md:
            parts.append(f"**{label}**\n\n{md}")
    return "\n\n".join(parts) or None


def _parse_job(job):
    job_id = job.get("jobVacancyId", "")
    job_title = job.get("title", "")
    grade = _normalize_grade(job.get("classification"))
    deadline = job.get("deadlineforapplications") or None

    if job_id:
        url = JOB_URL_TEMPLATE.format(job_id=job_id)
    else:
        url = JOBS_URL

    return {
        "agency": AGENCY,
        "agency_name": AGENCY_NAME,
        "job_title": job_title,
        "grade": grade,
        "city": "London",
        "country": "United Kingdom",
        "deadline": _parse_deadline(deadline),
        "pubdate": _parse_deadline(job.get("dateofissue") or None),
        "url": url,
        "description": _parse_description(job),
    }


def scrape() -> list:
    session = requests.Session()
    resp = session.get(API_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    jobs_data = resp.json()
    return [_parse_job(job) for job in jobs_data]


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
