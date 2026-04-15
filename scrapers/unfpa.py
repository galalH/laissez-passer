import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

AGENCY = "UNFPA"
AGENCY_NAME = "United Nations Population Fund"
JOBS_URL = "https://www.unfpa.org/jobs"

from urllib.parse import urljoin

_ORACLE_BASE = "https://estm.fa.em2.oraclecloud.com"
_DETAIL_API = f"{_ORACLE_BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"


def _fetch_pubdate(session: requests.Session, job_id: str) -> str | None:
    try:
        params = {
            "expand": "all", "onlyData": "true",
            "finder": f'ById;Id="{job_id}",siteNumber=CX_1',
        }
        resp = session.get(_DETAIL_API, params=params, timeout=30)
        resp.raise_for_status()
        item = (resp.json().get("items") or [{}])[0]
        start = item.get("ExternalPostedStartDate") or None
        return start[:10] if start else None
    except Exception:
        return None


def _collect_links_from_page(soup):
    """Extract job URLs from the paginated current-jobs view-content section."""
    urls = []
    # The page has two view-content divs; the first one is the paginated current jobs list
    view_contents = soup.find_all('div', class_='view-content')
    container = view_contents[0] if view_contents else None
    if not container:
        return urls
    for row in container.find_all('div', class_='jbs-rows'):
        a = row.find('h5').find('a') if row.find('h5') else None
        if not a:
            continue
        href = a.get('href', '')
        if href.startswith('/'):
            href = f"https://www.unfpa.org{href}"
        if href:
            urls.append(href)
    return urls


def scrape() -> list[dict]:
    """Scrapes current job listings from UNFPA jobs page."""
    jobs = []
    seen_urls = set()
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    all_job_urls = []

    # Fetch page 0 and determine max page from the first rel="last" link
    # (the jobs pager; a second pager for news/articles appears later in the DOM)
    try:
        response = session.get(JOBS_URL, timeout=30)
        response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    all_job_urls.extend(_collect_links_from_page(soup))

    last_link = soup.find('a', rel='last')
    max_page = 0
    if last_link:
        m = re.search(r'page=(\d+)', last_link.get('href', ''))
        if m:
            max_page = int(m.group(1))

    for page in range(1, max_page + 1):
        try:
            resp = session.get(f"{JOBS_URL}?page={page}", timeout=30)
            resp.raise_for_status()
            all_job_urls.extend(_collect_links_from_page(BeautifulSoup(resp.content, 'html.parser')))
        except Exception:
            continue

    # Deduplicate
    unique_job_urls = []
    for job_url in all_job_urls:
        if job_url not in seen_urls:
            seen_urls.add(job_url)
            unique_job_urls.append(job_url)

    def _fetch_job(job_url):
        try:
            resp = session.get(job_url, timeout=30)
            resp.raise_for_status()
            job_soup = BeautifulSoup(resp.content, 'html.parser')
            job_title = extract_job_title(job_soup)
            if not job_title:
                return None
            fields = _get_form_fields(job_soup)
            job_id = fields.get('job id') or None
            pubdate = _fetch_pubdate(session, job_id) if job_id else None
            return {
                'agency': AGENCY, 'agency_name': AGENCY_NAME,
                'job_title': job_title,
                'grade': extract_grade(job_soup),
                'city': extract_location(job_soup)[0],
                'country': extract_location(job_soup)[1],
                'deadline': extract_deadline(job_soup),
                'pubdate': pubdate,
                'url': job_url,
                'description': extract_description(job_soup),
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_fetch_job, url) for url in unique_job_urls]

    return [job for fut in futures if (job := fut.result()) is not None]

def extract_job_title(soup):
    h1 = soup.find('h1')
    if h1:
        return h1.get_text(strip=True)
    og_title = soup.find('meta', {'property': 'og:title'})
    if og_title:
        content = og_title.get('content', '')
        if '|' in content:
            content = content.split('|')[0].strip()
        return content
    return None

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}


def _get_form_fields(soup):
    """Extract all <div class='form-group'> label->value pairs."""
    fields = {}
    for div in soup.find_all('div', class_='form-group'):
        label = div.find('label')
        value = div.find('p')
        if label and value:
            fields[label.get_text(strip=True).lower()] = value.get_text(strip=True)
    return fields


def extract_description(soup):
    import copy
    article = soup.find('article')
    if not article:
        return None
    article = copy.copy(article)
    for fg in article.find_all('div', class_='form-group'):
        fg.decompose()
    # Normalize tables: rows with a single <td> get an empty second <td> so
    # MarkItDown doesn't lock the markdown table to 1 column.
    for tr in article.find_all('tr'):
        cells = tr.find_all('td')
        if len(cells) == 1:
            cells[0]['colspan'] = 2
    return trim(
        html_to_md(str(article)),
        after=[re.compile(r"\**\s*Compensation and Benefits"), re.compile(r"\**\s*UNFPA Work Environment")],
    )


def extract_grade(soup):
    fields = _get_form_fields(soup)
    return fields.get('staff grade/level') or None


def extract_location(soup):
    fields = _get_form_fields(soup)
    city = fields.get('duty station') or None
    return city, None


def extract_deadline(soup):
    fields = _get_form_fields(soup)
    raw = fields.get('closing date')
    if not raw:
        return None
    # Format: "25 March 2026 11:37(America/New_York)"
    parts = raw.split()
    if len(parts) >= 3:
        try:
            day = parts[0]
            month = _MONTHS.get(parts[1].lower())
            year = parts[2][:4]
            if month and year.isdigit():
                return f"{year}-{month}-{day.zfill(2)}"
        except Exception:
            pass
    return None

if __name__ == "__main__":
    print(json.dumps(scrape()))
