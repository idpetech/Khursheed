#!/bin/bash
# Test Enaam MCP Server endpoints

set -e

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🧪 Testing Enaam MCP Server..."
echo "Project root: $PROJECT_ROOT"

# Activate virtual environment
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    echo "📦 Activating virtual environment..."
    source "$PROJECT_ROOT/.venv/bin/activate"
else
    echo "❌ Virtual environment not found at $PROJECT_ROOT/.venv"
    exit 1
fi

# Change to project directory
cd "$PROJECT_ROOT"

# Parse command line arguments
HOST="${1:-localhost}"
PORT="${2:-8080}"

echo "🔍 Testing MCP server at $HOST:$PORT"
echo

# Test the MCP server
python -m enaam.mcp_server test "$HOST" "$PORT"