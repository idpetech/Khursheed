#!/bin/bash
# Start Hey Eman Streamlit app with venv activation

set -e

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🖥️  Starting Hey Eman Streamlit App..."
echo "Project root: $PROJECT_ROOT"

# Activate virtual environment
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    echo "📦 Activating virtual environment..."
    source "$PROJECT_ROOT/.venv/bin/activate"
else
    echo "❌ Virtual environment not found at $PROJECT_ROOT/.venv"
    echo "💡 Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Change to project directory
cd "$PROJECT_ROOT"

echo "🚀 Starting Streamlit app..."
echo "🌐 App will be available at: http://localhost:8501"
echo "⌨️  Press Ctrl+C to stop"
echo

# Start the Streamlit app
streamlit run hey_eman_app.py