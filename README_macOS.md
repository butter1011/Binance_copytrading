# Copy Trading Bot - macOS Setup Guide

## Quick Start for macOS

### Prerequisites
- macOS 10.15+ (Catalina or newer)
- Internet connection for downloading dependencies
- Admin privileges (for Homebrew installation if needed)

### Installation

1. **Run the macOS installation script:**
   ```bash
   chmod +x install_macos.sh
   ./install_macos.sh
   ```

   This script will:
   - Install Homebrew (if not already installed)
   - Install Python 3.11 via Homebrew
   - Install system dependencies (git, curl, screen, tmux, etc.)
   - Create a Python virtual environment
   - Install all required Python packages
   - Create a `.env` configuration file
   - Set up a macOS LaunchAgent for auto-start

2. **Configure your API keys:**
   ```bash
   nano .env
   ```
   
   Edit the following important settings:
   - Add your Binance API keys
   - Set `BINANCE_TESTNET=True` for testing (recommended)
   - Configure other trading parameters

### Running the Bot

#### Interactive Mode (see all output)
```bash
./start.sh
```

#### Background Mode (runs in background)
```bash
./start_background.sh
```

#### Check Status
```bash
./status.sh
```

#### Stop the Bot
```bash
./stop.sh
```

### macOS-Specific Features

#### Auto-Start with LaunchAgent
The installation creates a macOS LaunchAgent that can automatically start the bot when you log in:

```bash
# Enable auto-start
launchctl load ~/Library/LaunchAgents/com.copytrading.bot.plist
launchctl start com.copytrading.bot

# Disable auto-start
launchctl stop com.copytrading.bot
launchctl unload ~/Library/LaunchAgents/com.copytrading.bot.plist
```

#### Homebrew Package Management
All system dependencies are managed through Homebrew:
- Python 3.11
- OpenSSL (for cryptography)
- Git, curl, wget
- screen, tmux
- Development tools

### Troubleshooting

#### Permission Issues
If you get permission errors:
```bash
chmod +x *.sh
```

#### Homebrew Issues
If Homebrew installation fails or has issues:
```bash
# Uninstall and reinstall Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)"
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### Python/Cryptography Issues
If you get SSL or cryptography errors:
```bash
# The install script should handle this, but if issues persist:
export LDFLAGS="-L$(brew --prefix openssl)/lib"
export CPPFLAGS="-I$(brew --prefix openssl)/include"
export PKG_CONFIG_PATH="$(brew --prefix openssl)/lib/pkgconfig"

# Reinstall problematic packages
source venv/bin/activate
pip install --force-reinstall cryptography pyOpenSSL
```

#### Virtual Environment Issues
If the virtual environment is corrupted:
```bash
rm -rf venv
./install_macos.sh
```

### Accessing the Bot

- **Web Dashboard:** http://localhost:5000
- **API Documentation:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

### Log Files

- **Application logs:** `copy_trading.log`
- **Bot output:** `logs/bot.out.log` (when using LaunchAgent)
- **Bot errors:** `logs/bot.err.log` (when using LaunchAgent)

### Security Notes

1. **Never share your `.env` file** - it contains your API keys
2. **Start with testnet** - Set `BINANCE_TESTNET=True` for testing
3. **Use small amounts** - Start with small trade sizes
4. **Monitor regularly** - Check logs and dashboard frequently
5. **Keep API keys secure** - Use API keys with limited permissions

### Differences from Linux

- Uses Homebrew instead of apt/yum for package management
- LaunchAgent instead of systemd for auto-start
- macOS-specific OpenSSL configuration for Python packages
- Different default shell (zsh vs bash) - scripts work with both

### Getting Help

If you encounter issues:
1. Check the log files
2. Run `./status.sh` to check bot status
3. Verify your `.env` configuration
4. Make sure you're using testnet first
5. Check the main README.md for general troubleshooting

### Performance Notes

- macOS typically has excellent performance for this bot
- SSD storage recommended for database operations
- Ensure your Mac doesn't go to sleep if running long-term
- Consider using energy saver settings that keep network active
