# logging_config.py

import logging
import json
from logging.handlers import RotatingFileHandler

def setup_custom_log_levels():
    """
    Adds custom TRADE and SUCCESS log levels and methods to Python's logging.
    This function is designed to be called by both the main app and the test suite.
    """
    # --- Custom Log Levels ---
    TRADE = 25
    SUCCESS = 26
    
    # Check if levels are already added to avoid errors on re-import
    if not hasattr(logging, 'TRADE'):
        logging.addLevelName(TRADE, "TRADE")
        logging.TRADE = TRADE
    
    if not hasattr(logging, 'SUCCESS'):
        logging.addLevelName(SUCCESS, "SUCCESS")
        logging.SUCCESS = SUCCESS

    # --- Custom Logger Methods ---
    def trade(self, message, *args, **kws):
        if self.isEnabledFor(TRADE):
            self._log(TRADE, message, args, **kws)

    def success(self, message, *args, **kws):
        if self.isEnabledFor(SUCCESS):
            self._log(SUCCESS, message, args, **kws)
    
    # Add methods to the Logger class if they don't exist
    if not hasattr(logging.Logger, 'trade'):
        logging.Logger.trade = trade
    
    if not hasattr(logging.Logger, 'success'):
        logging.Logger.success = success


# --- JSON Formatter for Structured Logging ---
class JsonFormatter(logging.Formatter):
    """Formats log records into a JSON string."""
    def format(self, record):
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineNo": record.lineno
        }
        if record.exc_info:
            log_object['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(log_object)

def setup_logging():
    """Configures the root logger for dual file output (human-readable and JSON)."""
    # First, ensure custom levels and methods are defined
    setup_custom_log_levels()
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # --- Human-Readable Log File Handler ---
    log_format_string = '%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s'
    human_formatter = logging.Formatter(log_format_string)
    file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=2, mode='w')
    file_handler.setFormatter(human_formatter)
    logger.addHandler(file_handler)

    # --- Structured JSON Log File Handler ---
    json_formatter = JsonFormatter()
    json_handler = RotatingFileHandler('bot_structured.log', maxBytes=5*1024*1024, backupCount=2, mode='w')
    json_handler.setFormatter(json_formatter)
    logger.addHandler(json_handler)

    # --- Console Handler (for basic terminal output) ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(human_formatter)
    logger.addHandler(console_handler)

    logging.info("Logging configured with human-readable, JSON, and console outputs.")