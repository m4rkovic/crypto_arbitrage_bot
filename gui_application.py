# gui_application.py

import customtkinter as ctk
import queue
import threading
import asyncio
import logging
import time
from typing import Any, Dict, Optional

# --- Import Both Bot Engines ---
from bot_engine import ArbitrageBot
from async_bot_engine import AsyncArbitrageBot

# --- Import Managers for the Async Bot ---
from exchange_manager_async import AsyncExchangeManager
from risk_manager import RiskManager
from rebalancer import Rebalancer
from trade_logger import TradeLogger

# --- Import Your Original GUI Components ---
from gui_components.left_panel import LeftPanel
from gui_components.live_ops_tab import LiveOpsTab
from gui_components.analysis_tab import AnalysisTab

class QueueHandler(logging.Handler):
    """Your original logging handler."""
    def __init__(self, queue: queue.Queue):
        super().__init__()
        self.queue = queue
    def emit(self, record):
        self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

class App(ctk.CTk):
    """
    The main application class, correctly structured to prevent startup crashes.
    """
    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.title("Arbitrage Bot Control Center - V4 (Stable)")
        self.geometry("1600x900")
        ctk.set_appearance_mode("dark")
        
        self.config = config
        self.update_queue: queue.Queue = queue.Queue()
        self.add_gui_handler_to_logger()

        # THE FIX: The bot instance starts as None. It is only created
        # inside the background thread AFTER the user clicks "Start".
        self.bot_instance: Optional[Any] = None
        self.bot_thread: Optional[threading.Thread] = None
        self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.create_widgets()
        self.process_queue()

    def add_gui_handler_to_logger(self):
        queue_handler = QueueHandler(self.update_queue)
        # Use a simple formatter, as the bot engines will send pre-formatted strings
        queue_handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(queue_handler)

    def create_widgets(self):
        # THE FIX: We pass 'self' (the App instance) to the components,
        # because the bot does not exist yet.
        self.left_panel = LeftPanel(self, self.config, self.start_bot, self.stop_bot)
        self.left_panel.grid(row=0, column=0, sticky="nsw")

        right_frame = ctk.CTkFrame(self)
        right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        tab_view = ctk.CTkTabview(right_frame)
        tab_view.pack(expand=True, fill="both", padx=5, pady=5)
        tab_view.add("Live Operations")
        tab_view.add("Performance Analysis")

        self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"), self.config, self)
        self.analysis_tab = AnalysisTab(tab_view.tab("Performance Analysis"), self)
        
        self._add_engine_controls_to_left_panel()

    def _add_engine_controls_to_left_panel(self):
        """Adds the engine selector to your left panel."""
        self.engine_var = ctk.StringVar(value="Async")
        self.engine_switch = ctk.CTkSwitch(
            self.left_panel, text="Use Async Engine", variable=self.engine_var,
            onvalue="Async", offvalue="Regular"
        )
        # Place it above the start button
        self.engine_switch.pack(pady=(20, 10), padx=10, before=self.left_panel.start_button)

    def process_queue(self):
        """Your original, powerful queue processor."""
        try:
            for _ in range(100): # Process up to 100 messages per cycle
                message = self.update_queue.get_nowait()
                msg_type = message.get("type")
                data = message.get("data")

                if msg_type == "log":
                    self.live_ops_tab.add_log_message(message.get("level", "INFO"), data)
                elif msg_type == "stats":
                    self.left_panel.update_stats_display(**data)
                elif msg_type == "initial_portfolio":
                    self.initial_portfolio_snapshot = data
                    if self.analysis_tab: self.analysis_tab.update_portfolio_display(data, self.initial_portfolio_snapshot)
                elif msg_type == "portfolio_update":
                    if self.left_panel: self.left_panel.update_balance_display(data['balances'])
                    if self.analysis_tab: self.analysis_tab.update_portfolio_display(data['portfolio'], self.initial_portfolio_snapshot)
                elif msg_type == "market_data":
                    if self.live_ops_tab: self.live_ops_tab.update_market_data_display(data)
                elif msg_type == "stopped":
                    if not (self.bot_thread and self.bot_thread.is_alive()):
                        self.stop_bot()
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    def start_bot(self):
        """Your original start logic, adapted for safe threading."""
        self.left_panel.set_status("STARTING...", "cyan")
        try:
            self.params = self.left_panel.get_start_parameters()
            self.config['trading_parameters'].update(self.params)

            if self.engine_var.get() == "Async":
                thread_target = self._run_async_bot_in_thread
            else:
                thread_target = self._run_sync_bot_in_thread
                
            self.bot_thread = threading.Thread(target=thread_target, daemon=True)
            self.bot_thread.start()

            self.left_panel.set_controls_state(False)
            self.engine_switch.configure(state="disabled")
            self.update_runtime_clock()
        except Exception as e:
            self.live_ops_tab.add_log_message("ERROR", f"Failed to get start parameters: {e}")
            self.left_panel.set_status("ERROR", "red")

    def stop_bot(self):
        """Your original stop logic."""
        self.left_panel.set_status("STOPPING...", "orange")
        if self.bot_instance:
             # Check for 'running' (sync) or 'is_running' (async)
             is_running_attr = 'is_running' if hasattr(self.bot_instance, 'is_running') else 'running'
             if getattr(self.bot_instance, is_running_attr, False):
                # Use the bot's own stop method
                if hasattr(self.bot_instance, 'stop'):
                    self.bot_instance.stop()
                else: # Fallback for async bot
                    setattr(self.bot_instance, is_running_attr, False)

        if self.bot_thread and self.bot_thread.is_alive():
            logging.info("Waiting for bot thread to terminate...")
            self.bot_thread.join(timeout=10)
        
        self.left_panel.set_controls_state(True)
        self.engine_switch.configure(state="normal")
        self.left_panel.set_status("STOPPED", "red")
        self.left_panel.update_runtime_clock(0)

    def update_runtime_clock(self):
        """Your original runtime clock."""
        if self.bot_instance:
             is_running_attr = 'is_running' if hasattr(self.bot_instance, 'is_running') else 'running'
             if getattr(self.bot_instance, is_running_attr, False):
                uptime_seconds = int(time.time() - self.bot_instance.start_time)
                self.left_panel.update_runtime_clock(uptime_seconds)
                self.after(1000, self.update_runtime_clock)

    def _run_sync_bot_in_thread(self):
        """Correctly initializes and runs your original synchronous bot."""
        try:
            self.left_panel.set_status("RUNNING", "green")
            # The bot is created HERE, in the background, matching your original __init__
            self.bot_instance = ArbitrageBot(self.config, self.config['exchanges'], self.update_queue)
            self.bot_instance.run(self.params['selected_symbols'])
        except Exception as e:
            logging.critical(f"Fatal error in sync bot thread: {e}", exc_info=True)
            self.update_queue.put({"type": "critical_error", "data": f"Bot thread crashed: {e}"})
            self.left_panel.set_status("CRASHED", "red")

    def _run_async_bot_in_thread(self):
        """Correctly initializes and runs the new asynchronous bot."""
        try:
            self.left_panel.set_status("RUNNING (Async)", "green")
            # The bot and managers are created HERE, in the background.
            exchange_manager = AsyncExchangeManager(self.config)
            risk_manager = RiskManager(self.config, exchange_manager)
            rebalancer = Rebalancer(self.config, exchange_manager)
            trade_logger = TradeLogger()

            self.bot_instance = AsyncArbitrageBot(
                self.config, exchange_manager, risk_manager,
                rebalancer, trade_logger, self.update_queue
            )
            asyncio.run(self.bot_instance.run())
        except Exception as e:
            logging.critical(f"Fatal error in async bot thread: {e}", exc_info=True)
            self.update_queue.put({"type": "critical_error", "data": f"Async bot thread crashed: {e}"})
            self.left_panel.set_status("CRASHED", "red")

# # gui_application.py

# import customtkinter as ctk
# import queue
# import threading
# import asyncio
# import logging
# import time
# from typing import Any, Dict, Optional

# # --- Import Your Existing GUI Components ---
# from gui_components.left_panel import LeftPanel
# from gui_components.live_ops_tab import LiveOpsTab
# from gui_components.analysis_tab import AnalysisTab

# # --- Import Both Bot Engines and Their Managers ---
# from bot_engine import ArbitrageBot
# from async_bot_engine import AsyncArbitrageBot
# from exchange_manager import ExchangeManager
# from exchange_manager_async import AsyncExchangeManager
# from risk_manager import RiskManager
# from rebalancer import Rebalancer
# from trade_logger import TradeLogger

# # --- YOUR ORIGINAL QueueHandler IS RESTORED ---
# class QueueHandler(logging.Handler):
#     """Custom logging handler to route log records to the GUI queue."""
#     def __init__(self, queue: queue.Queue):
#         super().__init__()
#         self.queue = queue
#     def emit(self, record):
#         self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

# class App(ctk.CTk):
#     """
#     Your original application class, now with engine selection and safe threading.
#     """
#     def __init__(self, config: Dict[str, Any]):
#         super().__init__()
#         self.title("Arbitrage Bot Control Center - V2")
#         self.geometry("1600x900")
#         ctk.set_appearance_mode("dark")
        
#         self.config = config
#         self.update_queue: queue.Queue = queue.Queue()
#         self.add_gui_handler_to_logger()

#         self.bot_instance: Optional[Any] = None # Can be sync or async bot
#         self.bot_thread: Optional[threading.Thread] = None
#         self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None

#         self.grid_columnconfigure(1, weight=1)
#         self.grid_rowconfigure(0, weight=1)
        
#         self.create_widgets()
#         self.process_queue()

#     def add_gui_handler_to_logger(self):
#         """Adds the queue handler to the root logger, as per your original design."""
#         queue_handler = QueueHandler(self.update_queue)
#         queue_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
#         logging.getLogger().addHandler(queue_handler)

#     def create_widgets(self):
#         """Creates the main layout from your original design."""
#         # --- Left Panel ---
#         self.left_panel = LeftPanel(self, self.config, self.start_bot, self.stop_bot)
#         self.left_panel.grid(row=0, column=0, sticky="nsw")

#         # --- Right Panel (Main Tab View) ---
#         right_frame = ctk.CTkFrame(self)
#         right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
#         right_frame.grid_rowconfigure(0, weight=1)
#         right_frame.grid_columnconfigure(0, weight=1)

#         tab_view = ctk.CTkTabview(right_frame)
#         tab_view.pack(expand=True, fill="both", padx=5, pady=5)
#         tab_view.add("Live Operations")
#         tab_view.add("Performance Analysis")

#         # --- Instantiate Tabs ---
#         # Pass the app instance so tabs can access the bot, config, etc.
#         self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"), self.config, self)
#         self.analysis_tab = AnalysisTab(tab_view.tab("Performance Analysis"), self)
        
#         # --- NEW: Add Engine controls to the left panel ---
#         self._add_engine_controls_to_left_panel()

#     def _add_engine_controls_to_left_panel(self):
#         """Injects the new controls into your existing left panel."""
#         self.engine_var = ctk.StringVar(value="Async")
#         self.engine_switch = ctk.CTkSwitch(
#             self.left_panel, text="Use Async Engine", variable=self.engine_var,
#             onvalue="Async", offvalue="Regular"
#         )
#         # Pack it above the existing start button in your left_panel
#         self.engine_switch.pack(pady=10, padx=10, before=self.left_panel.start_button)


#     def process_queue(self):
#         """
#         Your original, powerful queue processor. It is fully restored.
#         """
#         try:
#             for _ in range(100):
#                 message = self.update_queue.get_nowait()
#                 msg_type = message.get("type")
#                 data = message.get("data")

#                 if msg_type == "initial_portfolio":
#                     self.initial_portfolio_snapshot = data
#                     self.analysis_tab.update_portfolio_display(data, self.initial_portfolio_snapshot)
#                 elif msg_type == "portfolio_update":
#                     self.left_panel.update_balance_display(data['balances'])
#                     self.analysis_tab.update_portfolio_display(data['portfolio'], self.initial_portfolio_snapshot)
#                 elif msg_type == "log":
#                     self.live_ops_tab.add_log_message(message.get("level", "INFO"), message['message'])
#                 elif msg_type == "stats":
#                     self.left_panel.update_stats_display(**data)
#                 elif msg_type == "market_data":
#                     self.live_ops_tab.update_market_data_display(data)
#                 elif msg_type == "stopped":
#                     if not (self.bot_thread and self.bot_thread.is_alive()):
#                         self.stop_bot()

#         except queue.Empty:
#             pass
#         finally:
#             self.after(100, self.process_queue)

#     # --- NEW, SAFE THREADING LOGIC ---
#     def start_bot(self):
#         """Starts the selected bot engine safely in a background thread."""
#         self.left_panel.set_status("STARTING...", "cyan")
#         use_async = self.engine_var.get() == "Async"
        
#         if use_async:
#             thread_target = self._run_async_bot_in_thread
#         else:
#             thread_target = self._run_sync_bot_in_thread
            
#         self.bot_thread = threading.Thread(target=thread_target, daemon=True)
#         self.bot_thread.start()

#         self.left_panel.set_controls_state(False)
#         self.engine_switch.configure(state="disabled")
#         self.update_runtime_clock()

#     def stop_bot(self):
#         """Stops the bot and resets the GUI, based on your original logic."""
#         self.left_panel.set_status("STOPPING...", "orange")
#         if self.bot_instance and self.bot_instance.is_running:
#             self.bot_instance.stop() # Use the bot's own stop method
#             if self.bot_thread and self.bot_thread.is_alive():
#                 logging.info("Waiting for bot thread to terminate...")
#                 self.bot_thread.join(timeout=10)
        
#         self.left_panel.set_controls_state(True)
#         self.engine_switch.configure(state="normal")
#         self.left_panel.set_status("STOPPED", "red")
#         self.left_panel.update_runtime_clock(0)
#         logging.info("Bot shutdown complete.")

#     def _run_sync_bot_in_thread(self):
#         """Initializes and runs the synchronous bot."""
#         try:
#             # All bot components are created here, in the background
#             exchange_manager = ExchangeManager(self.config['exchanges'])
#             risk_manager = RiskManager(self.config, exchange_manager)
#             rebalancer = Rebalancer(self.config, exchange_manager)
#             trade_logger = TradeLogger()
            
#             # Your original bot uses the update_queue for rich data
#             self.bot_instance = ArbitrageBot(self.config, self.config['exchanges'], self.update_queue)
            
#             # Get params from GUI just before running
#             params = self.left_panel.get_start_parameters()
#             self.bot_instance.config['trading_parameters'].update(params)
            
#             self.left_panel.set_status("RUNNING", "green")
#             self.bot_instance.run(params['selected_symbols'])
#         except Exception as e:
#             logging.critical(f"Fatal error in sync bot thread: {e}", exc_info=True)
#             self.update_queue.put({"type": "log", "level": "CRITICAL", "message": f"Bot thread crashed: {e}"})
#             self.left_panel.set_status("CRASHED", "red")

#     def _run_async_bot_in_thread(self):
#         """Initializes and runs the asynchronous bot."""
#         try:
#             exchange_manager = AsyncExchangeManager(self.config)
#             risk_manager = RiskManager(self.config, exchange_manager)
#             rebalancer = Rebalancer(self.config, exchange_manager)
#             trade_logger = TradeLogger()

#             # The async bot needs to be adapted to use the rich update_queue
#             self.bot_instance = AsyncArbitrageBot(
#                 self.config, exchange_manager, risk_manager,
#                 rebalancer, trade_logger, self.update_queue
#             )
            
#             self.left_panel.set_status("RUNNING (Async)", "green")
#             asyncio.run(self.bot_instance.run())
#         except Exception as e:
#             logging.critical(f"Fatal error in async bot thread: {e}", exc_info=True)
#             self.update_queue.put({"type": "log", "level": "CRITICAL", "message": f"Async bot thread crashed: {e}"})
#             self.left_panel.set_status("CRASHED", "red")
            
#     def update_runtime_clock(self):
#         """Your original runtime clock function, fully restored."""
#         if self.bot_instance and self.bot_instance.is_running:
#             uptime_seconds = int(time.time() - self.bot_instance.start_time)
#             self.left_panel.update_runtime_clock(uptime_seconds)
#             self.after(1000, self.update_runtime_clock)

            
# import threading
# import queue
# import logging
# import time
# from typing import Any, Dict, Optional
# import customtkinter as ctk
# from tkinter import messagebox

# from bot_engine import ArbitrageBot
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
#         self.update_queue: queue.Queue = queue.Queue()
#         self.logger = logging.getLogger()
#         self.add_gui_handler_to_logger()

#         self.bot: Optional[ArbitrageBot] = None
#         self.bot_thread: Optional[threading.Thread] = None
#         self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None

#         try:
#             self.bot = ArbitrageBot(config, exchanges_config, self.update_queue)
#         except (ConfigError, ExchangeInitError) as e:
#             messagebox.showerror("Initialization Failed", str(e))
        
#         self.grid_columnconfigure(1, weight=1)
#         self.grid_rowconfigure(0, weight=1)
        
#         self.create_widgets()

#         if not self.bot:
#             self.logger.critical("Bot initialization failed. Please check config and restart.")
#             self.left_panel.set_controls_state(False) # Disable controls if bot fails

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
#         self.left_panel.grid(row=0, column=0, sticky="nsw")

#         # --- Right Panel (Main Tab View) ---
#         right_frame = ctk.CTkFrame(self)
#         right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
#         right_frame.grid_rowconfigure(0, weight=1)
#         right_frame.grid_columnconfigure(0, weight=1)

#         tab_view = ctk.CTkTabview(right_frame)
#         tab_view.pack(expand=True, fill="both", padx=5, pady=5)
#         tab_view.add("Live Operations")
#         tab_view.add("Performance Analysis")

#         # --- Instantiate Tabs ---
#         self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"), self.config, self.bot)
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
#                     self.analysis_tab.update_portfolio_display(message['data']['portfolio'], self.initial_portfolio_snapshot)
#                 elif msg_type == "balance_update":
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
#         if not self.bot:
#             messagebox.showerror("Error", "Bot could not be started.")
#             return
        
#         # 1. Get and validate settings from the GUI
#         try:
#             params = self.left_panel.get_start_parameters()
#             self.bot.config['trading_parameters'].update(params)
            
#             self.logger.info(f"--- Starting New Session ---")
#             self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if params['dry_run'] else 'LIVE TRADING'}")
            
#             if params['sizing_mode'] == 'fixed':
#                  self.logger.info(f"Sizing Mode: FIXED @ ${params['trade_size_usdt']:.2f}")
#             else:
#                  self.logger.info(f"Sizing Mode: DYNAMIC ({params['dynamic_size_percentage']}% of balance, max ${params['dynamic_size_max_usdt']:.2f})")
            
#             self.logger.info(f"Symbols: {', '.join(params['selected_symbols'])}")

#         except (ValueError, TypeError) as e:
#             messagebox.showerror("Invalid Input", str(e))
#             return

#         # 2. Disable UI controls
#         self.left_panel.set_controls_state(False)

#         # 3. Reset bot state and start the thread
#         self.initial_portfolio_snapshot = None 
#         with self.bot.state_lock:
#             self.bot.session_profit, self.bot.trade_count, self.bot.successful_trades = 0.0, 0, 0
#             self.bot.failed_trades, self.bot.neutralized_trades, self.bot.critical_failures = 0, 0, 0
#         self.left_panel.update_stats_display(**self.bot._get_current_stats())
        
#         self.bot_thread = threading.Thread(
#             target=self.bot.run, 
#             args=(params['selected_symbols'],), 
#             daemon=True
#         )
#         self.bot_thread.start()
#         self.update_runtime_clock()

#     def stop_bot(self):
#         """Handles the logic for stopping the arbitrage bot."""
#         self.left_panel.set_status("STOPPING...", "orange")
#         if self.bot:
#             self.bot.stop()
#             if self.bot_thread and self.bot_thread.is_alive():
#                 self.logger.info("Waiting for bot thread to terminate...")
#                 self.bot_thread.join(timeout=10)
        
#         self.left_panel.set_controls_state(True)
#         self.left_panel.set_status("STOPPED", "red")
#         self.left_panel.update_runtime_clock(0) # Reset clock display
#         self.logger.info("Bot shutdown complete.")

#     def update_runtime_clock(self):
#         """Periodically updates the runtime clock on the GUI."""
#         if self.bot and self.bot.running:
#             uptime_seconds = int(time.time() - self.bot.start_time)
#             self.left_panel.update_runtime_clock(uptime_seconds)
#             self.after(1000, self.update_runtime_clock)
