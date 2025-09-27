# trade_logger.py

import csv
import os
import time
from threading import Lock
from typing import Any, Dict, List

from data_models import TradeLogData

class TradeLogger:
    """Handles writing trade and scan data to CSV files in a thread-safe manner."""
    TRADE_LOG_FILE = 'trades.csv'
    SCAN_LOG_FILE = 'scans.csv'
    
    TRADE_LOG_HEADER = [
        'session_id', 'timestamp', 'symbol', 'buy_exchange', 'sell_exchange', 'buy_price', 
        'sell_price', 'amount', 'net_profit_usd', 'running_profit_usd', 
        'latency_ms', 'fees_paid', 'fill_ratio', 'status'
    ]
    # --- NEW, DETAILED SCAN HEADER ---
    SCAN_LOG_HEADER = [
        'timestamp', 'symbol', 'exchange', 'bid', 'ask'
    ]

    def __init__(self):
        self._lock = Lock()
        self._initialize_files()

    def _initialize_files(self):
        """Create CSV files with headers if they don't exist."""
        with self._lock:
            if not os.path.exists(self.TRADE_LOG_FILE):
                with open(self.TRADE_LOG_FILE, 'w', newline='') as f:
                    csv.writer(f).writerow(self.TRADE_LOG_HEADER)
            
            # Note: If you change the scan format, it's best to delete the old scans.csv
            if not os.path.exists(self.SCAN_LOG_FILE):
                with open(self.SCAN_LOG_FILE, 'w', newline='') as f:
                    csv.writer(f).writerow(self.SCAN_LOG_HEADER)
    
    def log_trade(self, log_data: TradeLogData):
        """Appends a single trade record to the trades CSV file."""
        with self._lock:
            with open(self.TRADE_LOG_FILE, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.TRADE_LOG_HEADER)
                writer.writerow(log_data.to_dict())

    def log_scan_data(self, symbol: str, prices: Dict[str, Any]):
        """
        Appends multiple rows for a single market scan, one for each exchange.
        """
        timestamp = int(time.time())
        rows_to_write = []
        for exchange, data in prices.items():
            if data.get('bid') is not None and data.get('ask') is not None:
                rows_to_write.append({
                    'timestamp': timestamp,
                    'symbol': symbol,
                    'exchange': exchange,
                    'bid': data['bid'],
                    'ask': data['ask']
                })
        
        if rows_to_write:
            with self._lock:
                with open(self.SCAN_LOG_FILE, 'a', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=self.SCAN_LOG_HEADER)
                    writer.writerows(rows_to_write)