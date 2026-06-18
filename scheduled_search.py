"""
scheduled_search.py — Daily job search runner for Cindy.

Runs via cron at 6 AM on the Ubuntu server.
Logs to:  ~/ai-router/logs/search_log.txt

BEHAVIOR (SQLite dedup layer):
  - Parses raw Grok results and stores net-new postings to SQLite DB
  - Pulls additional listings from Himalayas public API (no key required)
  - Sends Cindy a SHORT notification email: "X new postings found today"
  - No more full digest emails — the DB is the source of truth
"""

import os
import sys
import logging
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — must come before local imports
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_DIR  = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "search_log.txt")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------

from router import search_with_grok, send_email, build_verified_search_urls
from job_db import store_jobs, store_jobs_list, get_total_count, fingerprint_exists
from himalayas_search import search_all as himalayas_search_all


# ---------------------------------------------------------------------------
# Search definitions
# ---------------------------------------------------------------------------

def _read_prompt(filename: str) -> str:
    """Read a prompt file from the Job-Search-Prompts repo."""
    path = os.path.join(
        os.path.expanduser("~"), "Job-Search-Prompts", "searches", filename
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


SEARCHES = [
    {
        "name":        "US Search",
        "prompt_file": "sr-sourcing-manager-prompt.txt",
    },
#    {
#        "name":        "Global Search",
#        "prompt_file": "sr-sourcing-manager-global-prompt.txt",
#    },
]


# ---------------------------------------------------------------------------
# Notification email builder
# ---------------------------------------------------------------------------

def build_notification_email(results_by_search: list[dict], run_date: str) -> str:
    """
    Build a concise notification email body.

    results_by_search: list of dicts, one per search:
        { name, new, duplicate, parsed, new_jobs }
    """
    results_by_search = [r for r in results_by_search if r is not None]
    total_new   = sum(r["new"]       for r in results_by_search)
    total_dupes = sum(r["duplicate"] for r in results_by_search)
    db_total    = get_total_count()

    lines = [
        f"Hi Cindy,",
        f"",
        f"Your daily job search ran this morning ({run_date}).",
        f"",
        f"{'─' * 44}",
        f"  New postings added today:   {total_new}",
        f"  Already seen (duplicates):  {total_dupes}",
        f"  Total in your database:     {db_total}",
        f"{'─' * 44}",
        f"",
    ]

    if total_new == 0:
        lines += [
            "No new postings were found today — all results were already in",
            "your database from a previous search.",
            "",
        ]
    else:
        lines += [
            f"Here's what was added today:",
            "",
        ]
        for search_result in results_by_search:
            if search_result["new"] == 0:
                continue
            lines.append(f"  {search_result['name']} ({search_result['new']} new):")
            for job in search_result.get("new_jobs", []):
                title   = job.get("title",    "Unknown Title")[:60]
                company = job.get("company",  "Unknown Company")[:50]
                loc     = job.get("location", "")[:40]
                sal     = job.get("salary",   "")
                url     = job.get("url",      "")

                lines.append(f"    • {title}")
                lines.append(f"      {company}" + (f" | {loc}" if loc else ""))
                if sal:
                    lines.append(f"      {sal}")
                if url:
                    lines.append(f"      {url}")
                lines.append("")

    lines += [
        "Kirk's AI Router added these to your job database automatically.",
        "",
        "Good luck today!",
        "— AI Router",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-search runner (Grok only)
# ---------------------------------------------------------------------------

def run_search(search_def: dict) -> dict:
    """
    Run a single Grok search:
      1. Load prompt
      2. Call Grok for raw results
      3. Store to SQLite (dedup happens here)
      4. Return store_jobs summary dict + search name
    """
    name = search_def["name"]
    log.info(f"Starting: {name}")

    try:
        prompt = _read_prompt(search_def["prompt_file"])
    except FileNotFoundError as e:
        log.error(f"Prompt file not found for {name}: {e}")
        return {"name": name, "new": 0, "duplicate": 0, "parsed": 0, "new_jobs": [], "error": str(e)}

    # --- Step 1: Grok search ---
    log.info(f"  Calling Grok...")
    raw_text = search_with_grok(prompt)
    log.info(f"  Grok returned {len(raw_text)} chars")

    # --- Step 2: Store + dedup ---
    summary = store_jobs(raw_text, source=name, verbose=True)
    summary["name"] = name

    log.info(f"  {name}: {summary['new']} new, {summary['duplicate']} dupes, {summary['parsed']} parsed")
    return summary


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_scheduled_searches() -> None:
    run_date = date.today().strftime("%B %d, %Y")
    log.info("=" * 60)
    log.info(f"Daily job search starting — {run_date}")
    log.info("=" * 60)

    results = []

    # --- Grok searches ---
    for search_def in SEARCHES:
        result = run_search(search_def)
        results.append(result)

    # --- Himalayas (internet-wide, runs once per daily job, separate from Grok) ---
    log.info("Running Himalayas search...")
    try:
        himalayas_jobs = himalayas_search_all(
            dedup_fn=lambda fp: fingerprint_exists(fp)
        )
        if himalayas_jobs:
            h_summary = store_jobs_list(himalayas_jobs, verbose=True)
            h_summary["name"] = "Himalayas"
            log.info(f"Himalayas: {h_summary['new']} new, {h_summary['duplicate']} dupes")
            results.append(h_summary)
        else:
            log.info("Himalayas: no new jobs found")
    except Exception as e:
        log.error(f"Himalayas search failed: {e}")

    # --- Build and send notification email ---
    total_new = sum(r["new"] for r in results if r is not None)
    subject   = f"Job Search Update — {total_new} New Posting{'s' if total_new != 1 else ''} — {run_date}"
    body      = build_notification_email(results, run_date)

    log.info(f"Sending notification email: {subject}")
    try:
        send_email(
            to_address="cindyrkeller@gmail.com, kirkkeller@gmail.com",
            subject=subject,
            body=body,
        )
        log.info("Notification email sent successfully.")
    except Exception as e:
        log.error(f"Failed to send notification email: {e}")

    # --- Final summary ---
    log.info("=" * 60)
    for r in results:
        if r is not None:
            log.info(f"  {r['name']}: {r['new']} new / {r['duplicate']} dupes / {r.get('parsed', len(r.get('new_jobs', [])))  } parsed")
    log.info(f"  Total new postings today: {total_new}")
    log.info(f"  Total in DB: {get_total_count()}")
    log.info("=" * 60)
    log.info("Run complete.")


if __name__ == "__main__":
    run_scheduled_searches()