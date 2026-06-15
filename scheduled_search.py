"""
scheduled_search.py — Daily job search runner for Cindy.

Runs via Windows Task Scheduler at 6 AM.
Logs to:  C:\\Users\\kirkk\\Projects\\ai-router\\logs\\search_log.txt

NEW BEHAVIOR (SQLite dedup layer):
  - Parses raw Grok results and stores net-new postings to SQLite DB
  - Sends Cindy a SHORT notification email: "X new postings found today"
  - No more full digest emails — the DB is the source of truth
"""

import os
import sys
import logging
from datetime import date, datetime

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

from router import search_with_grok, send_email   # existing router functions
from job_db import store_jobs, get_total_count     # new dedup layer

# ---------------------------------------------------------------------------
# Search definitions
# ---------------------------------------------------------------------------

def _read_prompt(filename: str) -> str:
    """Read a prompt file from the Job-Search-Prompts repo."""
    path = os.path.join(
        r"C:\Users\kirkk\Projects\Job-Search-Prompts", "searches", filename
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read().replace("###END###", "").strip()


SEARCHES = [
    {
        "name":        "US Search",
        "prompt_file": "sr-sourcing-manager-prompt.txt",
    },
    {
        "name":        "Global Search",
        "prompt_file": "sr-sourcing-manager-global-prompt.txt",
    },
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
            for job in search_result["new_jobs"]:
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
# Per-search runner
# ---------------------------------------------------------------------------

def run_search(search_def: dict) -> dict:
    """
    Run a single search:
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
    try:
        raw_text = search_with_grok(prompt)
        log.info(f"  Grok returned {len(raw_text)} chars")
    except Exception as e:
        log.error(f"  Grok search failed for {name}: {e}")
        return {"name": name, "new": 0, "duplicate": 0, "parsed": 0, "new_jobs": [], "error": str(e)}

    # --- Step 2: Store + dedup ---
    log.info(f"  Storing to SQLite (dedup)...")
    try:
        summary = store_jobs(raw_text, source=name, verbose=True)
        summary["name"] = name
        log.info(
            f"  {name}: parsed={summary['parsed']}  "
            f"new={summary['new']}  dupes={summary['duplicate']}"
        )
    except Exception as e:
        log.error(f"  DB store failed for {name}: {e}")
        return {"name": name, "new": 0, "duplicate": 0, "parsed": 0, "new_jobs": [], "error": str(e)}

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
    for search_def in SEARCHES:
        result = run_search(search_def)
        results.append(result)

    # --- Build and send notification email ---
    total_new = sum(r["new"] for r in results)
    subject   = f"Job Search Update — {total_new} New Posting{'s' if total_new != 1 else ''} — {run_date}"
    body      = build_notification_email(results, run_date)

    log.info(f"Sending notification email: {subject}")
    try:
        send_email(
            to_address="cindyrkeller@gmail.com",
            subject=subject,
            body=body,
        )
        log.info("Notification email sent successfully.")
    except Exception as e:
        log.error(f"Failed to send notification email: {e}")

    # --- Final summary ---
    log.info("=" * 60)
    for r in results:
        log.info(f"  {r['name']}: {r['new']} new / {r['duplicate']} dupes / {r['parsed']} parsed")
    log.info(f"  Total new postings today: {total_new}")
    log.info(f"  Total in DB: {get_total_count()}")
    log.info("=" * 60)
    log.info("Run complete.")


if __name__ == "__main__":
    run_scheduled_searches()
