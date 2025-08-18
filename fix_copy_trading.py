#!/usr/bin/env python3
"""
Script to fix copy trading issues and ensure proper configuration
"""
import logging
import sys
from models import get_session, Account, CopyTradingConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fix_copy_trading():
    """Fix copy trading setup and configuration issues"""
    try:
        session = get_session()
        
        logger.info("=== COPY TRADING DIAGNOSTICS ===")
        
        # Check accounts
        accounts = session.query(Account).all()
        master_accounts = [acc for acc in accounts if acc.is_master and acc.is_active]
        follower_accounts = [acc for acc in accounts if not acc.is_master and acc.is_active]
        
        logger.info(f"👥 Total accounts: {len(accounts)}")
        logger.info(f"👑 Master accounts: {len(master_accounts)}")
        logger.info(f"👤 Follower accounts: {len(follower_accounts)}")
        
        if not master_accounts:
            logger.error("❌ NO MASTER ACCOUNTS FOUND! Please create a master account first.")
            return False
            
        if not follower_accounts:
            logger.error("❌ NO FOLLOWER ACCOUNTS FOUND! Please create follower accounts first.")
            return False
            
        logger.info("\n📋 Account Details:")
        for account in accounts:
            account_type = "MASTER" if account.is_master else "FOLLOWER"
            status = "ACTIVE" if account.is_active else "INACTIVE"
            logger.info(f"  - Account {account.id}: {account.name} ({account_type}, {status})")
        
        # Check copy trading configurations
        configs = session.query(CopyTradingConfig).all()
        active_configs = [config for config in configs if config.is_active]
        
        logger.info(f"\n⚙️ Copy Trading Configurations:")
        logger.info(f"   Total: {len(configs)}")
        logger.info(f"   Active: {len(active_configs)}")
        
        if not configs:
            logger.warning("⚠️ NO COPY TRADING CONFIGURATIONS FOUND!")
            logger.info("🔧 This is the main reason why follower orders are not being placed.")
            
            # Auto-create configurations
            logger.info("\n🔄 Creating copy trading configurations...")
            for master in master_accounts:
                for follower in follower_accounts:
                    # Check if configuration already exists
                    existing = session.query(CopyTradingConfig).filter(
                        CopyTradingConfig.master_account_id == master.id,
                        CopyTradingConfig.follower_account_id == follower.id
                    ).first()
                    
                    if not existing:
                        config = CopyTradingConfig(
                            master_account_id=master.id,
                            follower_account_id=follower.id,
                            copy_percentage=100.0,
                            risk_multiplier=1.0,
                            is_active=True
                        )
                        session.add(config)
                        logger.info(f"✅ Created: Master {master.name} -> Follower {follower.name}")
                    else:
                        logger.info(f"📌 Exists: Master {master.name} -> Follower {follower.name} (Active: {existing.is_active})")
            
            session.commit()
            logger.info("✅ Copy trading configurations created/updated successfully!")
            
        else:
            logger.info("\n📋 Existing configurations:")
            for config in configs:
                master_name = next((acc.name for acc in accounts if acc.id == config.master_account_id), "Unknown")
                follower_name = next((acc.name for acc in accounts if acc.id == config.follower_account_id), "Unknown")
                status = "ACTIVE" if config.is_active else "INACTIVE"
                logger.info(f"   - Config {config.id}: {master_name} -> {follower_name} ({status}, {config.copy_percentage}%)")
        
        logger.info("\n✅ COPY TRADING SETUP VERIFICATION:")
        
        # Verify each master has at least one active configuration
        for master in master_accounts:
            master_configs = session.query(CopyTradingConfig).filter(
                CopyTradingConfig.master_account_id == master.id,
                CopyTradingConfig.is_active == True
            ).all()
            
            if master_configs:
                logger.info(f"✅ Master {master.name} has {len(master_configs)} active configuration(s)")
            else:
                logger.warning(f"⚠️ Master {master.name} has NO active configurations!")
        
        session.close()
        
        logger.info("\n🎯 NEXT STEPS:")
        logger.info("1. Restart the copy trading bot to load new configurations")
        logger.info("2. Check the bot logs for 'Copy trading config loaded' messages")
        logger.info("3. Monitor for follower order placement when master trades")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error fixing copy trading setup: {e}")
        return False

if __name__ == "__main__":
    success = fix_copy_trading()
    sys.exit(0 if success else 1)
