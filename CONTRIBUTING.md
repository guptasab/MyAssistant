# Contributing to MyAssistant

Thank you for your interest in contributing! MyAssistant is MIT-licensed and welcomes
contributions of all kinds — new skills, bug fixes, documentation improvements,
and new channel integrations.

---

## Getting Started

```bash
git clone https://github.com/yourusername/myassistant.git
cd MyAssistant
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your API keys
python -m myassistant skills  # verify setup
```

---

## How to Add a New Skill

A "skill" is a Python function that the AI agent can call as a tool. Skills
are the primary way to extend MyAssistant's capabilities.

### 1. Create the skill file

```python
# myassistant/skills/my_service.py
"""Skills for MyService integration.

Provides read and write access to MyService via their REST API.
Requires MY_SERVICE_API_KEY to be set in .env.
"""
from __future__ import annotations

from myassistant.core.registry import skill
from myassistant.core.config import settings


@skill(
    name="myservice_search",
    description="Search MyService for items matching a query",
    requires=["my_service_api_key"],  # skill is disabled if this env var is missing
)
def myservice_search(query: str, limit: int = 10) -> str:
    """Search for items in MyService.
    
    Args:
        query: Search query string.
        limit: Maximum number of results to return.
    
    Returns:
        Formatted list of results, or an error message.
    """
    import httpx
    try:
        r = httpx.get(
            "https://api.myservice.com/search",
            params={"q": query, "limit": limit},
            headers={"Authorization": f"Bearer {settings.my_service_api_key}"},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        return "\n".join(f"- {i['name']}: {i['description']}" for i in items)
    except Exception as e:
        return f"MyService search failed: {e}"
```

### 2. Add the config field

```python
# myassistant/core/config.py — add inside the Settings class
my_service_api_key: str = ""   # MyService API key
```

### 3. Add to .env.example

```env
# MyService
MY_SERVICE_API_KEY=       # Get yours at https://myservice.com/api
```

### 4. That's it!

Run `python -m myassistant skills` — your skill should appear in the list.
Drop a file anywhere under `myassistant/skills/` and it is auto-discovered.
No registration, no import lists to update.

---

## Skill Design Guidelines

### Be descriptive
The `description` parameter is what the AI reads to decide whether to call
your skill. Make it specific about *when* to use it:

```python
# ✅ Good
description="Search for restaurants near a location. Use for food, dining, takeout queries."

# ❌ Too vague
description="Search for places"
```

### Mark sensitive actions
Any action with side effects that can't be easily reversed should use
`sensitive=True`. This triggers a user-confirmation prompt:

```python
@skill(
    name="send_email",
    description="Send an email on behalf of the user",
    sensitive=True,   # ← user must type YES before this runs
)
def send_email(to: str, subject: str, body: str) -> str: ...
```

### Support dry_run
For sensitive skills, accept a `dry_run: bool = False` parameter and return
a description of what would happen without doing it:

```python
def send_email(to: str, subject: str, body: str, dry_run: bool = False) -> str:
    if dry_run:
        return f"Would send email to {to} — Subject: {subject}"
    # ... actual send logic
```

### Handle missing dependencies gracefully
Optional packages must be imported inside the function, not at module level:

```python
def my_skill(query: str) -> str:
    try:
        import some_optional_package
    except ImportError:
        return "This skill requires some_optional_package: pip install some_optional_package"
    # ... use the package
```

### Return useful strings
Skills return plain strings. The agent uses the string to formulate its reply.
Include relevant data, structured if appropriate:

```python
# ✅ Good
return f"Found 3 items:\n- Widget A ($12.99)\n- Widget B ($8.50)\n- Widget C ($5.00)"

# ❌ Returns opaque data the agent can't use
return str({"items": [...]})
```

---

## Code Style

- **Formatter**: We use `ruff format` (Black-compatible)
- **Linter**: `ruff check` with default settings
- **Type hints**: Required for all public functions
- **Docstrings**: Google style, required for all skills and public APIs
- **Imports**: `from __future__ import annotations` at top of every module

Run before submitting:
```bash
ruff check myassistant/
ruff format myassistant/
python -m compileall -q myassistant
```

---

## Testing

```bash
# Run all tests
pytest tests/

# Run a specific test file
pytest tests/test_skills.py -v

# Run with coverage
pytest --cov=myassistant tests/
```

When adding a new skill, please add a test in `tests/test_skills/`:

```python
# tests/test_skills/test_my_service.py
from myassistant.skills.my_service import myservice_search

def test_myservice_search_no_key(monkeypatch):
    """Skill returns error message when API key is missing."""
    monkeypatch.setattr("myassistant.core.config.settings.my_service_api_key", "")
    # With requires=[], should still be callable but return an error
    result = myservice_search("test")
    assert "failed" in result.lower() or "error" in result.lower()
```

---

## Pull Request Process

1. Fork the repository and create a branch: `git checkout -b feat/my-skill`
2. Make your changes following the guidelines above
3. Add or update tests as appropriate
4. Run the linter and compile check
5. Open a PR with a clear description of what you've added and why
6. Link any relevant issues

### PR checklist
- [ ] New skill has a clear `description` and `requires` list
- [ ] Sensitive skills set `sensitive=True` and support `dry_run`
- [ ] Optional imports are inside functions, not at module level
- [ ] Any new env vars are added to `config.py` and `.env.example`
- [ ] `python -m compileall -q myassistant` exits 0
- [ ] `ruff check myassistant/` is clean

---

## Reporting Issues

Please include:
1. Your Python version (`python --version`)
2. The channel you were using (CLI, tray, HTTP, SMS, etc.)
3. Which LLM provider you have configured
4. The full error message / traceback
5. Steps to reproduce

---

## Questions?

Open a GitHub Discussion for questions, ideas, or to show off what you've built with MyAssistant.

Thank you for contributing! 🐏
