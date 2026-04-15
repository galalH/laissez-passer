import requests
from bs4 import BeautifulSoup
import json
import re
from dateutil import parser as dateutil_parser
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim, load_cached_jobs

AGENCY = "UNESCO"
AGENCY_NAME = "United Nations Educational Scientific and Cultural Organization"
JOBS_URL = "https://careers.unesco.org/go/All-jobs-openings/784002/"

# French month names/abbreviations → English (for dateutil)
_FR_MONTHS = {
    "janvier": "January", "janv": "January",
    "février": "February", "fevrier": "February", "fév": "February", "fev": "February",
    "mars": "March",
    "avril": "April", "avr": "April",
    "mai": "May",
    "juin": "June",
    "juillet": "July", "juil": "July",
    "août": "August", "aout": "August", "aoû": "August",
    "septembre": "September", "sept": "September",
    "octobre": "October", "oct": "October",
    "novembre": "November", "nov": "November",
    "décembre": "December", "decembre": "December", "déc": "December", "dec": "December",
}
_FR_RE = re.compile("|".join(re.escape(k) for k in _FR_MONTHS), re.IGNORECASE)


def _normalize(s: str) -> str:
    return _FR_RE.sub(lambda m: _FR_MONTHS[m.group().lower()], s)


def _parse_deadline(s):
    """Parse deadline to YYYY-MM-DD; handles DD-MON-YYYY, DD/MM/YYYY, DD.MM.YYYY,
    YYYY-MM-DD, full month names, and French month abbreviations (e.g. '13-AVR-2026')."""
    if not s:
        return None
    try:
        return dateutil_parser.parse(_normalize(s.strip()), dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_location(location_str):
    """Parse location into city and country. Splits on last comma."""
    if not location_str:
        return None, None

    location_str = location_str.strip()
    if "," in location_str:
        # Split on the last comma
        last_comma_idx = location_str.rfind(",")
        city = location_str[:last_comma_idx].strip()
        country = location_str[last_comma_idx + 1:].strip()
        return city, country
    else:
        # No comma found, treat entire string as city
        return location_str, None


BASE_URL = "https://careers.unesco.org"
PAGE_SIZE = 25

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _fetch_description(session, job_url: str) -> tuple[str | None, str | None]:
    try:
        resp = session.get(job_url, timeout=20)
        resp.raise_for_status()
        html = resp.text
        pubdate = None
        m = re.search(r'itemprop="datePosted"\s+content="([^"]+)"', html)
        if not m:
            m = re.search(r'content="([^"]+)"\s+itemprop="datePosted"', html)
        if m:
            from datetime import datetime
            try:
                pubdate = datetime.strptime(m.group(1), "%a %b %d %H:%M:%S %Z %Y").strftime("%Y-%m-%d")
            except Exception:
                pubdate = m.group(1)
        el = BeautifulSoup(html, "html.parser").find(class_="jobdescription")
        description = trim(
            html_to_md(str(el)) if el else None,
            before=re.compile(r"UNESCO Core Values: Commitment to the Organization, Integrity, Respect for Diversity, Professionalism\**"),
            after=re.compile(r"\**\s*BENEFITS AND ENTITLEMENTS"),
        )
        return description, pubdate
    except Exception:
        return None, None


def scrape() -> list[dict]:
    stubs = []
    offset = 0
    session = requests.Session()
    session.headers.update(_HEADERS)

    while True:
        if offset == 0:
            url = f"{BASE_URL}/go/All-jobs-openings/784002/"
        else:
            url = f"{BASE_URL}/go/All-jobs-openings/784002/{offset}/"

        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except Exception:
            break

        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", {"id": "searchresults"})
        if not table:
            break

        rows = table.find_all("tr", {"class": "data-row"})
        if not rows:
            break

        for row in rows:
            try:
                title_link = row.find("a", {"class": "jobTitle-link"})
                if not title_link or not title_link.get("href"):
                    continue

                job_title = title_link.get_text(strip=True)
                job_url = title_link.get("href")
                if not job_url.startswith("http"):
                    job_url = BASE_URL + job_url

                location_el = row.find("span", {"class": "jobLocation"})
                location_str = location_el.get_text(strip=True) if location_el else None
                city, country = _parse_location(location_str)

                grade_el = row.find("span", {"class": "jobDepartment"})
                grade = grade_el.get_text(strip=True) if grade_el else None

                deadline_el = row.find("span", {"class": "jobShifttype"})
                deadline_raw = deadline_el.get_text(strip=True) if deadline_el else None
                deadline = _parse_deadline(deadline_raw)

                stubs.append({
                    "agency": AGENCY, "agency_name": AGENCY_NAME,
                    "job_title": job_title, "grade": grade or None,
                    "city": city, "country": country,
                    "deadline": deadline, "url": job_url,
                })
            except Exception:
                continue

        table_label = table.get("aria-label", "")
        try:
            total = int(table_label.split("of")[-1].strip())
        except Exception:
            break

        offset += PAGE_SIZE
        if offset >= total:
            break

    cache = load_cached_jobs()
    futures = []
    jobs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for s in stubs:
            if s["url"] in cache:
                c = cache[s["url"]]
                jobs.append({**s, "pubdate": c.get("pubdate"), "description": c.get("description")})
            else:
                futures.append((s, ex.submit(_fetch_description, session, s["url"])))
    for stub, fut in futures:
        description, pubdate = fut.result()
        jobs.append({**stub, "pubdate": pubdate, "description": description})
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
