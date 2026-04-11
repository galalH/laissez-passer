#!/usr/bin/env python3
"""Refresh data.json for a single scraper agency.

Usage: uv run refresh_one.py <agency>
Example: uv run refresh_one.py ifad
"""

import sys
import json
import importlib
from datetime import datetime
from pathlib import Path

# Make app-level helpers available without importing the Flask app
sys.path.insert(0, str(Path(__file__).parent))
from app import _process_job, _load_previous_jobs, DATA_FILE


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <agency>", file=sys.stderr)
        sys.exit(1)

    agency_arg = sys.argv[1].lower().replace("-", "_")

    try:
        plugin = importlib.import_module(f"scrapers.{agency_arg}")
    except ModuleNotFoundError:
        print(f"No scraper found for '{agency_arg}'", file=sys.stderr)
        sys.exit(1)

    agency = getattr(plugin, "AGENCY", agency_arg.upper())
    print(f"Scraping {agency}…")
    jobs = plugin.scrape()
    print(f"  got {len(jobs)} jobs")

    previous = _load_previous_jobs()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for job in jobs:
        warnings = _process_job(job, agency, previous, now)
        for w in warnings:
            print(f"  {w}", file=sys.stderr)

    data = {"updated": now, "jobs": jobs}

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  wrote {DATA_FILE} ({len(data['jobs'])} total jobs)")


if __name__ == "__main__":
    main()
