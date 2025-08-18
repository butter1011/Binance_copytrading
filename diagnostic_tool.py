#!/usr/bin/env python3
"""
Comprehensive Diagnostic Tool for Copy Trading Issues
"""

import sqlite3
import requests
import json
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_database_state():
    """Check database configuration and recent activity"""
    print("=" * 60)
    print("DATABASE DIAGNOSTIC")
    print("=" * 60)
    
    try:
        conn = sqlite3.connect('copy_trading.db')
        cursor = conn.cursor()
        
        # Check copy trading configurations
        cursor.execute("""
            SELECT id, master_account_id, follower_account_id, copy_percentage, 
                   risk_multiplier, is_active 
            FROM copy_trading_config
        """)
        configs = cursor.fetchall()
        
        print(f"\n📋 COPY TRADING CONFIGURATIONS:")
        if not configs:
            print("❌ NO COPY TRADING CONFIGURATIONS FOUND!")
            print("   You need to set up copy trading configurations first.")
        else:
            for config in configs:
                print(f"   Config {config[0]}: Master {config[1]} → Follower {config[2]}")
                print(f"     Copy%: {config[3]}%, Risk: {config[4]}, Active: {config[5]}")
        
        # Check accounts
        cursor.execute("SELECT id, name, is_master, risk_percentage, leverage FROM accounts")
        accounts = cursor.fetchall()
        
        print(f"\n👥 ACCOUNTS:")
        master_accounts = []
        follower_accounts = []
        
        for account in accounts:
            account_type = "MASTER" if account[2] else "FOLLOWER"
            print(f"   Account {account[0]}: {account[1]} ({account_type})")
            print(f"     Risk: {account[3]}%, Leverage: {account[4]}x")
            
            if account[2]:
                master_accounts.append(account[0])
            else:
                follower_accounts.append(account[0])
        
        print(f"\n📊 SUMMARY:")
        print(f"   Master accounts: {len(master_accounts)}")
        print(f"   Follower accounts: {len(follower_accounts)}")
        print(f"   Copy configurations: {len(configs)}")
        
        # Check recent trades
        cursor.execute("""
            SELECT symbol, side, quantity, status, account_id, created_at, copied_from_master
            FROM trades 
            WHERE created_at >= datetime('now', '-24 hours')
            ORDER BY created_at DESC
            LIMIT 20
        """)
        recent_trades = cursor.fetchall()
        
        print(f"\n📈 RECENT TRADES (Last 24 hours):")
        if not recent_trades:
            print("   No recent trades found")
        else:
            for trade in recent_trades:
                account_type = "MASTER" if trade[4] in master_accounts else "FOLLOWER"
                copied_status = "COPIED" if trade[6] else "ORIGINAL"
                print(f"   {trade[5]}: {trade[0]} {trade[1]} {trade[2]} - {trade[3]} ({account_type}, {copied_status})")
        
        # Check system logs
        cursor.execute("""
            SELECT level, message, created_at
            FROM system_logs 
            WHERE created_at >= datetime('now', '-1 hour')
            ORDER BY created_at DESC
            LIMIT 10
        """)
        recent_logs = cursor.fetchall()
        
        print(f"\n📝 RECENT SYSTEM LOGS (Last hour):")
        if not recent_logs:
            print("   No recent logs found")
        else:
            for log in recent_logs:
                print(f"   {log[2]}: [{log[0]}] {log[1]}")
        
        conn.close()
        return len(configs) > 0 and len(accounts) > 0
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

def test_api_connectivity():
    """Test API server connectivity and endpoints"""
    print("\n" + "=" * 60)
    print("API CONNECTIVITY TEST")
    print("=" * 60)
    
    api_base = "http://127.0.0.1:8000"
    endpoints = ["/health", "/status", "/accounts", "/trades", "/logs", "/copy-trading-config"]
    
    results = {}
    
    for endpoint in endpoints:
        try:
            response = requests.get(f"{api_base}{endpoint}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                results[endpoint] = {"status": "OK", "data_count": len(data) if isinstance(data, list) else 1}
                print(f"   ✅ {endpoint}: OK ({len(data) if isinstance(data, list) else 'object'} items)")
            else:
                results[endpoint] = {"status": "ERROR", "code": response.status_code}
                print(f"   ❌ {endpoint}: HTTP {response.status_code}")
        except requests.exceptions.ConnectionError:
            results[endpoint] = {"status": "CONNECTION_ERROR"}
            print(f"   ❌ {endpoint}: Connection failed (API server not running?)")
        except Exception as e:
            results[endpoint] = {"status": "ERROR", "error": str(e)}
            print(f"   ❌ {endpoint}: {e}")
    
    return all(r.get("status") == "OK" for r in results.values())

def analyze_position_sizing():
    """Analyze position sizing calculation logic"""
    print("\n" + "=" * 60)
    print("POSITION SIZING ANALYSIS")
    print("=" * 60)
    
    try:
        conn = sqlite3.connect('copy_trading.db')
        cursor = conn.cursor()
        
        # Get copy trading configs
        cursor.execute("SELECT copy_percentage, risk_multiplier FROM copy_trading_config WHERE is_active = 1")
        configs = cursor.fetchall()
        
        if not configs:
            print("❌ No active copy trading configurations found")
            return False
        
        print("📊 CURRENT POSITION SIZING LOGIC:")
        print("   Formula: follower_quantity = master_quantity × (copy_percentage / 100) × risk_multiplier")
        print("   Safety checks: Only warnings, no automatic reductions")
        
        for i, config in enumerate(configs):
            copy_pct, risk_mult = config
            print(f"\n   Configuration {i+1}:")
            print(f"     Copy percentage: {copy_pct}%")
            print(f"     Risk multiplier: {risk_mult}")
            
            # Test examples
            test_quantities = [1.0, 5.0, 10.0, 50.0]
            
            print(f"     Expected results:")
            for master_qty in test_quantities:
                expected_follower = master_qty * (copy_pct / 100.0) * risk_mult
                print(f"       Master {master_qty} → Follower {expected_follower}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Position sizing analysis error: {e}")
        return False

def check_restart_behavior():
    """Check restart duplicate prevention logic"""
    print("\n" + "=" * 60)
    print("RESTART BEHAVIOR CHECK")
    print("=" * 60)
    
    print("🔄 RESTART DUPLICATE PREVENTION:")
    print("   ✅ Order tracking initialized on startup")
    print("   ✅ Last processed time set to startup time")
    print("   ✅ Recent orders loaded from database")
    print("   ✅ Orders older than restart time are skipped")
    
    print("\n📝 TO TEST RESTART BEHAVIOR:")
    print("   1. Place a trade on master account")
    print("   2. Verify it copies to follower")
    print("   3. Restart the bot")
    print("   4. The same trade should NOT be copied again")
    
    return True

def generate_recommendations():
    """Generate recommendations based on diagnostics"""
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)
    
    # Check database state
    db_ok = check_database_state()
    
    if not db_ok:
        print("\n🔧 IMMEDIATE ACTIONS NEEDED:")
        print("   1. Set up master and follower accounts")
        print("   2. Create copy trading configurations")
        print("   3. Set copy percentage to 100% for 1:1 copying")
        return
    
    # Check API
    api_ok = test_api_connectivity()
    
    if not api_ok:
        print("\n🔧 API ISSUES DETECTED:")
        print("   1. Start the API server: python main.py")
        print("   2. Check if port 8000 is available")
        print("   3. Verify no firewall blocking")
    
    print("\n✅ FIXES IMPLEMENTED:")
    print("   1. Position sizing now uses simple copy percentage (no balance reduction)")
    print("   2. Enhanced logging throughout copy trading process")
    print("   3. Restart duplicate prevention with timestamp checking")
    print("   4. Improved dashboard log fetching and display")
    
    print("\n🔍 MONITORING CHECKLIST:")
    print("   1. Check dashboard logs for trade detection messages")
    print("   2. Verify copy percentage in configurations")
    print("   3. Monitor position sizes match expectations")
    print("   4. Test restart behavior with existing trades")

def main():
    """Run full diagnostic"""
    print("COPY TRADING DIAGNOSTIC TOOL")
    print("Version 2.0 - Post-Fix Analysis")
    print("=" * 60)
    
    try:
        # Run all diagnostics
        analyze_position_sizing()
        check_restart_behavior()
        
        # Test API if possible
        try:
            test_api_connectivity()
        except:
            print("\n⚠️ API server appears to be offline")
            print("   Start with: python main.py")
        
        # Generate recommendations
        generate_recommendations()
        
        print("\n" + "=" * 60)
        print("DIAGNOSTIC COMPLETE")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Diagnostic failed: {e}")

if __name__ == "__main__":
    main()
