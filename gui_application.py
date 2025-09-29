# gui_application.py

import threading
import queue
import logging
import time
from typing import Any, Dict, Optional
import customtkinter as ctk
from tkinter import messagebox
import asyncio

# --- CORRECTED IMPORTS to match your file structure ---
from exchange_manager_async import AsyncExchangeManager # Use the async manager
from rebalancer import Rebalancer
from risk_manager import RiskManager
from trade_logger import TradeLogger # Import directly from the root

from bot_engine import ArbitrageBot
from async_bot_engine import AsyncArbitrageBot
from utils import ConfigError, ExchangeInitError
from gui_components.left_panel import LeftPanel
from gui_components.live_ops_tab import LiveOpsTab
from gui_components.analysis_tab import AnalysisTab

class QueueHandler(logging.Handler):
    def __init__(self, queue: queue.Queue):
        super().__init__()
        self.queue = queue
    def emit(self, record):
        self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

class App(ctk.CTk):
    def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any]):
        super().__init__()
        self.title("Arbitrage Bot Control Center")
        self.geometry("1600x900")
        ctk.set_appearance_mode("dark")
        
        self.config = config
        self.exchanges_config = exchanges_config
        self.update_queue: queue.Queue = queue.Queue()
        self.logger = logging.getLogger()
        self.add_gui_handler_to_logger()

        self.bot_instance: Optional[ArbitrageBot | AsyncArbitrageBot] = None
        self.bot_thread: Optional[threading.Thread] = None
        self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None
        
        self.create_widgets()
        self.process_queue()

    def add_gui_handler_to_logger(self):
        queue_handler = QueueHandler(self.update_queue)
        queue_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logging.getLogger().addHandler(queue_handler)

    def create_widgets(self):
        self.left_panel = LeftPanel(self, self.config, self.start_bot, self.stop_bot)
        self.left_panel.pack(side="left", fill="y", padx=(20, 10), pady=20)

        right_frame = ctk.CTkFrame(self)
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 20), pady=20)
        
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        tab_view = ctk.CTkTabview(right_frame)
        tab_view.pack(expand=True, fill="both", padx=5, pady=5)
        tab_view.add("Live Operations")
        tab_view.add("Performance Analysis")

        self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"))
        self.analysis_tab = AnalysisTab(tab_view.tab("Performance Analysis"), self)

    def process_queue(self):
        try:
            for _ in range(100):
                message = self.update_queue.get_nowait()
                msg_type = message.get("type")

                if msg_type == "initial_portfolio":
                    self.initial_portfolio_snapshot = message['data']
                    self.analysis_tab.update_portfolio_display(message['data'], self.initial_portfolio_snapshot)
                elif msg_type == "portfolio_update":
                    self.left_panel.update_balance_display(message['data']['balances'])
                    self.analysis_tab.update_portfolio_display(message['data'], self.initial_portfolio_snapshot)
                elif msg_type == "balance_update":
                    self.left_panel.update_balance_display(message['data'])
                elif msg_type == "log":
                    self.live_ops_tab.add_log_message(message.get("level", "INFO"), message['message'])
                elif msg_type == "stats":
                    self.left_panel.update_stats_display(**message['data'])
                elif msg_type == "market_data":
                    self.live_ops_tab.update_market_data_display(message['data'])
                elif msg_type == "opportunity_found":
                    self.live_ops_tab.add_opportunity_to_history(message['data'])
                elif msg_type == "critical_error":
                    messagebox.showerror("Critical Runtime Error", message['data'])
                elif msg_type == "stopped":
                    if not (self.bot_thread and self.bot_thread.is_alive()):
                        self.stop_bot()
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)
            
   # In gui_application.py

# In gui_application.py

    def start_bot(self):
        if self.bot_thread and self.bot_thread.is_alive():
            self.logger.warning("Bot is already running.")
            return

        try:
            params = self.left_panel.get_start_parameters()
            self.config['trading_parameters'].update(params)
            
            selected_engine = self.left_panel.engine_selector.get()
            self.logger.info(f"--- Starting New Session ({selected_engine} Engine) ---")

            if selected_engine == "Sync":
                self.bot_instance = ArbitrageBot(self.config, self.exchanges_config, self.update_queue)
            else: # Async engine
                exchange_manager = AsyncExchangeManager({'exchanges': self.exchanges_config})
                trade_logger = TradeLogger()
                risk_manager = RiskManager(self.config, exchange_manager)
                # --- THIS LINE IS THE FIX ---
                rebalancer = Rebalancer(exchange_manager, self.config) # Removed trade_logger

                self.bot_instance = AsyncArbitrageBot(
                    config=self.config,
                    exchange_manager=exchange_manager,
                    risk_manager=risk_manager,
                    rebalancer=rebalancer,
                    trade_logger=trade_logger
                )
            
            self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if params['dry_run'] else 'LIVE TRADING'}")
            if params['sizing_mode'] == 'fixed':
                self.logger.info(f"Sizing Mode: FIXED @ ${params['trade_size_usdt']:.2f}")
            else:
                self.logger.info(f"Sizing Mode: DYNAMIC ({params['dynamic_size_percentage']}% of balance, max ${params['dynamic_size_max_usdt']:.2f})")
            self.logger.info(f"Symbols: {', '.join(params['selected_symbols'])}")

            self.left_panel.set_controls_state(False)
            self.initial_portfolio_snapshot = None 

            if selected_engine == "Sync":
                self.bot_thread = threading.Thread(target=self.bot_instance.run, args=(params['selected_symbols'],), daemon=True)
            else:
                self.bot_thread = threading.Thread(target=lambda: asyncio.run(self.bot_instance.run()), daemon=True)
            
            self.bot_thread.start()
            self.update_runtime_clock()
        except Exception as e:
            self.logger.critical(f"Failed to start bot: {e}", exc_info=True)
            messagebox.showerror("Bot Start Failed", f"An error occurred while starting the bot:\n\n{e}")
            self.left_panel.set_controls_state(True)
            self.bot_instance = None
            self.bot_thread = None
            
    def stop_bot(self):
        self.left_panel.set_status("STOPPING...", "orange")
        if self.bot_instance:
            self.bot_instance.stop()
            if self.bot_thread and self.bot_thread.is_alive():
                self.logger.info("Waiting for bot thread to terminate...")
                self.bot_thread.join(timeout=10)
        
        self.bot_instance = None
        self.bot_thread = None
        self.left_panel.set_controls_state(True)
        self.left_panel.set_status("STOPPED", "red")
        self.left_panel.update_runtime_clock(0)
        self.logger.info("Bot shutdown complete.")

    def update_runtime_clock(self):
        if self.bot_instance and self.bot_instance.is_running():
            uptime_seconds = int(time.time() - self.bot_instance.start_time)
            self.left_panel.update_runtime_clock(uptime_seconds)
            self.after(1000, self.update_runtime_clock)
            
# # gui_application.py

# import threading
# import queue
# import logging
# import time
# from typing import Any, Dict, Optional
# import customtkinter as ctk
# from tkinter import messagebox
# import asyncio  # <-- ADDED

# # Ensure you are importing the correct class names from your files
# from bot_engine import ArbitrageBot
# from async_bot_engine import AsyncArbitrageBot
# from utils import ConfigError, ExchangeInitError
# from gui_components.left_panel import LeftPanel
# from gui_components.live_ops_tab import LiveOpsTab
# from gui_components.analysis_tab import AnalysisTab

# class QueueHandler(logging.Handler):
#     """Custom logging handler to route log records to the GUI queue."""
#     def __init__(self, queue: queue.Queue):
#         super().__init__()
#         self.queue = queue
#     def emit(self, record):
#         self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

# class App(ctk.CTk):
#     """
#     The main application class. It initializes the bot, builds the main UI structure,
#     and handles the communication between the bot engine and the UI components.
#     """
#     def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any]):
#         super().__init__()
#         self.title("Arbitrage Bot Control Center")
#         self.geometry("1600x900")
#         ctk.set_appearance_mode("dark")
        
#         self.config = config
#         self.exchanges_config = exchanges_config
#         self.update_queue: queue.Queue = queue.Queue()
#         self.logger = logging.getLogger()
#         self.add_gui_handler_to_logger()

#         self.bot_instance: Optional[ArbitrageBot | AsyncArbitrageBot] = None
#         self.bot_thread: Optional[threading.Thread] = None
#         self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None

#         # --- EXPLICIT GRID CONFIGURATION FOR THE MAIN WINDOW ---
#         # This tells the window how its columns should behave
#         # Column 0 (Left Panel) gets 0 weight -> It will NOT expand
#         self.grid_columnconfigure(0, weight=0) 
#         # Column 1 (Right Panel) gets 1 weight -> It WILL expand to fill all space
#         self.grid_columnconfigure(1, weight=1)
#         # The main row will expand vertically
#         self.grid_rowconfigure(0, weight=1)
        
#         self.create_widgets()
#         self.process_queue()


#     def add_gui_handler_to_logger(self):
#         """Adds the queue handler to the root logger."""
#         queue_handler = QueueHandler(self.update_queue)
#         queue_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
#         logging.getLogger().addHandler(queue_handler)

#     def create_widgets(self):
#         """Creates the main layout and instantiates the UI components."""
#         # --- Left Panel ---
#         self.left_panel = LeftPanel(self, self.config, self.start_bot, self.stop_bot)
#         # We revert to "nsw" sticky and add padding for spacing
#         self.left_panel.grid(row=0, column=0, padx=(20, 10), pady=20, sticky="nsw")

#         # --- Right Panel (Main Tab View) ---
#         right_frame = ctk.CTkFrame(self)
#         right_frame.grid(row=0, column=1, padx=(10, 20), pady=20, sticky="nsew")
#         right_frame.grid_rowconfigure(0, weight=1)
#         right_frame.grid_columnconfigure(0, weight=1)

#         tab_view = ctk.CTkTabview(right_frame)
#         tab_view.pack(expand=True, fill="both", padx=5, pady=5)
#         tab_view.add("Live Operations")
#         tab_view.add("Performance Analysis")

#         # --- Instantiate Tabs ---
#         self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"))
#         self.analysis_tab = AnalysisTab(tab_view.tab("Performance Analysis"), self)

#     def process_queue(self):
#         """
#         The heart of the GUI. Processes messages from the bot engine's queue
#         and dispatches them to the appropriate UI component for updates.
#         """
#         try:
#             for _ in range(100): # Process up to 100 messages per cycle
#                 message = self.update_queue.get_nowait()
#                 msg_type = message.get("type")

#                 if msg_type == "initial_portfolio":
#                     self.initial_portfolio_snapshot = message['data']
#                     self.analysis_tab.update_portfolio_display(message['data'], self.initial_portfolio_snapshot)
#                 elif msg_type == "portfolio_update":
#                     self.left_panel.update_balance_display(message['data']['balances'])
#                     # Note: portfolio_update from async bot is the full portfolio object
#                     self.analysis_tab.update_portfolio_display(message['data'], self.initial_portfolio_snapshot)
#                 elif msg_type == "balance_update": # For sync bot
#                     self.left_panel.update_balance_display(message['data'])
#                 elif msg_type == "log":
#                     self.live_ops_tab.add_log_message(message.get("level", "INFO"), message['message'])
#                 elif msg_type == "stats":
#                     self.left_panel.update_stats_display(**message['data'])
#                 elif msg_type == "market_data":
#                     self.live_ops_tab.update_market_data_display(message['data'])
#                 elif msg_type == "opportunity_found":
#                     self.live_ops_tab.add_opportunity_to_history(message['data'])
#                 elif msg_type == "critical_error":
#                     messagebox.showerror("Critical Runtime Error", message['data'])
#                 elif msg_type == "stopped":
#                     if not (self.bot_thread and self.bot_thread.is_alive()):
#                         self.stop_bot()

#         except queue.Empty:
#             pass
#         finally:
#             self.after(100, self.process_queue)
            
#     def start_bot(self):
#         """Handles the logic for starting the arbitrage bot thread."""
#         if self.bot_thread and self.bot_thread.is_alive():
#             self.logger.warning("Bot is already running.")
#             return

#         # --- WRAP THE ENTIRE STARTUP LOGIC IN A TRY/EXCEPT BLOCK ---
#         try:
#             # 1. Get and validate settings from the GUI
#             params = self.left_panel.get_start_parameters()
#             self.config['trading_parameters'].update(params)
            
#             selected_engine = self.left_panel.engine_selector.get()
#             self.logger.info(f"--- Starting New Session ({selected_engine} Engine) ---")

#             # 2. Instantiate the correct bot engine
#             if selected_engine == "Sync":
#                 self.bot_instance = ArbitrageBot(self.config, self.exchanges_config, self.update_queue)
#             else: # Async engine
#                 self.bot_instance = AsyncArbitrageBot(self.config, self.exchanges_config, self.update_queue)
                
#             # 3. Log start parameters
#             self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if params['dry_run'] else 'LIVE TRADING'}")
#             if params['sizing_mode'] == 'fixed':
#                 self.logger.info(f"Sizing Mode: FIXED @ ${params['trade_size_usdt']:.2f}")
#             else:
#                 self.logger.info(f"Sizing Mode: DYNAMIC ({params['dynamic_size_percentage']}% of balance, max ${params['dynamic_size_max_usdt']:.2f})")
#             self.logger.info(f"Symbols: {', '.join(params['selected_symbols'])}")

#             # 4. Disable UI controls and reset state
#             self.left_panel.set_controls_state(False)
#             self.initial_portfolio_snapshot = None 

#             # 5. Create and start the appropriate thread
#             if selected_engine == "Sync":
#                 self.bot_thread = threading.Thread(
#                     target=self.bot_instance.run, 
#                     args=(params['selected_symbols'],), 
#                     daemon=True
#                 )
#             else: # Async engine
#                 self.bot_thread = threading.Thread(
#                     target=lambda: asyncio.run(self.bot_instance.run()), 
#                     daemon=True
#                 )
            
#             self.bot_thread.start()
#             self.update_runtime_clock()

#         except Exception as e:
#             # --- THIS IS THE CRITICAL PART ---
#             # If anything fails, show an error and re-enable the controls
#             self.logger.critical(f"Failed to start bot: {e}", exc_info=True)
#             messagebox.showerror("Bot Start Failed", f"An error occurred while starting the bot:\n\n{e}")
#             # Re-enable controls so you can try again
#             self.left_panel.set_controls_state(True)
#             self.bot_instance = None
#             self.bot_thread = None
        
#         # 2. Instantiate the correct bot engine
#         try:
#             if selected_engine == "Sync":
#                 self.bot_instance = ArbitrageBot(self.config, self.exchanges_config, self.update_queue)
#             else: # Async engine
#                 self.bot_instance = AsyncArbitrageBot(self.config, self.exchanges_config, self.update_queue)
#         except (ConfigError, ExchangeInitError) as e:
#             messagebox.showerror("Initialization Failed", str(e))
#             self.logger.critical(f"Bot initialization failed: {e}")
#             return
            
#         # 3. Log start parameters
#         self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if params['dry_run'] else 'LIVE TRADING'}")
#         if params['sizing_mode'] == 'fixed':
#             self.logger.info(f"Sizing Mode: FIXED @ ${params['trade_size_usdt']:.2f}")
#         else:
#             self.logger.info(f"Sizing Mode: DYNAMIC ({params['dynamic_size_percentage']}% of balance, max ${params['dynamic_size_max_usdt']:.2f})")
#         self.logger.info(f"Symbols: {', '.join(params['selected_symbols'])}")

#         # 4. Disable UI controls and reset state
#         self.left_panel.set_controls_state(False)
#         self.initial_portfolio_snapshot = None 

#         # 5. Create and start the appropriate thread
#         if selected_engine == "Sync":
#             self.bot_thread = threading.Thread(
#                 target=self.bot_instance.run, 
#                 args=(params['selected_symbols'],), 
#                 daemon=True
#             )
#         else: # Async engine
#             # The async bot's run method handles its own parameters from the config
#             self.bot_thread = threading.Thread(
#                 target=lambda: asyncio.run(self.bot_instance.run()), 
#                 daemon=True
#             )
        
#         self.bot_thread.start()
#         self.update_runtime_clock()


#     def stop_bot(self):
#         """Handles the logic for stopping the arbitrage bot."""
#         self.left_panel.set_status("STOPPING...", "orange")
#         if self.bot_instance:
#             self.bot_instance.stop()
#             if self.bot_thread and self.bot_thread.is_alive():
#                 self.logger.info("Waiting for bot thread to terminate...")
#                 self.bot_thread.join(timeout=10)
        
#         self.bot_instance = None # Clear instance
#         self.bot_thread = None
#         self.left_panel.set_controls_state(True)
#         self.left_panel.set_status("STOPPED", "red")
#         self.left_panel.update_runtime_clock(0) # Reset clock display
#         self.logger.info("Bot shutdown complete.")

#     def update_runtime_clock(self):
#         """Periodically updates the runtime clock on the GUI."""
#         if self.bot_instance and self.bot_instance.is_running():
#             uptime_seconds = int(time.time() - self.bot_instance.start_time)
#             self.left_panel.update_runtime_clock(uptime_seconds)
#             self.after(1000, self.update_runtime_clock)