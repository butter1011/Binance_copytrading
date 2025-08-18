#!/usr/bin/env python3
"""
Quick Fix Script for Database Schema Issue
Run this to fix the "table trades has no column named follower_order_ids" error
"""

import sqlite3
import os
from datetime import datetime

def fix_database():
    """Quick fix for the missing column issue"""
    db_path = "copy_trading.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database file {db_path} not found!")
        return False
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("🔄 Checking current database structure...")
        
        # Check current columns
        cursor.execute("PRAGMA table_info(trades)")
        columns = [column[1] for column in cursor.fetchall()]
        print(f"📋 Current columns: {columns}")
        
        # Add missing columns
        missing_added = 0
        
        if 'follower_order_ids' not in columns:
            print("➕ Adding follower_order_ids column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN follower_order_ids TEXT")
            missing_added += 1
        
        if 'master_trade_id' not in columns:
            print("➕ Adding master_trade_id column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN master_trade_id INTEGER")
            missing_added += 1
        
        if 'copied_from_master' not in columns:
            print("➕ Adding copied_from_master column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN copied_from_master BOOLEAN DEFAULT 0")
            missing_added += 1
        
        if 'stop_price' not in columns:
            print("➕ Adding stop_price column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN stop_price REAL")
            missing_added += 1
        
        if 'take_profit_price' not in columns:
            print("➕ Adding take_profit_price column...")
            cursor.execute("ALTER TABLE trades ADD COLUMN take_profit_price REAL")
            missing_added += 1
        
        # Commit changes
        conn.commit()
        
        # Verify
        cursor.execute("PRAGMA table_info(trades)")
        new_columns = [column[1] for column in cursor.fetchall()]
        print(f"✅ Updated columns: {new_columns}")
        
        conn.close()
        
        if missing_added > 0:
            print(f"✅ Successfully added {missing_added} missing columns!")
            print("🚀 Database is now ready. You can restart your bot.")
        else:
            print("✅ All columns already exist. Database is ready.")
        
        return True
        
    except Exception as e:
        print(f"❌ Error fixing database: {e}")
        return False

if __name__ == "__main__":
    print("🔧 Quick Fix for Copy Trading Database Schema")
    print("=" * 50)
    
    success = fix_database()
    
    if success:
        print("\n🎉 Database schema fixed successfully!")
        print("\n📝 Next steps:")
        print("1. Restart your copy trading bot")
        print("2. The bot should now work without the 'follower_order_ids' error")
        print("3. Master order cancellations and position closing will now work properly")
    else:
        print("\n❌ Failed to fix database schema.")
        print("Please check the error messages above.")
