# Laissez-Passer

Aggregates job listings from 30+ UN agencies and international organizations into a single searchable dashboard.

## Stack

- Python 3.14+, Flask, Playwright, BeautifulSoup4, pandas

## Install

```bash
uv pip install -e .
playwright install
```

## Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000).

## Refresh jobs

Click **Refresh** in the UI or `POST /refresh` to trigger a live scrape. Progress streams in real time and output is saved to `static/data.json`.

## Add a scraper

Create a file in `scrapers/` with:

```python
AGENCY = "Agency Name"

def scrape():
    # return a list of job dicts
    return [{"title": ..., "link": ..., "location": ..., "grade": ..., "deadline": ...}]
```

It will be auto-discovered on the next scrape.
