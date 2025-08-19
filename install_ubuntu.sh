#!/bin/bash

# Copy Trading Bot - Ubuntu Installation Script
# This script sets up the complete environment for the copy trading bot on Ubuntu

set -e  # Exit on any error

echo "========================================"
echo "COPY TRADING BOT - UBUNTU INSTALLATION"
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

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_warning "Please do not run this script as root"
    print_info "Run: ./install_ubuntu.sh"
    exit 1
fi

# Check Python version first
python_version=$(python3 --version 2>/dev/null | cut -d' ' -f2 | cut -d'.' -f1,2)
if [ -z "$python_version" ]; then
    print_error "Python 3 not found! Please install Python 3.8 or higher"
    exit 1
fi

required_version="3.8"
if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" = "$required_version" ]; then
    print_success "Found Python $python_version - compatible!"
else
    print_error "Python $python_version is not compatible. Need Python 3.8 or higher"
    exit 1
fi

# Update system packages (optional - you can skip this if system is up to date)
read -p "Update system packages? (recommended but can be skipped) [Y/n]: " -r
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    print_info "Updating system packages..."
    sudo apt update && sudo apt upgrade -y
fi

# Install only required system packages (skip python3 since you have it)
print_info "Installing system dependencies..."
sudo apt install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libssl-dev \
    libffi-dev \
    git \
    curl \
    wget \
    nano \
    htop \
    screen \
    tmux

# Create virtual environment
print_info "Creating Python virtual environment..."
if [ -d "venv" ]; then
    print_warning "Virtual environment already exists, removing old one..."
    rm -rf venv
fi

python3 -m venv venv
print_success "Virtual environment created"

# Activate virtual environment
print_info "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
print_info "Upgrading pip..."
pip install --upgrade pip setuptools wheel

# Install Python dependencies
print_info "Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    print_success "Dependencies installed from requirements.txt"
else
    print_warning "requirements.txt not found, installing basic dependencies..."
    pip install \
        python-binance==1.0.19 \
        ccxt==4.1.77 \
        fastapi==0.111.0 \
        uvicorn==0.24.0 \
        python-multipart==0.0.7 \
        python-jose[cryptography]==3.3.0 \
        passlib[bcrypt]==1.7.4 \
        python-dotenv==1.0.0 \
        websockets==10.4 \
        aiohttp==3.9.5 \
        pandas==2.1.4 \
        numpy==1.25.2 \
        pydantic==2.7.0 \
        sqlalchemy==2.0.23 \
        alembic==1.13.1 \
        psycopg2-binary==2.9.9 \
        redis==5.0.1 \
        celery==5.3.4 \
        flask==3.0.0 \
        flask-cors==4.0.0 \
        flask-socketio==5.3.6 \
        eventlet==0.33.3 \
        cryptography==3.4.8 \
        httpx==0.23.0 \
        requests==2.32.1 \
        pyOpenSSL==23.3.0 \
        nest-asyncio==1.5.8
fi

# Create .env file if it doesn't exist
print_info "Setting up environment configuration..."
if [ ! -f ".env" ]; then
    if [ -f "env_example.txt" ]; then
        cp env_example.txt .env
        print_warning ".env file created from env_example.txt"
        print_warning "Please edit .env file with your API keys and settings"
    else
        cat > .env << EOF
# Copy Trading Bot Configuration
# Edit these values with your actual API keys and settings

# Database Configuration
DATABASE_URL=sqlite:///./copy_trading.db

# API Security
API_SECRET_KEY=your-secret-key-here-change-this
API_TOKEN=butter1011

# Binance Configuration
BINANCE_TESTNET=True
# Set to False for live trading (BE CAREFUL!)

# Logging
LOG_LEVEL=INFO

# Server Configuration
API_HOST=0.0.0.0
API_PORT=8000
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=5000

# Risk Management (Optional - can be set per account)
DEFAULT_RISK_PERCENTAGE=5.0
DEFAULT_LEVERAGE=10
EOF
        print_warning ".env file created with default values"
        print_warning "Please edit .env file with your actual API keys and settings"
    fi
else
    print_success ".env file already exists"
fi

# Set file permissions
print_info "Setting file permissions..."
chmod +x *.sh 2>/dev/null || true
chmod 600 .env 2>/dev/null || true

# Create log directory
print_info "Creating log directory..."
mkdir -p logs
chmod 755 logs

# Initialize database (if main.py exists)
if [ -f "main.py" ]; then
    print_info "Initializing database..."
    python main.py --init-db 2>/dev/null || print_warning "Database initialization skipped (normal if already exists)"
fi

# Create systemd service file (optional)
print_info "Creating systemd service file..."
cat > copy-trading-bot.service << EOF
[Unit]
Description=Copy Trading Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment=PATH=$(pwd)/venv/bin
ExecStart=$(pwd)/venv/bin/python $(pwd)/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

print_info "To install as system service, run:"
print_info "sudo cp copy-trading-bot.service /etc/systemd/system/"
print_info "sudo systemctl daemon-reload"
print_info "sudo systemctl enable copy-trading-bot"
print_info "sudo systemctl start copy-trading-bot"

print_success "Installation completed successfully!"
echo
echo "========================================"
echo "NEXT STEPS:"
echo "========================================"
echo "1. Edit .env file with your API keys:"
echo "   nano .env"
echo
echo "2. Start the bot:"
echo "   ./start.sh"
echo
echo "3. Or run in background:"
echo "   ./start_background.sh"
echo
echo "4. Access the dashboard:"
echo "   http://localhost:5000"
echo
echo "5. Access the API:"
echo "   http://localhost:8000"
echo
echo "========================================"
echo "IMPORTANT SECURITY NOTES:"
echo "========================================"
echo "- Edit .env file with your actual API keys"
echo "- Set BINANCE_TESTNET=False only when ready for live trading"
echo "- Never share your .env file or API keys"
echo "- Start with small amounts for testing"
echo "========================================"
