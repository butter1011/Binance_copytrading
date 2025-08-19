# Copy Trading Bot - Ubuntu Installation & Usage Guide

## Quick Start Commands

### 1. **Installation** (One-time setup)
```bash
# Download and make executable
chmod +x install_ubuntu.sh
./install_ubuntu.sh
```

### 2. **Configuration**
```bash
# Edit your API keys and settings
nano .env
```

### 3. **Run the Bot**
```bash
# Interactive mode (recommended for testing)
./start.sh

# Background mode (recommended for production)
./start_background.sh
```

### 4. **Monitor & Control**
```bash
# Check status
./status.sh

# Stop the bot
./stop.sh

# View background bot output
screen -r copy-trading-bot
# or
tmux attach-session -t copy-trading-bot
```

## Detailed Installation Steps

### Prerequisites
- Ubuntu 18.04 or newer
- Internet connection
- sudo privileges

### Step 1: Download the Bot
```bash
git clone <your-repo-url>
cd Binance_copytrading
```

### Step 2: Run Installation Script
```bash
chmod +x install_ubuntu.sh
./install_ubuntu.sh
```

**What this script does:**
- Updates system packages
- Installs Python 3.8+ and dependencies
- Creates virtual environment
- Installs Python packages
- Creates .env configuration file
- Sets up systemd service (optional)

### Step 3: Configure API Keys
```bash
nano .env
```

**Required settings:**
```bash
# Your Binance API credentials
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET_KEY=your_secret_key_here

# Set to False for live trading (start with True for testing)
BINANCE_TESTNET=True

# Security token
API_TOKEN=butter1011

# Database (default SQLite is fine)
DATABASE_URL=sqlite:///./copy_trading.db
```

### Step 4: Start the Bot
```bash
# For testing/development (shows output)
./start.sh

# For production (runs in background)
./start_background.sh
```

## Available Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `install_ubuntu.sh` | Install and setup | `./install_ubuntu.sh` |
| `start.sh` | Start bot (interactive) | `./start.sh` |
| `start_background.sh` | Start bot (background) | `./start_background.sh` |
| `stop.sh` | Stop the bot | `./stop.sh` |
| `status.sh` | Check bot status | `./status.sh` |

## URLs After Starting

- **Dashboard**: http://localhost:5000
- **API Documentation**: http://localhost:8000/docs
- **API Health Check**: http://localhost:8000/health

## Common Commands

### Managing Background Bot
```bash
# Start in background
./start_background.sh

# Check if running
./status.sh

# View live output
screen -r copy-trading-bot

# Detach but keep running
# Press Ctrl+A then D (in screen)
# Press Ctrl+B then D (in tmux)

# Stop background bot
./stop.sh
```

### Viewing Logs
```bash
# Real-time logs
tail -f copy_trading.log

# Or if using log directory
tail -f logs/app.log

# View bot output in background mode
screen -r copy-trading-bot
```

### Updating the Bot
```bash
# Stop bot
./stop.sh

# Update code
git pull

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Restart
./start_background.sh
```

## System Service Setup (Optional)

To run the bot as a system service that starts automatically:

```bash
# Copy service file
sudo cp copy-trading-bot.service /etc/systemd/system/

# Enable service
sudo systemctl daemon-reload
sudo systemctl enable copy-trading-bot

# Start service
sudo systemctl start copy-trading-bot

# Check status
sudo systemctl status copy-trading-bot

# View logs
journalctl -u copy-trading-bot -f
```

## Troubleshooting

### Bot Won't Start
```bash
# Check Python version
python3 --version

# Check virtual environment
source venv/bin/activate
python --version

# Check dependencies
pip list | grep fastapi

# Reinstall if needed
./install_ubuntu.sh
```

### Permission Errors
```bash
# Make scripts executable
chmod +x *.sh

# Fix .env permissions
chmod 600 .env
```

### API Connection Issues
```bash
# Check if ports are free
netstat -ln | grep :8000
netstat -ln | grep :5000

# Test API manually
curl http://localhost:8000/health

# Check firewall
sudo ufw status
```

### Database Issues
```bash
# Reset database (WARNING: Deletes all data)
rm copy_trading.db
python main.py --init-db
```

## Production Deployment Tips

### 1. **Security**
```bash
# Use strong API tokens
# Set proper file permissions
chmod 600 .env
chmod 700 logs/

# Consider using environment variables instead of .env file
export BINANCE_API_KEY="your_key"
export BINANCE_SECRET_KEY="your_secret"
```

### 2. **Monitoring**
```bash
# Setup log rotation
sudo nano /etc/logrotate.d/copy-trading-bot

# Monitor with systemd
sudo systemctl status copy-trading-bot

# Setup monitoring alerts
# Use tools like Prometheus, Grafana, or simple cron jobs
```

### 3. **Backup**
```bash
# Backup database
cp copy_trading.db backup_$(date +%Y%m%d).db

# Backup configuration
cp .env .env.backup
```

### 4. **Resource Monitoring**
```bash
# Check resource usage
./status.sh

# Monitor with htop
htop

# Check disk space
df -h
```

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./copy_trading.db` | Database connection string |
| `BINANCE_TESTNET` | `True` | Use testnet (set False for live) |
| `API_TOKEN` | `butter1011` | API authentication token |
| `LOG_LEVEL` | `INFO` | Logging level |
| `API_HOST` | `0.0.0.0` | API server host |
| `API_PORT` | `8000` | API server port |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard host |
| `DASHBOARD_PORT` | `5000` | Dashboard port |

## Support

If you encounter issues:

1. Check `./status.sh` for bot status
2. Review logs: `tail -f copy_trading.log`
3. Ensure .env is properly configured
4. Verify API keys are correct
5. Start with testnet before live trading

**Important**: Always test with small amounts and testnet before live trading!
