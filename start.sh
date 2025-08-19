#!/bin/bash

# Copy Trading Bot - Ubuntu Start Script
# Equivalent to start.bat for Windows

set -e  # Exit on any error

echo "========================================"
echo "COPY TRADING BOT - STARTUP SCRIPT"
echo "========================================"
echo

# Function to print colored output
print_info() {
    echo -e "\033[1;34m[INFO]\033[0m $1"
}

print_success() {
    echo -e "\033[1;32m[SUCCESS]\033[0m $1"
}

print_warning() {
    echo -e "\033[1;33m[WARNING]\033[0m $1"
}

print_error() {
    echo -e "\033[1;31m[ERROR]\033[0m $1"
}

# Check if virtual environment exists
if [ ! -f "venv/bin/activate" ]; then
    print_error "Virtual environment not found!"
    print_info "Please run ./install_ubuntu.sh first to create the virtual environment"
    echo
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    print_warning ".env file not found!"
    print_info "Please copy env_example.txt to .env and configure your settings"
    echo
    print_info "Press Enter to continue anyway..."
    read -r
fi

# Activate virtual environment
print_info "Activating virtual environment..."
source venv/bin/activate

# Check if main.py exists
if [ ! -f "main.py" ]; then
    print_error "main.py not found!"
    print_info "Please make sure you're in the correct directory"
    exit 1
fi

# Check Python dependencies
print_info "Checking dependencies..."
if ! python -c "import fastapi, uvicorn, flask, sqlalchemy" 2>/dev/null; then
    print_warning "Some dependencies missing. Installing..."
    pip install -r requirements.txt
fi

print_success "Starting copy trading bot..."
echo
print_info "The bot will start two servers:"
print_info "- API Server: http://localhost:8000"
print_info "- Dashboard: http://localhost:5000"
echo
print_info "Press Ctrl+C to stop the bot"
echo

# Start the bot
python main.py
