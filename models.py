from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import json

Base = declarative_base()

class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    api_key = Column(String, nullable=False)
    secret_key = Column(String, nullable=False)
    is_master = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    leverage = Column(Integer, default=10)
    risk_percentage = Column(Float, default=10.0)
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    trades = relationship("Trade", back_populates="account")
    positions = relationship("Position", back_populates="account")

class Trade(Base):
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # BUY, SELL
    order_type = Column(String, nullable=False)  # MARKET, LIMIT, STOP_MARKET, TAKE_PROFIT_MARKET
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    take_profit_price = Column(Float, nullable=True)
    status = Column(String, default="PENDING")  # PENDING, FILLED, CANCELLED, REJECTED
    binance_order_id = Column(String, nullable=True)
    copied_from_master = Column(Boolean, default=False)
    master_trade_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    account = relationship("Account", back_populates="trades")

class Position(Base):
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # LONG, SHORT
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    mark_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    leverage = Column(Integer, default=10)
    is_open = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    account = relationship("Account", back_populates="positions")

class CopyTradingConfig(Base):
    __tablename__ = "copy_trading_config"
    
    id = Column(Integer, primary_key=True, index=True)
    master_account_id = Column(Integer, ForeignKey("accounts.id"))
    follower_account_id = Column(Integer, ForeignKey("accounts.id"))
    is_active = Column(Boolean, default=True)
    copy_percentage = Column(Float, default=100.0)  # Percentage of master trades to copy
    risk_multiplier = Column(Float, default=1.0)  # Risk multiplier for position sizing
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SystemLog(Base):
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, nullable=False)  # INFO, WARNING, ERROR, DEBUG
    message = Column(Text, nullable=False)
    account_id = Column(Integer, nullable=True)
    trade_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Database setup
def get_database_url():
    from config import Config
    return Config.DATABASE_URL

def create_database():
    engine = create_engine(get_database_url())
    Base.metadata.create_all(bind=engine)
    return engine

def get_session():
    engine = create_database()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()
