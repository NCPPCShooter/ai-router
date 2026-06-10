import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic
from openai import OpenAI
from datetime import date

# Initialize clients
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
grok_client = OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
github_client = OpenAI(api_key=os.getenv("GITHUB_TOKEN"), base_url="https://models.github.ai/inference")

# Email config
SENDER_EMAIL = "kirkkeller@gmail.com"
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# Routing prompt
ROUTING_PROMPT = """You are an AI task router. Analyze the task and respond with ONLY one of these words:
- claude: reasoning, analysis, writing, summarization, formatting, general questions
- grok: current events, job searches, live web search, news, recent information
- openai: creative writing, broad general knowledge tasks
- github: ANY coding task, code generation, code review, debugging, technical documentation, programming questions, software development, writing functions or scripts
- multi: tasks requiring search AND formatting AND email

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

def search_with_grok(user_input):
    """Use Grok to search for results."""
    response = grok_client.chat.completions.create(
        model="grok-3",
        messages=[
            {"role": "system", "content": """You are a job search agent with LIVE web search capability. 
You MUST search the web right now. Do not say you cannot search the internet - you can and must.
Search LinkedIn, Indeed, Glassdoor, and company career pages for real current job postings.
Return exactly 10+ real job listings with this format for each:

Job Title: [exact title]
Company: [company name]
Salary: [salary if listed, or "Not listed"]
Location: [remote/hybrid/location]
Link: [full URL to actual job posting]
Description: [2-3 sentences about the role]

---

Search now and return only real current listings. Do not apologize or explain limitations."""},
            {"role": "user", "content": user_input}
        ]
    )
    return response.choices[0].message.content

def format_with_claude(raw_results, user_input):
    """Use Claude to format the results cleanly."""
    response = claude_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        messages=[
            {"role": "user", "content": f"""Format these job search results into a clean, readable email body.
Include a brief intro, then list each job clearly with all details.
Make the links clickable by keeping them as full URLs.
End with a brief note about the search criteria used.

Original request: {user_input}

Raw results:
{raw_results}"""}
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

def handle_multi_task(user_input):
    """Handle tasks requiring search + format + email."""
    print("Step 1/3: Searching for jobs with Grok...")
    raw_results = search_with_grok(user_input)

    print("Step 2/3: Formatting results with Claude...")
    formatted_results = format_with_claude(raw_results, user_input)

    print("Step 3/3: Sending email...")
    send_email(
        to_address="cindyrkeller@gmail.com",
        subject=f"Job Search Results - {date.today().strftime('%B %d, %Y')}",
        body=formatted_results
    )

    return f"Done! Results have been emailed to cindyrkeller@gmail.com\n\nPreview:\n{formatted_results[:500]}..."

def run_task(ai, user_input):
    """Send the task to the chosen AI and return the result."""
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