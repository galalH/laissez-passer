import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json

AGENCY = "UNFPA"
AGENCY_NAME = "United Nations Population Fund"
JOBS_URL = "https://www.unfpa.org/jobs"

from urllib.parse import urljoin


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

    # Extract job information from each job page
    for job_url in unique_job_urls:
        try:
            job_response = session.get(job_url, timeout=30)
            job_response.raise_for_status()
        except Exception as e:
            print(f"Error fetching job {job_url}: {e}")
            continue

        job_soup = BeautifulSoup(job_response.content, 'html.parser')

        # Extract job details
        job_title = extract_job_title(job_soup)
        grade = extract_grade(job_soup)
        city, country = extract_location(job_soup)
        deadline = extract_deadline(job_soup)

        if job_title:  # Only add if we got a title
            jobs.append({
                'agency': AGENCY,
                'agency_name': AGENCY_NAME,
                'job_title': job_title,
                'grade': grade,
                'city': city,
                'country': country,
                'deadline': deadline,
                'url': job_url
            })

    return jobs

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
