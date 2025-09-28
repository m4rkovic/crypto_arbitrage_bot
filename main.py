# gui_application.py

import customtkinter as ctk
import queue
import threading
import asyncio

# --- Import Your Existing GUI Components ---
from gui_components.left_panel import LeftPanel
from gui_components.live_ops_tab import LiveOpsTab
from gui_components.analysis_tab import AnalysisTab

# --- Import Both Bot Engines and Their Managers ---
from bot_engine import ArbitrageBot
from async_bot_engine import AsyncArbitrageBot
from exchange_manager import ExchangeManager
from exchange_manager_async import AsyncExchangeManager
from risk_manager import RiskManager
from rebalancer import Rebalancer
from trade_logger import TradeLogger

class App(ctk.CTk):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.title("Crypto Arbitrage Bot - Professional Edition")
        self.geometry("1200x750")

        # --- Bot Control State ---
        self.bot_thread = None
        self.bot_instance = None
        self.update_queue = queue.Queue() # Your original queue for structured data

        # --- Layout ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Your Original Left Panel ---
        self.left_panel = LeftPanel(self, width=250)
        self.left_panel.grid(row=0, column=0, padx=(10, 0), pady=10, sticky="ns")

        # --- Your Original Tab View ---
        self.tab_view = ctk.CTkTabview(self, width=900)
        self.tab_view.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.tab_view.add("Live Operations")
        self.tab_view.add("Analysis")

        # --- Your Original Tabs ---
        self.live_ops_tab = LiveOpsTab(self.tab_view.tab("Live Operations"))
        self.analysis_tab = AnalysisTab(self.tab_view.tab("Analysis"))

        # --- NEW: Add the Engine Selector and Buttons to your Left Panel ---
        self.add_engine_controls()

        # Start the queue processor to listen for updates from the bot
        self.process_queue()

    def add_engine_controls(self):
        """Injects the new controls into your existing left panel."""
        engine_frame = ctk.CTkFrame(self.left_panel)
        engine_frame.pack(pady=20, padx=10, fill="x", side="bottom")

        title_label = ctk.CTkLabel(engine_frame, text="Bot Control", font=ctk.CTkFont(size=16, weight="bold"))
        title_label.pack(pady=(5, 10))

        self.engine_var = ctk.StringVar(value="Async")
        self.engine_switch = ctk.CTkSwitch(
            engine_frame, text="Use Async Engine", variable=self.engine_var, 
            onvalue="Async", offvalue="Regular"
        )
        self.engine_switch.pack(pady=10, padx=10)

        self.start_button = ctk.CTkButton(engine_frame, text="Start Bot", command=self.start_bot)
        self.start_button.pack(pady=10, fill="x", padx=10)

        self.stop_button = ctk.CTkButton(engine_frame, text="Stop Bot", command=self.stop_bot, state="disabled")
        self.stop_button.pack(pady=5, fill="x", padx=10)

    def start_bot(self):
        """Starts the selected bot engine in a background thread."""
        use_async = self.engine_var.get() == "Async"
        
        try:
            if use_async:
                self.live_ops_tab.log_message("[GUI] Initializing ASYNC bot engine...")
                self.bot_instance = self._create_async_bot()
                # Async functions must be run within an asyncio event loop
                thread_target = lambda: asyncio.run(self.bot_instance.run())
            else:
                self.live_ops_tab.log_message("[GUI] Initializing REGULAR bot engine...")
                self.bot_instance = self._create_sync_bot()
                thread_target = self.bot_instance.run
            
            self.bot_thread = threading.Thread(target=thread_target, daemon=True)
            self.bot_thread.start()

            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.engine_switch.configure(state="disabled")
            self.live_ops_tab.log_message("[GUI] Bot started in background thread.")

        except Exception as e:
            self.live_ops_tab.log_message(f"[GUI-ERROR] Failed to start bot: {e}", "CRITICAL")

    def stop_bot(self):
        """Signals the running bot to stop and cleans up."""
        if self.bot_instance and self.bot_instance.is_running:
            self.live_ops_tab.log_message("[GUI] Sending stop signal to bot...")
            # This is the flag both your engines use to stop their loops
            self.bot_instance.is_running = False 
        
        # Reset GUI state
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.engine_switch.configure(state="normal")
        self.live_ops_tab.log_message("[GUI] Bot stop signal sent.")

    def process_queue(self):
        """
        Process messages from the bot's update_queue to update the GUI.
        This handles the structured data your bot sends.
        """
        try:
            while not self.update_queue.empty():
                message = self.update_queue.get_nowait()
                msg_type = message.get("type")
                data = message.get("data")

                # Route the message to the correct GUI component
                if msg_type == "log": # Simple text log
                    self.live_ops_tab.log_message(data)
                elif msg_type == "stats_update":
                    self.left_panel.update_stats(data)
                elif msg_type == "portfolio_update":
                    self.left_panel.update_portfolio(data)
                elif msg_type == "market_data":
                     self.live_ops_tab.update_market_data(data)
                # Add more message types as needed for your GUI
        finally:
            self.after(100, self.process_queue) # Check for new messages every 100ms

    def _create_sync_bot(self):
        """Initializes all components for the synchronous bot."""
        exchange_manager = ExchangeManager(self.config['exchanges'])
        risk_manager = RiskManager(self.config, exchange_manager)
        rebalancer = Rebalancer(self.config, exchange_manager)
        trade_logger = TradeLogger()
        # Your original bot expected the update_queue
        return ArbitrageBot(self.config, exchange_manager, risk_manager, rebalancer, trade_logger, self.update_queue)

    def _create_async_bot(self):
        """Initializes all components for the asynchronous bot."""
        exchange_manager = AsyncExchangeManager(self.config)
        risk_manager = RiskManager(self.config, exchange_manager)
        rebalancer = Rebalancer(self.config, exchange_manager)
        trade_logger = TradeLogger()
        # We need to adapt the async bot to use the same update_queue
        return AsyncArbitrageBot(self.config, exchange_manager, risk_manager, rebalancer, trade_logger, self.update_queue)
    
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