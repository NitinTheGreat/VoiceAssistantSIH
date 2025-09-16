#!/bin/bash

# Voice Assistant Backend Startup Script

echo "Starting Voice Assistant Backend..."

# Create necessary directories
mkdir -p logs

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "Please edit .env file with your API keys and configuration"
    exit 1
fi

# Install dependencies if requirements.txt has changed
if [ requirements.txt -nt venv/pyvenv.cfg ] 2>/dev/null; then
    echo "Installing/updating dependencies..."
    pip install -r requirements.txt
fi

# Start the application
echo "Starting FastAPI server..."
python main.py