# Quick Ubuntu Setup Guide
### For Systems with Python 3.11.9 Already Installed

Since you already have Python 3.11.9 installed, here's a streamlined setup process:

## 🚀 Quick Commands (Copy & Paste)

### 1. **Make Scripts Executable**
```bash
chmod +x *.sh
```

### 2. **Install Dependencies & Setup**
```bash
./install_ubuntu.sh
```

### 3. **Configure Your API Keys**
```bash
nano .env
```
**Add your Binance API credentials:**
```bash
BINANCE_API_KEY=your_actual_api_key_here
BINANCE_SECRET_KEY=your_actual_secret_key_here
BINANCE_TESTNET=True  # Set to False for live trading
```

### 4. **Start the Bot**
```bash
# Test mode (shows output)
./start.sh

# OR Background mode (recommended)
./start_background.sh
```

### 5. **Access Dashboard**
- **Dashboard**: http://localhost:5000
- **API**: http://localhost:8000

## 📋 Management Commands

```bash
# Check if bot is running
./status.sh

# Stop the bot
./stop.sh

# View background bot output
screen -r copy-trading-bot
```

## ⚡ Super Quick One-Liner Setup

```bash
chmod +x *.sh && ./install_ubuntu.sh && echo "Now edit .env with your API keys, then run ./start.sh"
```

## 🔧 What the install_ubuntu.sh Does

1. ✅ Detects your Python 3.11.9 (already installed)
2. ✅ Installs system dependencies (pip, venv, etc.)
3. ✅ Creates virtual environment
4. ✅ Installs Python packages from requirements.txt
5. ✅ Creates .env configuration file
6. ✅ Sets up directory structure

## 📝 Configuration Example

Your `.env` file should look like this:
```bash
# Binance API (REQUIRED)
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_SECRET_KEY=your_binance_secret_key_here
BINANCE_TESTNET=True

# Database
DATABASE_URL=sqlite:///./copy_trading.db

# Security
API_TOKEN=butter1011

# Servers
API_HOST=0.0.0.0
API_PORT=8000
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=5000
```

## 🛡️ Safety First

**IMPORTANT:** 
- Start with `BINANCE_TESTNET=True` for testing
- Use small amounts initially
- Test thoroughly before live trading
- Never share your API keys

## 🔍 Troubleshooting

### Python Issues
```bash
# Check Python version
python3 --version
# Should show: Python 3.11.9

# Check pip
python3 -m pip --version
```

### Permission Issues
```bash
# Fix script permissions
chmod +x *.sh

# Fix .env permissions
chmod 600 .env
```

### Bot Not Starting
```bash
# Check dependencies
source venv/bin/activate
python -c "import fastapi, uvicorn"

# Check logs
tail -f copy_trading.log
```

## 🎯 Success Indicators

When everything is working, you should see:
1. ✅ `./status.sh` shows "Bot is running"
2. ✅ Dashboard accessible at http://localhost:5000
3. ✅ API accessible at http://localhost:8000
4. ✅ Logs showing "Copy trading engine initialized"

That's it! Your Python 3.11.9 setup is perfect for this bot. 🚀
