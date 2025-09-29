# trade_logger.py
# crypto_arbitrage_bot/trade_logger.py

import logging
from logging.handlers import RotatingFileHandler
from data_models import Trade  # Make sure you're importing your Trade data class

class TradeLogger:
    """
    A dedicated logger to record trade executions to a structured CSV file.
    """
    def __init__(self, filename: str = "trades.csv"):
        self.filename = filename
        self.logger = self._setup_logger()
        # Write the header if the file is new/empty
        self._write_header()

    def _setup_logger(self) -> logging.Logger:
        """
        Creates and configures a logger that writes to the specified CSV file.
        """
        # Create a custom logger to avoid interfering with the main app logger
        trade_logger = logging.getLogger('trade_logger')
        trade_logger.setLevel(logging.INFO)
        
        # Prevent logs from propagating to the root logger
        trade_logger.propagate = False

        # Create a handler for the CSV file with rotation
        handler = RotatingFileHandler(self.filename, maxBytes=5*1024*1024, backupCount=2)
        
        # Create a simple formatter that just logs the raw message (our CSV line)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        
        # Add the handler to the logger if it doesn't have one already
        if not trade_logger.handlers:
            trade_logger.addHandler(handler)
            
        return trade_logger

    def _write_header(self):
        """Checks if the file is empty and writes a CSV header if needed."""
        try:
            with open(self.filename, 'r') as f:
                has_content = f.read(1)
            if not has_content:
                header = "timestamp_utc,symbol,buy_exchange,sell_exchange,buy_price,sell_price,amount,status"
                self.logger.info(header)
        except FileNotFoundError:
            # File doesn't exist, so the logger will create it and we should write the header
            header = "timestamp_utc,symbol,buy_exchange,sell_exchange,buy_price,sell_price,amount,status"
            self.logger.info(header)


    def log_trade(self, trade: Trade):
        """
        Formats a Trade object into a CSV string and logs it.
        """
        if not isinstance(trade, Trade):
            self.logger.error("log_trade received an object that was not a Trade.")
            return

        # Format the data from the Trade object into a CSV row
        log_entry = (
            f"{int(datetime.utcnow().timestamp())},"
            f"{trade.symbol},"
            f"{trade.buy_exchange},"
            f"{trade.sell_exchange},"
            f"{trade.buy_price:.8f},"
            f"{trade.sell_price:.8f},"
            f"{trade.amount:.8f},"
            f"{trade.status}"
        )
        self.logger.info(log_entry)

# You will need to add this import at the top of the file
from datetime import datetime