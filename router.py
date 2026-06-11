import os
import re
import json
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date
import anthropic
from openai import OpenAI

# Initialize clients
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
grok_client = OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1")
from xai_sdk import Client as XAIClient
from xai_sdk.tools import web_search as grok_web_search
xai_client = XAIClient(api_key=os.getenv("XAI_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
github_client = OpenAI(api_key=os.getenv("GITHUB_TOKEN"), base_url="https://models.github.ai/inference")
perplexity_client = OpenAI(api_key=os.getenv("PERPLEXITY_API_KEY"), base_url="https://api.perplexity.ai")

# Email config
SENDER_EMAIL = "kirkkeller@gmail.com"
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# Routing prompt
ROUTING_PROMPT = """You are an AI task router. Analyze the task and respond with ONLY one of these words:
- claude: reasoning, analysis, writing, summarization, formatting, general questions
- grok: current events, live web search, news, recent information
- openai: creative writing, broad general knowledge tasks
- github: ANY coding task, code generation, code review, debugging, technical documentation, programming questions, software development, writing functions or scripts
- research: search for contact information, company details, recruiter info, business research, or any research requiring cited sources then email results
- multi: search for JOB OPENINGS or JOB POSTINGS then format and email results

Respond with ONLY one word. Nothing else."""


def route_task(user_input):
    """Ask Claude to decide which AI should handle this task."""
    response = claude_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=10,
        messages=[
            {"role": "user", "content": f"{ROUTING_PROMPT}\n\nTask: {user_input}"}
        ]
    )
    return response.content[0].text.strip().lower()


def build_verified_search_urls(job_title, company):
    """Build guaranteed working search URLs for a job at a company."""
    title_encoded = requests.utils.quote(job_title)
    company_encoded = requests.utils.quote(company)
    query = f"{title_encoded}+{company_encoded}"

    return {
        "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={query}&f_WT=2",
        "Indeed": f"https://www.indeed.com/jobs?q={query}&l=Remote",
        "Glassdoor": f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={query}"
    }


def validate_url(url):
    """Check if a URL returns a valid response."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.head(url, headers=headers, timeout=5, allow_redirects=True)
        if response.status_code in [200, 301, 302]:
            return True
        return False
    except:
        return False


def parse_jobs_from_grok(raw_text):
    """Ask Claude to parse Grok's response into structured job data."""
    response = claude_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        messages=[
            {"role": "user", "content": f"""Parse the following job search results into a JSON array.
Each job should have these exact fields:
- title (job title)
- company (company name)
- salary (salary range or "Not listed")
- location (location or remote status)
- description (2-3 sentence description)

Return ONLY a valid JSON array with no other text, no markdown, no backticks.
If you cannot parse any jobs, return an empty array: []

Raw results:
{raw_text}"""}
        ]
    )
    
    raw_response = response.content[0].text.strip()
    print(f"\n--- DEBUG: Claude parse response (first 300 chars) ---")
    print(raw_response[:300])
    print("--- END DEBUG ---\n")
    
    try:
        # Strip any accidental markdown backticks
        clean = raw_response.replace("```json", "").replace("```", "").strip()
        jobs = json.loads(clean)
        return jobs if isinstance(jobs, list) else []
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        return []


def search_with_grok(user_input, exclude_companies=None):
    """Use Grok with live web search tool enabled."""
    exclude_text = ""
    if exclude_companies:
        exclude_text = f"\nDo NOT include positions from: {', '.join(exclude_companies)}"

    search_query = f"""Search the web right now for real current remote job postings.
Find at least 10 remote Senior Sourcing or Procurement Manager positions paying $140,000-$175,000+.

Search LinkedIn, Indeed, Glassdoor for these titles:
Senior Sourcing Manager, Director of Sourcing, Strategic Sourcing Manager, 
Senior Procurement Manager, Global Sourcing Manager, Contract Manager, Vendor Manager

Requirements: Remote only, US-based, salary $140k-$175k+
{exclude_text}

For each job return:
Job Title: [title]
Company: [company]
Salary: [salary or Not listed]
Location: [remote/location]
Description: [2-3 sentences]"""

    from xai_sdk.chat import user as xai_user
    from xai_sdk.tools import web_search as grok_web_search

    chat = xai_client.chat.create(
        model="grok-3",
        tools=[grok_web_search()],
    )

    chat.append(xai_user(search_query))
    response = chat.sample()

    if hasattr(response, 'message'):
        result = response.message.content
    elif hasattr(response, 'choices'):
        result = response.choices[0].message.content
    elif hasattr(response, 'content'):
        result = response.content
    else:
        result = str(response)

    print(f"\n--- DEBUG: Grok raw response (first 500 chars) ---")
    print(result[:500])
    print("--- END DEBUG ---\n")
    return result

def research_with_grok(user_input):
    """Use Grok to research contact information and business details."""
    from xai_sdk.chat import user as xai_user
    from xai_sdk.tools import web_search as grok_web_search

    chat = xai_client.chat.create(
        model="grok-3",
        tools=[grok_web_search()],
    )

    chat.append(xai_user(user_input))
    response = chat.sample()

    if hasattr(response, 'message'):
        result = response.message.content
    elif hasattr(response, 'choices'):
        result = response.choices[0].message.content
    elif hasattr(response, 'content'):
        result = response.content
    else:
        result = str(response)

    print(f"\n--- DEBUG: Grok research response (first 500 chars) ---")
    print(result[:500])
    print("--- END DEBUG ---\n")
    return result

def research_with_perplexity(user_input):
    """Use Perplexity for research tasks with cited sources."""
    response = perplexity_client.chat.completions.create(
        model="sonar",
        messages=[
            {"role": "system", "content": "You are a research assistant. Search the web thoroughly and provide detailed, accurate results with citations and sources for every claim."},
            {"role": "user", "content": user_input}
        ]
    )
    result = response.choices[0].message.content
    print(f"\n--- DEBUG: Perplexity response (first 500 chars) ---")
    print(result[:500])
    print("--- END DEBUG ---\n")
    return result

def research_with_both(user_input):
    """Use Grok for discovery, Perplexity for verification."""
    print("  Discovery search with Grok...")
    grok_results = research_with_grok(user_input)
    print("  Verification search with Perplexity...")
    perplexity_results = research_with_perplexity(user_input)
    return f"GROK FINDINGS:\n{grok_results}\n\nPERPLEXITY VERIFIED:\n{perplexity_results}"

def format_with_claude(jobs_with_links, user_input):
    """Use Claude to format validated jobs into a clean email."""
    jobs_text = json.dumps(jobs_with_links, indent=2)
    
    response = claude_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        messages=[
            {"role": "user", "content": f"""Format these verified job search results into a clean email.

Each job has been verified and includes working search links.
Format each job clearly with all details.
Note that links go to job board searches for that specific role at that company.
End with a brief note about search criteria used.

Original request summary: {user_input[:200]}

Jobs data:
{jobs_text}"""}
        ]
    )
    return response.content[0].text


def send_email(to_address, subject, body):
    """Send email via Gmail SMTP."""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.send_message(msg)

def handle_research_task(user_input):
    """Handle research tasks - search web and email results."""
    print("Searching with Grok + Perplexity...")
    raw_results = research_with_both(user_input)

    print("Formatting results with Claude...")
    formatted_results = format_with_claude(
        raw_results,
        user_input + "\n\nNote: Results include both Grok discovery findings and Perplexity verified citations. Where they agree, treat as confirmed. Where they differ, note the discrepancy. Prioritize Perplexity citations as more reliable."
    )

    # Extract email address from prompt if present
    import re
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_input)
    to_address = email_match.group(0) if email_match else "cindyrkeller@gmail.com"

    # Extract subject from prompt or use default
    subject_match = re.search(r'subject[:\s]+"?([^"\n]+)"?', user_input, re.IGNORECASE)
    subject = subject_match.group(1).strip() if subject_match else f"Research Results - {date.today().strftime('%B %d, %Y')}"

    print(f"Sending email to {to_address}...")
    send_email(
        to_address=to_address,
        subject=subject,
        body=formatted_results
    )

    return f"Done! Results emailed to {to_address}\n\nPreview:\n{formatted_results[:500]}..."

def handle_multi_task(user_input, target_valid=10, max_attempts=5):
    """Handle tasks requiring search + format + email with recursive validation."""
    
    # Extract excluded companies from the prompt
    exclude_companies = []
    if "First Citizens" in user_input:
        exclude_companies = ["First Citizens", "First Citizens Bank & Trust"]

    validated_jobs = []
    attempt = 0
    seen_companies = set()

    while len(validated_jobs) < target_valid and attempt < max_attempts:
        attempt += 1
        print(f"Step {attempt}: Searching for jobs (attempt {attempt}/{max_attempts})...")
        
        raw_results = search_with_grok(user_input, exclude_companies)
        
        print(f"   Parsing job listings...")
        jobs = parse_jobs_from_grok(raw_results)
        
        print(f"   Found {len(jobs)} listings, building and validating links...")
        
        for job in jobs:
            # Skip if we already have this company
            company_key = job.get("company", "").lower().strip()
            if company_key in seen_companies:
                continue
            
            # Skip excluded companies
            if any(exc.lower() in company_key for exc in exclude_companies):
                continue

            # Build verified search URLs
            search_urls = build_verified_search_urls(
                job.get("title", ""), 
                job.get("company", "")
            )
            
            # Validate at least one URL works
            verified_urls = {}
            for platform, url in search_urls.items():
                if validate_url(url):
                    verified_urls[platform] = url
            
            if verified_urls:
                job["search_links"] = verified_urls
                job["link_status"] = "✅ Verified"
                validated_jobs.append(job)
                seen_companies.add(company_key)
                print(f"   ✅ {job.get('company')} - {job.get('title')}")
            else:
                print(f"   ⚠️  Skipping {job.get('company')} - no valid links found")

            if len(validated_jobs) >= target_valid:
                break

        print(f"   Have {len(validated_jobs)}/{target_valid} verified jobs so far...")

    if not validated_jobs:
        return "No verified job listings found after maximum search attempts."

    print(f"\nFormatting {len(validated_jobs)} verified results with Claude...")
    formatted_results = format_with_claude(validated_jobs, user_input)

    print("Sending email...")
    send_email(
        to_address="cindyrkeller@gmail.com",
        subject=f"Job Search Results - {date.today().strftime('%B %d, %Y')}",
        body=formatted_results
    )

    return f"Done! {len(validated_jobs)} verified jobs emailed to cindyrkeller@gmail.com\n\nPreview:\n{formatted_results[:500]}..."


def run_task(ai, user_input):
    """Send the task to the chosen AI and return the result."""
    if ai == "research":
        return handle_research_task(user_input)
    
    if ai == "multi":
        return handle_multi_task(user_input)

    elif ai == "claude":
        response = claude_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": user_input}]
        )
        return response.content[0].text

    elif ai == "grok":
        response = grok_client.chat.completions.create(
            model="grok-3",
            messages=[
                {"role": "system", "content": "You are a research assistant with live web search. Search the web and return detailed results with links and sources."},
                {"role": "user", "content": user_input}
            ]
        )
        return response.choices[0].message.content

    elif ai == "openai":
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": user_input}]
        )
        return response.choices[0].message.content

    elif ai == "github":
        response = github_client.chat.completions.create(
            model="openai/gpt-4.1",
            messages=[
                {"role": "system", "content": "You are an expert software engineer and technical assistant. Help with code generation, code review, debugging, and technical documentation."},
                {"role": "user", "content": user_input}
            ]
        )
        return response.choices[0].message.content


def main():
    print("AI Router ready. Type 'quit' or paste your prompt, then press Enter twice when done.\n")
    while True:
        print("Your task (press Enter twice when done):")
        lines = []
        while True:
            line = input()
            if line.strip() == "###END###":
                break
            else:
                lines.append(line)
        user_input = "\n".join(lines).strip()

        if user_input.lower() == "quit":
            break
        if not user_input:
            continue

        print("\nRouting your task...")
        chosen_ai = route_task(user_input)
        print(f"Routing to: {chosen_ai.upper()}\n")

        result = run_task(chosen_ai, user_input)
        print(f"Result:\n{result}\n")
        print("-" * 50 + "\n")


if __name__ == "__main__":
    main()