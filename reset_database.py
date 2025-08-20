#!/usr/bin/env python3
"""
Database Reset Script - Clear all historical trade data
"""

import sys
import os
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

from models import get_session, Trade, SystemLog, Position, CopyTradingConfig
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_database():
    """Reset the database by clearing historical data"""
    try:
        session = get_session()
        
        # Count existing data
        trade_count = session.query(Trade).count()
        log_count = session.query(SystemLog).count()
        position_count = session.query(Position).count()
        
        print(f"📊 Current database state:")
        print(f"   - Trades: {trade_count}")
        print(f"   - System Logs: {log_count}")
        print(f"   - Positions: {position_count}")
        print()
        
        # Ask for confirmation
        response = input("⚠️  This will delete ALL trades, logs, and positions. Continue? (y/N): ")
        if response.lower() != 'y':
            print("❌ Operation cancelled")
            return False
        
        print("🧹 Clearing database...")
        
        # Clear all trades (this is the main historical data causing issues)
        if trade_count > 0:
            session.query(Trade).delete()
            print(f"   ✅ Cleared {trade_count} trades")
        
        # Clear all system logs
        if log_count > 0:
            session.query(SystemLog).delete()
            print(f"   ✅ Cleared {log_count} system logs")
        
        # Clear all positions
        if position_count > 0:
            session.query(Position).delete()
            print(f"   ✅ Cleared {position_count} positions")
        
        # Note: We keep CopyTradingConfig (account configurations)
        config_count = session.query(CopyTradingConfig).count()
        print(f"   ℹ️  Kept {config_count} copy trading configurations")
        
        # Commit changes
        session.commit()
        session.close()
        
        print()
        print("✅ Database reset completed successfully!")
        print("💡 Now restart your copy trading server to start fresh")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error resetting database: {e}")
        if session:
            session.rollback()
            session.close()
        return False

def clear_trades_only():
    """Clear only trade data, keeping logs and configurations"""
    try:
        session = get_session()
        
        # Count existing trades
        trade_count = session.query(Trade).count()
        
        print(f"📊 Current trades in database: {trade_count}")
        
        if trade_count == 0:
            print("ℹ️  No trades to clear")
            return True
        
        # Ask for confirmation
        response = input(f"⚠️  This will delete {trade_count} trades. Continue? (y/N): ")
        if response.lower() != 'y':
            print("❌ Operation cancelled")
            return False
        
        print("🧹 Clearing trades...")
        
        # Clear all trades
        session.query(Trade).delete()
        session.commit()
        session.close()
        
        print(f"✅ Cleared {trade_count} trades successfully!")
        print("💡 Now restart your copy trading server to start fresh")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error clearing trades: {e}")
        if session:
            session.rollback()
            session.close()
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Reset copy trading database')
    parser.add_argument('--trades-only', action='store_true', help='Clear only trades, keep logs and configs')
    parser.add_argument('--full-reset', action='store_true', help='Clear all data including logs')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("COPY TRADING DATABASE RESET")
    print("=" * 60)
    
    if args.trades_only:
        clear_trades_only()
    elif args.full_reset:
        reset_database()
    else:
        print("Choose an option:")
        print("1. Clear trades only (recommended)")
        print("2. Full database reset (clear everything)")
        print("3. Cancel")
        
        choice = input("\nEnter choice (1-3): ")
        
        if choice == "1":
            clear_trades_only()
        elif choice == "2":
            reset_database()
        else:
            print("❌ Operation cancelled")
