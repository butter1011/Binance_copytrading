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
            
            for account in accounts:
                client = BinanceClient(
                    api_key=account.api_key,
                    secret_key=account.secret_key,
                    testnet=Config.BINANCE_TESTNET
                )
                
                # Test connection
                if await client.test_connection():
                    if account.is_master:
                        self.master_clients[account.id] = client
                        logger.info(f"Master account loaded: {account.name}")
                    else:
                        self.follower_clients[account.id] = client
                        logger.info(f"Follower account loaded: {account.name}")
                else:
                    logger.error(f"Failed to connect to account: {account.name}")
                    
            session.close()
        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")
            raise
    
    async def setup_copy_trading_configs(self):
        """Setup copy trading configurations"""
        try:
            session = get_session()
            configs = session.query(CopyTradingConfig).filter(CopyTradingConfig.is_active == True).all()
            
            for config in configs:
                if config.master_account_id in self.master_clients and config.follower_account_id in self.follower_clients:
                    logger.info(f"Copy trading config loaded: Master {config.master_account_id} -> Follower {config.follower_account_id}")
                else:
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
            logger.info(f"Starting monitoring for master account {master_id}")
            
            while self.is_running:
                try:
                    # Get recent trades from master account
                    await self.check_master_trades(master_id, client)
                    
                    # Wait before next check
                    await asyncio.sleep(Config.TRADE_SYNC_DELAY)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error monitoring master account {master_id}: {e}")
                    await asyncio.sleep(5)  # Wait before retrying
                    
        except Exception as e:
            logger.error(f"Failed to monitor master account {master_id}: {e}")
    
    async def check_master_trades(self, master_id: int, client: BinanceClient):
        """Check for new trades in master account"""
        try:
            session = get_session()
            
            # Get the last trade timestamp for this master
            last_check = self.last_trade_check.get(master_id, datetime.utcnow() - timedelta(hours=1))
            
            # Get recent trades from database (you might want to implement a more sophisticated way)
            recent_trades = session.query(Trade).filter(
                Trade.account_id == master_id,
                Trade.created_at > last_check,
                Trade.copied_from_master == False
            ).all()
            
            for trade in recent_trades:
                await self.copy_trade_to_followers(trade, session)
            
            # Update last check time
            self.last_trade_check[master_id] = datetime.utcnow()
            
            session.close()
            
        except Exception as e:
            logger.error(f"Error checking master trades: {e}")
    
    async def copy_trade_to_followers(self, master_trade: Trade, session: Session):
        """Copy a master trade to all follower accounts"""
        try:
            logger.info(f"Copying trade {master_trade.id} to followers")
            
            # Get copy trading configurations for this master
            configs = session.query(CopyTradingConfig).filter(
                CopyTradingConfig.master_account_id == master_trade.account_id,
                CopyTradingConfig.is_active == True
            ).all()
            
            for config in configs:
                follower_client = self.follower_clients.get(config.follower_account_id)
                if not follower_client:
                    logger.warning(f"Follower client not found for account {config.follower_account_id}")
                    continue
                
                # Calculate position size for follower
                follower_quantity = await self.calculate_follower_quantity(
                    master_trade, config, follower_client
                )
                
                if follower_quantity <= 0:
                    logger.warning(f"Invalid quantity calculated for follower {config.follower_account_id}")
                    continue
                
                # Place the trade on follower account
                await self.place_follower_trade(master_trade, config, follower_quantity, session)
            
            # Mark master trade as copied
            master_trade.copied_from_master = True
            session.commit()
            
        except Exception as e:
            logger.error(f"Error copying trade to followers: {e}")
            session.rollback()
    
    async def calculate_follower_quantity(self, master_trade: Trade, config: CopyTradingConfig, follower_client: BinanceClient) -> float:
        """Calculate the quantity for follower trade based on risk management"""
        try:
            # Get follower account balance
            follower_balance = await follower_client.get_balance()
            
            # Calculate risk amount based on follower's risk percentage
            session = get_session()
            follower_account = session.query(Account).filter(Account.id == config.follower_account_id).first()
            session.close()
            
            if not follower_account:
                return 0
            
            risk_amount = follower_balance * (follower_account.risk_percentage / 100.0)
            risk_amount *= config.risk_multiplier
            
            # Calculate position size
            quantity = await follower_client.calculate_position_size(
                master_trade.symbol,
                risk_amount,
                follower_account.leverage
            )
            
            # Apply copy percentage
            quantity *= (config.copy_percentage / 100.0)
            
            return quantity
            
        except Exception as e:
            logger.error(f"Error calculating follower quantity: {e}")
            return 0
    
    async def place_follower_trade(self, master_trade: Trade, config: CopyTradingConfig, quantity: float, session: Session):
        """Place the trade on follower account"""
        try:
            follower_client = self.follower_clients[config.follower_account_id]
            
            # Set leverage if needed
            follower_account = session.query(Account).filter(Account.id == config.follower_account_id).first()
            await follower_client.set_leverage(master_trade.symbol, follower_account.leverage)
            
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
                return
            
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
            
        except Exception as e:
            logger.error(f"Error placing follower trade: {e}")
            session.rollback()
    
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
