"""
Configuration management for QuAgent.
Loads and validates paper/live config from YAML files.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, validator

from app.logger import get_logger
from app.utils import get_relative_path

logger = get_logger(__name__)


class IBKRConfig(BaseModel):
    """IBKR connection configuration."""
    host: str = "127.0.0.1"
    port: int = Field(default=7497, ge=1, le=65535)
    client_id: int = Field(default=1, ge=1)
    read_only_api: bool = Field(
        default=True,
        description=(
            "When True, skip any API call that requires write access in TWS "
            "(openTrades, reqOpenOrders, cancelOrder). "
            "Set to False only when order management is fully implemented."
        ),
    )

    class Config:
        extra = "allow"


class AccountConfig(BaseModel):
    """Account configuration."""
    max_position_size: float = Field(default=10000, ge=0)
    buying_power_limit: float = Field(default=50000, ge=0)
    max_daily_loss_pct: float = Field(default=2.0, ge=0)
    max_order_notional_usd: float = Field(default=5000.0, ge=0)
    allowed_asset_classes: List[str] = Field(default_factory=lambda: ["STK"])
    require_stop_loss: bool = False
    enable_safeguards: bool = True

    class Config:
        extra = "allow"


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = Field(default="INFO")
    file: str = Field(default="logs/trading.log")
    
    @validator('level')
    def validate_level(cls, v):
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}")
        return v.upper()


class DatabaseConfig(BaseModel):
    """Database configuration."""
    url: str = Field(default="sqlite:///data/trading_log.sqlite")


class TradingConfig(BaseModel):
    """Trading parameters."""
    check_interval: int = Field(default=60, ge=1)

    class Config:
        extra = "allow"


class MarketDataConfig(BaseModel):
    """Market data configuration."""
    data_type: str = Field(
        default="delayed",
        description=(
            "IBKR market data type sent via reqMarketDataType() before each request. "
            "'live' (1) requires a paid subscription; "
            "'frozen' (2) requires subscription; "
            "'delayed' (3) is 15-20 min delayed, free, no subscription needed; "
            "'delayed_frozen' (4) is delayed data from last close, free."
        ),
    )
    stale_seconds: int = Field(
        default=300,
        ge=0,
        description="Seconds after which a cached quote should be refreshed.",
    )

    @validator("data_type")
    def validate_data_type(cls, v):
        valid = {"live", "frozen", "delayed", "delayed_frozen"}
        if v not in valid:
            raise ValueError(f"data_type must be one of {valid}, got '{v}'")
        return v

    class Config:
        extra = "allow"


class QuAgentConfig(BaseModel):
    """Main QuAgent configuration."""
    trading_mode: str = Field(default="paper")
    allow_live: bool = False
    ibkr: IBKRConfig = Field(default_factory=IBKRConfig)
    account: AccountConfig = Field(default_factory=AccountConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    
    @validator('trading_mode')
    def validate_trading_mode(cls, v):
        if v not in {"paper", "live"}:
            raise ValueError("trading_mode must be 'paper' or 'live'")
        return v
    
    @validator('allow_live')
    def validate_allow_live(cls, v, values):
        if v and values.get('trading_mode') == 'live':
            logger.warning(
                "⚠️  LIVE TRADING ENABLED - Extreme caution required. "
                "Orders will use REAL MONEY. Ensure safeguards are in place."
            )
        return v
    
    class Config:
        extra = "allow"


def load_config(config_path: Optional[str] = None) -> QuAgentConfig:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to config file (relative to project root).
                    If None, uses QUAGENT_CONFIG env var or defaults to configs/paper.yaml
    
    Returns:
        QuAgentConfig instance
    
    Raises:
        FileNotFoundError: If config file not found
        ValueError: If config validation fails
    """
    if config_path is None:
        config_path = os.getenv("QUAGENT_CONFIG", "configs/paper.yaml")
    
    config_file = get_relative_path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    
    logger.info(f"Loading config from: {config_file}")
    
    with open(config_file, 'r') as f:
        config_dict = yaml.safe_load(f) or {}
    
    try:
        config = QuAgentConfig(**config_dict)
        logger.info(f"Config loaded successfully. Mode: {config.trading_mode}")
        
        if config.trading_mode == 'live' and not config.allow_live:
            raise ValueError(
                "Live trading mode selected but allow_live=false. "
                "Set allow_live=true in config to enable live trading."
            )
        
        return config
    except Exception as e:
        logger.error(f"Config validation failed: {e}")
        raise


def get_config(config_path: Optional[str] = None) -> QuAgentConfig:
    """Get configuration (with caching)."""
    if not hasattr(get_config, '_config_cache'):
        get_config._config_cache = {}
    
    cache_key = config_path or "default"
    if cache_key not in get_config._config_cache:
        get_config._config_cache[cache_key] = load_config(config_path)
    
    return get_config._config_cache[cache_key]


def reset_config_cache():
    """Reset config cache (for testing)."""
    get_config._config_cache = {}
