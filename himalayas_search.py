"""
himalayas_search.py
-------------------
Fetches remote job listings from the Himalayas public API and returns
them in a format compatible with Cindy's existing job_db.py schema.

API: https://himalayas.app/jobs/api/search
No API key or authentication required.
Rate limit: once per day is fine; data refreshes every 24 hours.

Attribution: job listings sourced from Himalayas (https://himalayas.app)
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Callable

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — tune these to Cindy's target profile
# ---------------------------------------------------------------------------

SEARCH_URL = "https://himalayas.app/jobs/api/search"

# Keywords that reflect Cindy's seniority and function.
# Mix broad and specific terms to maximise coverage without noise.
SEARCH_QUERIES = [
    "sourcing procurement director",
    "strategic sourcing VP",
    "procurement executive remote",
    "supply chain sourcing director",
    "global procurement manager",
    "indirect sourcing director",
]

# Seniority values accepted by the Himalayas API:
# Entry-level | Mid-level | Senior | Manager | Director | Executive
TARGET_SENIORITY = ["Senior", "Manager", "Director", "Executive"]

# How many pages to fetch per query (20 jobs/page, so 2 pages = 40 jobs max per query).
# Keep low to stay polite on the rate limit.
PAGES_PER_QUERY = 2

# Seconds to wait between API requests — be a good citizen.
REQUEST_DELAY = 1.5

# Request timeout in seconds.
REQUEST_TIMEOUT = 20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fingerprint(title: str, company: str) -> str:
    """
    SHA-256 fingerprint matching the pattern in job_db.py.
    Deduplicates on (normalised title, normalised company).
    """
    key = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()


def _strip_html(html: str) -> str:
    """Return plain text from sanitised HTML description."""
    if not html:
        return ""
    try:
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        return html  # fall back to raw string if parser unavailable


def _salary_label(job: dict) -> str:
    """Human-readable salary string for logging / display."""
    lo = job.get("minSalary")
    hi = job.get("maxSalary")
    cur = job.get("currency", "USD")
    if lo and hi:
        return f"{cur} {lo:,}–{hi:,}"
    if lo:
        return f"{cur} {lo:,}+"
    return ""


def _normalize(raw: dict) -> dict:
    """
    Map a raw Himalayas job object to the schema used by job_db.py.

    job_db.py expected columns (based on the existing pipeline):
        title, company, location, url, source, date_found,
        description, salary_min, salary_max, fingerprint
    """
    title = raw.get("title", "").strip()
    company = raw.get("companyName", "").strip()

    # Location: show country restrictions if present, else "Worldwide Remote"
    loc_restrictions = raw.get("locationRestrictions", [])
    if loc_restrictions:
        # API returns either strings or dicts depending on the endpoint
        parts = []
        for r in loc_restrictions:
            if isinstance(r, dict):
                parts.append(r.get("name", "") or r.get("alpha2", ""))
            elif isinstance(r, str):
                parts.append(r)
        countries = ", ".join(p for p in parts if p)
        location = f"Remote ({countries})" if countries else "Remote"
    else:
        location = "Worldwide Remote"

    return {
        "title":       title,
        "company":     company,
        "location":    location,
        "url":         raw.get("applicationLink", ""),
        "source":      "Himalayas",
        "date_found":  datetime.now(timezone.utc).isoformat(),
        "description": _strip_html(raw.get("description", "")),
        "salary_min":  raw.get("minSalary"),
        "salary_max":  raw.get("maxSalary"),
        "fingerprint": _fingerprint(title, company),
        # Extra fields — job_db.py can ignore these or store them in a JSON blob
        "seniority":   raw.get("seniority", []),
        "categories":  raw.get("categories", []),
        "pub_date":    raw.get("pubDate", ""),
    }


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def _fetch_page(query: str, page: int) -> list[dict]:
    """
    Fetch one page of search results for a single query.
    Returns a list of raw job dicts (or empty list on error).
    """
    params = {
        "q":               query,
        "employment_type": "Full Time",
        "sort":            "recent",   # newest listings first
        "page":            page,
    }
    # Add seniority filters as repeated params (Himalayas accepts multiple)
    # requests encodes list values as repeated keys automatically when passed as list
    params["seniority"] = TARGET_SENIORITY

    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs", [])
        logger.debug(
            "Himalayas | query=%r page=%d -> %d jobs (total available: %s)",
            query, page, len(jobs), data.get("totalCount", "?")
        )
        return jobs
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            logger.warning("Himalayas rate-limited (429). Skipping remaining pages for %r.", query)
        else:
            logger.error("Himalayas HTTP error for query %r page %d: %s", query, page, e)
        return []
    except requests.exceptions.RequestException as e:
        logger.error("Himalayas request failed for query %r page %d: %s", query, page, e)
        return []


def _fetch_query(query: str) -> list[dict]:
    """Fetch all configured pages for a single search query."""
    raw_jobs = []
    for page in range(1, PAGES_PER_QUERY + 1):
        page_jobs = _fetch_page(query, page)
        if not page_jobs:
            break  # no results or error — stop paginating this query
        raw_jobs.extend(page_jobs)
        if page < PAGES_PER_QUERY:
            time.sleep(REQUEST_DELAY)
    return raw_jobs


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def search_all(dedup_fn: Callable[[str], bool] | None = None) -> list[dict]:
    """
    Run all SEARCH_QUERIES, normalise results, and return new jobs only.

    Parameters
    ----------
    dedup_fn : callable, optional
        A function that accepts a fingerprint (str) and returns True if that
        job is already stored in the SQLite database.  Pass in:

            lambda fp: db.fingerprint_exists(fp)

        If None, only intra-batch deduplication is performed.

    Returns
    -------
    list[dict]
        Normalised job records ready to be inserted by job_db.py.
    """
    seen_in_batch: set[str] = set()
    new_jobs: list[dict] = []
    total_fetched = 0

    for i, query in enumerate(SEARCH_QUERIES):
        logger.info("Himalayas | searching: %r", query)
        raw_jobs = _fetch_query(query)
        total_fetched += len(raw_jobs)

        for raw in raw_jobs:
            job = _normalize(raw)
            fp = job["fingerprint"]

            # Skip duplicates within this batch
            if fp in seen_in_batch:
                continue
            seen_in_batch.add(fp)

            # Skip jobs already in the SQLite DB
            if dedup_fn and dedup_fn(fp):
                continue

            new_jobs.append(job)

        # Pause between queries (not needed after the last one)
        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(REQUEST_DELAY)

    logger.info(
        "Himalayas | done. Fetched %d raw, %d unique batch, %d new after DB dedup.",
        total_fetched, len(seen_in_batch), len(new_jobs)
    )
    return new_jobs


# ---------------------------------------------------------------------------
# Standalone test — run directly to verify the API is working
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== Himalayas API test run ===\n")
    jobs = search_all()  # no dedup_fn in test mode

    if not jobs:
        print("No jobs returned. Check your queries or network connection.")
    else:
        for j in jobs[:10]:  # show first 10
            sal = ""
            if j.get("salary_min") and j.get("salary_max"):
                sal = f"  [{j['salary_min']:,}–{j['salary_max']:,}]"
            pub = "date unknown"
            print(f"  {j['title']} @ {j['company']}{sal}")
            print(f"    {j['location']} | {pub}")
            print(f"    {j['url']}\n")

        if len(jobs) > 10:
            print(f"  ... and {len(jobs) - 10} more.")
