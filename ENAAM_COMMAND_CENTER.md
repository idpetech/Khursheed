# 🤖 Enaam Command Center

## Overview

The Enaam Command Center is a unified, stable AI assistant control system that consolidates all Khursheed/Enaam functionality through a single orchestration layer. This implementation follows Victor-style principles: simpler, stable, and traceable.

## Key Features

### ✅ Unified Timeline
- **Single view** aggregating all system activity from `skill_runs`, `pending_actions`, `notification_log`, and `scheduled_jobs`
- **Append-only runs** with unique `run_id` for complete traceability
- **Real-time activity** tracking across all system components
- **Filterable interface** by event type, status, and date range

### ✅ Review Queue
- **Pending actions** table for side-effect operations requiring approval
- **Review/approve flow** in UI for email sending, notifications, and file operations
- **Priority-based** queue with urgency levels (Low, Medium, High, Urgent)
- **Audit trail** with reviewer tracking and timestamps

### ✅ Job Ledger
- **Scheduled jobs** table replacing simple `interval_days` approach
- **Database as source of truth** with JSON import/export capabilities
- **Next run tracking** with last status and error logging
- **Flexible scheduling** supporting intervals, daily runs, and one-time jobs

### ✅ Single Orchestration Entry
- **Central VictorOrchestrator** handling all commands from CLI, UI, and MCP
- **Unified routing** eliminating duplicate keyword handlers
- **Consistent response format** across all interfaces
- **Comprehensive logging** and error handling

### ✅ Chat Memory
- **ChatContextManager** wired into Streamlit UI
- **Persistent sessions** with conversation history
- **Context-aware** responses building on previous interactions
- **Multi-interface** support (UI, CLI, MCP)

### ✅ Skill Registry
- **Central registry** with dynamic skill discovery
- **Database-backed** manifest with metadata storage
- **Version tracking** and dependency management
- **Enable/disable** controls for individual skills

### ✅ Notification Delivery Log
- **Complete tracking** of all notification attempts
- **Status monitoring** (sent, failed, pending, retry)
- **Error logging** with retry count tracking
- **Multi-channel** support (email, file, webhook)

### ✅ Thin Enaam Layer
- **Adapter pattern** connecting Enaam MCP to Victor orchestrator
- **Reduced duplication** with Victor as single execution engine
- **Maintained compatibility** with existing Enaam API
- **Enhanced logging** through Enaam layer while using Victor execution

## Architecture

```
┌─────────────────┬─────────────────┬─────────────────┐
│   Streamlit UI  │    CLI Tool     │   MCP Server    │
│   (victor_ui)   │   (ask.py)      │   (enaam/mcp)   │
└─────────┬───────┴─────────┬───────┴─────────┬───────┘
          │                 │                 │
          └─────────────────┼─────────────────┘
                           │
                    ┌──────▼──────┐
                    │   Victor    │
                    │ Orchestrator│
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼─────┐   ┌──────▼──────┐  ┌─────▼─────┐
    │   Skill   │   │  Scheduled  │  │ Pending   │
    │ Registry  │   │    Jobs     │  │ Actions   │
    └───────────┘   └─────────────┘  └───────────┘
                           │
                    ┌──────▼──────┐
                    │   SQLite    │
                    │  Database   │
                    │ (khursheed  │
                    │    .db)     │
                    └─────────────┘
```

## Database Schema

### Core Tables

#### `skill_runs` (Append-only)
```sql
CREATE TABLE skill_runs (
    run_id TEXT PRIMARY KEY,           -- Unique run identifier
    task_id TEXT NOT NULL,            -- Task context
    skill_name TEXT NOT NULL,         -- Skill executed
    executed_at TEXT NOT NULL,        -- Execution timestamp
    result_json TEXT NOT NULL,        -- Full result data
    status TEXT NOT NULL,             -- success/failed/error
    error_message TEXT,               -- Error details
    execution_time_ms INTEGER,        -- Performance tracking
    created_at TEXT NOT NULL          -- Record creation
);
```

#### `pending_actions` (Review Queue)
```sql
CREATE TABLE pending_actions (
    action_id TEXT PRIMARY KEY,       -- Unique action ID
    action_type TEXT NOT NULL,        -- email/notification/file_write
    title TEXT NOT NULL,              -- Human-readable title
    description TEXT,                 -- Detailed description
    payload_json TEXT NOT NULL,       -- Action parameters
    status TEXT NOT NULL,             -- pending/approved/rejected/executed
    priority INTEGER NOT NULL,        -- 0=low, 1=medium, 2=high, 3=urgent
    created_by TEXT NOT NULL,         -- Creator identifier
    reviewed_by TEXT,                 -- Reviewer identifier
    created_at TEXT NOT NULL,         -- Creation timestamp
    reviewed_at TEXT,                 -- Review timestamp
    executed_at TEXT                  -- Execution timestamp
);
```

#### `scheduled_jobs` (Job Ledger)
```sql
CREATE TABLE scheduled_jobs (
    job_id TEXT PRIMARY KEY,          -- Unique job ID
    job_name TEXT NOT NULL UNIQUE,    -- Human-readable name
    job_type TEXT NOT NULL,           -- skill/bridge_function/custom
    target TEXT NOT NULL,             -- Skill name or function
    schedule_config TEXT NOT NULL,    -- JSON schedule configuration
    next_run_at TEXT NOT NULL,        -- Next execution time
    last_run_at TEXT,                 -- Last execution time
    last_status TEXT,                 -- success/failed/skipped
    last_error TEXT,                  -- Last error message
    run_count INTEGER DEFAULT 0,      -- Execution counter
    enabled BOOLEAN DEFAULT 1         -- Enable/disable flag
);
```

#### `unified_timeline` (View)
Aggregates all events from skill_runs, pending_actions, notification_log, and scheduled_jobs into a single chronological timeline.

## Usage

### Enaam Command Center UI

Access the unified interface at **http://localhost:8501**

#### Navigation Tabs:
- **🤖 Chat**: AI-powered conversation with context memory
- **📊 Timeline**: Unified activity view with filtering
- **📋 Review Queue**: Pending actions requiring approval
- **🛠️ Skills**: Skill management and testing dashboard
- **⚡ System Status**: Environment and health monitoring

#### Quick Actions Sidebar:
- **📧 Check Emails**: Run email processing skill
- **📊 Executive Summary**: Generate comprehensive report
- **🔍 Lead Generation**: Execute lead discovery process

### CLI Usage

```bash
# Activate virtual environment
source .venv/bin/activate

# Execute commands through Victor orchestrator
python -c "
from victor_orchestrator import execute_command
result = execute_command('check_email')
print(result)
"
```

### MCP Integration

The Enaam MCP server continues to work through the thin adapter layer:

```bash
# Start MCP server
python -c "
from enaam.mcp.server import MCPServer
server = MCPServer(host='0.0.0.0', port=8093)
server.start()
"

# Test via curl
curl -X POST http://localhost:8093/ \
  -H 'Content-Type: application/json' \
  -d '{
    "method": "chat_query",
    "params": {
      "query": "Check my emails please",
      "context": {"session_id": "test", "user_id": "demo"}
    },
    "response_type": "chat",
    "id": "test-1"
  }'
```

## Commands

### Available Commands

| Command | Description | Context Parameters |
|---------|-------------|-------------------|
| `run_skill` | Execute specific skill | `skill_name`, `payload`, `task_id` |
| `check_email` | Run email processing | None |
| `executive_summary` | Generate summary report | None |
| `lead_generation` | Run lead discovery | `queries` (optional) |
| `get_timeline` | Get unified activity timeline | `limit` (optional) |
| `get_pending_actions` | Get review queue | `limit` (optional) |
| `approve_action` | Approve pending action | `action_id`, `reviewed_by` |
| `reject_action` | Reject pending action | `action_id`, `reviewed_by` |
| `run_scheduled_jobs` | Execute due jobs | None |
| `list_skills` | List available skills | None |

### Example Usage

```python
from victor_orchestrator import execute_command

# Check emails
result = execute_command("check_email")

# Generate executive summary
result = execute_command("executive_summary")

# Run specific skill
result = execute_command("run_skill", {
    "skill_name": "lead_scout",
    "payload": {"queries": ["AI consulting services"]}
})

# Get recent timeline
result = execute_command("get_timeline", {"limit": 20})

# Approve pending action
result = execute_command("approve_action", {
    "action_id": "action-123",
    "reviewed_by": "admin"
})
```

## Configuration

### Database Initialization

Victor automatically handles database migrations:

```python
from database_migrations import migrate_database
migrate_database("khursheed.db")
```

### Skill Registration

```python
from victor_orchestrator import get_orchestrator
from skills.echo import EchoSkill
from skills.lead_scout import LeadScoutSkill

orchestrator = get_orchestrator()
orchestrator.register_skills([
    EchoSkill(),
    LeadScoutSkill(),
    # ... other skills
])
```

### Environment Variables

```bash
# OpenAI integration
OPENAI_API_KEY=sk-proj-...

# Email skills
YAHOO_EMAIL=your@yahoo.com
YAHOO_PASSWORD=app_password
GMAIL_EMAIL=your@gmail.com
GMAIL_PASSWORD=app_password

# Lead generation
TAVILY_API_KEY=tvly-...

# Summary delivery
SUMMARY_TO=recipient@email.com
```

## Benefits

### 1. **Stability**
- Single orchestration point reduces complexity
- Database-backed state eliminates file-based coordination issues
- Append-only design ensures data integrity

### 2. **Traceability** 
- Complete audit trail of all operations
- Unified timeline across all system components
- 1:1 mapping between business operations and technical execution

### 3. **Simplicity**
- Consistent API across all interfaces (CLI, UI, MCP)
- Reduced code duplication through central orchestrator
- Clear separation between UI layer and business logic

### 4. **Scalability**
- Review queue prevents accidental side effects
- Scheduled jobs with proper error handling and retry logic
- Skill registry enables dynamic capability management

### 5. **Maintainability**
- Thin adapter layers keep components loosely coupled
- Database migrations handle schema evolution
- Comprehensive logging and error handling

## Migration Path

The Victor system maintains backward compatibility:

1. **Existing skills** continue to work without modification
2. **Enaam MCP** routes through thin adapter maintaining API compatibility  
3. **Database migrations** handle schema updates automatically
4. **Old UI** (hey_eman_app.py) remains functional alongside Victor UI

## Next Steps

1. **Gradual Migration**: Migrate existing workflows to use Victor orchestrator
2. **Skill Enhancement**: Add more skills to the registry with proper metadata
3. **Monitoring**: Implement health checks and alerting through the unified timeline
4. **Automation**: Create scheduled jobs for regular maintenance tasks
5. **Integration**: Connect external systems through the pending actions review flow

---

**Enaam Command Center** - Simple, stable, traceable AI assistant orchestration 🤖