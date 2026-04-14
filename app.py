#!/usr/bin/env python3
"""Laissez-Passer — Flask app and scraper driver."""

import importlib.util
import io
import json
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import country_converter as coco
import pandas as pd
from flask import Flask, Response, jsonify, send_from_directory, stream_with_context

from scrapers._grade import normalize_grade

logging.getLogger("country_converter").setLevel(logging.ERROR)
logging.getLogger("country_converter.country_converter").setLevel(logging.ERROR)
_cc = coco.CountryConverter()


def _cc_convert(val: str, to: str):
    result = _cc.convert(val, to=to, not_found=None)
    return result[0] if isinstance(result, list) else result


_HOME_BASED_RE = re.compile(r"home.?based|remote", re.IGNORECASE)
_MULTI_LOCATION_RE = re.compile(
    r"anywhere|multiple|various|locations?|\d+\s+locations?|field|tbd|to\s+be\s+determined|\bother\b",
    re.IGNORECASE,
)

_CC_COUNTRY_NAMES = set()
for _col in ("name_short", "name_official"):
    _CC_COUNTRY_NAMES.update(_cc.data[_col].str.lower().dropna())

BASE_DIR = Path(__file__).parent
SCRAPERS_DIR = BASE_DIR / "scrapers"
DATA_FILE = BASE_DIR / "static" / "data.json"

_DUTY_STATION_URL = "https://unsceb.org/sites/default/files/statistic_files/HR/duty_station.csv"


def _load_duty_stations() -> dict[str, tuple[str, str]]:
    df = pd.read_csv(_DUTY_STATION_URL, encoding="utf-8-sig")
    df = df[df["YEAR"] == df["YEAR"].max()]
    counts = df.groupby("DS")["COUNTRY"].nunique()
    unambiguous = counts[counts == 1].index
    df = df[df["DS"].isin(unambiguous)].drop_duplicates("DS")
    return {row["DS"].lower(): (row["DS"], row["COUNTRY"]) for _, row in df.iterrows()}


_DS_LOOKUP = _load_duty_stations()

_STRIP_PATS = [
    re.compile(r"\s*\([^)]+\)\s*$"),
    re.compile(r"\s*-\s*other\s+cities\s*$", re.IGNORECASE),
    re.compile(r"^(?:HQ|FO)\s+", re.IGNORECASE),
    re.compile(r"\s+RO\s*$", re.IGNORECASE),
]


def _strip_city(city: str) -> tuple[str, str | None]:
    s = city.strip()
    country_hint = None

    m = re.search(r"\(([^)]+)\)\s*$", s)
    if m:
        hint = m.group(1).strip()
        cc = _cc.convert(hint, to="name_short", not_found=None)
        if cc:
            country_hint = cc

    prev = None
    while prev != s:
        prev = s
        for pat in _STRIP_PATS:
            s = pat.sub("", s).strip()

    if "," in s:
        base, suffix = s.split(",", 1)
        suffix = suffix.strip()
        if suffix and country_hint is None:
            country_hint = suffix
        s = base.strip()

    return s, country_hint


def _normalize_location(
    city: str | None, country: str | None
) -> tuple[str | None, str | None]:
    for val in (city, country):
        if val and _HOME_BASED_RE.search(val):
            return None, "Home Based"
        if val and _MULTI_LOCATION_RE.search(val):
            return None, "Multiple Locations"

    country_hint = None

    if city:
        ds = _DS_LOOKUP.get(city.lower())
        if ds:
            return ds

        cleaned, country_hint = _strip_city(city)
        ds = _DS_LOOKUP.get(cleaned.lower())
        if ds:
            return ds

        cc = _cc.convert(cleaned, to="name_short", not_found=None)
        if cc and cc.lower() in _CC_COUNTRY_NAMES:
            return None, cc

        city = cleaned

    return city, country or country_hint


def _process_job(job: dict, agency: str, previous: dict, now: str) -> list[str]:
    warnings: list[str] = []

    job["pubdate"] = previous.get(job.get("url", ""), now)

    raw = job.get("grade")
    job["grade_raw"] = raw
    try:
        job["grade"], job["grade_category"] = normalize_grade(
            raw, agency=job.get("agency", agency), title=job.get("job_title", "")
        )
    except Exception as e:
        warnings.append(f"WARNING: {agency} grade normalization failed for {raw!r}: {e}")
        job["grade"], job["grade_category"] = raw, "Other"

    city, country_raw = _normalize_location(job.get("city"), job.get("country"))
    job["city"] = city

    if country_raw == "Home Based":
        job["country"] = "Home Based"
        job["country_iso3"] = "XRM"
    elif country_raw == "Multiple Locations":
        job["country"] = "Multiple Locations"
        job["country_iso3"] = "XMU"
    elif country_raw:
        name = _cc_convert(country_raw, "name_short")
        iso3 = _cc_convert(country_raw, "ISO3")
        if name is not None:
            job["country"] = name
            job["country_iso3"] = iso3
        else:
            job["country"] = None
            job["city"] = None
            job["country_iso3"] = "XXX"
            warnings.append(f"WARNING: {agency} could not normalize country {country_raw!r} for job {job.get('url', '')}")
    else:
        job["country"] = None
        job["country_iso3"] = "XXX"

    if not job.get("country") and job.get("city"):
        job["city_raw"] = job["city"]
        job["city"] = None

    return warnings


def _load_previous_jobs() -> dict[str, str]:
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            payload = json.load(f)
        jobs = payload.get("jobs", payload) if isinstance(payload, dict) else payload
        return {job["url"]: job["pubdate"] for job in jobs if job.get("url") and job.get("pubdate")}
    return {}


def _discover_plugins() -> list:
    modules = []
    for py_file in sorted(SCRAPERS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        if spec is None or spec.loader is None:
            print(f"WARNING: Could not load {py_file.name}", file=sys.stderr)
            continue
        try:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            modules.append(mod)
        except Exception as e:
            print(f"WARNING: Failed to import {py_file.name}: {e}", file=sys.stderr)
    return modules




def scrape(progress=print):
    """Run all scrapers. Calls progress(msg) for each status line."""
    previous = _load_previous_jobs()
    plugins = _discover_plugins()
    random.shuffle(plugins)
    now = datetime.now().astimezone().isoformat(timespec='seconds')

    all_jobs = []
    agency_count = 0
    warning_count = 0
    total = len(plugins)

    progress(f"total:{total}")

    def run_plugin(plugin):
        warnings = []
        agency = getattr(plugin, "AGENCY", plugin.__name__)
        try:
            jobs = plugin.scrape()
            if not isinstance(jobs, list):
                warnings.append(f"WARNING: {agency} scrape() did not return a list")
                return agency, [], warnings
            unknown = getattr(plugin, "unknown_depts", set())
            for dept in unknown:
                warnings.append(f"WARNING: un_secretariat: unknown department {dept!r} — defaulting to UNS")
            unknown.clear()
            return agency, jobs, warnings
        except Exception as e:
            warnings.append(f"WARNING: {agency} scrape failed: {e}")
            return agency, [], warnings

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(run_plugin, p): p for p in plugins}
        n = 0
        for future in as_completed(futures):
            agency, jobs, warnings = future.result()
            n += 1
            for w in warnings:
                progress(f"warning:{w}")
                warning_count += 1
            if not jobs:
                progress(f"warning:INFO: {agency} returned 0 jobs")
                warning_count += 1
            else:
                for job in jobs:
                    for w in _process_job(job, agency, previous, now):
                        progress(f"warning:{w}")
                        warning_count += 1
                all_jobs.extend(jobs)
                agency_count += 1
            progress(f"progress:{n}/{total}:{agency}:{len(jobs)}")

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": now, "jobs": all_jobs}
    with open(DATA_FILE, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    suffix = f" · {warning_count} warnings" if warning_count else ""
    progress(f"done:{len(all_jobs)} jobs from {agency_count} agencies{suffix}")

    return all_jobs


# ── Scoring ──────────────────────────────────────────────────────────────────

_SCORE_TOOL = {
    "type": "function",
    "function": {
        "name": "record_score",
        "description": "Record the relevance score for the job listing.",
        "parameters": {
            "type": "object",
            "properties": {
                "score": {
                    "type": "number",
                    "description": "Relevance score between 0.0 and 1.0",
                }
            },
            "required": ["score"],
        },
    },
}

_SCORE_TOOL_CHOICE = {"type": "function", "function": {"name": "record_score"}}

_PERSONA_FILE = BASE_DIR / "static" / "persona.md"


def _build_score_message(job: dict) -> str:
    location = ", ".join(filter(None, [job.get("city", ""), job.get("country", "")]))
    header = " | ".join(filter(None, [
        job.get("agency_name", ""),
        job.get("job_title", ""),
        location,
    ]))
    description = (job.get("description") or "").strip()
    return (
        f"{header}\n\n"
        f"{description}\n\n"
        "Score this job's relevance to the persona on a scale of 0.0 to 1.0. "
        "Call record_score with your score."
    )


def score_new_jobs(all_jobs: list, progress=print, jobs_to_score: list | None = None) -> None:
    """Score jobs that are missing a score using GPT-5.4-nano via OpenAI Batch API.

    all_jobs is the full list written back to disk.  jobs_to_score is the subset
    that should be scored (must be references into all_jobs); defaults to all_jobs.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        progress("scoring_skip:no OPENAI_API_KEY — skipping scoring")
        return

    if not _PERSONA_FILE.exists() or not _PERSONA_FILE.read_text().strip():
        progress("scoring_skip:persona not configured — skipping scoring")
        return

    try:
        import openai
    except ImportError as e:
        progress(f"scoring_skip:missing dependency ({e}) — skipping scoring")
        return

    try:
        persona = _PERSONA_FILE.read_text().strip()
        source = jobs_to_score if jobs_to_score is not None else all_jobs

        to_score = [
            (i, job) for i, job in enumerate(source)
            if job.get("score") is None
        ]

        if not to_score:
            progress("scoring_skip:all jobs already scored")
            return

        client = openai.OpenAI(api_key=api_key, max_retries=0)

        # ── Split into token-capped batches ───────────────────────────────────
        # Rough estimate: 1 token ≈ 4 chars.  Each request costs:
        #   persona (fixed) + tool definition (~100 tok) + user message + 64 output + ~50 overhead
        _BATCH_TOKEN_TARGET = int(2_000_000 * 0.8)  # 1.6 M tokens per batch
        _FIXED_PER_REQ = (len(persona) // 4) + 100 + 64 + 50

        requests: list[tuple[int, dict, str]] = [
            (idx, job, _build_score_message(job)) for idx, job in to_score
        ]

        batches: list[list[tuple[int, dict, str]]] = []
        current: list[tuple[int, dict, str]] = []
        current_tokens = 0
        for idx, job, user_msg in requests:
            tokens = _FIXED_PER_REQ + len(user_msg) // 4
            if current and current_tokens + tokens > _BATCH_TOKEN_TARGET:
                batches.append(current)
                current = [(idx, job, user_msg)]
                current_tokens = tokens
            else:
                current.append((idx, job, user_msg))
                current_tokens += tokens
        if current:
            batches.append(current)

        progress(f"scoring_start:{len(to_score)}")

        # ── Process batches sequentially: submit → wait → collect → next ──────
        _TERMINAL = {"completed", "failed", "expired", "cancelled"}
        scores: dict[int, float | None] = {}
        jobs_done = 0  # cumulative across completed batches

        for batch_requests in batches:
            lines = [
                json.dumps({
                    "custom_id": str(idx),
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-5.4-nano",
                        "max_completion_tokens": 64,
                        "tools": [_SCORE_TOOL],
                        "tool_choice": _SCORE_TOOL_CHOICE,
                        "messages": [
                            {"role": "system", "content": persona},
                            {"role": "user", "content": user_msg},
                        ],
                    },
                })
                for idx, _job, user_msg in batch_requests
            ]
            batch_file = client.files.create(
                file=("score.jsonl", io.BytesIO("\n".join(lines).encode()), "application/jsonl"),
                purpose="batch",
            )
            batch = client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
            )

            started_at = time.monotonic()
            while batch.status not in _TERMINAL:
                time.sleep(10)
                batch = client.batches.retrieve(batch.id)
                elapsed = int(time.monotonic() - started_at)
                progress(f"scoring:{jobs_done + batch.request_counts.completed}:{len(to_score)}:{elapsed}")

            if batch.status != "completed":
                progress(f"scoring_skip:batch ended with status {batch.status}")
            else:
                scores.update(_parse_batch_scores(
                    client.files.content(batch.output_file_id).text
                ))

            jobs_done += len(batch_requests)

        for idx, job in to_score:
            job["score"] = scores.get(idx)

        # Reload to get the updated timestamp written by scrape(), then write scores back
        try:
            with DATA_FILE.open() as f:
                payload = json.load(f)
            updated = payload.get("updated", "")
        except Exception:
            updated = ""
        with DATA_FILE.open("w") as f:
            json.dump({"updated": updated, "jobs": all_jobs}, f,
                      ensure_ascii=False, separators=(",", ":"))

        n_scored = sum(1 for s in scores.values() if s is not None)
        progress(f"scoring_done:{n_scored}/{len(to_score)}")

    except Exception as e:
        progress(f"scoring_skip:scoring failed ({e})")


def _parse_batch_scores(result_text: str) -> dict[int, float | None]:
    """Parse OpenAI batch output JSONL into {custom_id -> score}."""
    scores: dict[int, float | None] = {}
    for line in result_text.strip().splitlines():
        row = json.loads(line)
        idx = int(row["custom_id"])
        if row.get("error"):
            scores[idx] = None
            continue
        tool_calls = row["response"]["body"]["choices"][0]["message"].get("tool_calls", [])
        score = None
        for tc in tool_calls:
            name = tc["function"]["name"] if isinstance(tc, dict) else tc.function.name
            args = tc["function"]["arguments"] if isinstance(tc, dict) else tc.function.arguments
            if name == "record_score":
                try:
                    score = float(json.loads(args)["score"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    pass
                break
        scores[idx] = score
    return scores


def _resume_scoring(progress) -> bool:
    """Check for active OpenAI batches and poll them to completion.

    Returns True if active batches were found (caller should skip scraping),
    False if there is nothing in flight.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return False

    try:
        import openai
    except ImportError:
        return False

    try:
        client = openai.OpenAI(api_key=api_key, max_retries=0)

        _ACTIVE    = {"validating", "in_progress", "finalizing"}
        _TERMINAL  = {"completed", "failed", "expired", "cancelled"}

        active_batches = [b for b in client.batches.list() if b.status in _ACTIVE]
        if not active_batches:
            return False

        if not DATA_FILE.exists():
            return False

        with open(DATA_FILE) as f:
            payload = json.load(f)
        all_jobs = payload.get("jobs", [])
        total = sum(1 for job in all_jobs if job.get("score") is None)

        if not total:
            return False

        progress(f"scoring_start:{total}")

        batch_objs = {b.id: b for b in active_batches}
        still_active = set(batch_objs)
        started_at = time.monotonic()

        while still_active:
            for bid in list(still_active):
                b = client.batches.retrieve(bid)
                batch_objs[bid] = b
                if b.status in _TERMINAL:
                    still_active.discard(bid)
            total_completed = sum(b.request_counts.completed for b in batch_objs.values())
            elapsed = int(time.monotonic() - started_at)
            progress(f"scoring:{total_completed}:{total}:{elapsed}")
            if still_active:
                time.sleep(10)

        all_scores: dict[int, float | None] = {}
        for b in batch_objs.values():
            if b.status != "completed":
                progress(f"scoring_skip:batch ended with status {b.status}")
                continue
            all_scores.update(_parse_batch_scores(client.files.content(b.output_file_id).text))

        for i, job in enumerate(all_jobs):
            if i in all_scores:
                job["score"] = all_scores[i]

        try:
            with DATA_FILE.open() as f:
                existing = json.load(f)
            updated = existing.get("updated", "")
        except Exception:
            updated = ""
        with DATA_FILE.open("w") as f:
            json.dump({"updated": updated, "jobs": all_jobs}, f,
                      ensure_ascii=False, separators=(",", ":"))

        n_scored = sum(1 for s in all_scores.values() if s is not None)
        progress(f"scoring_done:{n_scored}/{total}")
        return True

    except Exception as e:
        progress(f"scoring_skip:scoring failed during resume ({e})")
        return False


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", static_url_path="")


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/data.json")
def data():
    if not DATA_FILE.exists():
        return jsonify({"error": "no data yet"}), 404
    return send_from_directory(app.static_folder, "data.json")


@app.route("/refresh", methods=["POST"])
def refresh():
    def generate():
        for line in _scrape_lines():
            yield f"data:{line}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


def _scrape_lines():
    """Run scrape() then score_new_jobs(), yielding progress lines as they're emitted."""
    import queue
    import threading

    q = queue.Queue()

    def progress(msg):
        q.put(msg)

    def run():
        try:
            if not _resume_scoring(progress):
                all_jobs = scrape(progress=progress)
                score_new_jobs(all_jobs, progress=progress)
        finally:
            q.put(None)  # sentinel

    t = threading.Thread(target=run, daemon=True)
    t.start()

    while True:
        msg = q.get()
        if msg is None:
            break
        yield msg


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
