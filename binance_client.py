import asyncio
import json
import time
from typing import Dict, List, Optional, Tuple
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
import websockets
import logging
from config import Config

logger = logging.getLogger(__name__)

class BinanceClient:
    def __init__(self, api_key: str, secret_key: str, testnet: bool = False):
        self.api_key = api_key
        self.secret_key = secret_key
        self.testnet = testnet
        
        # Initialize Binance client
        if testnet:
            # Enable testnet mode and force USD-M Futures endpoints
            self.client = Client(api_key, secret_key, testnet=True)
            try:
                # Ensure python-binance uses Futures TESTNET REST base
                # USD-M Futures (fapi)
                self.client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
                # Optional: Futures data endpoint
                if hasattr(self.client, "FUTURES_DATA_URL"):
                    self.client.FUTURES_DATA_URL = "https://testnet.binancefuture.com/futures/data"
                # Optional: COIN-M Futures (not used here, but set to testnet just in case)
                if hasattr(self.client, "FUTURES_COIN_URL"):
                    self.client.FUTURES_COIN_URL = "https://testnet.binancefuture.com/dapi"
            except Exception:
                pass
            self.base_url = "https://testnet.binancefuture.com"
        else:
            # Mainnet defaults are already USD-M Futures (fapi) aware in python-binance
            self.client = Client(api_key, secret_key)
            self.base_url = "https://fapi.binance.com"
        
        self.ws_connections = {}
        self.ws_tasks = {}
        
    async def test_connection(self) -> bool:
        """Test API connection"""
        try:
            account = self.client.futures_account()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    async def get_account_info(self) -> Dict:
        """Get account information"""
        try:
            account = self.client.futures_account()
            return {
                'total_wallet_balance': float(account['totalWalletBalance']),
                'total_unrealized_profit': float(account['totalUnrealizedProfit']),
                'total_margin_balance': float(account['totalMarginBalance']),
                'available_balance': float(account['availableBalance']),
                'positions': account['positions']
            }
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise
    
    async def get_positions(self) -> List[Dict]:
        """Get current positions"""
        try:
            positions = self.client.futures_position_information()
            return [
                {
                    'symbol': pos['symbol'],
                    'side': 'LONG' if float(pos['positionAmt']) > 0 else 'SHORT',
                    'size': abs(float(pos['positionAmt'])),
                    'entry_price': float(pos['entryPrice']),
                    'mark_price': float(pos['markPrice']),
                    'unrealized_pnl': float(pos['unRealizedProfit']),
                    'leverage': int(pos['leverage'])
                }
                for pos in positions if float(pos['positionAmt']) != 0
            ]
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            raise
    
    async def get_balance(self) -> float:
        """Get available balance"""
        try:
            account = self.client.futures_account()
            return float(account['availableBalance'])
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise
    
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol"""
        try:
            result = self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"Leverage set to {leverage}x for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to set leverage: {e}")
            return False
    
    async def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place a market order"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            logger.info(f"Market order placed: {symbol} {side} {quantity}")
            return order
        except BinanceOrderException as e:
            logger.error(f"Order placement failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error placing order: {e}")
            raise
    
    async def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Dict:
        """Place a limit order"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='LIMIT',
                timeInForce='GTC',
                quantity=quantity,
                price=price
            )
            logger.info(f"Limit order placed: {symbol} {side} {quantity} @ {price}")
            return order
        except BinanceOrderException as e:
            logger.error(f"Order placement failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error placing order: {e}")
            raise
    
    async def place_stop_market_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict:
        """Place a stop market order"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='STOP_MARKET',
                quantity=quantity,
                stopPrice=stop_price
            )
            logger.info(f"Stop market order placed: {symbol} {side} {quantity} @ {stop_price}")
            return order
        except BinanceOrderException as e:
            logger.error(f"Order placement failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error placing order: {e}")
            raise
    
    async def place_take_profit_market_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict:
        """Place a take profit market order"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='TAKE_PROFIT_MARKET',
                quantity=quantity,
                stopPrice=stop_price
            )
            logger.info(f"Take profit market order placed: {symbol} {side} {quantity} @ {stop_price}")
            return order
        except BinanceOrderException as e:
            logger.error(f"Order placement failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error placing order: {e}")
            raise
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order"""
        try:
            result = self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"Order cancelled: {symbol} {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False
    
    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        """Get order status"""
        try:
            order = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            return order
        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            raise
    
    async def get_symbol_info(self, symbol: str) -> Dict:
        """Get symbol information"""
        try:
            info = self.client.futures_exchange_info()
            for symbol_info in info['symbols']:
                if symbol_info['symbol'] == symbol:
                    return symbol_info
            return None
        except Exception as e:
            logger.error(f"Failed to get symbol info: {e}")
            raise
    
    async def get_mark_price(self, symbol: str) -> float:
        """Get current mark price"""
        try:
            price = self.client.futures_mark_price(symbol=symbol)
            return float(price['markPrice'])
        except Exception as e:
            logger.error(f"Failed to get mark price: {e}")
            raise
    
    async def calculate_position_size(self, symbol: str, risk_amount: float, leverage: int) -> float:
        """Calculate position size based on risk amount and leverage"""
        try:
            mark_price = await self.get_mark_price(symbol)
            position_value = risk_amount * leverage
            quantity = position_value / mark_price
            
            # Get symbol info for quantity precision
            symbol_info = await self.get_symbol_info(symbol)
            if symbol_info:
                lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                if lot_size_filter:
                    step_size = float(lot_size_filter['stepSize'])
                    quantity = round(quantity / step_size) * step_size
            
            return quantity
        except Exception as e:
            logger.error(f"Failed to calculate position size: {e}")
            raise
    
    async def start_user_socket(self, callback):
        """Start user data stream using websockets"""
        try:
            # Get listen key for user data stream
            listen_key = self.client.futures_stream_get_listen_key()
            
            # Create WebSocket connection
            ws_url = f"wss://fstream.binance.com/ws/{listen_key}"
            if self.testnet:
                ws_url = f"wss://stream.binancefuture.com/ws/{listen_key}"
            
            async def websocket_handler():
                try:
                    async with websockets.connect(ws_url) as websocket:
                        self.ws_connections['user_data'] = websocket
                        logger.info("User data stream started")
                        
                        while True:
                            try:
                                message = await websocket.recv()
                                data = json.loads(message)
                                await callback(data)
                            except websockets.exceptions.ConnectionClosed:
                                logger.warning("WebSocket connection closed, attempting to reconnect...")
                                break
                            except Exception as e:
                                logger.error(f"Error processing WebSocket message: {e}")
                                
                except Exception as e:
                    logger.error(f"WebSocket connection error: {e}")
            
            # Start WebSocket task
            task = asyncio.create_task(websocket_handler())
            self.ws_tasks['user_data'] = task
            return task
            
        except Exception as e:
            logger.error(f"Failed to start user socket: {e}")
            raise
    
    async def stop_user_socket(self):
        """Stop user data stream"""
        try:
            if 'user_data' in self.ws_tasks:
                task = self.ws_tasks['user_data']
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                del self.ws_tasks['user_data']
                
            if 'user_data' in self.ws_connections:
                websocket = self.ws_connections['user_data']
                await websocket.close()
                del self.ws_connections['user_data']
                
            logger.info("User data stream stopped")
        except Exception as e:
            logger.error(f"Failed to stop user socket: {e}")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop_user_socket()
