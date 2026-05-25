# Enaam Scripts

Convenience scripts to run Enaam components with proper virtual environment activation.

## Available Scripts

### 🚀 MCP Server Management

- **`start_mcp_server.sh`** - Start the Enaam MCP server
  ```bash
  ./scripts/start_mcp_server.sh [host] [port]
  
  # Examples:
  ./scripts/start_mcp_server.sh                    # localhost:8080
  ./scripts/start_mcp_server.sh 0.0.0.0 9000      # all interfaces, port 9000
  ```

- **`test_mcp_server.sh`** - Test MCP server endpoints
  ```bash
  ./scripts/test_mcp_server.sh [host] [port]
  
  # Examples:
  ./scripts/test_mcp_server.sh                     # test localhost:8080
  ./scripts/test_mcp_server.sh localhost 9000     # test localhost:9000
  ```

### 🤖 CLI Interface

- **`enaam_cli.sh`** - Interactive Enaam CLI
  ```bash
  ./scripts/enaam_cli.sh                           # interactive mode
  ./scripts/enaam_cli.sh "email summary"          # single command
  ./scripts/enaam_cli.sh status                   # system status
  ```

### 🖥️ Web Interface

- **`streamlit_app.sh`** - Start Hey Eman web interface
  ```bash
  ./scripts/streamlit_app.sh                      # starts on localhost:8501
  ```

## Prerequisites

- Python virtual environment at `.venv/`
- Dependencies installed via `pip install -r requirements.txt`

## Quick Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Test CLI
./scripts/enaam_cli.sh status

# Start MCP server (in another terminal)
./scripts/start_mcp_server.sh

# Test MCP server (in another terminal)
./scripts/test_mcp_server.sh
```

## Usage Examples

### Start Complete System

```bash
# Terminal 1: Start MCP server
./scripts/start_mcp_server.sh

# Terminal 2: Start web interface
./scripts/streamlit_app.sh

# Terminal 3: Test functionality
./scripts/enaam_cli.sh "executive summary"
./scripts/test_mcp_server.sh
```

### Development Workflow

```bash
# Quick CLI test
./scripts/enaam_cli.sh "get status"

# Test specific functionality
./scripts/enaam_cli.sh "weekly digest"

# Test MCP endpoints
./scripts/test_mcp_server.sh
```

All scripts automatically activate the virtual environment and set the correct working directory.