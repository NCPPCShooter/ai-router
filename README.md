# AI Router

A personal AI orchestration system that accepts natural language input, intelligently routes tasks to the best available AI, and returns results — including email delivery of output.

## Architecture

```
Your Input → Router (Claude) → [Claude / Grok / OpenAI] → Result / Email
```

For complex tasks (search + format + email):
```
Input → Grok (web search) → Claude (format) → Gmail (deliver)
```

## Setup

### Prerequisites
- Python 3.13+
- VS Code with GitHub Copilot Chat (`Ctrl+Alt+I`)

### Install Dependencies
```bash
pip install anthropic openai python-dotenv
```

### Environment Variables
Store all API keys as **Windows User Environment Variables** (never in code files).

| Variable | Where to Get It |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `XAI_API_KEY` | console.x.ai |
| `OPENAI_API_KEY` | platform.openai.com |
| `GMAIL_APP_PASSWORD` | myaccount.google.com → Security → App Passwords |

> After setting environment variables, **fully restart VS Code** to pick them up.

## Usage

```bash
python router.py
```

Type your task in plain English at the prompt. Examples:

- `Summarize the pros and cons of microservices architecture`  → routes to **Claude**
- `What are the latest AI news stories today?` → routes to **Grok**
- `Find remote Sr. Sourcing Manager jobs paying $150K+ and email results to me` → routes to **Multi** (Grok + Claude + Gmail)

Type `quit` to exit.

## File Structure

```
ai-router/
├── .gitignore          # Protects .env from git
├── README.md           # This file
├── router.py           # Main AI router
├── test_claude.py      # Claude API connection test
├── test_grok.py        # Grok API connection test
└── test_openai.py      # OpenAI API connection test
```

## Routing Logic

Claude acts as the router brain and selects one of:

| Route | Used For |
|---|---|
| `claude` | Reasoning, analysis, writing, coding, formatting |
| `grok` | Live web search, job searches, current events |
| `openai` | General knowledge, creative writing |
| `multi` | Tasks requiring search + format + email |

## AI Roster

| Tool | Role |
|---|---|
| Claude (Anthropic) | Router brain + reasoning/writing/analysis worker |
| Grok (xAI) | Live web search and current information |
| OpenAI GPT-4o | General knowledge and creative tasks |
| GitHub Copilot | Coding assistant while building (VS Code) |

## Key Gotchas

- **Never** use `type .env` in terminal — use `dir .env` to verify file exists
- Rotate keys immediately at their respective consoles if ever exposed
- OpenAI API credits are separate from ChatGPT subscriptions (manage at platform.openai.com)
- Grok uses the OpenAI-compatible SDK with `base_url="https://api.x.ai/v1"`
- Always fully restart VS Code after updating Windows environment variables

## Next Steps

- [ ] Refine job search prompt templates
- [ ] Add Excel/CSV output for search results  
- [ ] Build Streamlit UI for browser-based access
- [ ] Add task history and logging
- [ ] Package as desktop app
