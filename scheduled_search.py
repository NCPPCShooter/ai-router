import os
import sys
import time
from datetime import date, datetime

# Add the router directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from router import handle_multi_task

# Log file location
LOG_DIR = r"C:\Users\kirkk\Projects\ai-router\logs"
LOG_FILE = os.path.join(LOG_DIR, "search_log.txt")

# Job search prompts to run each morning
SEARCHES = [
    {
        "name": "Cindy - US Search",
        "prompt": open(r"C:\Users\kirkk\Projects\Job-Search-Prompts\searches\sr-sourcing-manager-prompt.txt").read().replace("###END###", "").strip()
    },
    # Uncomment below to also run global search each morning
    # {
    #     "name": "Cindy - Global Search",
    #     "prompt": open(r"C:\Users\kirkk\Projects\Job-Search-Prompts\searches\sr-sourcing-manager-global-prompt.txt").read().replace("###END###", "").strip()
    # },
]


def write_log(message, also_print=True):
    """Write a message to the log file and optionally print it."""
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")
    if also_print:
        print(message)


def run_scheduled_searches():
    now = datetime.now().strftime("%B %d, %Y - %I:%M %p")
    
    write_log("\n" + "=" * 51)
    write_log(f"AI Job Search Log - {now}")
    write_log("=" * 51)

    total_start = time.time()

    for search in SEARCHES:
        write_log(f"\nRunning: {search['name']}")
        write_log("-" * 30)
        
        search_start = time.time()
        
        try:
            # Monkey-patch handle_multi_task to capture job results for logging
            result = handle_multi_task_logged(search['prompt'], search['name'])
            elapsed = round(time.time() - search_start, 1)
            write_log(f"  Completed in {elapsed} seconds")
            write_log(f"  Status: Success")
            
        except Exception as e:
            elapsed = round(time.time() - search_start, 1)
            write_log(f"  ERROR after {elapsed} seconds: {str(e)}")

    total_elapsed = round(time.time() - total_start, 1)
    write_log(f"\nAll searches complete in {total_elapsed} seconds.")
    write_log("=" * 51 + "\n")


def handle_multi_task_logged(user_input, search_name):
    """Wrapper around handle_multi_task that logs progress."""
    import re
    from router import (
        search_with_grok, parse_jobs_from_grok, build_verified_search_urls,
        validate_url, format_with_claude, send_email
    )
    from datetime import date

    exclude_companies = []
    if "First Citizens" in user_input:
        exclude_companies = ["First Citizens", "First Citizens Bank & Trust"]

    validated_jobs = []
    attempt = 0
    seen_companies = set()
    target_valid = 10
    max_attempts = 5

    while len(validated_jobs) < target_valid and attempt < max_attempts:
        attempt += 1
        write_log(f"  Search attempt {attempt}/{max_attempts}...")

        raw_results = search_with_grok(user_input, exclude_companies)
        jobs = parse_jobs_from_grok(raw_results)

        write_log(f"  Found {len(jobs)} raw listings, validating...")

        for job in jobs:
            company_key = job.get("company", "").lower().strip()
            if company_key in seen_companies:
                continue
            if any(exc.lower() in company_key for exc in exclude_companies):
                continue

            search_urls = build_verified_search_urls(
                job.get("title", ""),
                job.get("company", "")
            )

            verified_urls = {}
            for platform, url in search_urls.items():
                if validate_url(url):
                    verified_urls[platform] = url

            if verified_urls:
                job["search_links"] = verified_urls
                job["link_status"] = "✅ Verified"
                validated_jobs.append(job)
                seen_companies.add(company_key)
                write_log(f"  ✅ {job.get('company')} - {job.get('title')}")
            else:
                write_log(f"  ⚠️  Skipped {job.get('company')} - no valid links")

            if len(validated_jobs) >= target_valid:
                break

        write_log(f"  Progress: {len(validated_jobs)}/{target_valid} verified jobs")

    if not validated_jobs:
        write_log("  ❌ No verified jobs found after all attempts")
        return "No verified job listings found."

    write_log(f"\n  Formatting {len(validated_jobs)} results with Claude...")
    formatted_results = format_with_claude(validated_jobs, user_input)

    write_log(f"  Sending email to cindyrkeller@gmail.com...")
    send_email(
        to_address="cindyrkeller@gmail.com",
        subject=f"{search_name} - {date.today().strftime('%B %d, %Y')}",
        body=formatted_results
    )
    write_log(f"  ✅ Email delivered successfully")
    return f"Done! {len(validated_jobs)} jobs emailed."


if __name__ == "__main__":
    run_scheduled_searches()