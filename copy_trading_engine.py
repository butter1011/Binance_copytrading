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
        logger.info("🏗️ CopyTradingEngine initialized")
        
    async def initialize(self):
        """Initialize the copy trading engine"""
        try:
            logger.info("Initializing copy trading engine...")
            
            # Load all accounts and configurations
            await self.load_accounts()
            await self.setup_copy_trading_configs()
            
            logger.info("Copy trading engine initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize copy trading engine: {e}")
            return False
    
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
                    
                    for order in recent_orders:
                        try:
                            logger.info(f"📝 About to process order {order['orderId']} for master {master_id}")
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
                is_open_order = order_status in ['NEW', 'PARTIALLY_FILLED']
                is_recent_filled = order_status == 'FILLED' and order_time >= start_time
                
                if (order_id not in seen_orders and 
                    order['side'] in ['BUY', 'SELL'] and 
                    order_status in ['NEW', 'PARTIALLY_FILLED', 'FILLED'] and
                    (is_open_order or is_recent_filled)):
                    seen_orders.add(order_id)
                    relevant_orders.append(order)
                    status_note = "📋 OPEN" if is_open_order else "🏁 RECENT"
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
                    elif not (is_open_order or is_recent_filled):
                        timestamp_display = datetime.fromtimestamp(order_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        start_time_display = datetime.fromtimestamp(start_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        logger.debug(f"⏭️ Skipping old order: {order_id} (time: {timestamp_display}, threshold: {start_time_display})")
            
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
            
            logger.info(f"🎯 Starting to process master order: {order['symbol']} {order['side']} {original_qty} - Status: {order_status}")
            
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
            
            # Copy to followers immediately when orders are placed (NEW) or filled
            # This ensures followers trade simultaneously with master, not after completion
            if order_status in ['NEW', 'FILLED']:
                logger.info(f"🚀 Copying {order_status.lower()} order to followers immediately")
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
                    success = await self.place_follower_trade(master_trade, config, follower_quantity, session)
                    if success:
                        logger.info(f"✅ Successfully placed follower trade for account {config.follower_account_id}")
                    else:
                        logger.warning(f"⚠️ Follower trade was skipped for account {config.follower_account_id} (likely due to minimum notional or other validation)")
                except Exception as follower_error:
                    logger.error(f"❌ FAILED TO PLACE FOLLOWER TRADE for account {config.follower_account_id}: {follower_error}")
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
        """Calculate the quantity for follower trade based on risk management"""
        try:
            # Get follower account balance (handle subaccount limitations)
            follower_balance = await follower_client.get_balance()
            
            # For subaccounts with limited permissions, use a default balance if balance retrieval fails
            if follower_balance <= 0:
                logger.warning(f"⚠️ Could not get balance for follower account, using master trade quantity")
                # Use the same quantity as master trade (1:1 copy)
                return master_trade.quantity * (config.copy_percentage / 100.0)
            
            # Calculate risk amount based on follower's risk percentage
            session = get_session()
            follower_account = session.query(Account).filter(Account.id == config.follower_account_id).first()
            session.close()
            
            if not follower_account:
                logger.error(f"❌ Follower account {config.follower_account_id} not found in database")
                return 0
            
            risk_amount = follower_balance * (follower_account.risk_percentage / 100.0)
            risk_amount *= config.risk_multiplier
            
            # Calculate position size
            try:
                quantity = await follower_client.calculate_position_size(
                    master_trade.symbol,
                    risk_amount,
                    follower_account.leverage
                )
            except Exception as calc_error:
                logger.warning(f"⚠️ Position size calculation failed for subaccount: {calc_error}")
                # Fallback: Use master quantity scaled by copy percentage
                quantity = master_trade.quantity
            
            # Apply copy percentage
            quantity *= (config.copy_percentage / 100.0)
            
            # Fix floating point precision issues by rounding to a reasonable number of decimal places
            # Most crypto futures have precision of 0.1, 0.01, 0.001, etc.
            quantity = round(quantity, 8)  # Round to 8 decimal places to avoid floating point errors
            
            logger.info(f"📊 Calculated follower quantity: {quantity} (master: {master_trade.quantity}, copy%: {config.copy_percentage}%)")
            return quantity
            
        except Exception as e:
            logger.error(f"Error calculating follower quantity: {e}")
            # Fallback: Use master quantity scaled by copy percentage
            fallback_quantity = master_trade.quantity * (config.copy_percentage / 100.0)
            fallback_quantity = round(fallback_quantity, 8)  # Fix precision issues
            logger.warning(f"⚠️ Using fallback quantity: {fallback_quantity}")
            return fallback_quantity
    
    async def place_follower_trade(self, master_trade: Trade, config: CopyTradingConfig, quantity: float, session: Session):
        """Place the trade on follower account"""
        try:
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
            if master_trade.order_type == "MARKET":
                order = await follower_client.place_market_order(
                    master_trade.symbol,
                    master_trade.side,
                    quantity
                )
            elif master_trade.order_type == "LIMIT":
                order = await follower_client.place_limit_order(
                    master_trade.symbol,
                    master_trade.side,
                    quantity,
                    master_trade.price
                )
            elif master_trade.order_type == "STOP_MARKET":
                order = await follower_client.place_stop_market_order(
                    master_trade.symbol,
                    master_trade.side,
                    quantity,
                    master_trade.stop_price
                )
            elif master_trade.order_type == "TAKE_PROFIT_MARKET":
                order = await follower_client.place_take_profit_market_order(
                    master_trade.symbol,
                    master_trade.side,
                    quantity,
                    master_trade.take_profit_price
                )
            else:
                logger.warning(f"Unsupported order type: {master_trade.order_type}")
                return False
            
            logger.info(f"✅ Follower order placed successfully: Order ID {order.get('orderId', 'Unknown')}")
            
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
            
            # Log the copy trade
            log = SystemLog(
                level="INFO",
                message=f"Copied trade {master_trade.id} to follower {config.follower_account_id}",
                account_id=config.follower_account_id,
                trade_id=follower_trade.id
            )
            session.add(log)
            session.commit()
            
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
