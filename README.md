# Khursheed

A technical executive assistant that automates lead discovery, email triage, and daily reporting.

## Tech Stack

- **Python** — core implementation
- **SQLite** — task state persistence
- **Streamlit** — web UI ("Hey Eman")
- **OpenAI** — LLM-powered natural language interface
- **Tavily** — lead discovery search

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and fill in your API keys / credentials
```

## Usage

### Streamlit UI

```bash
source .venv/bin/activate
streamlit run hey_eman_app.py
```

### CLI

```bash
source .venv/bin/activate
python khursheed.py
```

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/
```

## Project Structure

```
khursheed.py          — CLI entry point
hey_eman_app.py       — Streamlit web UI
llm_agent.py          — OpenAI-powered conversational agent
manager.py            — Task runner and SQLite state manager
notifications.py      — Notifier abstractions
executive_summary.py  — Daily report generator
skills/               — Pluggable skill modules
  base.py             — Abstract Skill base class
  echo.py             — Echo skill (testing)
  timestamp.py        — Timestamp skill
  lead_scout.py       — Tavily-powered lead discovery
  scout.py            — Company research + assessment hooks
  sifter.py           — IMAP email triage + expense extraction
  tavily_client.py    — Shared Tavily search client
config/               — Configuration files
tests/                — Unit tests
```
