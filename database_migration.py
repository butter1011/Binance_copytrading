#!/usr/bin/env python3
"""
Database Migration Script
Adds missing columns to existing database tables for copy trading functionality
"""

import sqlite3
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def migrate_database(db_path="copy_trading.db"):
    """Migrate the database to add missing columns"""
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        logger.info("🔄 Starting database migration...")
        
        # Check if follower_order_ids column exists
        cursor.execute("PRAGMA table_info(trades)")
        columns = [column[1] for column in cursor.fetchall()]
        
        logger.info(f"📋 Current trades table columns: {columns}")
        
        migrations_applied = 0
        
        # Add follower_order_ids column if it doesn't exist
        if 'follower_order_ids' not in columns:
            logger.info("➕ Adding follower_order_ids column to trades table...")
            cursor.execute("ALTER TABLE trades ADD COLUMN follower_order_ids TEXT")
            migrations_applied += 1
            logger.info("✅ Added follower_order_ids column")
        else:
            logger.info("✅ follower_order_ids column already exists")
        
        # Check if we need any other columns that might be missing
        expected_columns = [
            'id', 'account_id', 'symbol', 'side', 'order_type', 'quantity', 
            'price', 'stop_price', 'take_profit_price', 'status', 
            'binance_order_id', 'copied_from_master', 'master_trade_id', 
            'follower_order_ids', 'created_at', 'updated_at'
        ]
        
        missing_columns = []
        for col in expected_columns:
            if col not in columns:
                missing_columns.append(col)
        
        # Add any other missing columns
        for col in missing_columns:
            if col == 'follower_order_ids':
                continue  # Already handled above
            elif col == 'master_trade_id':
                logger.info("➕ Adding master_trade_id column to trades table...")
                cursor.execute("ALTER TABLE trades ADD COLUMN master_trade_id INTEGER")
                migrations_applied += 1
                logger.info("✅ Added master_trade_id column")
            elif col == 'stop_price':
                logger.info("➕ Adding stop_price column to trades table...")
                cursor.execute("ALTER TABLE trades ADD COLUMN stop_price REAL")
                migrations_applied += 1
                logger.info("✅ Added stop_price column")
            elif col == 'take_profit_price':
                logger.info("➕ Adding take_profit_price column to trades table...")
                cursor.execute("ALTER TABLE trades ADD COLUMN take_profit_price REAL")
                migrations_applied += 1
                logger.info("✅ Added take_profit_price column")
            elif col == 'copied_from_master':
                logger.info("➕ Adding copied_from_master column to trades table...")
                cursor.execute("ALTER TABLE trades ADD COLUMN copied_from_master BOOLEAN DEFAULT 0")
                migrations_applied += 1
                logger.info("✅ Added copied_from_master column")
        
        # Commit the changes
        conn.commit()
        
        # Verify the migration
        cursor.execute("PRAGMA table_info(trades)")
        new_columns = [column[1] for column in cursor.fetchall()]
        logger.info(f"📋 Updated trades table columns: {new_columns}")
        
        # Create indexes for better performance if they don't exist
        try:
            logger.info("📊 Creating performance indexes...")
            
            # Index on binance_order_id for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_binance_order_id 
                ON trades(binance_order_id)
            """)
            
            # Index on master_trade_id for faster follower trade lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_master_trade_id 
                ON trades(master_trade_id)
            """)
            
            # Index on account_id and status for faster filtering
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_account_status 
                ON trades(account_id, status)
            """)
            
            # Index on symbol and created_at for recent trades lookup
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_created 
                ON trades(symbol, created_at)
            """)
            
            conn.commit()
            logger.info("✅ Performance indexes created")
            
        except Exception as idx_error:
            logger.warning(f"⚠️ Warning creating indexes: {idx_error}")
        
        # Close the connection
        conn.close()
        
        if migrations_applied > 0:
            logger.info(f"✅ Database migration completed successfully! Applied {migrations_applied} changes.")
            logger.info("🚀 You can now restart your copy trading bot.")
        else:
            logger.info("✅ Database is already up to date. No migrations needed.")
            
        return True
        
    except Exception as e:
        logger.error(f"❌ Database migration failed: {e}")
        return False

def verify_database_schema(db_path="copy_trading.db"):
    """Verify that the database schema is correct"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check trades table structure
        cursor.execute("PRAGMA table_info(trades)")
        trades_columns = {column[1]: column[2] for column in cursor.fetchall()}
        
        logger.info("🔍 Verifying database schema...")
        logger.info("📋 Trades table structure:")
        for col_name, col_type in trades_columns.items():
            logger.info(f"   - {col_name}: {col_type}")
        
        # Required columns check
        required_columns = [
            'follower_order_ids', 'master_trade_id', 'copied_from_master',
            'stop_price', 'take_profit_price'
        ]
        
        missing = [col for col in required_columns if col not in trades_columns]
        if missing:
            logger.error(f"❌ Missing required columns: {missing}")
            return False
        else:
            logger.info("✅ All required columns are present")
            return True
            
    except Exception as e:
        logger.error(f"❌ Schema verification failed: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def backup_database(db_path="copy_trading.db"):
    """Create a backup of the database before migration"""
    try:
        import shutil
        backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(db_path, backup_path)
        logger.info(f"💾 Database backup created: {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"❌ Failed to create backup: {e}")
        return None

if __name__ == "__main__":
    logger.info("🚀 Starting database migration for copy trading bot...")
    
    # Create backup first
    backup_path = backup_database()
    if backup_path:
        logger.info(f"✅ Backup created successfully")
    else:
        logger.warning("⚠️ Could not create backup, proceeding anyway...")
    
    # Run migration
    success = migrate_database()
    
    if success:
        # Verify the migration
        if verify_database_schema():
            logger.info("🎉 Migration completed and verified successfully!")
            logger.info("📝 Summary:")
            logger.info("   - Database schema updated")
            logger.info("   - Performance indexes added")
            logger.info("   - Copy trading functionality enabled")
            logger.info("")
            logger.info("🚀 You can now restart your copy trading bot!")
        else:
            logger.error("❌ Migration completed but verification failed")
    else:
        logger.error("❌ Migration failed")
        if backup_path:
            logger.info(f"💾 Restore from backup if needed: {backup_path}")
