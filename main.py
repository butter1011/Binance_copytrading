#!/usr/bin/env python3
"""
Copy Trading Bot - Main Application
A comprehensive copy trading system for Binance futures trading.

This application provides:
- Real-time copy trading from master accounts to follower accounts
- Web-based dashboard for monitoring and control
- REST API for programmatic access
- Secure API key management
- Risk management and position sizing
- Comprehensive logging and monitoring

Author: Copy Trading Bot Team
Version: 1.0.0
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

from config import Config
from models import create_database
from copy_trading_engine import copy_trading_engine
import uvicorn
from api import app as api_app
from dashboard import app as dashboard_app, socketio

# Setup logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

async def initialize_system():
    """Initialize the copy trading system"""
    try:
        logger.info("Starting Copy Trading Bot...")
        
        # Create database and tables
        logger.info("Creating database...")
        create_database()
        
        # Initialize copy trading engine
        logger.info("Initializing copy trading engine...")
        success = await copy_trading_engine.initialize()
        if not success:
            logger.error("Failed to initialize copy trading engine")
            return False
        
        logger.info("System initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize system: {e}")
        return False

def start_api_server():
    """Start the FastAPI server"""
    try:
        logger.info("Starting API server on port 8000...")
        import uvicorn
        import nest_asyncio
        nest_asyncio.apply()
        
        # Use the default event loop instead of creating a new one
        uvicorn.run(
            api_app,
            host="0.0.0.0",
            port=8000,
            log_level=Config.LOG_LEVEL.lower(),
            access_log=True
        )
    except Exception as e:
        logger.error(f"Failed to start API server: {e}")

def start_dashboard():
    """Start the Flask dashboard"""
    try:
        logger.info("Starting dashboard on port 5000...")
        
        # Check if port is already in use
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 5000))
        sock.close()
        
        if result == 0:
            logger.warning("Port 5000 is already in use. Trying port 5001...")
            port = 5001
        else:
            port = 5000
            
        socketio.run(
            dashboard_app,
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        logger.error(f"Failed to start dashboard: {e}")

async def main():
    """Main application entry point"""
    try:
        # Initialize the system
        if not await initialize_system():
            logger.error("System initialization failed. Exiting.")
            sys.exit(1)
        
        # Start the copy trading engine
        logger.info("Starting copy trading engine...")
        await copy_trading_engine.start_monitoring()
        
        logger.info("Copy Trading Bot is running!")
        logger.info("API Server: http://localhost:8000")
        logger.info("Dashboard: http://localhost:5000")
        logger.info("Press Ctrl+C to stop the application")
        
        # Start both servers in separate threads with proper error handling
        import threading
        import time
        
        # Start API server in background thread
        api_thread = threading.Thread(target=start_api_server, daemon=True)
        api_thread.start()
        
        # Wait a moment for API server to start
        time.sleep(3)
        
        # Start dashboard in background thread
        dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
        dashboard_thread.start()
        
        try:
            # Keep the main thread alive
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down Copy Trading Bot...")
            await copy_trading_engine.stop_monitoring()
            logger.info("Copy Trading Bot stopped successfully")
            
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Check if running on Windows
    if os.name == 'nt':
        # Use Windows-specific event loop policy
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Run the main application
    asyncio.run(main())
