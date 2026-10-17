# 🛠️ Enaam Skills Development Guide

This guide explains how to add new skills to the Enaam Chief-of-Staff AI platform. Follow this step-by-step process to extend Enaam's capabilities with custom functionality.

## 📋 Table of Contents

- [Overview](#overview)
- [Skill Architecture](#skill-architecture)
- [Step-by-Step Development Process](#step-by-step-development-process)
- [Skill Templates](#skill-templates)
- [Registration Process](#registration-process)
- [Testing Your Skills](#testing-your-skills)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## 🎯 Overview

### What are Enaam Skills?

Skills are modular components that extend Enaam's functionality. Each skill performs a specific task like:
- Data processing (calculator, file analysis)
- External API integration (weather, lead generation)
- System operations (email processing, scheduling)

### Current Available Skills

- ✅ **echo** - Echoes input data
- ✅ **timestamp** - Generates ISO timestamps
- ✅ **sifter** - Email processing and analysis
- ✅ **lead_scout** - Lead discovery and generation
- ✅ **calculator** - Mathematical operations
- ✅ **weather** - Weather information (requires API key)
- ✅ **file_analyzer** - File/directory analysis

---

## 🏗️ Skill Architecture

### Base Skill Structure

All skills inherit from the base `Skill` class:

```python
from typing import Any, Dict
from skills.base import Skill

class YourSkill(Skill):
    name = "your_skill"  # Unique skill identifier
    
    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a task and return results
        
        Args:
            task: {
                "id": "unique-task-id",
                "payload": {...},  # User input parameters
                "skills": ["skill_name"]
            }
            
        Returns:
            Dict with task results and status
        """
        # Your skill logic here
        pass
```

### Input/Output Format

#### Input Structure
```python
{
    "id": "task-123",
    "payload": {
        "param1": "value1",
        "param2": "value2"
    },
    "skills": ["your_skill"]
}
```

#### Output Structure
```python
{
    "task_id": "task-123",
    "status": "success",  # or "error"
    "your_data": "result",
    # ... additional fields
}
```

---

## 🔧 Step-by-Step Development Process

### Step 1: Create Your Skill File

Create a new file in the `skills/` directory:

```bash
# Create new skill file
touch skills/my_awesome_skill.py
```

### Step 2: Implement Your Skill

```python
# skills/my_awesome_skill.py
"""
My Awesome Skill - Description of what it does
"""

import os
from typing import Any, Dict
from skills.base import Skill

class MyAwesomeSkill(Skill):
    name = "my_awesome_skill"
    
    def __init__(self):
        # Initialize any required resources
        self.api_key = os.getenv("MY_API_KEY")
    
    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Process the task"""
        payload = task.get("payload", {})
        
        try:
            # Your skill logic here
            result = self._process_data(payload)
            
            return {
                "task_id": task.get("id"),
                "status": "success",
                "result": result,
                "processed_at": time.time()
            }
            
        except Exception as e:
            return {
                "task_id": task.get("id"),
                "status": "error",
                "error": str(e)
            }
    
    def _process_data(self, payload: Dict[str, Any]) -> Any:
        """Your custom processing logic"""
        # Implementation details
        pass
```

### Step 3: Register in Skills Package

Update `skills/__init__.py`:

```python
# Add your import
from skills.my_awesome_skill import MyAwesomeSkill

# Add to __all__ list
__all__ = [
    # ... existing skills
    "MyAwesomeSkill",
]
```

### Step 4: Update Legacy Bridge

Update `enaam/legacy_modules.py`:

```python
def get_skill_classes():
    """Get skill classes."""
    if skills is None:
        raise ImportError("Skills package not available")
    
    return {
        # ... existing skills
        "MyAwesomeSkill": getattr(skills, "MyAwesomeSkill", None),
    }
```

### Step 5: Export in Legacy Layer

Update `enaam/legacy/__init__.py`:

```python
# In the try block, add:
MyAwesomeSkill = _skill_classes["MyAwesomeSkill"]

# In the except block, add:
MyAwesomeSkill = None

# Add to __all__:
__all__ = [
    # ... existing exports
    "MyAwesomeSkill",
]
```

### Step 6: Register in MCP Bridge

Update `enaam/integrations/khursheed_bridge.py`:

```python
def _initialize_manager(self) -> None:
    """Initialize the Khursheed manager with all available skills"""
    # ... existing code
    
    # Add to skills_to_register in the try block:
    try:
        from ..legacy import MyAwesomeSkill  # Add this line
        skills_to_register.extend([
            # ... existing new skills
            MyAwesomeSkill(),  # Add this line
        ])
    except ImportError:
        pass
```

### Step 7: Add to CLI (Optional)

Update `ask.py` if you want CLI access:

```python
from skills import (
    # ... existing skills
    MyAwesomeSkill
)

# Add to manager registration:
manager.register_many([
    # ... existing skills
    MyAwesomeSkill()
])
```

---

## 📝 Skill Templates

### Template 1: Simple Data Processing

```python
class DataProcessorSkill(Skill):
    name = "data_processor"
    
    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        payload = task.get("payload", {})
        data = payload.get("data", "")
        
        if not data:
            return {
                "task_id": task.get("id"),
                "status": "error",
                "error": "No data provided"
            }
        
        # Process data
        processed = data.upper()  # Example processing
        
        return {
            "task_id": task.get("id"),
            "status": "success",
            "original": data,
            "processed": processed
        }
```

### Template 2: External API Integration

```python
import requests

class APIIntegrationSkill(Skill):
    name = "api_integration"
    
    def __init__(self):
        self.api_key = os.getenv("YOUR_API_KEY")
        self.base_url = "https://api.example.com"
    
    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        payload = task.get("payload", {})
        
        if not self.api_key:
            return {
                "task_id": task.get("id"),
                "status": "error",
                "error": "API key not configured",
                "setup": "Add YOUR_API_KEY to .env file"
            }
        
        try:
            response = self._call_api(payload)
            return {
                "task_id": task.get("id"),
                "status": "success",
                "data": response
            }
        except requests.RequestException as e:
            return {
                "task_id": task.get("id"),
                "status": "error",
                "error": f"API request failed: {e}"
            }
    
    def _call_api(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = requests.get(
            f"{self.base_url}/endpoint",
            headers=headers,
            params=payload,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
```

### Template 3: File Operations

```python
from pathlib import Path

class FileOperationSkill(Skill):
    name = "file_operations"
    
    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        payload = task.get("payload", {})
        file_path = payload.get("path", "")
        operation = payload.get("operation", "read")
        
        if not file_path:
            return {
                "task_id": task.get("id"),
                "status": "error",
                "error": "No file path provided"
            }
        
        try:
            path = Path(file_path).resolve()
            
            if operation == "read":
                result = self._read_file(path)
            elif operation == "analyze":
                result = self._analyze_file(path)
            else:
                raise ValueError(f"Unknown operation: {operation}")
            
            return {
                "task_id": task.get("id"),
                "status": "success",
                "operation": operation,
                "path": str(path),
                **result
            }
            
        except Exception as e:
            return {
                "task_id": task.get("id"),
                "status": "error",
                "error": str(e)
            }
    
    def _read_file(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        content = path.read_text()
        return {
            "content": content,
            "size": len(content),
            "lines": len(content.splitlines())
        }
    
    def _analyze_file(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        stat = path.stat()
        return {
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
            "is_file": path.is_file(),
            "extension": path.suffix
        }
```

---

## 🔄 Registration Process

After creating your skill, you need to register it in 5 locations:

### Registration Checklist

- [ ] **skills/__init__.py** - Import and export
- [ ] **enaam/legacy_modules.py** - Add to skill classes function
- [ ] **enaam/legacy/__init__.py** - Export in legacy layer
- [ ] **enaam/integrations/khursheed_bridge.py** - Register in MCP bridge
- [ ] **ask.py** - (Optional) Add to CLI interface

### Quick Registration Script

```bash
# You can create a script to help with registration:
./scripts/register_skill.py my_awesome_skill MyAwesomeSkill
```

---

## 🧪 Testing Your Skills

### Method 1: Web Interface Testing

1. **Start the server:**
   ```bash
   source .venv/bin/activate
   python -c "
   from enaam.mcp.server import MCPServer
   server = MCPServer(host='localhost', port=8093)
   server.start()
   "
   ```

2. **Open web tester:**
   Open `web_chat_test.html` in your browser

3. **Test your skill:**
   - Direct skill call: "run my_awesome_skill with data=test"
   - Chat integration: "use my awesome skill to process this data"

### Method 2: Direct API Testing

```bash
curl -X POST http://localhost:8093/ \
  -H 'Content-Type: application/json' \
  -d '{
    "method": "run_skill",
    "params": {
      "skill_name": "my_awesome_skill",
      "input": {
        "param1": "value1",
        "param2": "value2"
      }
    },
    "response_type": "json",
    "id": "test-1"
  }'
```

### Method 3: CLI Testing

```bash
source .venv/bin/activate
python ask.py "test my awesome skill"
```

### Method 4: Unit Testing

Create tests in `tests/skills/test_my_awesome_skill.py`:

```python
import pytest
from skills.my_awesome_skill import MyAwesomeSkill

def test_my_awesome_skill():
    skill = MyAwesomeSkill()
    
    task = {
        "id": "test-123",
        "payload": {"data": "test input"},
        "skills": ["my_awesome_skill"]
    }
    
    result = skill.run(task)
    
    assert result["status"] == "success"
    assert result["task_id"] == "test-123"
    # Add your specific assertions
```

---

## ✅ Best Practices

### Error Handling

```python
def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # Main logic
        result = self._process(task)
        return {"status": "success", **result}
    except ValueError as e:
        return {"status": "error", "error": f"Invalid input: {e}"}
    except requests.RequestException as e:
        return {"status": "error", "error": f"Network error: {e}"}
    except Exception as e:
        return {"status": "error", "error": f"Unexpected error: {e}"}
```

### Input Validation

```python
def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
    payload = task.get("payload", {})
    
    # Validate required parameters
    required_params = ["param1", "param2"]
    for param in required_params:
        if param not in payload:
            return {
                "status": "error",
                "error": f"Missing required parameter: {param}",
                "required": required_params
            }
    
    # Continue with processing
```

### Environment Configuration

```python
def __init__(self):
    # Load configuration from environment
    self.api_key = os.getenv("MY_SKILL_API_KEY")
    self.timeout = int(os.getenv("MY_SKILL_TIMEOUT", "30"))
    self.debug = os.getenv("MY_SKILL_DEBUG", "false").lower() == "true"
    
    # Validate critical configuration
    if not self.api_key:
        logging.warning("MY_SKILL_API_KEY not set - some features will be disabled")
```

### Logging

```python
import logging

class MyAwesomeSkill(Skill):
    def __init__(self):
        self.logger = logging.getLogger(f"skills.{self.name}")
    
    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info(f"Processing task {task.get('id')}")
        
        try:
            result = self._process(task)
            self.logger.info(f"Task {task.get('id')} completed successfully")
            return result
        except Exception as e:
            self.logger.error(f"Task {task.get('id')} failed: {e}")
            raise
```

### Resource Management

```python
def __init__(self):
    self._session = requests.Session()  # Reuse connections
    
def __del__(self):
    if hasattr(self, '_session'):
        self._session.close()
```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. Skill Not Found Error
```
Error: Skill 'my_skill' not found
```
**Solution:** Check all 5 registration points are updated

#### 2. Import Errors
```
ImportError: cannot import name 'MySkill'
```
**Solutions:**
- Check file name matches class name
- Verify `__init__.py` imports are correct
- Check for circular imports

#### 3. Server Not Starting
```
Error: Address already in use
```
**Solutions:**
- Use different port: `MCPServer(port=8094)`
- Kill existing server: `lsof -ti:8093 | xargs kill`

#### 4. Skill Internal Errors
```
Error: Internal server error
```
**Solutions:**
- Check skill `run()` method returns proper dict
- Add try-catch blocks in skill
- Check server logs for details

### Debugging Steps

1. **Test skill in isolation:**
   ```python
   from skills.my_awesome_skill import MyAwesomeSkill
   
   skill = MyAwesomeSkill()
   result = skill.run({"id": "test", "payload": {}})
   print(result)
   ```

2. **Check skill registration:**
   ```python
   from enaam.legacy_modules import get_skill_classes
   skills = get_skill_classes()
   print("Available skills:", list(skills.keys()))
   ```

3. **Verify server startup:**
   ```bash
   source .venv/bin/activate
   python -c "
   from enaam.mcp.server import MCPServer
   server = MCPServer(port=8094)
   result = server.start()
   print(result)
   "
   ```

### Getting Help

- Check existing skills in `skills/` for examples
- Review test files in `tests/skills/` 
- Check server logs in `logs/enaam_mcp_server.log`
- Use web interface debugger for real-time testing

---

## 📚 Additional Resources

### Example Skills to Study

- **calculator.py** - Input validation and mathematical operations
- **weather.py** - External API integration with error handling
- **file_analyzer.py** - File operations and recursive processing
- **echo.py** - Simplest skill implementation
- **timestamp.py** - System integration example

### Configuration Files

- **.env** - Environment variables for API keys
- **config/development.json** - Development configuration
- **pyproject.toml** - Project dependencies

### Server Management

- **Start server:** `python enaam/mcp_server.py start localhost 8093`
- **Test health:** `curl http://localhost:8093/health`
- **View capabilities:** `curl http://localhost:8093/capabilities`

---

## 🎉 Ready to Build!

You now have everything needed to create powerful new skills for Enaam. Remember:

1. **Start simple** - Begin with basic data processing
2. **Test thoroughly** - Use all testing methods
3. **Handle errors gracefully** - Users will appreciate robust skills
4. **Document your skills** - Add docstrings and examples
5. **Follow the patterns** - Study existing skills for consistency

Happy skill development! 🚀

---

## Priority Inbox, Lead Skills & Composition Kernel

This section documents the capabilities added by the `priority-inbox-and-leads` work.

### Priority actions (`priority_inbox.py`)

Any skill can escalate a finding into the shared `pending_actions` table:

```python
import priority_inbox

action_id = priority_inbox.emit_priority_action(
    kind="overdue_payment",            # free-form category string
    title="overdue_payment: Acme - 50 USD",
    description="Subject line / short context",
    payload={"amount": 50, "message_id": "<...>"},  # JSON-serialized automatically
    priority=3,                         # 0=low, 1=medium, 2=high, 3=urgent
    source_key="<sha256 dedup key>",   # REQUIRED for idempotency
    expires_at="2026-10-10T23:59:59",  # optional ISO timestamp
)
```

Read them back (used by the executive summary and the LLM agent):

```python
open_actions = priority_inbox.list_open_priority_actions(min_priority=2)
```

**Priority levels**

| priority | meaning | email sent? |
|----------|---------|-------------|
| 0 | low      | no |
| 1 | medium   | no |
| 2 | high     | yes (if `KHURSHEED_PRIORITY_EMAIL_*` configured) |
| 3 | urgent   | yes (if configured) |

Email is sent via `notifications.EmailNotifier` only when `priority >= 2`. Missing
email env vars cause a logged skip, never an exception. Every send/skip is recorded in
`notification_log` with `related_action_id`.

**`source_key` dedup contract**

`source_key` is backed by a unique partial index (migration #8):
`CREATE UNIQUE INDEX ... ON pending_actions(source_key) WHERE source_key IS NOT NULL`.

`emit_priority_action` is idempotent: if a row with the same `source_key` already exists,
it returns the existing `action_id` without inserting a new row or re-sending email.
Use a stable, content-derived key so re-runs don't create duplicates. Conventions:

- Sifter emails: `sha256(f"{account_name}|{rfc822_message_id}|{kind}")`
- Blogger drafts: `sha256(f"{theme}{iso_date}")`

### Sifter financial detection

Sifter now runs a two-stage detector on each email (on top of the existing categorize /
expense flow, which is unchanged):

1. **Keyword prefilter** (free) flags candidates for `new_bill`, `overdue_payment`, or
   `trial_ending`.
2. **LLM extractor** (`gpt-4o-mini`, only on candidates) returns strict JSON with
   vendor / amount / currency / due_date / confidence. Gated on `OPENAI_API_KEY`; if it is
   missing or fails, Sifter falls back to keyword-only extraction with `confidence: "low"`.

Priority mapping: `overdue_payment` → 3; `new_bill` / `trial_ending` → 1 (>7d), 2 (<=7d),
3 (<=2d) based on the due/end date. Confirmed items are escalated via `priority_inbox`.

### Lead skills

- **`cto_radar`** — Tavily-backed search for fractional / interim / part-time CTO roles that
  are remote-US or Jacksonville-FL hybrid/remote, with location-aware scoring. Returns
  `{"opportunities": [...]}` (top 10).
- **`icp_prospector`** — seed-list-driven company prospector. Reads `data/icp_seed.csv`.

**ICP seed-list contract** (`data/icp_seed.csv`):

```
company_name,website,industry,employee_count,funding_stage,has_cto,acquired,hiring_signals_url
```

Hard filters (rows failing any are dropped before enrichment):

- `industry` in `{saas, fintech, edtech, commerce}` (configurable via payload `industries`)
- `employee_count` within `[employee_min, employee_max]` (default 10-50)
- `funding_stage` in `{seed, series-a, series-b}` (configurable via `funding_stages`)
- `has_cto == "yes"` is **dropped** (ICP targets companies that still need a CTO; keep `no`/`unknown`)
- `acquired == "yes"` is **dropped** (keep `no`/`unknown`)

Survivors with `unknown` cells are enriched via targeted Tavily queries, then ranked by an
LLM (falls back to a heuristic when `OPENAI_API_KEY` is absent). Returns
`{"top_companies": [...], "rejected": [...], "seed_rows_scanned": N}`.

### Composition kernel (`skill_context.py`, `mcp_registry.py`)

Skills now receive a `SkillContext` at `task["ctx"]` (built once per `Manager` invocation).
Existing skills that ignore it are unaffected; composite skills opt in:

```python
def run(self, task):
    ctx = task.get("ctx")
    facts = ctx.run_skill("cto_radar", {})          # compose another skill (max depth 3)
    vault = ctx.mcp("insight_vault")                 # MCP handle
    if vault.available():                            # ALWAYS check before depending on it
        data = vault.request("retrieve_biases", {"theme": "..."})
    client = ctx.llm()                               # shared OpenAI client (or None)
    ctx.priority_inbox.emit_priority_action(...)     # escalate without re-importing
```

**MCP is optional and additive.** `MCPHandle.available()` is health-checked with a 60s TTL
cache; unreachable servers return `False` (and are logged to `notification_log` with
`notification_type='mcp_unavailable'`). Composite skills must degrade gracefully when a
server is down — never block on it.

**Declaring dependencies.** Populate `skill_configurations.dependencies_json` with a typed
list. `enaam_skill_loader.py` validates them at load time:

```json
[
  {"type": "env", "key": "OPENAI_API_KEY", "required": true},
  {"type": "mcp", "alias": "insight_vault", "required": false},
  {"type": "skill", "name": "cto_radar", "required": false}
]
```

Missing **required** deps set `skill.degraded = True`; the skill's `run()` should
short-circuit with a structured `{"status": "degraded", ...}` rather than crash. Missing
**optional** deps are logged and the skill chooses its fallback.

### Blogger (composite skill example)

`blogger` demonstrates the pattern: the LLM generates the post, and InsightVault *tempers*
it with the user's stored biases/opinions (`retrieve_biases`). The `tempering` knob accepts
`vault_preferred` (default), `vault_required`, or `vault_off`. Each draft is flagged
`bias_tempering` = `tempered` / `lightly_tempered` / `untempered`; untempered drafts are
prefixed `[UNTEMPERED]` in the review queue. `mode="draft"` (default) writes a priority-1
`linkedin_post_draft` pending action; `mode="publish"` requires the
`KHURSHEED_BLOGGER_PUBLISH_ENABLED` kill switch plus LinkedIn credentials, and demotes to a
draft on any failure.

---

*Last updated: 2026-10-06*
*Enaam Platform Version: 1.0*