import asyncio
import json
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import Session
import ssl

# Fix OpenSSL issue
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except:
    pass

from models import Account, Trade, Position, CopyTradingConfig, SystemLog, get_session
from binance_client import BinanceClient
from config import Config

logger = logging.getLogger(__name__)

class CopyTradingEngine:
    def __init__(self):
        self.master_clients = {}  # account_id -> BinanceClient
        self.follower_clients = {}  # account_id -> BinanceClient
        self.is_running = False
        self.monitoring_tasks = {}
        self.last_trade_check = {}
        self.processed_orders = {}  # account_id -> set of order_ids to avoid duplicates
        self.last_processed_order_time = {}  # account_id -> datetime to avoid processing old orders on restart
        logger.info("🏗️ CopyTradingEngine initialized")
        
    async def initialize(self):
        """Initialize the copy trading engine"""
        try:
            logger.info("Initializing copy trading engine...")
            
            # Load all accounts and configurations
            await self.load_accounts()
            await self.setup_copy_trading_configs()
            
            # Initialize order tracking to prevent duplicate trades on restart
            await self.initialize_order_tracking()
            
            logger.info("Copy trading engine initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize copy trading engine: {e}")
            return False
    
    def add_system_log(self, level: str, message: str, account_id: int = None, trade_id: int = None):
        """Add a system log entry to database with fallback to file logging"""
        try:
            session = get_session()
            
            # Cleanup old logs periodically to prevent massive log accumulation
            # Keep only last 1000 logs per level to prevent database bloat
            try:
                log_count = session.query(SystemLog).filter(SystemLog.level == level.upper()).count()
                if log_count > 1000:
                    # Remove oldest logs of this level, keeping only the most recent 500
                    oldest_logs = session.query(SystemLog).filter(
                        SystemLog.level == level.upper()
                    ).order_by(SystemLog.created_at.asc()).limit(log_count - 500).all()
                    
                    for old_log in oldest_logs:
                        session.delete(old_log)
                    
                    logger.info(f"🧹 Cleaned up {len(oldest_logs)} old {level} logs")
            except Exception as cleanup_error:
                logger.warning(f"⚠️ Log cleanup failed: {cleanup_error}")
            
            log = SystemLog(
                level=level.upper(),
                message=message,
                account_id=account_id,
                trade_id=trade_id
            )
            session.add(log)
            session.commit()
            session.close()
            
            # Also log to file logger for immediate visibility
            log_func = getattr(logger, level.lower(), logger.info)
            log_func(f"[DB_LOG] {message}")
            
        except Exception as e:
            logger.error(f"Failed to add system log to database: {e}")
            # Log to file as fallback
            log_func = getattr(logger, level.lower(), logger.info)
            log_func(f"[FALLBACK] {message}")
    
    def cleanup_old_logs(self, max_logs_per_level: int = 500):
        """Clean up old system logs to prevent database bloat"""
        try:
            session = get_session()
            
            # Get all log levels
            levels = session.query(SystemLog.level).distinct().all()
            total_cleaned = 0
            
            for (level,) in levels:
                log_count = session.query(SystemLog).filter(SystemLog.level == level).count()
                
                if log_count > max_logs_per_level:
                    # Remove oldest logs, keeping only the most recent ones
                    logs_to_remove = log_count - max_logs_per_level
                    oldest_logs = session.query(SystemLog).filter(
                        SystemLog.level == level
                    ).order_by(SystemLog.created_at.asc()).limit(logs_to_remove).all()
                    
                    for old_log in oldest_logs:
                        session.delete(old_log)
                    
                    total_cleaned += len(oldest_logs)
                    logger.info(f"🧹 Cleaned up {len(oldest_logs)} old {level} logs")
            
            session.commit()
            session.close()
            
            if total_cleaned > 0:
                logger.info(f"✅ Total log cleanup: {total_cleaned} old logs removed")
                self.add_system_log("INFO", f"🧹 Log cleanup completed: {total_cleaned} old logs removed")
            
            return total_cleaned
            
        except Exception as e:
            logger.error(f"❌ Error during log cleanup: {e}")
            return 0
    
    async def initialize_order_tracking(self):
        """Initialize order tracking to prevent duplicates on restart"""
        try:
            logger.info("🔄 Initializing order tracking to prevent restart duplicates...")
            current_time = datetime.utcnow()
            
            # Set last processed time to current time for all master accounts
            # This prevents processing old orders when the bot restarts
            for master_id in self.master_clients.keys():
                self.last_processed_order_time[master_id] = current_time
                self.processed_orders[master_id] = set()
                logger.info(f"🕒 Set last processed time for master {master_id} to {current_time}")
                
                # Also log recent database trades to avoid reprocessing
                try:
                    session = get_session()
                    recent_trades = session.query(Trade).filter(
                        Trade.account_id == master_id,
                        Trade.created_at >= current_time - timedelta(hours=24)  # Last 24 hours
                    ).all()
                    
                    for trade in recent_trades:
                        if trade.binance_order_id:
                            self.processed_orders[master_id].add(str(trade.binance_order_id))
                    
                    logger.info(f"📋 Loaded {len(recent_trades)} recent orders for master {master_id} to prevent duplicates")
                    session.close()
                    
                except Exception as db_error:
                    logger.warning(f"⚠️ Could not load recent orders for master {master_id}: {db_error}")
                    
            self.add_system_log("INFO", "🔄 Order tracking initialized - old orders will not be reprocessed on restart")
            
        except Exception as e:
            logger.error(f"Failed to initialize order tracking: {e}")
            self.add_system_log("ERROR", f"Failed to initialize order tracking: {e}")
    
    async def load_accounts(self):
        """Load all accounts from database"""
        try:
            session = get_session()
            accounts = session.query(Account).filter(Account.is_active == True).all()
            
            logger.info(f"Loading {len(accounts)} active accounts...")
            
            for account in accounts:
                logger.info(f"Processing account {account.id}: {account.name} (is_master: {account.is_master})")
                
                client = BinanceClient(
                    api_key=account.api_key,
                    secret_key=account.secret_key,
                    testnet=Config.BINANCE_TESTNET
                )
                
                # Test connection with different requirements for master vs follower
                connection_valid = await client.test_connection()
                
                if connection_valid:
                    if account.is_master:
                        self.master_clients[account.id] = client
                        logger.info(f"✅ Master account loaded: {account.name} (ID: {account.id})")
                    else:
                        self.follower_clients[account.id] = client
                        logger.info(f"✅ Follower account loaded: {account.name} (ID: {account.id})")
                elif not account.is_master:
                    # For follower accounts (subaccounts), be more lenient
                    logger.warning(f"⚠️ Follower account {account.name} has limited API permissions")
                    logger.info(f"🔄 Attempting to load anyway for copy trading...")
                    
                    # Load follower anyway if it's a subaccount - we'll handle errors during trading
                    self.follower_clients[account.id] = client
                    logger.info(f"✅ Follower account loaded with limited permissions: {account.name} (ID: {account.id})")
                else:
                    logger.error(f"❌ Failed to connect to account: {account.name} (ID: {account.id})")
            
            logger.info(f"Loaded {len(self.master_clients)} master accounts and {len(self.follower_clients)} follower accounts")
            session.close()
        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")
            raise
    
    async def setup_copy_trading_configs(self):
        """Setup copy trading configurations"""
        try:
            session = get_session()
            configs = session.query(CopyTradingConfig).filter(CopyTradingConfig.is_active == True).all()
            
            logger.info(f"Loading {len(configs)} active copy trading configurations...")
            logger.info(f"Available master accounts: {list(self.master_clients.keys())}")
            logger.info(f"Available follower accounts: {list(self.follower_clients.keys())}")
            
            for config in configs:
                master_available = config.master_account_id in self.master_clients
                follower_available = config.follower_account_id in self.follower_clients
                
                if master_available and follower_available:
                    logger.info(f"Copy trading config loaded: Master {config.master_account_id} -> Follower {config.follower_account_id}")
                else:
                    if not master_available:
                        logger.warning(f"Master account {config.master_account_id} not available (not loaded or not master)")
                    if not follower_available:
                        logger.warning(f"Follower account {config.follower_account_id} not available (not loaded or is master)")
                    logger.warning(f"Invalid copy trading config: Master {config.master_account_id} -> Follower {config.follower_account_id}")
                    
            session.close()
        except Exception as e:
            logger.error(f"Failed to setup copy trading configs: {e}")
            raise
    
    async def start_monitoring(self):
        """Start monitoring all master accounts"""
        if self.is_running:
            logger.warning("Copy trading engine is already running")
            return
        
        self.is_running = True
        logger.info("Starting copy trading monitoring...")
        
        # Start monitoring each master account
        for master_id, client in self.master_clients.items():
            task = asyncio.create_task(self.monitor_master_account(master_id, client))
            self.monitoring_tasks[master_id] = task
            self.last_trade_check[master_id] = datetime.utcnow()
            # Initialize processed orders tracking for this master
            if master_id not in self.processed_orders:
                self.processed_orders[master_id] = set()
        
        logger.info(f"Started monitoring {len(self.master_clients)} master accounts")
    
    async def stop_monitoring(self):
        """Stop monitoring all master accounts"""
        if not self.is_running:
            return
        
        self.is_running = False
        logger.info("Stopping copy trading monitoring...")
        
        # Cancel all monitoring tasks
        for task in self.monitoring_tasks.values():
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self.monitoring_tasks.values(), return_exceptions=True)
        self.monitoring_tasks.clear()
        
        logger.info("Copy trading monitoring stopped")
    
    async def monitor_master_account(self, master_id: int, client: BinanceClient):
        """Monitor a specific master account for new trades"""
        try:
            logger.info(f"🔍 Starting monitoring for master account {master_id}")
            loop_count = 0
            
            while self.is_running:
                try:
                    loop_count += 1
                    if loop_count % 60 == 0:  # Log every 60 loops (about 1 minute)
                        logger.info(f"📊 Monitoring master {master_id} - Loop {loop_count}")
                    
                    # Get recent trades from master account
                    await self.check_master_trades(master_id, client)
                    
                    # Wait before next check
                    await asyncio.sleep(Config.TRADE_SYNC_DELAY)
                    
                except asyncio.CancelledError:
                    logger.info(f"⏹️ Monitoring cancelled for master {master_id}")
                    break
                except Exception as e:
                    logger.error(f"❌ Error monitoring master account {master_id}: {e}")
                    await asyncio.sleep(5)  # Wait before retrying
                    
        except Exception as e:
            logger.error(f"💥 Failed to monitor master account {master_id}: {e}")
        finally:
            logger.info(f"🔚 Stopped monitoring master account {master_id}")
    
    async def check_master_trades(self, master_id: int, client: BinanceClient):
        """Check for new trades in master account using Binance API"""
        try:
            # Get the last trade timestamp for this master
            last_check = self.last_trade_check.get(master_id, datetime.utcnow() - timedelta(hours=1))
            
            # Get recent trades from Binance API directly
            logger.debug(f"Checking trades for master {master_id} since {last_check}")
            
            try:
                # Get recent orders from Binance
                recent_orders = await self.get_recent_orders(client, last_check)
                
                if recent_orders:
                    logger.info(f"Found {len(recent_orders)} recent orders for master {master_id}")
                    
                    # Sort orders by time to process them in chronological order
                    recent_orders.sort(key=lambda x: x.get('time', x.get('updateTime', 0)))
                    
                    for order in recent_orders:
                        try:
                            order_status = order.get('status', 'UNKNOWN')
                            logger.info(f"📝 About to process order {order['orderId']} (Status: {order_status}) for master {master_id}")
                            await self.process_master_order(master_id, order)
                            logger.info(f"✅ Successfully processed order {order['orderId']} for master {master_id}")
                        except Exception as order_error:
                            logger.error(f"❌ Error processing order {order['orderId']} for master {master_id}: {order_error}")
                            import traceback
                            logger.error(f"Full traceback: {traceback.format_exc()}")
                else:
                    logger.debug(f"No recent orders found for master {master_id}")
                    
            except Exception as e:
                logger.warning(f"Failed to get orders from Binance for master {master_id}: {e}")
                # Fallback to database check
                await self.check_database_trades(master_id, last_check)
            
            # Update last check time
            self.last_trade_check[master_id] = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"Error checking master trades: {e}")
    
    async def get_recent_orders(self, client: BinanceClient, since_time: datetime):
        """Get recent orders from Binance API - includes both open and filled orders"""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            
            # Convert datetime to timestamp
            start_time = int(since_time.timestamp() * 1000)
            
            logger.info(f"🔍 Fetching orders since {since_time}")
            
            # Get both open orders and recent historical orders
            all_orders = []
            
            # 1. Get current open orders (these should be copied immediately)
            try:
                open_orders = await client.get_open_orders()
                if open_orders:
                    logger.info(f"📋 Retrieved {len(open_orders)} open orders")
                    for order in open_orders:
                        # Fix timestamp display in logs
                        order_time = int(order['time'])
                        current_time_ms = int(datetime.utcnow().timestamp() * 1000)
                        if order_time > current_time_ms + 86400000:  # More than 1 day in future
                            timestamp_display = "INVALID_FUTURE_TIME"
                        else:
                            timestamp_display = datetime.fromtimestamp(order_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        logger.info(f"📋 Open order details: ID={order['orderId']}, Symbol={order['symbol']}, Side={order['side']}, Status={order['status']}, Time={timestamp_display}")
                    all_orders.extend(open_orders)
                else:
                    logger.debug("📋 No open orders found")
            except Exception as e:
                logger.warning(f"⚠️ Failed to get open orders: {e}")
            
            # 2. Get recent historical orders
            try:
                historical_orders = await loop.run_in_executor(
                    None, 
                    lambda: client.client.futures_get_all_orders(startTime=start_time, limit=100)
                )
                logger.info(f"📊 Retrieved {len(historical_orders)} historical orders from Binance")
                all_orders.extend(historical_orders)
            except Exception as e:
                logger.error(f"❌ Failed to get historical orders: {e}")
            
            # Remove duplicates based on orderId and filter for relevant orders
            seen_orders = set()
            relevant_orders = []
            
            for order in all_orders:
                order_id = order['orderId']
                order_time = int(order['time'])
                order_status = order['status']
                
                # Fix timestamp issue: Binance sometimes returns future timestamps
                # Validate timestamp is reasonable (not in the far future)
                current_time_ms = int(datetime.utcnow().timestamp() * 1000)
                if order_time > current_time_ms + 86400000:  # More than 1 day in future
                    logger.warning(f"⚠️ Order {order_id} has invalid future timestamp: {order_time}, using current time")
                    order_time = current_time_ms
                
                # Include orders if:
                # 1. They are open orders (NEW/PARTIALLY_FILLED) - regardless of time
                # 2. They are recent filled orders (within time range)
                # 3. They are recent cancelled/expired orders (need to cancel followers)
                # 4. ANY filled orders in the last 5 minutes to catch fast-filling orders
                is_open_order = order_status in ['NEW', 'PARTIALLY_FILLED']
                is_recent_filled = order_status == 'FILLED' and order_time >= start_time
                # EXTENDED WINDOW: Also catch FILLED orders from last 5 minutes to handle fast execution
                five_minutes_ago = int((datetime.utcnow() - timedelta(minutes=5)).timestamp() * 1000)
                is_recently_filled = order_status == 'FILLED' and order_time >= five_minutes_ago
                # For cancelled orders, process recent ones (within normal time range) to handle follower cancellations
                is_recent_cancelled = order_status in ['CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED'] and order_time >= start_time
                
                if (order_id not in seen_orders and 
                    order['side'] in ['BUY', 'SELL'] and 
                    order_status in ['NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED'] and
                    (is_open_order or is_recent_filled or is_recently_filled or is_recent_cancelled)):
                    seen_orders.add(order_id)
                    relevant_orders.append(order)
                    if is_open_order:
                        status_note = "📋 OPEN"
                    elif is_recent_cancelled:
                        status_note = "❌ CANCELLED"
                    elif is_recently_filled:
                        status_note = "🏁 FILLED (Extended Window)"
                    else:
                        status_note = "🏁 RECENT"
                    # Fix timestamp display for logging
                    timestamp_display = datetime.fromtimestamp(order_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    logger.info(f"🎯 Found order {status_note}: {order['symbol']} {order['side']} {order['origQty']} - Status: {order_status} - Time: {timestamp_display}")
                else:
                    # Log why orders are being filtered out
                    if order_id in seen_orders:
                        logger.debug(f"⏭️ Skipping duplicate order: {order_id}")
                    elif order['side'] not in ['BUY', 'SELL']:
                        logger.debug(f"⏭️ Skipping non-trading order: {order_id} (side: {order['side']})")
                    elif order_status not in ['NEW', 'PARTIALLY_FILLED', 'FILLED']:
                        logger.debug(f"⏭️ Skipping order with status: {order_id} (status: {order_status})")
                    elif not (is_open_order or is_recent_filled or is_recently_filled):
                        timestamp_display = datetime.fromtimestamp(order_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        start_time_display = datetime.fromtimestamp(start_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        five_min_display = datetime.fromtimestamp(five_minutes_ago / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        logger.debug(f"⏭️ Skipping old order: {order_id} (time: {timestamp_display}, normal threshold: {start_time_display}, extended threshold: {five_min_display})")
            
            logger.info(f"✅ Found {len(relevant_orders)} relevant orders (open + filled)")
            return relevant_orders
            
        except Exception as e:
            logger.error(f"❌ Error getting recent orders: {e}")
            return []
    
    async def check_database_trades(self, master_id: int, last_check: datetime):
        """Fallback method to check database for trades"""
        try:
            session = get_session()
            
            recent_trades = session.query(Trade).filter(
                Trade.account_id == master_id,
                Trade.created_at > last_check,
                Trade.copied_from_master == False
            ).all()
            
            for trade in recent_trades:
                await self.copy_trade_to_followers(trade, session)
            
            session.close()
            
        except Exception as e:
            logger.error(f"Error checking database trades: {e}")
    
    async def process_master_order(self, master_id: int, order: dict):
        """Process an order from master account (open, partially filled, or filled)"""
        session = None
        try:
            order_id = str(order['orderId'])
            order_status = order['status']
            executed_qty = float(order.get('executedQty', 0))
            original_qty = float(order['origQty'])
            order_time = datetime.fromtimestamp(order.get('time', order.get('updateTime', 0)) / 1000)
            
            logger.info(f"🎯 Starting to process master order: {order['symbol']} {order['side']} {original_qty} - Status: {order_status} - Time: {order_time}")
            logger.info(f"🔍 Order details: ID={order_id}, ExecutedQty={executed_qty}, Type={order.get('type', 'UNKNOWN')}")
            
            # Check if this order is from before restart (prevent duplicate processing)
            if master_id in self.last_processed_order_time:
                if order_time < self.last_processed_order_time[master_id]:
                    logger.info(f"⏭️ Skipping old order {order_id} from {order_time} (before restart time {self.last_processed_order_time[master_id]})")
                    return
            
            # Check if we've already processed this order
            if master_id not in self.processed_orders:
                self.processed_orders[master_id] = set()
                logger.debug(f"🆕 Initialized processed_orders for master {master_id}")
            
            if order_id in self.processed_orders[master_id]:
                # Check if the order actually exists in the database with proper error handling
                session_check = None
                try:
                    session_check = get_session()
                    existing_trade = session_check.query(Trade).filter(
                        Trade.binance_order_id == order_id,
                        Trade.account_id == master_id
                    ).first()
                    
                    if existing_trade:
                        logger.debug(f"✅ Order {order_id} exists in database, skipping")
                        # For cancelled orders, still check if we need to handle follower cancellations
                        if order_status in ['CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED'] and existing_trade.status != 'CANCELLED':
                            logger.info(f"🔄 Order {order_id} status changed to CANCELLED - handling follower cancellations")
                            existing_trade.status = 'CANCELLED'
                            session_check.commit()
                            await self.handle_master_order_cancellation_with_trade(existing_trade, session_check)
                            session_check.close()
                        return
                    else:
                        logger.warning(f"🔄 Order {order_id} NOT in database - reprocessing...")
                        # Remove from processed set so we can reprocess
                        self.processed_orders[master_id].discard(order_id)
                        
                except Exception as db_error:
                    logger.error(f"❌ Database check failed for order {order_id}: {db_error}")
                    # Continue processing the order despite database check failure
                    self.processed_orders[master_id].discard(order_id)
                finally:
                    if session_check:
                        try:
                            session_check.close()
                        except Exception as cleanup_error:
                            logger.error(f"❌ Error closing database session: {cleanup_error}")
            
            logger.info(f"📋 Processing NEW master order: {order['symbol']} {order['side']} {original_qty} - Status: {order_status}")
            
            # Mark this order as processed (with cleanup to prevent memory leaks)
            self.processed_orders[master_id].add(order_id)
            logger.debug(f"✔️ Marked order {order_id} as processed")
            
            # Clean up old processed orders to prevent memory leaks (keep only last 1000)
            if len(self.processed_orders[master_id]) > 1000:
                # Convert to list, sort by order_id (assuming newer orders have higher IDs)
                sorted_orders = sorted(self.processed_orders[master_id])
                # Keep only the most recent 500 orders
                self.processed_orders[master_id] = set(sorted_orders[-500:])
                logger.debug(f"🧹 Cleaned up processed orders for master {master_id}")
            
            # Create trade record in database
            logger.info(f"💾 Creating database session...")
            session = get_session()
            logger.info(f"💾 Database session created successfully")
            
            # Log master trade detection
            self.add_system_log("INFO", f"🔍 Master trade detected: {order.get('symbol')} {order.get('side')} {executed_qty} (Status: {order_status})", master_id)
            
            # Determine the status and quantity to record
            if order_status == 'NEW':
                db_status = 'PENDING'
                quantity_to_record = original_qty
                price_to_record = float(order.get('price', 0))
            elif order_status == 'PARTIALLY_FILLED':
                db_status = 'PARTIALLY_FILLED'
                quantity_to_record = executed_qty
                price_to_record = float(order.get('avgPrice', order.get('price', 0)))
            elif order_status == 'FILLED':
                db_status = 'FILLED'
                quantity_to_record = executed_qty
                price_to_record = float(order.get('avgPrice', order.get('price', 0)))
            elif order_status in ['CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED']:
                # Handle cancelled/expired orders - need to cancel follower orders
                logger.info(f"🚫 Processing cancelled/expired order: {order_id} - Symbol: {order.get('symbol')} Side: {order.get('side')} Qty: {order.get('origQty')}")
                
                # First, try to find existing master trade record for this order
                existing_master_trade = session.query(Trade).filter(
                    Trade.account_id == master_id,
                    Trade.binance_order_id == str(order_id)
                ).first()
                
                if existing_master_trade:
                    logger.info(f"📝 Found existing master trade {existing_master_trade.id} for cancelled order - Status: {existing_master_trade.status}")
                    # Update the existing trade status
                    if existing_master_trade.status != 'CANCELLED':
                        existing_master_trade.status = 'CANCELLED'
                        session.commit()
                        logger.info(f"📝 Updated master trade {existing_master_trade.id} status to CANCELLED")
                    # Handle follower cancellations using the existing trade
                    await self.handle_master_order_cancellation_with_trade(existing_master_trade, session)
                else:
                    logger.info(f"📝 No existing master trade found for cancelled order {order_id}")
                    # Search for follower trades by order symbol, side, and time range
                    # This catches cases where the master order was cancelled before the trade record was created
                    logger.info(f"🔍 Searching for follower trades by order details: {order.get('symbol')} {order.get('side')} {order.get('origQty')}")
                    await self.handle_cancellation_by_order_details(master_id, order, session)
                    
                    # Log the cancellation
                    self.add_system_log("INFO", f"🚫 Master order cancelled: {order.get('symbol')} {order.get('side')} {order_id}", master_id)
                
                logger.info(f"🔚 Completed processing cancelled order {order_id}")
                session.close()
                return
            else:
                logger.warning(f"⚠️ Unsupported order status: {order_status}")
                session.close()
                return
            
            db_trade = Trade(
                account_id=master_id,
                symbol=order['symbol'],
                side=order['side'],
                order_type=order['type'],
                quantity=quantity_to_record,
                price=price_to_record,
                status=db_status,
                binance_order_id=str(order['orderId']),
                copied_from_master=False
            )
            
            logger.info(f"💾 Adding trade to database...")
            session.add(db_trade)
            logger.info(f"💾 Committing trade to database...")
            session.commit()
            logger.info(f"💾 Refreshing trade from database...")
            session.refresh(db_trade)
            logger.info(f"✅ Trade {db_trade.id} saved to database successfully")
            
            # Copy to followers for NEW orders and FILLED orders  
            # Also handle case where we missed the NEW state and only see FILLED
            if order_status in ['NEW', 'FILLED']:
                logger.info(f"🚀 Copying {order_status.lower()} order to followers immediately")
                
                # For FILLED orders, check if we already copied this as NEW to avoid duplicates
                if order_status == 'FILLED':
                    existing_copy = session.query(Trade).filter(
                        Trade.master_trade_id == db_trade.id,
                        Trade.copied_from_master == True
                    ).first()
                    
                    if existing_copy:
                        logger.info(f"📝 FILLED order already copied when it was NEW, skipping duplicate")
                        session.close()
                        return
                    else:
                        logger.info(f"🎯 FILLED order was not copied as NEW - copying now (this handles fast-filling orders)")
                
                # Check if this is a position closing order (reduceOnly = True or opposite direction trade)
                if await self.is_position_closing_order(master_id, db_trade, session):
                    logger.info(f"🔄 Detected position closing order - closing follower positions")
                    await self.close_follower_positions(db_trade, session)
                else:
                    logger.info(f"📈 Regular trade order - copying to followers")
                    await self.copy_trade_to_followers(db_trade, session)
                    
            elif order_status == 'PARTIALLY_FILLED':
                # For partially filled orders, check if we already copied this order
                # to avoid duplicate trades
                logger.info(f"📝 Partially filled order recorded, checking if already copied")
                existing_copy = session.query(Trade).filter(
                    Trade.master_trade_id == db_trade.id,
                    Trade.copied_from_master == True
                ).first()
                
                if not existing_copy:
                    logger.info(f"🚀 Copying partially filled order to followers")
                    
                    # Check if this is a position closing order
                    if await self.is_position_closing_order(master_id, db_trade, session):
                        logger.info(f"🔄 Detected position closing order - closing follower positions")
                        await self.close_follower_positions(db_trade, session)
                    else:
                        logger.info(f"📈 Regular trade order - copying to followers")
                        await self.copy_trade_to_followers(db_trade, session)
                else:
                    logger.info(f"📝 Order already copied, skipping duplicate")
            else:
                logger.info(f"📝 Order recorded but not copied (status: {order_status})")
            
            logger.info(f"🔒 Closing database session...")
            session.close()
            logger.info(f"✅ Master order {order_id} processed completely")
            
        except Exception as e:
            logger.error(f"❌ Error processing master order: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            if session:
                try:
                    session.rollback()
                    session.close()
                    logger.info(f"🔒 Database session closed after error")
                except Exception as cleanup_error:
                    logger.error(f"❌ Error cleaning up database session: {cleanup_error}")
    
    async def copy_trade_to_followers(self, master_trade: Trade, session: Session):
        """Copy a master trade to all follower accounts"""
        try:
            logger.info(f"Copying trade {master_trade.id} to followers")
            
            # Get copy trading configurations for this master
            configs = session.query(CopyTradingConfig).filter(
                CopyTradingConfig.master_account_id == master_trade.account_id,
                CopyTradingConfig.is_active == True
            ).all()
            
            logger.info(f"📋 Found {len(configs)} active copy trading configurations for master {master_trade.account_id}")
            if len(configs) == 0:
                logger.error(f"❌ NO COPY TRADING CONFIGURATIONS FOUND for master {master_trade.account_id}")
                logger.error(f"🔧 THIS IS WHY FOLLOWER ORDERS ARE NOT BEING PLACED!")
                logger.error(f"💡 To fix this issue:")
                logger.error(f"   1. Check the database tables 'accounts' and 'copy_trading_configs'")
                logger.error(f"   2. Ensure master account {master_trade.account_id} has active copy configurations")
                logger.error(f"   3. Run: SELECT * FROM copy_trading_configs WHERE master_account_id = {master_trade.account_id};")
                
                # Also log available accounts and configurations for debugging
                try:
                    all_accounts = session.query(Account).all()
                    logger.info(f"🔍 Total accounts in database: {len(all_accounts)}")
                    for account in all_accounts:
                        account_type = "MASTER" if account.is_master else "FOLLOWER"
                        status = "ACTIVE" if account.is_active else "INACTIVE"
                        logger.info(f"   - Account {account.id}: {account.name} ({account_type}, {status})")
                    
                    all_configs = session.query(CopyTradingConfig).all()
                    logger.info(f"🔍 Total copy trading configurations in database: {len(all_configs)}")
                    if all_configs:
                        for config in all_configs:
                            status = "ACTIVE" if config.is_active else "INACTIVE"
                            logger.info(f"   - Config {config.id}: Master {config.master_account_id} -> Follower {config.follower_account_id} ({status})")
                    else:
                        logger.error(f"❌ NO COPY TRADING CONFIGURATIONS EXIST AT ALL!")
                        logger.error(f"   You need to create copy trading configurations in the database")
                        
                except Exception as debug_error:
                    logger.error(f"❌ Error fetching debug information: {debug_error}")
                
                return
            
            for config in configs:
                logger.info(f"🔗 Processing copy config: Master {config.master_account_id} -> Follower {config.follower_account_id} (Copy: {config.copy_percentage}%)")
                
                follower_client = self.follower_clients.get(config.follower_account_id)
                if not follower_client:
                    logger.error(f"❌ FOLLOWER CLIENT NOT FOUND for account {config.follower_account_id}")
                    logger.error(f"🔧 Available follower clients: {list(self.follower_clients.keys())}")
                    logger.error(f"💡 This means:")
                    logger.error(f"   - The follower account {config.follower_account_id} is not loaded")
                    logger.error(f"   - Check if the account is active and has valid API credentials")
                    logger.error(f"   - Restart the bot to reload accounts")
                    continue
                
                logger.info(f"✅ Found follower client for account {config.follower_account_id}")
                
                # Calculate position size for follower
                follower_quantity = await self.calculate_follower_quantity(
                    master_trade, config, follower_client
                )
                
                if follower_quantity <= 0:
                    logger.warning(f"Invalid quantity calculated for follower {config.follower_account_id}")
                    continue
                
                # Place the trade on follower account
                try:
                    logger.info(f"🚀 About to place follower trade: {master_trade.symbol} {master_trade.side} {follower_quantity}")
                    # Add detailed log before attempting trade
                    self.add_system_log("INFO", f"Attempting to copy trade: {master_trade.symbol} {master_trade.side} Qty: {follower_quantity} to follower {config.follower_account_id}", config.follower_account_id)
                    
                    success = await self.place_follower_trade(master_trade, config, follower_quantity, session)
                    if success:
                        logger.info(f"✅ Successfully placed follower trade for account {config.follower_account_id}")
                        self.add_system_log("INFO", f"✅ Successfully placed follower trade: {master_trade.symbol} {master_trade.side} Qty: {follower_quantity}", config.follower_account_id)
                    else:
                        logger.warning(f"⚠️ Follower trade was skipped for account {config.follower_account_id} (likely due to minimum notional or other validation)")
                        self.add_system_log("WARNING", f"⚠️ Follower trade skipped: {master_trade.symbol} (minimum notional or validation issue)", config.follower_account_id)
                except Exception as follower_error:
                    error_msg = f"❌ FAILED TO PLACE FOLLOWER TRADE for account {config.follower_account_id}: {follower_error}"
                    logger.error(error_msg)
                    self.add_system_log("ERROR", error_msg, config.follower_account_id)
                    import traceback
                    logger.error(f"Full error traceback: {traceback.format_exc()}")
                    # Continue with other followers instead of stopping completely
                    continue
            
            # Mark master trade as copied
            master_trade.copied_from_master = True
            session.commit()
            
        except Exception as e:
            logger.error(f"Error copying trade to followers: {e}")
            session.rollback()
    
    async def calculate_follower_quantity(self, master_trade: Trade, config: CopyTradingConfig, follower_client: BinanceClient) -> float:
        """Calculate the quantity for follower trade based on balance, risk management, and leverage"""
        try:
            session = get_session()
            follower_account = session.query(Account).filter(Account.id == config.follower_account_id).first()
            master_account = session.query(Account).filter(Account.id == master_trade.account_id).first()
            session.close()
            
            if not follower_account:
                logger.error(f"❌ Follower account {config.follower_account_id} not found in database")
                return 0
            
            if not master_account:
                logger.error(f"❌ Master account {master_trade.account_id} not found in database")
                return 0
            
            # Get current account balances
            follower_balance = await follower_client.get_balance()
            if follower_balance <= 0:
                logger.warning(f"⚠️ Could not get follower balance or balance is zero")
                return await self.calculate_fallback_quantity(master_trade, config)
            
            # Get mark price for the symbol
            try:
                mark_price = await follower_client.get_mark_price(master_trade.symbol)
                if mark_price <= 0:
                    mark_price = master_trade.price if master_trade.price > 0 else 1.0
            except Exception:
                mark_price = master_trade.price if master_trade.price > 0 else 1.0
            
            logger.info(f"📊 Risk-based calculation starting:")
            logger.info(f"   Follower balance: ${follower_balance:.2f}")
            logger.info(f"   Follower risk%: {follower_account.risk_percentage}%")
            logger.info(f"   Follower leverage: {follower_account.leverage}x")
            logger.info(f"   Symbol price: ${mark_price:.4f}")
            
            # OPTION 1: Risk-Based Position Sizing (Recommended)
            if follower_account.risk_percentage > 0:
                quantity = await self.calculate_risk_based_quantity(
                    follower_balance, follower_account, mark_price, master_trade, config
                )
                logger.info(f"📊 Using risk-based sizing: {quantity}")
            else:
                # OPTION 2: Fallback to balance-proportional sizing
                quantity = await self.calculate_balance_proportional_quantity(
                    follower_balance, mark_price, master_trade, config
                )
                logger.info(f"📊 Using balance-proportional sizing: {quantity}")
            
            # Apply copy percentage as final scaling factor
            quantity *= (config.copy_percentage / 100.0)
            logger.info(f"📊 After copy percentage {config.copy_percentage}%: {quantity}")
            
            # Apply risk multiplier
            if config.risk_multiplier != 1.0:
                quantity *= config.risk_multiplier
                logger.info(f"📊 After risk multiplier {config.risk_multiplier}: {quantity}")
            
            # Safety checks and limits
            quantity = await self.apply_safety_limits(quantity, follower_balance, mark_price, follower_account, master_trade)
            
            # Fix floating point precision
            quantity = round(quantity, 8)
            
            # Final validation
            if quantity <= 0:
                logger.warning(f"⚠️ Calculated quantity is zero or negative: {quantity}")
                return 0
            
            # Calculate notional value for logging
            notional_value = quantity * mark_price
            risk_percentage_actual = (notional_value / follower_balance) * 100
            
            logger.info(f"📊 FINAL CALCULATION RESULT:")
            logger.info(f"   Quantity: {quantity}")
            logger.info(f"   Notional value: ${notional_value:.2f}")
            logger.info(f"   Risk percentage: {risk_percentage_actual:.2f}%")
            logger.info(f"   Master quantity: {master_trade.quantity} (for comparison)")
            
            return quantity
            
        except Exception as e:
            logger.error(f"Error calculating follower quantity: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return await self.calculate_fallback_quantity(master_trade, config)
    
    async def calculate_risk_based_quantity(self, follower_balance: float, follower_account, mark_price: float, master_trade: Trade, config: CopyTradingConfig) -> float:
        """Calculate position size based on account risk percentage and leverage"""
        try:
            # Calculate the maximum risk amount per trade
            risk_amount = follower_balance * (follower_account.risk_percentage / 100.0)
            
            # With leverage, we can control more value than our risk amount
            # Position Value = Risk Amount × Leverage
            max_position_value = risk_amount * follower_account.leverage
            
            # Calculate quantity based on position value
            quantity = max_position_value / mark_price
            
            logger.info(f"📊 Risk-based calculation:")
            logger.info(f"   Risk amount: ${risk_amount:.2f} ({follower_account.risk_percentage}% of ${follower_balance:.2f})")
            logger.info(f"   Max position value: ${max_position_value:.2f} (risk × {follower_account.leverage}x leverage)")
            logger.info(f"   Calculated quantity: {quantity}")
            
            return quantity
            
        except Exception as e:
            logger.error(f"Error in risk-based calculation: {e}")
            return 0
    
    async def calculate_balance_proportional_quantity(self, follower_balance: float, mark_price: float, master_trade: Trade, config: CopyTradingConfig) -> float:
        """Calculate position size proportional to account balance"""
        try:
            # Use a conservative approach: risk 2% of balance per trade
            conservative_risk_percentage = 2.0
            risk_amount = follower_balance * (conservative_risk_percentage / 100.0)
            
            # Calculate quantity based on risk amount
            quantity = risk_amount / mark_price
            
            logger.info(f"📊 Balance-proportional calculation:")
            logger.info(f"   Conservative risk: ${risk_amount:.2f} ({conservative_risk_percentage}% of ${follower_balance:.2f})")
            logger.info(f"   Calculated quantity: {quantity}")
            
            return quantity
            
        except Exception as e:
            logger.error(f"Error in balance-proportional calculation: {e}")
            return 0
    
    async def apply_safety_limits(self, quantity: float, follower_balance: float, mark_price: float, follower_account, master_trade: Trade) -> float:
        """Apply safety limits to prevent excessive risk"""
        try:
            original_quantity = quantity
            
            # 1. Maximum position size: 20% of balance (conservative limit)
            max_position_value = follower_balance * 0.20  # 20% max
            max_quantity_by_balance = max_position_value / mark_price
            
            if quantity > max_quantity_by_balance:
                logger.warning(f"⚠️ Quantity reduced by balance limit: {quantity} -> {max_quantity_by_balance}")
                quantity = max_quantity_by_balance
            
            # 2. Maximum leverage check: prevent over-leveraging
            position_value = quantity * mark_price
            effective_leverage = position_value / follower_balance
            max_allowed_leverage = follower_account.leverage * 0.8  # Use 80% of max leverage
            
            if effective_leverage > max_allowed_leverage:
                safe_quantity = (follower_balance * max_allowed_leverage) / mark_price
                logger.warning(f"⚠️ Quantity reduced by leverage limit: {quantity} -> {safe_quantity}")
                logger.warning(f"   Effective leverage would be {effective_leverage:.1f}x, max allowed: {max_allowed_leverage:.1f}x")
                quantity = safe_quantity
            
            # 3. Minimum position size (Binance minimum notional: $5)
            min_notional = 5.0
            min_quantity = min_notional / mark_price
            
            if quantity < min_quantity:
                logger.warning(f"⚠️ Quantity below minimum notional: {quantity} -> {min_quantity}")
                quantity = min_quantity
            
            # 4. Maximum single trade risk: 10% of balance
            max_risk_value = follower_balance * 0.10  # 10% max risk per trade
            max_quantity_by_risk = max_risk_value / mark_price
            
            if quantity > max_quantity_by_risk:
                logger.warning(f"⚠️ Quantity reduced by risk limit: {quantity} -> {max_quantity_by_risk}")
                quantity = max_quantity_by_risk
            
            if quantity != original_quantity:
                logger.info(f"📊 Safety limits applied: {original_quantity:.8f} -> {quantity:.8f}")
            
            return quantity
            
        except Exception as e:
            logger.error(f"Error applying safety limits: {e}")
            return quantity
    
    async def calculate_fallback_quantity(self, master_trade: Trade, config: CopyTradingConfig) -> float:
        """Fallback calculation when balance-based sizing fails"""
        try:
            # Conservative fallback: use copy percentage with reduced scaling
            fallback_quantity = master_trade.quantity * (config.copy_percentage / 100.0) * 0.5  # 50% reduction for safety
            fallback_quantity = round(fallback_quantity, 8)
            
            logger.warning(f"⚠️ Using fallback quantity calculation: {fallback_quantity}")
            logger.warning(f"   Master quantity: {master_trade.quantity}, Copy%: {config.copy_percentage}%, Safety reduction: 50%")
            
            return fallback_quantity
            
        except Exception as e:
            logger.error(f"Error in fallback calculation: {e}")
            return 0
    
    async def get_portfolio_risk(self, follower_client: BinanceClient, follower_balance: float) -> float:
        """Calculate current portfolio risk percentage"""
        try:
            positions = await follower_client.get_positions()
            total_position_value = 0
            
            for position in positions:
                if position.get('size', 0) != 0:  # Only count open positions
                    position_value = abs(float(position.get('size', 0))) * float(position.get('markPrice', 0))
                    total_position_value += position_value
            
            portfolio_risk_percentage = (total_position_value / follower_balance) * 100 if follower_balance > 0 else 0
            
            logger.info(f"📊 Portfolio risk: ${total_position_value:.2f} ({portfolio_risk_percentage:.1f}% of balance)")
            
            return portfolio_risk_percentage
            
        except Exception as e:
            logger.warning(f"⚠️ Could not calculate portfolio risk: {e}")
            return 0
    
    async def place_follower_trade(self, master_trade: Trade, config: CopyTradingConfig, quantity: float, session: Session):
        """Place the trade on follower account"""
        try:
            logger.info(f"🔄 Starting follower trade placement process...")
            logger.info(f"📋 Master trade details:")
            logger.info(f"   Symbol: {master_trade.symbol}")
            logger.info(f"   Side: {master_trade.side}")
            logger.info(f"   Order Type: {master_trade.order_type}")
            logger.info(f"   Master Quantity: {master_trade.quantity}")
            logger.info(f"   Follower Quantity: {quantity}")
            logger.info(f"   Price: {master_trade.price}")
            logger.info(f"   Stop Price: {master_trade.stop_price}")
            logger.info(f"   Take Profit Price: {master_trade.take_profit_price}")
            logger.info(f"📋 Copy config: {config.follower_account_id} -> {config.copy_percentage}%")
            
            follower_client = self.follower_clients[config.follower_account_id]
            
            # Set leverage and position mode if needed (handle subaccount limitations)
            follower_account = session.query(Account).filter(Account.id == config.follower_account_id).first()
            try:
                await follower_client.set_leverage(master_trade.symbol, follower_account.leverage)
                logger.info(f"✅ Set leverage {follower_account.leverage}x for {master_trade.symbol}")
            except Exception as leverage_error:
                logger.warning(f"⚠️ Could not set leverage for subaccount (normal for limited permissions): {leverage_error}")
                # Continue without setting leverage - subaccounts often can't change leverage
            
            # Ensure position mode is set to One-way (default) to avoid position side conflicts
            try:
                current_mode = await follower_client.get_position_mode()
                if current_mode:  # If in hedge mode, try to switch to one-way mode
                    logger.info(f"📊 Follower account is in hedge mode, attempting to switch to one-way mode")
                    await follower_client.set_position_mode(dual_side_position=False)
                else:
                    logger.info(f"📊 Follower account is already in one-way mode")
            except Exception as mode_error:
                logger.warning(f"⚠️ Could not check/set position mode (may have open positions or limited permissions): {mode_error}")
                # Continue - this is not critical for trading
            
            # Adjust quantity precision for symbol requirements
            try:
                adjusted_quantity = await follower_client.adjust_quantity_precision(master_trade.symbol, quantity)
                if adjusted_quantity != quantity:
                    logger.info(f"📏 Quantity adjusted for precision: {quantity} -> {adjusted_quantity}")
                    quantity = adjusted_quantity
                
                # Final safety check: ensure no floating point precision issues remain
                quantity = round(quantity, 8)  # Round to 8 decimal places as final safety check
                
            except Exception as precision_error:
                logger.warning(f"⚠️ Could not adjust quantity precision: {precision_error}")
                # Fallback: round to 1 decimal place as safety measure
                quantity = round(quantity, 1)
                logger.info(f"📏 Applied safety precision rounding: -> {quantity}")
            
            # Validate minimum notional value (Binance requires $5 minimum)
            notional_value = quantity * master_trade.price if master_trade.price else 0
            min_notional = 5.0  # $5 minimum for Binance futures
            
            if notional_value < min_notional and master_trade.price > 0:
                logger.warning(f"⚠️ Order value ${notional_value:.2f} is below minimum ${min_notional}")
                logger.warning(f"📊 Quantity: {quantity}, Price: {master_trade.price}")
                
                # Try to adjust quantity to meet minimum notional requirement
                if master_trade.price > 0:
                    min_quantity = min_notional / master_trade.price
                    # Round up to next valid quantity step
                    try:
                        adjusted_min_quantity = await follower_client.adjust_quantity_precision(master_trade.symbol, min_quantity)
                        if adjusted_min_quantity > quantity:
                            logger.info(f"🔧 Adjusting quantity to meet minimum notional: {quantity} -> {adjusted_min_quantity}")
                            quantity = adjusted_min_quantity
                            notional_value = quantity * master_trade.price
                            logger.info(f"✅ New order value: ${notional_value:.2f}")
                        else:
                            logger.warning(f"⚠️ Cannot adjust quantity high enough to meet minimum notional")
                            logger.warning(f"⚠️ Skipping this trade (too small)")
                            return False
                    except Exception as adjust_error:
                        logger.warning(f"⚠️ Failed to adjust quantity for minimum notional: {adjust_error}")
                        logger.warning(f"⚠️ Skipping this trade (too small)")
                        return False
                else:
                    logger.warning(f"⚠️ Cannot validate notional value (price is 0), proceeding with caution")
            
            # Validate trade parameters before placing order
            logger.info(f"🎯 Placing follower order: {master_trade.symbol} {master_trade.side} {quantity} ({master_trade.order_type})")
            if notional_value > 0:
                logger.info(f"💰 Order notional value: ${notional_value:.2f}")
            
            # Place the order based on order type
            logger.info(f"🔄 Attempting to place {master_trade.order_type} order...")
            order = None
            
            try:
                if master_trade.order_type == "MARKET":
                    logger.info(f"📊 Placing MARKET order: {master_trade.symbol} {master_trade.side} {quantity}")
                    order = await follower_client.place_market_order(
                        master_trade.symbol,
                        master_trade.side,
                        quantity
                    )
                elif master_trade.order_type == "LIMIT":
                    # Validate price for LIMIT orders
                    if not master_trade.price or master_trade.price <= 0:
                        logger.error(f"❌ Invalid price for LIMIT order: {master_trade.price}")
                        logger.error(f"❌ LIMIT orders require a valid positive price")
                        return False
                    
                    logger.info(f"📊 Placing LIMIT order: {master_trade.symbol} {master_trade.side} {quantity} @ {master_trade.price}")
                    order = await follower_client.place_limit_order(
                        master_trade.symbol,
                        master_trade.side,
                        quantity,
                        master_trade.price
                    )
                elif master_trade.order_type == "STOP_MARKET":
                    logger.info(f"📊 Placing STOP_MARKET order: {master_trade.symbol} {master_trade.side} {quantity} @ {master_trade.stop_price}")
                    order = await follower_client.place_stop_market_order(
                        master_trade.symbol,
                        master_trade.side,
                        quantity,
                        master_trade.stop_price
                    )
                elif master_trade.order_type == "TAKE_PROFIT_MARKET":
                    logger.info(f"📊 Placing TAKE_PROFIT_MARKET order: {master_trade.symbol} {master_trade.side} {quantity} @ {master_trade.take_profit_price}")
                    order = await follower_client.place_take_profit_market_order(
                        master_trade.symbol,
                        master_trade.side,
                        quantity,
                        master_trade.take_profit_price
                    )
                else:
                    logger.warning(f"❌ Unsupported order type: {master_trade.order_type}")
                    return False
                
                if order:
                    logger.info(f"✅ Follower order placed successfully!")
                    logger.info(f"📋 Order details: Order ID {order.get('orderId', 'Unknown')}")
                    logger.info(f"📋 Order status: {order.get('status', 'Unknown')}")
                    logger.info(f"📋 Full order response: {order}")
                else:
                    logger.error(f"❌ Order placement returned None - this should not happen!")
                    return False
                    
            except Exception as order_error:
                logger.error(f"❌ CRITICAL: Order placement failed with exception: {order_error}")
                logger.error(f"❌ Order type: {master_trade.order_type}")
                logger.error(f"❌ Symbol: {master_trade.symbol}")
                logger.error(f"❌ Side: {master_trade.side}")
                logger.error(f"❌ Quantity: {quantity}")
                logger.error(f"❌ Price: {master_trade.price}")
                raise order_error  # Re-raise to be caught by outer exception handler
            
            # Save follower trade to database
            follower_trade = Trade(
                account_id=config.follower_account_id,
                symbol=master_trade.symbol,
                side=master_trade.side,
                order_type=master_trade.order_type,
                quantity=quantity,
                price=master_trade.price,
                stop_price=master_trade.stop_price,
                take_profit_price=master_trade.take_profit_price,
                status="PENDING",
                binance_order_id=order.get('orderId'),
                copied_from_master=True,
                master_trade_id=master_trade.id
            )
            
            session.add(follower_trade)
            session.commit()
            
            # Log the copy trade with more details
            success_message = f"✅ Successfully copied trade: {master_trade.symbol} {master_trade.side} - Master: {master_trade.quantity}, Follower: {follower_trade.quantity} (Copy%: {config.copy_percentage}%)"
            log = SystemLog(
                level="INFO",
                message=success_message,
                account_id=config.follower_account_id,
                trade_id=follower_trade.id
            )
            session.add(log)
            session.commit()
            
            # Also use our centralized logging function
            self.add_system_log("INFO", f"Trade copied: {master_trade.symbol} {master_trade.side} - Master: {master_trade.quantity}, Follower: {follower_trade.quantity}", config.follower_account_id, follower_trade.id)
            
            logger.info(f"Successfully copied trade to follower {config.follower_account_id}")
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error placing follower trade: {e}")
            
            # Provide specific guidance based on error type
            if "code=-4061" in error_msg:
                logger.error("❌ Position side mismatch error - this should be fixed with the recent updates")
                logger.info("🔧 Try restarting the application to ensure the position mode fixes are active")
            elif "code=-1022" in error_msg:
                logger.error("❌ Signature validation error - check API key permissions for subaccount")
            elif "code=-2015" in error_msg:
                logger.error("❌ Permission denied - subaccount may not have futures trading permissions")
            elif "code=-2019" in error_msg:
                logger.error("❌ Margin insufficient - subaccount may not have enough balance")
            elif "code=-1013" in error_msg:
                logger.error("❌ Invalid quantity - check minimum order size requirements")
            elif "code=-4003" in error_msg:
                logger.error("❌ Quantity precision error - adjusting quantity precision")
            elif "code=-1111" in error_msg:
                logger.error("❌ PRECISION ERROR - This has been fixed!")
                logger.error(f"🔧 The quantity precision fix should prevent this error")
                logger.error(f"💡 If you still see this error, please restart the copy trading service")
                logger.error(f"📊 Problem quantity was: {quantity}")
            elif "code=-4164" in error_msg:
                notional_value = quantity * master_trade.price if master_trade.price else 0
                logger.error("❌ NOTIONAL VALUE TOO SMALL!")
                logger.error(f"📊 Order value: ${notional_value:.2f} (minimum required: $5)")
                logger.error(f"📊 Quantity: {quantity}, Price: {master_trade.price}")
                logger.error(f"💡 Solution: Increase the quantity or skip small orders")
                logger.warning(f"⚠️ Skipping this trade due to minimum notional requirement")
                # Don't rollback the session for this error - it's expected for small orders
                return False
            else:
                logger.error(f"❌ Unhandled error: {error_msg}")
            
            session.rollback()
            return False
    
    async def get_engine_status(self) -> Dict:
        """Get the current status of the copy trading engine"""
        return {
            'is_running': self.is_running,
            'master_accounts': len(self.master_clients),
            'follower_accounts': len(self.follower_clients),
            'monitoring_tasks': len(self.monitoring_tasks),
            'last_trade_checks': self.last_trade_check
        }
    
    async def add_account(self, account: Account):
        """Add a new account to the engine"""
        try:
            client = BinanceClient(
                api_key=account.api_key,
                secret_key=account.secret_key,
                testnet=Config.BINANCE_TESTNET
            )
            
            if await client.test_connection():
                if account.is_master:
                    self.master_clients[account.id] = client
                    logger.info(f"Added master account: {account.name}")
                    
                    # Start monitoring if engine is running
                    if self.is_running:
                        task = asyncio.create_task(self.monitor_master_account(account.id, client))
                        self.monitoring_tasks[account.id] = task
                        self.last_trade_check[account.id] = datetime.utcnow()
                else:
                    self.follower_clients[account.id] = client
                    logger.info(f"Added follower account: {account.name}")
            else:
                logger.error(f"Failed to connect to new account: {account.name}")
                
        except Exception as e:
            logger.error(f"Error adding account: {e}")
    
    async def is_position_closing_order(self, master_id: int, trade: Trade, session: Session) -> bool:
        """Determine if this trade is closing an existing position"""
        try:
            # Get master account client to check positions
            master_client = self.master_clients.get(master_id)
            if not master_client:
                logger.warning(f"⚠️ Master client not found for position check: {master_id}")
                return False
            
            # Get current positions from Binance API
            positions = await master_client.get_positions()
            
            # Check if there's an existing position in the opposite direction
            for position in positions:
                if position['symbol'] == trade.symbol:
                    # If we have a LONG position and the trade is SELL, it's closing
                    # If we have a SHORT position and the trade is BUY, it's closing
                    if (position['side'] == 'LONG' and trade.side == 'SELL') or \
                       (position['side'] == 'SHORT' and trade.side == 'BUY'):
                        logger.info(f"🔄 Position closing detected: {trade.symbol} {position['side']} position, {trade.side} order")
                        return True
            
            # Also check database for recent opposite trades that might have created positions
            recent_trades = session.query(Trade).filter(
                Trade.account_id == master_id,
                Trade.symbol == trade.symbol,
                Trade.status == 'FILLED',
                Trade.created_at >= datetime.utcnow() - timedelta(hours=24)  # Last 24 hours
            ).order_by(Trade.created_at.desc()).limit(10).all()
            
            # Simple heuristic: if the most recent trades were in opposite direction, this might be closing
            opposite_side = 'BUY' if trade.side == 'SELL' else 'SELL'
            recent_opposite_trades = [t for t in recent_trades if t.side == opposite_side]
            
            if recent_opposite_trades:
                total_opposite_qty = sum(t.quantity for t in recent_opposite_trades)
                same_side_trades = [t for t in recent_trades if t.side == trade.side]
                total_same_qty = sum(t.quantity for t in same_side_trades)
                
                # If we have more quantity in opposite direction, this trade is likely closing
                if total_opposite_qty > total_same_qty:
                    logger.info(f"🔄 Position closing heuristic: recent opposite trades {total_opposite_qty} > same side {total_same_qty}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error checking if order is position closing: {e}")
            return False  # Default to regular trade copying
    
    async def close_follower_positions(self, master_trade: Trade, session: Session):
        """Close corresponding positions in follower accounts"""
        try:
            logger.info(f"🔄 Closing follower positions for master trade: {master_trade.symbol} {master_trade.side}")
            
            # Get copy trading configurations for this master
            configs = session.query(CopyTradingConfig).filter(
                CopyTradingConfig.master_account_id == master_trade.account_id,
                CopyTradingConfig.is_active == True
            ).all()
            
            if not configs:
                logger.warning(f"⚠️ No copy trading configurations found for position closing")
                return
            
            logger.info(f"📋 Found {len(configs)} follower accounts to close positions")
            
            closed_count = 0
            for config in configs:
                try:
                    follower_client = self.follower_clients.get(config.follower_account_id)
                    if not follower_client:
                        logger.error(f"❌ Follower client not found for account {config.follower_account_id}")
                        continue
                    
                    # Get follower positions
                    follower_positions = await follower_client.get_positions()
                    position_to_close = None
                    
                    # Find the position that corresponds to what the master is closing
                    for pos in follower_positions:
                        if pos['symbol'] == master_trade.symbol:
                            # Master is selling (closing long) -> close follower's long position
                            # Master is buying (closing short) -> close follower's short position
                            if (master_trade.side == 'SELL' and pos['side'] == 'LONG') or \
                               (master_trade.side == 'BUY' and pos['side'] == 'SHORT'):
                                position_to_close = pos
                                break
                    
                    if position_to_close:
                        # Calculate quantity to close (proportional to copy percentage)
                        close_quantity = position_to_close['size'] * (config.copy_percentage / 100.0)
                        close_quantity = round(close_quantity, 8)  # Fix precision
                        
                        logger.info(f"🔄 Closing follower position: {config.follower_account_id} {master_trade.symbol} {position_to_close['side']} {close_quantity}")
                        
                        # Close the position
                        close_order = await follower_client.close_position(
                            master_trade.symbol, 
                            position_to_close['side'], 
                            close_quantity
                        )
                        
                        if close_order:
                            # Record the position close as a trade
                            close_side = 'SELL' if position_to_close['side'] == 'LONG' else 'BUY'
                            follower_trade = Trade(
                                account_id=config.follower_account_id,
                                symbol=master_trade.symbol,
                                side=close_side,
                                order_type='MARKET',
                                quantity=close_quantity,
                                price=0,  # Market order, price determined by market
                                status='FILLED',
                                binance_order_id=close_order.get('orderId'),
                                copied_from_master=True,
                                master_trade_id=master_trade.id
                            )
                            
                            session.add(follower_trade)
                            session.commit()
                            closed_count += 1
                            
                            logger.info(f"✅ Closed follower position: {config.follower_account_id} {master_trade.symbol}")
                            self.add_system_log("INFO", f"🔄 Position closed: {master_trade.symbol} {position_to_close['side']} {close_quantity} (master position closing)", config.follower_account_id, follower_trade.id)
                        else:
                            logger.warning(f"⚠️ Failed to close position for follower {config.follower_account_id}")
                    else:
                        logger.info(f"ℹ️ No corresponding position found to close for follower {config.follower_account_id}")
                        
                except Exception as follower_error:
                    logger.error(f"❌ Error closing position for follower {config.follower_account_id}: {follower_error}")
                    self.add_system_log("ERROR", f"❌ Error closing position: {follower_error}", config.follower_account_id)
            
            if closed_count > 0:
                logger.info(f"✅ Successfully closed positions for {closed_count}/{len(configs)} followers")
                self.add_system_log("INFO", f"🔄 Master position closing - {closed_count} follower positions closed", master_trade.account_id, master_trade.id)
            else:
                logger.warning(f"⚠️ No follower positions were closed for master position closing")
                
            # Mark master trade as copied
            master_trade.copied_from_master = True
            session.commit()
            
        except Exception as e:
            logger.error(f"❌ Error closing follower positions: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            session.rollback()
    
    async def handle_master_order_cancellation_with_trade(self, master_trade: Trade, session: Session):
        """Handle cancellation of master orders using existing trade record"""
        try:
            logger.info(f"🚫 Handling master order cancellation for trade {master_trade.id}")
            
            # Find all follower trades that were copied from this master trade
            follower_trades = session.query(Trade).filter(
                Trade.master_trade_id == master_trade.id,
                Trade.copied_from_master == True,
                Trade.status.in_(['PENDING', 'PARTIALLY_FILLED'])  # Only cancel active orders
            ).all()
            
            if not follower_trades:
                logger.info(f"ℹ️ No active follower trades found for cancelled master trade {master_trade.id}")
                return
            
            logger.info(f"🔍 Found {len(follower_trades)} follower trades to cancel")
            
            # Cancel each follower trade
            cancelled_count = 0
            for follower_trade in follower_trades:
                try:
                    follower_client = self.follower_clients.get(follower_trade.account_id)
                    if not follower_client:
                        logger.error(f"❌ Follower client not found for account {follower_trade.account_id}")
                        continue
                    
                    if follower_trade.binance_order_id:
                        # Determine order type for enhanced logging
                        order_type_desc = "order"
                        if follower_trade.order_type == "STOP_MARKET":
                            order_type_desc = "stop-loss order"
                        elif follower_trade.order_type == "TAKE_PROFIT_MARKET":
                            order_type_desc = "take-profit order"
                        elif follower_trade.order_type == "LIMIT":
                            order_type_desc = "limit order"
                        elif follower_trade.order_type == "MARKET":
                            order_type_desc = "market order"
                        
                        logger.info(f"🚫 Cancelling follower {order_type_desc}: {follower_trade.symbol} {follower_trade.side} for account {follower_trade.account_id}")
                        
                        # Cancel the order on Binance
                        success = await follower_client.cancel_order(
                            follower_trade.symbol, 
                            str(follower_trade.binance_order_id)
                        )
                        
                        if success:
                            # Update follower trade status
                            follower_trade.status = 'CANCELLED'
                            session.commit()
                            cancelled_count += 1
                            
                            logger.info(f"✅ Cancelled follower {order_type_desc} {follower_trade.binance_order_id} for account {follower_trade.account_id}")
                            
                            # Enhanced logging for different order types
                            if follower_trade.order_type in ["STOP_MARKET", "TAKE_PROFIT_MARKET"]:
                                self.add_system_log("INFO", f"🚫 Cancelled follower {order_type_desc}: {follower_trade.symbol} (master {order_type_desc} cancelled)", follower_trade.account_id, follower_trade.id)
                            else:
                                self.add_system_log("INFO", f"🚫 Cancelled follower {order_type_desc}: {follower_trade.symbol} (master order cancelled)", follower_trade.account_id, follower_trade.id)
                        else:
                            logger.error(f"❌ Failed to cancel follower {order_type_desc} {follower_trade.binance_order_id} for account {follower_trade.account_id}")
                            self.add_system_log("ERROR", f"❌ Failed to cancel follower {order_type_desc}: {follower_trade.symbol}", follower_trade.account_id, follower_trade.id)
                    else:
                        logger.warning(f"⚠️ No Binance order ID found for follower trade {follower_trade.id}")
                        
                except Exception as cancel_error:
                    logger.error(f"❌ Error cancelling follower trade {follower_trade.id}: {cancel_error}")
                    self.add_system_log("ERROR", f"❌ Error cancelling follower order: {cancel_error}", follower_trade.account_id, follower_trade.id)
            
            if cancelled_count > 0:
                logger.info(f"✅ Successfully cancelled {cancelled_count}/{len(follower_trades)} follower orders")
                self.add_system_log("INFO", f"🚫 Master order cancelled - {cancelled_count} follower orders cancelled", master_trade.account_id, master_trade.id)
            else:
                logger.warning(f"⚠️ No follower orders were successfully cancelled for master trade {master_trade.id}")
                
        except Exception as e:
            logger.error(f"❌ Error handling master order cancellation with trade: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            session.rollback()

    async def handle_cancellation_by_order_details(self, master_id: int, order: dict, session: Session):
        """Handle cancellation by searching for follower trades using order details"""
        try:
            order_symbol = order.get('symbol')
            order_side = order.get('side')
            order_time = datetime.fromtimestamp(order.get('time', order.get('updateTime', 0)) / 1000)
            order_quantity = float(order.get('origQty', 0))
            
            logger.info(f"🔍 Searching for follower trades to cancel: {order_symbol} {order_side} {order_quantity}")
            
            # Search for recent follower trades that match this order criteria
            # Look for orders placed within a reasonable time window (last 30 minutes)
            time_window = order_time - timedelta(minutes=30), order_time + timedelta(minutes=30)
            
            follower_trades = session.query(Trade).filter(
                Trade.symbol == order_symbol,
                Trade.side == order_side,
                Trade.copied_from_master == True,
                Trade.status.in_(['PENDING', 'PARTIALLY_FILLED']),  # Only active orders
                Trade.created_at >= time_window[0],
                Trade.created_at <= time_window[1]
            ).all()
            
            logger.info(f"🔍 Found {len(follower_trades)} potential follower trades to cancel")
            
            # Get copy trading configurations for this master to filter relevant followers
            configs = session.query(CopyTradingConfig).filter(
                CopyTradingConfig.master_account_id == master_id,
                CopyTradingConfig.is_active == True
            ).all()
            
            relevant_follower_ids = {config.follower_account_id for config in configs}
            
            # Filter trades to only those from relevant followers
            relevant_trades = [
                trade for trade in follower_trades 
                if trade.account_id in relevant_follower_ids
            ]
            
            logger.info(f"🔍 Found {len(relevant_trades)} relevant follower trades to cancel")
            
            cancelled_count = 0
            for follower_trade in relevant_trades:
                try:
                    follower_client = self.follower_clients.get(follower_trade.account_id)
                    if not follower_client:
                        logger.error(f"❌ Follower client not found for account {follower_trade.account_id}")
                        continue
                    
                    if follower_trade.binance_order_id:
                        logger.info(f"🚫 Cancelling follower order: {follower_trade.symbol} {follower_trade.side} {follower_trade.quantity} for account {follower_trade.account_id}")
                        
                        # Cancel the order on Binance
                        success = await follower_client.cancel_order(
                            follower_trade.symbol, 
                            str(follower_trade.binance_order_id)
                        )
                        
                        if success:
                            # Update follower trade status
                            follower_trade.status = 'CANCELLED'
                            session.commit()
                            cancelled_count += 1
                            
                            logger.info(f"✅ Cancelled follower order {follower_trade.binance_order_id} for account {follower_trade.account_id}")
                            self.add_system_log("INFO", f"🚫 Cancelled follower order: {follower_trade.symbol} {follower_trade.side} (master order cancelled)", follower_trade.account_id, follower_trade.id)
                        else:
                            logger.error(f"❌ Failed to cancel follower order {follower_trade.binance_order_id} for account {follower_trade.account_id}")
                            self.add_system_log("ERROR", f"❌ Failed to cancel follower order: {follower_trade.symbol}", follower_trade.account_id, follower_trade.id)
                    else:
                        logger.warning(f"⚠️ No Binance order ID found for follower trade {follower_trade.id}")
                        
                except Exception as cancel_error:
                    logger.error(f"❌ Error cancelling follower trade {follower_trade.id}: {cancel_error}")
                    self.add_system_log("ERROR", f"❌ Error cancelling follower order: {cancel_error}", follower_trade.account_id, follower_trade.id)
            
            if cancelled_count > 0:
                logger.info(f"✅ Successfully cancelled {cancelled_count} follower orders by order details")
                self.add_system_log("INFO", f"🚫 Master order cancelled - {cancelled_count} follower orders cancelled by details search", master_id)
            else:
                logger.info(f"ℹ️ No follower orders found to cancel for master order cancellation")
                
        except Exception as e:
            logger.error(f"❌ Error handling cancellation by order details: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            session.rollback()

    async def handle_master_order_cancellation(self, master_id: int, master_order_id: str, session: Session):
        """Handle cancellation of master orders by cancelling corresponding follower orders (Legacy method)"""
        try:
            logger.info(f"🚫 Handling master order cancellation: {master_order_id}")
            
            # Find the master trade record
            master_trade = session.query(Trade).filter(
                Trade.account_id == master_id,
                Trade.binance_order_id == str(master_order_id)
            ).first()
            
            if not master_trade:
                logger.warning(f"⚠️ Master trade not found for cancelled order {master_order_id}")
                return
            
            # Update master trade status
            master_trade.status = 'CANCELLED'
            session.commit()
            
            logger.info(f"📝 Updated master trade {master_trade.id} status to CANCELLED")
            
            # Use the new method with the trade record
            await self.handle_master_order_cancellation_with_trade(master_trade, session)
            
        except Exception as e:
            logger.error(f"❌ Error handling master order cancellation: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            session.rollback()
    
    async def handle_position_closing(self, master_id: int, order: dict, session: Session):
        """Handle position closing orders (market orders that close existing positions)"""
        try:
            order_id = str(order['orderId'])
            logger.info(f"🔄 Handling position closing order: {order_id}")
            
            # Create a temporary trade object to use existing closing logic
            temp_trade = Trade(
                account_id=master_id,
                symbol=order['symbol'],
                side=order['side'],
                order_type=order['type'],
                quantity=float(order.get('executedQty', order.get('origQty', 0))),
                price=float(order.get('avgPrice', order.get('price', 0))),
                status='FILLED',
                binance_order_id=str(order['orderId']),
                copied_from_master=False
            )
            
            # Add to database
            session.add(temp_trade)
            session.commit()
            session.refresh(temp_trade)
            
            logger.info(f"✅ Created trade record {temp_trade.id} for position closing")
            
            # Check if this is a position closing order and close follower positions
            if await self.is_position_closing_order(master_id, temp_trade, session):
                logger.info(f"🔄 Confirmed position closing - closing follower positions")
                await self.close_follower_positions(temp_trade, session)
            else:
                logger.info(f"📈 Not a position closing order - copying as regular trade")
                await self.copy_trade_to_followers(temp_trade, session)
            
        except Exception as e:
            logger.error(f"❌ Error handling position closing: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            session.rollback()
    
    async def remove_account(self, account_id: int):
        """Remove an account from the engine"""
        try:
            if account_id in self.master_clients:
                # Stop monitoring task
                if account_id in self.monitoring_tasks:
                    self.monitoring_tasks[account_id].cancel()
                    del self.monitoring_tasks[account_id]
                
                # Close client
                client = self.master_clients[account_id]
                client.stop_user_socket()
                del self.master_clients[account_id]
                
                logger.info(f"Removed master account: {account_id}")
                
            elif account_id in self.follower_clients:
                # Close client
                client = self.follower_clients[account_id]
                client.stop_user_socket()
                del self.follower_clients[account_id]
                
                logger.info(f"Removed follower account: {account_id}")
                
        except Exception as e:
            logger.error(f"Error removing account: {e}")

# Global instance
copy_trading_engine = CopyTradingEngine()
