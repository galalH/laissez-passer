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

## Relevance scoring (optional)

After each scrape, jobs can be automatically scored for relevance using OpenAI's `gpt-5.4-nano` model via the Batch API. Set your API key to enable it:

```bash
export OPENAI_API_KEY=sk-...
```

Scoring is skipped silently if the key is absent or if no persona is configured.

### Persona

A persona is a plain-text (Markdown) description of what you're looking for — your background, skills, and the kinds of roles you're interested in. It is used as the system prompt when scoring each job.

Open the settings panel (gear icon in the UI) to write or edit your persona. Saving a new persona resets all existing scores and re-scores every job against the updated description.

### Filter

The filter lets you narrow the jobs shown in the UI using plain English — for example: *"P-3 to P-5 roles in Geneva or home-based"*. The description is translated to a pandas query by `gpt-5.4-nano` and cached; the filter is re-applied on every page load and during scoring so only matching jobs are scored. The filter can also be cleared from the settings panel.

## Add a scraper

Create a file in `scrapers/` with:

```python
AGENCY = "Agency Name"

def scrape():
    # return a list of job dicts
    return [{"title": ..., "link": ..., "location": ..., "grade": ..., "deadline": ...}]
```

It will be auto-discovered on the next scrape.
