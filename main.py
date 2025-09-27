# main.py

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import customtkinter as ctk
from tkinter import messagebox
from dotenv import load_dotenv

import logging_config # <-- IMPORT THE NEW FILE
from utils import load_config, ConfigError
from gui_application import App

def setup_simple_logging():
    """Configures a simple rotating file logger and a console logger."""
    logging_config.setup_custom_log_levels() # <-- SETUP CUSTOM LEVELS
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    log_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s')
    
    file_handler = RotatingFileHandler('bot.log', maxBytes=2*1024*1024, backupCount=2, mode='w', encoding='utf-8')
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    logging.info("Simplified logging configured.")

if __name__ == "__main__":
    load_dotenv()
    try:
        setup_simple_logging()
        config = load_config()
        
        EXCHANGES = {
            'okx': {
                "apiKey": os.getenv("OKX_TESTNET_API_KEY"), 
                "secret": os.getenv("OKX_TESTNET_SECRET"), 
                "password": os.getenv("OKX_TESTNET_PASSPHRASE")
            },
            'binance': {
                "apiKey": os.getenv("BINANCE_TESTNET_API_KEY"), 
                "secret": os.getenv("BINANCE_TESTNET_SECRET")
            },
            'bybit':{
                "apiKey": os.getenv("BYBIT_TESTNET_API_KEY"), 
                "secret": os.getenv("BYBIT_TESTNET_SECRET")
            }
        }

        all_keys_present = all(val for ex_config in EXCHANGES.values() for val in ex_config.values())
        if not all_keys_present:
            raise ConfigError("CRITICAL: One or more API keys are missing from your .env file for an active exchange.")
        
        app = App(config, EXCHANGES)
        app.mainloop()

    except ConfigError as e:
        logging.critical(f"Fatal Configuration Error: {e}", exc_info=True)
        messagebox.showerror("Fatal Configuration Error", str(e))
    except Exception as e:
        logging.critical(f"An unexpected fatal error occurred: {e}", exc_info=True)
        messagebox.showerror("Unexpected Fatal Error", f"An unrecoverable error occurred:\n\n{e}\n\nCheck bot.log for details.")