# main.py

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from tkinter import messagebox
from dotenv import load_dotenv

# --- Your Original Imports, All Restored ---
import logging_config
from utils import load_config, ConfigError
from gui_application import App

def setup_logging():
    """
    Your original logging setup function, ensuring logs go to console and file.
    """
    logging_config.setup_custom_log_levels()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if this is ever called more than once
    if logger.hasHandlers():
        logger.handlers.clear()

    log_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s')
    
    # File handler from your original code
    file_handler = RotatingFileHandler('bot.log', maxBytes=2*1024*1024, backupCount=2, mode='w', encoding='utf-8')
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)
    
    # Console handler from your original code
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    logging.info("Root logger configured.")


def get_unified_config() -> dict:
    """
    Loads configuration from both config.yaml and .env file and merges them.
    This replaces the separate config and EXCHANGES dictionaries.
    """
    load_dotenv()
    config = load_config() # Loads from config.yaml

    enabled_exchanges_str = os.getenv("ENABLED_EXCHANGES")
    if not enabled_exchanges_str:
        raise ConfigError("CRITICAL: ENABLED_EXCHANGES not found in .env file.")
    
    enabled_exchanges = [ex.strip().lower() for ex in enabled_exchanges_str.split(',')]
    
    config['exchanges'] = {}
    for ex_id in enabled_exchanges:
        api_key_var = f"{ex_id.upper()}_TESTNET_API_KEY"
        secret_var = f"{ex_id.upper()}_TESTNET_SECRET"
        api_key, api_secret = os.getenv(api_key_var), os.getenv(secret_var)
        
        if not api_key or not api_secret:
            raise ConfigError(f"CRITICAL: Missing API credentials for '{ex_id}'. Check {api_key_var} and {secret_var} in .env file.")
        
        # This structure is now used by both sync and async managers
        exchange_data = {"apiKey": api_key, "secret": api_secret}

        # Special handling for OKX passphrase, as in your original code
        if ex_id == 'okx':
            password = os.getenv("OKX_TESTNET_PASSPHRASE")
            if not password:
                 raise ConfigError("CRITICAL: OKX requires OKX_TESTNET_PASSPHRASE in .env file.")
            exchange_data["password"] = password
            
        config["exchanges"][ex_id] = exchange_data
            
    return config


if __name__ == "__main__":
    """
    The main entry point for the application, restored to your original design.
    """
    try:
        setup_logging()
        unified_config = get_unified_config()
        
        # This now correctly calls your GUI app with the single config object it expects
        app = App(unified_config)
        app.mainloop()

    except ConfigError as e:
        # Your original fatal error handling
        logging.critical(f"Fatal Configuration Error: {e}", exc_info=True)
        messagebox.showerror("Fatal Configuration Error", str(e))
    except Exception as e:
        # Your original fatal error handling
        logging.critical(f"An unexpected fatal error occurred: {e}", exc_info=True)
        messagebox.showerror("Unexpected Fatal Error", f"An unrecoverable error occurred:\n\n{e}\n\nCheck bot.log for details.")
    
# import customtkinter as ctk
# import threading
# import queue
# import asyncio
# import logging
# import sys
# from PIL import Image, ImageTk

# # --- Import Bot Components ---
# # We need to be able to launch either engine
# from bot_engine import ArbitrageBot
# from async_bot_engine import AsyncArbitrageBot

# # We also need all the managers and config loaders
# from utils import load_config, ConfigError
# from exchange_manager import ExchangeManager
# from exchange_manager_async import AsyncExchangeManager
# from risk_manager import RiskManager
# from rebalancer import Rebalancer
# from trade_logger import TradeLogger

# # --- Environment and API Key Loading ---
# import os
# from dotenv import load_dotenv

# def inject_api_keys(config: dict) -> dict:
#     """Loads API keys from .env and injects them into the config."""
#     load_dotenv()
#     enabled_exchanges_str = os.getenv("ENABLED_EXCHANGES")
#     if not enabled_exchanges_str:
#         raise ConfigError("CRITICAL: ENABLED_EXCHANGES not found in .env file.")
#     enabled_exchanges = [ex.strip().lower() for ex in enabled_exchanges_str.split(',')]
    
#     config['exchanges'] = {}
#     for ex_id in enabled_exchanges:
#         api_key_var = f"{ex_id.upper()}_TESTNET_API_KEY"
#         secret_var = f"{ex_id.upper()}_TESTNET_SECRET"
#         api_key, api_secret = os.getenv(api_key_var), os.getenv(secret_var)
        
#         if not api_key or not api_secret:
#             raise ConfigError(f"CRITICAL: Missing API credentials for '{ex_id}'. Check .env file.")
            
#         config["exchanges"][ex_id] = {"api_key": api_key, "api_secret": api_secret}
#     return config

# # --- GUI Application Class ---
# class BotApp(ctk.CTk):
#     def __init__(self):
#         super().__init__()
#         self.title("Crypto Arbitrage Bot")
#         self.geometry("800x600")
        
#         self.log_queue = queue.Queue()
#         self.bot_thread = None
#         self.bot_instance = None
        
#         # --- UI Elements ---
#         self.engine_var = ctk.StringVar(value="Async")
#         self.engine_switch = ctk.CTkSwitch(
#             self, text="Use Async Engine", variable=self.engine_var, 
#             onvalue="Async", offvalue="Regular"
#         )
#         self.engine_switch.pack(pady=10, padx=20, anchor="w")

#         self.start_button = ctk.CTkButton(self, text="Start Bot", command=self.start_bot)
#         self.start_button.pack(pady=5, padx=20, fill="x")

#         self.stop_button = ctk.CTkButton(self, text="Stop Bot", command=self.stop_bot, state="disabled")
#         self.stop_button.pack(pady=5, padx=20, fill="x")
        
#         self.log_textbox = ctk.CTkTextbox(self, state="disabled", width=760, height=450)
#         self.log_textbox.pack(pady=10, padx=20, fill="both", expand=True)

#         self.process_log_queue()

#     def start_bot(self):
#         """Starts the selected bot engine in a background thread."""
#         try:
#             config = load_config()
#             config = inject_api_keys(config)
            
#             use_async = self.engine_var.get() == "Async"
            
#             # We create a target function that will run in the thread
#             if use_async:
#                 self.log_message("Initializing ASYNC bot engine...")
#                 self.bot_instance = self._create_async_bot(config, self.log_queue)
#                 thread_target = lambda: asyncio.run(self.bot_instance.run())
#             else:
#                 self.log_message("Initializing REGULAR bot engine...")
#                 self.bot_instance = self._create_sync_bot(config, self.log_queue)
#                 thread_target = self.bot_instance.run
                
#             self.bot_thread = threading.Thread(target=thread_target, daemon=True)
#             self.bot_thread.start()
            
#             self.start_button.configure(state="disabled")
#             self.stop_button.configure(state="normal")
#             self.engine_switch.configure(state="disabled")
#             self.log_message("Bot started in a background thread.")

#         except Exception as e:
#             self.log_message(f"ERROR starting bot: {e}", "ERROR")

#     def stop_bot(self):
#         """Signals the running bot to stop."""
#         if self.bot_instance and self.bot_instance.is_running:
#             self.log_message("Sending stop signal to bot...")
#             self.bot_instance.is_running = False # Signal the bot's main loop to exit
            
#         self.start_button.configure(state="normal")
#         self.stop_button.configure(state="disabled")
#         self.engine_switch.configure(state="normal")
#         self.log_message("Bot stopped.")

#     def log_message(self, msg, level="INFO"):
#         """Thread-safe way to add a message to the log box."""
#         self.log_queue.put(f"{level}: {msg}")

#     def process_log_queue(self):
#         """Checks the queue for new log messages and updates the GUI."""
#         try:
#             while not self.log_queue.empty():
#                 message = self.log_queue.get_nowait()
#                 self.log_textbox.configure(state="normal")
#                 self.log_textbox.insert("end", message + "\n")
#                 self.log_textbox.see("end")
#                 self.log_textbox.configure(state="disabled")
#         finally:
#             self.after(200, self.process_log_queue) # Check again after 200ms

#     def _create_sync_bot(self, config, log_queue):
#         # Helper to initialize the synchronous bot components
#         exchange_manager = ExchangeManager(config)
#         risk_manager = RiskManager(config, exchange_manager)
#         rebalancer = Rebalancer(config, exchange_manager)
#         trade_logger = TradeLogger()
#         return ArbitrageBot(config, exchange_manager, risk_manager, rebalancer, trade_logger, log_queue)
    
#     def _create_async_bot(self, config, log_queue):
#         # Helper to initialize the asynchronous bot components
#         exchange_manager = AsyncExchangeManager(config)
#         risk_manager = RiskManager(config, exchange_manager)
#         rebalancer = Rebalancer(config, exchange_manager)
#         trade_logger = TradeLogger()
#         # NOTE: We need to adapt the AsyncArbitrageBot to accept and use the log_queue
#         # This will be done in the next file.
#         return AsyncArbitrageBot(config, exchange_manager, risk_manager, rebalancer, trade_logger, log_queue)

# if __name__ == "__main__":
#     app = BotApp()
#     app.mainloop()


# # main.py

# import os
# import sys
# import logging
# from logging.handlers import RotatingFileHandler
# import customtkinter as ctk
# from tkinter import messagebox
# from dotenv import load_dotenv

# import logging_config # <-- IMPORT THE NEW FILE
# from utils import load_config, ConfigError
# from gui_application import App

# def setup_simple_logging():
#     """Configures a simple rotating file logger and a console logger."""
#     logging_config.setup_custom_log_levels() # <-- SETUP CUSTOM LEVELS
    
#     logger = logging.getLogger()
#     logger.setLevel(logging.INFO)

#     if logger.hasHandlers():
#         logger.handlers.clear()

#     log_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s')
    
#     file_handler = RotatingFileHandler('bot.log', maxBytes=2*1024*1024, backupCount=2, mode='w', encoding='utf-8')
#     file_handler.setFormatter(log_format)
#     logger.addHandler(file_handler)
    
#     console_handler = logging.StreamHandler()
#     console_handler.setFormatter(log_format)
#     logger.addHandler(console_handler)
    
#     logging.info("Simplified logging configured.")

# if __name__ == "__main__":
#     load_dotenv()
#     try:
#         setup_simple_logging()
#         config = load_config()
        
#         EXCHANGES = {
#             'okx': {
#                 "apiKey": os.getenv("OKX_TESTNET_API_KEY"), 
#                 "secret": os.getenv("OKX_TESTNET_SECRET"), 
#                 "password": os.getenv("OKX_TESTNET_PASSPHRASE")
#             },
#             'binance': {
#                 "apiKey": os.getenv("BINANCE_TESTNET_API_KEY"), 
#                 "secret": os.getenv("BINANCE_TESTNET_SECRET")
#             },
#             'bybit':{
#                 "apiKey": os.getenv("BYBIT_TESTNET_API_KEY"), 
#                 "secret": os.getenv("BYBIT_TESTNET_SECRET")
#             }
#         }

#         all_keys_present = all(val for ex_config in EXCHANGES.values() for val in ex_config.values())
#         if not all_keys_present:
#             raise ConfigError("CRITICAL: One or more API keys are missing from your .env file for an active exchange.")
        
#         app = App(config, EXCHANGES)
#         app.mainloop()

#     except ConfigError as e:
#         logging.critical(f"Fatal Configuration Error: {e}", exc_info=True)
#         messagebox.showerror("Fatal Configuration Error", str(e))
#     except Exception as e:
#         logging.critical(f"An unexpected fatal error occurred: {e}", exc_info=True)
#         messagebox.showerror("Unexpected Fatal Error", f"An unrecoverable error occurred:\n\n{e}\n\nCheck bot.log for details.")