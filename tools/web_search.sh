#!/bin/bash
# Wrapper script for web_research.py using Python virtual environment

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Path to the virtual environment
VENV_PATH="$PROJECT_DIR/env-ai"

# Check if venv exists, create if not
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_PATH"
    echo "Installing required packages (httpx, ddgs)..."
    PYTHONPATH="" "$VENV_PATH/bin/pip" install -q httpx ddgs
fi

# Run web_research.py with the virtual environment Python
# Clear PYTHONPATH to avoid conflicts with system Python packages
PYTHONPATH="" "$VENV_PATH/bin/python" "$SCRIPT_DIR/web_research.py" "$@"