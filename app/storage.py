"""
Storage and database management for QuAgent.
SQLite-based trade logging.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.logger import get_logger
from app.utils import get_relative_path
from app.schemas import Order, Execution

logger = get_logger(__name__)


class Database:
    """SQLite database manager for trade logging."""
    
    def __init__(self, db_path: str = "data/trading_log.sqlite"):
        """
        Initialize database.
        
        Args:
            db_path: Path to SQLite database (relative to project root)
        """
        self.db_path = get_relative_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(str(self.db_path))
    
    def _init_schema(self) -> None:
        """Initialize database schema."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    limit_price REAL,
                    status TEXT NOT NULL,
                    filled_quantity REAL DEFAULT 0,
                    filled_price REAL,
                    submitted_at TIMESTAMP NOT NULL,
                    filled_at TIMESTAMP,
                    cancelled_at TIMESTAMP,
                    error_msg TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Executions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    order_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    commission REAL DEFAULT 0,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id)
                )
            """)
            
            # Events table (for all significant events)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL,
                    severity TEXT DEFAULT 'INFO',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            conn.close()
            logger.info(f"Database initialized at {self.db_path}")
        
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def log_order(self, order: Order) -> bool:
        """Log order to database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO orders
                (order_id, symbol, action, quantity, order_type, limit_price,
                 status, filled_quantity, filled_price, submitted_at, filled_at,
                 cancelled_at, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id,
                order.symbol,
                order.action.value,
                order.quantity,
                order.order_type.value,
                order.limit_price,
                order.status.value,
                order.filled_quantity,
                order.filled_price,
                order.submitted_at,
                order.filled_at,
                order.cancelled_at,
                order.error_msg,
            ))
            
            conn.commit()
            conn.close()
            return True
        
        except Exception as e:
            logger.error(f"Error logging order: {e}")
            return False
    
    def log_execution(self, execution: Execution) -> bool:
        """Log execution to database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO executions
                (execution_id, order_id, symbol, action, quantity, price, commission, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                execution.execution_id,
                execution.order_id,
                execution.symbol,
                execution.action.value,
                execution.quantity,
                execution.price,
                execution.commission,
                execution.timestamp,
            ))
            
            conn.commit()
            conn.close()
            return True
        
        except Exception as e:
            logger.error(f"Error logging execution: {e}")
            return False
    
    def log_event(self, event_type: str, event_data: str, severity: str = "INFO") -> bool:
        """Log event to database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO events (event_type, event_data, severity)
                VALUES (?, ?, ?)
            """, (event_type, event_data, severity))
            
            conn.commit()
            conn.close()
            return True
        
        except Exception as e:
            logger.error(f"Error logging event: {e}")
            return False
    
    def get_orders(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get orders from database."""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if symbol:
                cursor.execute(
                    "SELECT * FROM orders WHERE symbol = ? ORDER BY created_at DESC LIMIT ?",
                    (symbol, limit)
                )
            else:
                cursor.execute(
                    "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return []
    
    def get_executions(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get executions from database."""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if symbol:
                cursor.execute(
                    "SELECT * FROM executions WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                    (symbol, limit)
                )
            else:
                cursor.execute(
                    "SELECT * FROM executions ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                )
            
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error fetching executions: {e}")
            return []
