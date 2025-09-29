import threading
import queue
import logging
import time
from typing import Any, Dict, Optional
import customtkinter as ctk
from tkinter import messagebox

from bot_engine import ArbitrageBot
from utils import ConfigError, ExchangeInitError
from gui_components.left_panel import LeftPanel
from gui_components.live_ops_tab import LiveOpsTab
from gui_components.analysis_tab import AnalysisTab

class QueueHandler(logging.Handler):
    """Custom logging handler to route log records to the GUI queue."""
    def __init__(self, queue: queue.Queue):
        super().__init__()
        self.queue = queue
    def emit(self, record):
        self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

class App(ctk.CTk):
    """
    The main application class. It initializes the bot, builds the main UI structure,
    and handles the communication between the bot engine and the UI components.
    """
    def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any]):
        super().__init__()
        self.title("Arbitrage Bot Control Center")
        self.geometry("1600x900")
        ctk.set_appearance_mode("dark")
        
        self.config = config
        self.update_queue: queue.Queue = queue.Queue()
        self.logger = logging.getLogger()
        self.add_gui_handler_to_logger()

        self.bot: Optional[ArbitrageBot] = None
        self.bot_thread: Optional[threading.Thread] = None
        self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None

        try:
            self.bot = ArbitrageBot(config, exchanges_config, self.update_queue)
        except (ConfigError, ExchangeInitError) as e:
            messagebox.showerror("Initialization Failed", str(e))
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.create_widgets()

        if not self.bot:
            self.logger.critical("Bot initialization failed. Please check config and restart.")
            self.left_panel.set_controls_state(False) # Disable controls if bot fails

        self.process_queue()

    def add_gui_handler_to_logger(self):
        """Adds the queue handler to the root logger."""
        queue_handler = QueueHandler(self.update_queue)
        queue_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logging.getLogger().addHandler(queue_handler)

    def create_widgets(self):
        """Creates the main layout and instantiates the UI components."""
        # --- Left Panel ---
        self.left_panel = LeftPanel(self, self.config, self.start_bot, self.stop_bot)
        self.left_panel.grid(row=0, column=0, sticky="nsw")

        # --- Right Panel (Main Tab View) ---
        right_frame = ctk.CTkFrame(self)
        right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        tab_view = ctk.CTkTabview(right_frame)
        tab_view.pack(expand=True, fill="both", padx=5, pady=5)
        tab_view.add("Live Operations")
        tab_view.add("Performance Analysis")

        # --- Instantiate Tabs ---
        self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"), self.config, self.bot)
        self.analysis_tab = AnalysisTab(tab_view.tab("Performance Analysis"), self)

    def process_queue(self):
        """
        The heart of the GUI. Processes messages from the bot engine's queue
        and dispatches them to the appropriate UI component for updates.
        """
        try:
            for _ in range(100): # Process up to 100 messages per cycle
                message = self.update_queue.get_nowait()
                msg_type = message.get("type")

                if msg_type == "initial_portfolio":
                    self.initial_portfolio_snapshot = message['data']
                    self.analysis_tab.update_portfolio_display(message['data'], self.initial_portfolio_snapshot)
                elif msg_type == "portfolio_update":
                    self.left_panel.update_balance_display(message['data']['balances'])
                    self.analysis_tab.update_portfolio_display(message['data']['portfolio'], self.initial_portfolio_snapshot)
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

    def start_bot(self):
        """Handles the logic for starting the arbitrage bot thread."""
        if not self.bot:
            messagebox.showerror("Error", "Bot could not be started.")
            return
        
        # 1. Get and validate settings from the GUI
        try:
            params = self.left_panel.get_start_parameters()
            # This line correctly updates the bot's config with the selected symbols
            self.bot.config['trading_parameters'].update(params)
            
            self.logger.info(f"--- Starting New Session ---")
            self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if params['dry_run'] else 'LIVE TRADING'}")
            
            if params['sizing_mode'] == 'fixed':
                self.logger.info(f"Sizing Mode: FIXED @ ${params['trade_size_usdt']:.2f}")
            else:
                self.logger.info(f"Sizing Mode: DYNAMIC ({params['dynamic_size_percentage']}% of balance, max ${params['dynamic_size_max_usdt']:.2f})")
            
            self.logger.info(f"Symbols: {', '.join(params['selected_symbols'])}")

        except (ValueError, TypeError) as e:
            messagebox.showerror("Invalid Input", str(e))
            return

        # 2. Disable UI controls
        self.left_panel.set_controls_state(False)

        # 3. Reset bot state and start the thread
        self.bot.reset_session_stats() # <-- Cleaner way to reset stats
        self.left_panel.update_stats_display(**self.bot._get_current_stats())
        
        self.bot_thread = threading.Thread(
            target=self.bot.run,
            # args=(params['selected_symbols'],), # <-- CRITICAL: This line is removed to fix the TypeError
            daemon=True
        )
        self.bot_thread.start()
        self.update_runtime_clock()

    def stop_bot(self):
        """Handles the logic for stopping the arbitrage bot."""
        self.left_panel.set_status("STOPPING...", "orange")
        if self.bot:
            self.bot.stop()
            if self.bot_thread and self.bot_thread.is_alive():
                self.logger.info("Waiting for bot thread to terminate...")
                self.bot_thread.join(timeout=10)
        
        self.left_panel.set_controls_state(True)
        self.left_panel.set_status("STOPPED", "red")
        self.left_panel.update_runtime_clock(0) # Reset clock display
        self.logger.info("Bot shutdown complete.")

    def update_runtime_clock(self):
        """Periodically updates the runtime clock on the GUI."""
        if self.bot and self.bot.is_running:
            uptime_seconds = int(time.time() - self.bot.start_time)
            self.left_panel.update_runtime_clock(uptime_seconds)
            self.after(1000, self.update_runtime_clock)



# import threading
# import queue
# import logging
# import time
# from typing import Any, Dict, List, Optional
# import customtkinter as ctk
# from tkinter import messagebox
# from matplotlib.figure import Figure
# from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
# import pandas as pd

# from bot_engine import ArbitrageBot
# from utils import ConfigError, ExchangeInitError
# from performance_analyzer import PerformanceAnalyzer

# class QueueHandler(logging.Handler):
#     def __init__(self, queue: queue.Queue):
#         super().__init__()
#         self.queue = queue
#     def emit(self, record):
#         self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

# class App(ctk.CTk):
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
#         self.symbol_checkboxes: Dict[str, ctk.CTkCheckBox] = {}
#         self.kpi_labels: Dict[str, ctk.CTkLabel] = {}
#         self.portfolio_labels: Dict[str, ctk.CTkLabel] = {}
#         self.analysis_canvas_widgets: Dict[str, Any] = {}
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
#             self.start_button.configure(state="disabled")

#         self.process_queue()

#     def add_gui_handler_to_logger(self):
#         queue_handler = QueueHandler(self.update_queue)
#         queue_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
#         logging.getLogger().addHandler(queue_handler)

#     def create_widgets(self):
#         self.left_frame = ctk.CTkFrame(self, width=350, corner_radius=0)
#         self.left_frame.grid(row=0, column=0, sticky="nsw")
#         self.left_frame.grid_propagate(False) # Prevent frame from shrinking
        
#         self.right_frame = ctk.CTkFrame(self)
#         self.right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
#         self.right_frame.grid_rowconfigure(0, weight=1)
#         self.right_frame.grid_columnconfigure(0, weight=1)

#         self.tab_view = ctk.CTkTabview(self.right_frame)
#         self.tab_view.pack(expand=True, fill="both", padx=5, pady=5)
#         self.tab_view.add("Live Operations")
#         self.tab_view.add("Performance Analysis")

#         self.create_live_operations_tab(self.tab_view.tab("Live Operations"))
#         self.create_analysis_tab(self.tab_view.tab("Performance Analysis"))
#         self.populate_left_frame()

#     def populate_left_frame(self):
#         self.left_frame.grid_rowconfigure(4, weight=1)
#         ctk.CTkLabel(self.left_frame, text="Arbitrage Bot", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10))
        
#         control_frame = ctk.CTkFrame(self.left_frame)
#         control_frame.grid(row=1, column=0, padx=20, pady=(10,0), sticky="ew")
#         self.start_button = ctk.CTkButton(control_frame, text="Start Bot", command=self.start_bot)
#         self.start_button.pack(side="left", expand=True, padx=5, pady=5)
#         self.stop_button = ctk.CTkButton(control_frame, text="Stop Bot", command=self.stop_bot, state="disabled")
#         self.stop_button.pack(side="left", expand=True, padx=5, pady=5)
        
#         sizing_frame = ctk.CTkFrame(self.left_frame)
#         sizing_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
#         sizing_frame.grid_columnconfigure(0, weight=1)
        
#         ctk.CTkLabel(sizing_frame, text="Sizing Mode", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(5,0))
#         self.sizing_mode_var = ctk.StringVar(value=self.config['trading_parameters'].get('sizing_mode', 'fixed'))
        
#         self.fixed_radio = ctk.CTkRadioButton(sizing_frame, text="Fixed", variable=self.sizing_mode_var, value="fixed", command=self._toggle_sizing_frames)
#         self.fixed_radio.grid(row=1, column=0, padx=(10,5), pady=5, sticky="w")
#         self.dynamic_radio = ctk.CTkRadioButton(sizing_frame, text="Dynamic", variable=self.sizing_mode_var, value="dynamic", command=self._toggle_sizing_frames)
#         self.dynamic_radio.grid(row=1, column=1, padx=(5,10), pady=5, sticky="w")

#         self.fixed_sizing_frame = ctk.CTkFrame(sizing_frame)
#         self.fixed_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
#         self.fixed_sizing_frame.grid_columnconfigure(1, weight=1)
#         ctk.CTkLabel(self.fixed_sizing_frame, text="Size (USDT):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
#         self.trade_size_entry = ctk.CTkEntry(self.fixed_sizing_frame)
#         self.trade_size_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
#         self.trade_size_entry.insert(0, str(self.config['trading_parameters'].get('trade_size_usdt', 20.0)))
        
#         self.dynamic_sizing_frame = ctk.CTkFrame(sizing_frame)
#         self.dynamic_sizing_frame.grid_columnconfigure(1, weight=1)
#         ctk.CTkLabel(self.dynamic_sizing_frame, text="Balance (%):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
#         self.dynamic_pct_entry = ctk.CTkEntry(self.dynamic_sizing_frame)
#         self.dynamic_pct_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
#         self.dynamic_pct_entry.insert(0, str(self.config['trading_parameters'].get('dynamic_size_percentage', 5.0)))
        
#         ctk.CTkLabel(self.dynamic_sizing_frame, text="Max Size (USDT):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
#         self.dynamic_max_entry = ctk.CTkEntry(self.dynamic_sizing_frame)
#         self.dynamic_max_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
#         self.dynamic_max_entry.insert(0, str(self.config['trading_parameters'].get('dynamic_size_max_usdt', 100.0)))

#         self.dry_run_checkbox = ctk.CTkCheckBox(sizing_frame, text="Dry Run (Simulation Mode)")
#         self.dry_run_checkbox.grid(row=4, column=0, columnspan=2, padx=10, pady=10, sticky="w")
#         if self.config['trading_parameters'].get('dry_run', True):
#             self.dry_run_checkbox.select()
        
#         self._toggle_sizing_frames()
        
#         symbol_frame = ctk.CTkFrame(self.left_frame)
#         symbol_frame.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
#         ctk.CTkLabel(symbol_frame, text="Symbol Selection", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(5,0))
#         symbol_scroll_frame = ctk.CTkScrollableFrame(symbol_frame, height=150)
#         symbol_scroll_frame.pack(fill="x", expand=True, padx=5, pady=5)
#         for symbol in self.config['trading_parameters']['symbols_to_scan']:
#             checkbox = ctk.CTkCheckBox(symbol_scroll_frame, text=symbol)
#             checkbox.pack(anchor="w", padx=10, pady=2)
#             checkbox.select()
#             self.symbol_checkboxes[symbol] = checkbox
            
#         left_tab_view = ctk.CTkTabview(self.left_frame)
#         left_tab_view.grid(row=4, column=0, padx=20, pady=10, sticky="nsew")
#         left_tab_view.add("Session Stats")
#         left_tab_view.add("Wallet Balances")

#         stats_tab = left_tab_view.tab("Session Stats")
#         self.stats_frame = ctk.CTkFrame(stats_tab, fg_color="transparent")
#         self.stats_frame.pack(fill="both", expand=True, padx=5, pady=5)
#         self.stats_frame.grid_columnconfigure(1, weight=1)
        
#         self.status_label = ctk.CTkLabel(self.stats_frame, text="Status: STOPPED", text_color="red", font=ctk.CTkFont(weight="bold"))
#         self.status_label.grid(row=0, column=0, columnspan=2, padx=10, pady=(5,10))
#         ctk.CTkLabel(self.stats_frame, text="Session P/L:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
#         self.profit_value = ctk.CTkLabel(self.stats_frame, text="$0.00")
#         self.profit_value.grid(row=1, column=1, padx=10, pady=5, sticky="e")
#         ctk.CTkLabel(self.stats_frame, text="Total Trades:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
#         self.trades_value = ctk.CTkLabel(self.stats_frame, text="0")
#         self.trades_value.grid(row=2, column=1, padx=10, pady=5, sticky="e")
#         ctk.CTkLabel(self.stats_frame, text="Win Rate:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
#         self.win_rate_value = ctk.CTkLabel(self.stats_frame, text="N/A")
#         self.win_rate_value.grid(row=3, column=1, padx=10, pady=5, sticky="e")
#         ctk.CTkLabel(self.stats_frame, text="Avg Profit/Trade:").grid(row=4, column=0, padx=10, pady=5, sticky="w")
#         self.avg_profit_value = ctk.CTkLabel(self.stats_frame, text="$0.00")
#         self.avg_profit_value.grid(row=4, column=1, padx=10, pady=5, sticky="e")
#         ctk.CTkLabel(self.stats_frame, text="Failed / Neutralized:", text_color="gray").grid(row=5, column=0, padx=10, pady=5, sticky="w")
#         self.failed_value = ctk.CTkLabel(self.stats_frame, text="0 / 0")
#         self.failed_value.grid(row=5, column=1, padx=10, pady=5, sticky="e")
#         ctk.CTkLabel(self.stats_frame, text="Critical Failures:", text_color="gray").grid(row=6, column=0, padx=10, pady=5, sticky="w")
#         self.critical_value = ctk.CTkLabel(self.stats_frame, text="0", text_color="red")
#         self.critical_value.grid(row=6, column=1, padx=10, pady=5, sticky="e")
#         ctk.CTkLabel(self.stats_frame, text="Runtime:").grid(row=7, column=0, padx=10, pady=5, sticky="w")
#         self.runtime_label = ctk.CTkLabel(self.stats_frame, text="00:00:00")
#         self.runtime_label.grid(row=7, column=1, padx=10, pady=5, sticky="e")
        
#         balances_tab = left_tab_view.tab("Wallet Balances")
#         balances_tab.grid_columnconfigure(0, weight=1)
#         balances_tab.grid_rowconfigure(0, weight=1)
#         self.balance_frame = ctk.CTkScrollableFrame(balances_tab, label_text="")
#         self.balance_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")

#     def _toggle_sizing_frames(self):
#         mode = self.sizing_mode_var.get()
#         if mode == "fixed":
#             self.fixed_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
#             self.dynamic_sizing_frame.grid_remove()
#         elif mode == "dynamic":
#             self.fixed_sizing_frame.grid_remove()
#             self.dynamic_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

#     def create_live_operations_tab(self, tab):
#         tab.grid_rowconfigure(2, weight=1)
#         tab.grid_columnconfigure(0, weight=1)
#         self.build_market_scan_panel(tab)
#         self.build_opportunity_history_panel(tab)
#         self.log_textbox = ctk.CTkTextbox(tab, state="disabled", font=("Courier New", 12))
#         self.log_textbox.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
#         self.setup_log_colors()

#     def create_analysis_tab(self, tab):
#         tab.grid_columnconfigure(1, weight=1)
#         tab.grid_rowconfigure(1, weight=1)
        
#         control_frame = ctk.CTkFrame(tab)
#         control_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
#         refresh_button = ctk.CTkButton(control_frame, text="Load/Refresh Trade Data", command=self._on_refresh_analysis_data)
#         refresh_button.pack(side="left", padx=10, pady=5)
#         self.analysis_status_label = ctk.CTkLabel(control_frame, text="Waiting for session data...", text_color="gray")
#         self.analysis_status_label.pack(side="left", padx=10, pady=5)

#         left_panel = ctk.CTkScrollableFrame(tab)
#         left_panel.grid(row=1, column=0, sticky="ns", padx=10, pady=10)

#         kpi_frame = ctk.CTkFrame(left_panel)
#         kpi_frame.pack(fill="x", expand=True, padx=5, pady=5)
#         ctk.CTkLabel(kpi_frame, text="Trade Performance KPIs", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
#         kpi_list = ["Total Trades", "Successful Trades", "Win Rate (%)", "Net P/L ($)", "Profit Factor", "Max Drawdown ($)", "Sharpe Ratio"]
#         for kpi_name in kpi_list:
#             frame = ctk.CTkFrame(kpi_frame, fg_color="transparent")
#             frame.pack(fill="x", padx=10, pady=5)
#             ctk.CTkLabel(frame, text=f"{kpi_name}:", anchor="w").pack(side="left")
#             value_label = ctk.CTkLabel(frame, text="N/A", anchor="e")
#             value_label.pack(side="right")
#             self.kpi_labels[kpi_name] = value_label

#         portfolio_frame = ctk.CTkFrame(left_panel)
#         portfolio_frame.pack(fill="x", expand=True, padx=5, pady=15)
#         ctk.CTkLabel(portfolio_frame, text="Portfolio Performance", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
#         portfolio_list = {"Starting Value ($)": "N/A", "Current Value ($)": "N/A", "Portfolio P/L ($)": "N/A", "Portfolio Growth (%)": "N/A"}
#         for name, default_val in portfolio_list.items():
#             frame = ctk.CTkFrame(portfolio_frame, fg_color="transparent")
#             frame.pack(fill="x", padx=10, pady=5)
#             ctk.CTkLabel(frame, text=f"{name}:", anchor="w").pack(side="left")
#             value_label = ctk.CTkLabel(frame, text=default_val, anchor="e")
#             value_label.pack(side="right")
#             self.portfolio_labels[name] = value_label
        
#         self.portfolio_asset_breakdown_frame = ctk.CTkFrame(portfolio_frame)
#         self.portfolio_asset_breakdown_frame.pack(fill="x", expand=True, padx=10, pady=10)
#         ctk.CTkLabel(self.portfolio_asset_breakdown_frame, text="Asset Breakdown:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")

#         chart_tab_view = ctk.CTkTabview(tab)
#         chart_tab_view.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
#         chart_tab_view.add("P/L Curve")
#         chart_tab_view.add("Profit By Symbol")
#         chart_tab_view.add("Trade Log")
        
#         self.chart_frames = {
#             "P/L Curve": chart_tab_view.tab("P/L Curve"),
#             "Profit By Symbol": chart_tab_view.tab("Profit By Symbol"),
#         }
#         self.trade_log_frame = ctk.CTkScrollableFrame(chart_tab_view.tab("Trade Log"))
#         self.trade_log_frame.pack(fill="both", expand=True)

#     def build_market_scan_panel(self, parent):
#         self.scan_outer_frame = ctk.CTkFrame(parent)
#         self.scan_outer_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
#         self.scan_outer_frame.grid_columnconfigure(0, weight=1)
#         ctk.CTkLabel(self.scan_outer_frame, text="Live Market Scan", font=ctk.CTkFont(weight="bold")).pack()
#         self.scan_frame = ctk.CTkScrollableFrame(self.scan_outer_frame, height=200)
#         self.scan_frame.pack(fill="x", expand=True, padx=5, pady=5)
#         if not self.bot: return
#         self.market_data_labels: Dict[str, Dict[str, ctk.CTkLabel]] = {}
#         clients = self.bot.exchange_manager.get_all_clients()
#         headers = ["Symbol"] + [f"{name.capitalize()} {val}" for name in clients for val in ["Bid", "Ask"]] + ["Spread %"]
#         self.scan_frame.grid_columnconfigure(list(range(len(headers))), weight=1)
#         for i, header in enumerate(headers):
#             ctk.CTkLabel(self.scan_frame, text=header, font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=5)
#         for i, symbol in enumerate(self.config['trading_parameters']['symbols_to_scan']):
#             row_index = i + 1
#             self.market_data_labels[symbol] = {}
#             symbol_label = ctk.CTkLabel(self.scan_frame, text=symbol, fg_color="transparent")
#             symbol_label.grid(row=row_index, column=0, padx=5, pady=2, sticky="ew")
#             self.market_data_labels[symbol]['symbol'] = symbol_label
#             col_idx = 1
#             for ex_name in clients:
#                 for val in ["bid", "ask"]:
#                     label = ctk.CTkLabel(self.scan_frame, text="-", fg_color="transparent")
#                     label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
#                     self.market_data_labels[symbol][f"{ex_name}_{val}"] = label
#                     col_idx += 1
#             spread_label = ctk.CTkLabel(self.scan_frame, text="-", fg_color="transparent")
#             spread_label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
#             self.market_data_labels[symbol]['spread'] = spread_label

#     def build_opportunity_history_panel(self, parent):
#         self.opp_history_frame = ctk.CTkFrame(parent)
#         self.opp_history_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
#         ctk.CTkLabel(self.opp_history_frame, text="Recent Profitable Opportunities", font=ctk.CTkFont(weight="bold")).pack(pady=(5,5))
#         self.opp_history_textbox = ctk.CTkTextbox(self.opp_history_frame, state="disabled", height=120, font=("Calibri", 12))
#         self.opp_history_textbox.pack(fill="x", expand=True, padx=5, pady=5)
#         self.opp_history_textbox.tag_config("profit", foreground="cyan")
    
#     def _on_refresh_analysis_data(self):
#         self.analysis_status_label.configure(text="Loading and analyzing trade data...")
#         analyzer = PerformanceAnalyzer()
        
#         if not analyzer.load_data():
#             self.analysis_status_label.configure(text="Could not load trade data. Run bot to generate trades.csv.", text_color="orange")
#             return

#         kpis = analyzer.calculate_kpis()
#         for name, label in self.kpi_labels.items():
#             value = kpis.get(name, "N/A")
#             label.configure(text=str(value))
#             if name == "Net P/L ($)":
#                 try:
#                     profit_val = float(str(value).replace("$","").replace(",",""))
#                     label.configure(text_color="green" if profit_val >= 0 else "red")
#                 except (ValueError, TypeError):
#                     label.configure(text_color="gray")
        
#         self._embed_chart(analyzer.generate_equity_curve(), "P/L Curve")
#         self._embed_chart(analyzer.generate_profit_by_symbol_chart(), "Profit By Symbol")
#         self._populate_trade_log_table(analyzer.trades_df)
#         self.analysis_status_label.configure(text="Analysis complete.", text_color="green")

#     def _embed_chart(self, fig: Figure, chart_name: str):
#         if chart_name in self.analysis_canvas_widgets and self.analysis_canvas_widgets[chart_name]:
#             self.analysis_canvas_widgets[chart_name].get_tk_widget().destroy()
        
#         parent_frame = self.chart_frames.get(chart_name)
#         if parent_frame:
#             canvas = FigureCanvasTkAgg(fig, master=parent_frame)
#             canvas_widget = canvas.get_tk_widget()
#             canvas_widget.pack(side="top", fill="both", expand=True, padx=5, pady=5)
#             canvas.draw()
#             self.analysis_canvas_widgets[chart_name] = canvas
    
#     def _populate_trade_log_table(self, df: pd.DataFrame):
#         for widget in self.trade_log_frame.winfo_children():
#             widget.destroy()
            
#         headers = ['Timestamp', 'Symbol', 'Buy Ex', 'Sell Ex', 'Net Profit ($)']
#         self.trade_log_frame.grid_columnconfigure((0,1,2,3,4), weight=1)
#         for i, header in enumerate(headers):
#             ctk.CTkLabel(self.trade_log_frame, text=header, font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=5, pady=2)
        
#         df_display = df[df['status'] == 'SUCCESS'].reset_index()
#         for index, row in df_display.iterrows():
#             ctk.CTkLabel(self.trade_log_frame, text=row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')).grid(row=index+1, column=0, padx=5, pady=2, sticky="w")
#             ctk.CTkLabel(self.trade_log_frame, text=row['symbol']).grid(row=index+1, column=1, padx=5, pady=2)
#             ctk.CTkLabel(self.trade_log_frame, text=row['buy_exchange']).grid(row=index+1, column=2, padx=5, pady=2)
#             ctk.CTkLabel(self.trade_log_frame, text=row['sell_exchange']).grid(row=index+1, column=3, padx=5, pady=2)
#             profit_label = ctk.CTkLabel(self.trade_log_frame, text=f"{row['net_profit_usd']:.4f}")
#             profit_label.grid(row=index+1, column=4, padx=5, pady=2, sticky="e")
#             profit_label.configure(text_color="green" if row['net_profit_usd'] > 0 else "red")
    
#     def _update_portfolio_display(self, current_data: Dict):
#         if not self.initial_portfolio_snapshot: return

#         start_val = self.initial_portfolio_snapshot.get("total_usd_value", 0.0)
#         current_val = current_data.get("total_usd_value", 0.0)
#         pnl = current_val - start_val
#         growth = (pnl / start_val * 100) if start_val > 0 else 0.0
        
#         self.portfolio_labels["Starting Value ($)"].configure(text=f"${start_val:,.2f}")
#         self.portfolio_labels["Current Value ($)"].configure(text=f"${current_val:,.2f}")
#         self.portfolio_labels["Portfolio P/L ($)"].configure(text=f"${pnl:,.2f}", text_color="green" if pnl >= 0 else "red")
#         self.portfolio_labels["Portfolio Growth (%)"].configure(text=f"{growth:.2f}%", text_color="green" if growth >= 0 else "red")

#         for widget in self.portfolio_asset_breakdown_frame.winfo_children():
#             if not isinstance(widget, ctk.CTkLabel) or widget.cget("text") != "Asset Breakdown:":
#                 widget.destroy()

#         all_assets = sorted(list(set(self.initial_portfolio_snapshot.get("assets", {}).keys()) | set(current_data.get("assets", {}).keys())))
#         for asset in all_assets:
#             start_asset = self.initial_portfolio_snapshot.get("assets", {}).get(asset, {"balance": 0.0, "value_usd": 0.0})
#             current_asset = current_data.get("assets", {}).get(asset, {"balance": 0.0, "value_usd": 0.0})
            
#             asset_frame = ctk.CTkFrame(self.portfolio_asset_breakdown_frame)
#             asset_frame.pack(fill="x", pady=2)
#             ctk.CTkLabel(asset_frame, text=asset, font=ctk.CTkFont(weight="bold"), width=60).pack(side="left", padx=5)
#             ctk.CTkLabel(asset_frame, text=f"Start: ${start_asset['value_usd']:,.2f} ({start_asset['balance']:.4f})").pack(side="left", padx=10)
#             ctk.CTkLabel(asset_frame, text=f"Now: ${current_asset['value_usd']:,.2f} ({current_asset['balance']:.4f})").pack(side="left", padx=10)
    
#     def process_queue(self):
#         try:
#             for _ in range(100):
#                 message = self.update_queue.get_nowait()
#                 msg_type = message.get("type")
#                 if msg_type == "initial_portfolio":
#                     self.initial_portfolio_snapshot = message['data']
#                     self._update_portfolio_display(message['data'])
#                 elif msg_type == "portfolio_update":
#                     self.update_balance_display(message['data']['balances'])
#                     self._update_portfolio_display(message['data']['portfolio'])
#                 elif msg_type == "balance_update":
#                     self.update_balance_display(message['data'])
#                 elif msg_type == "log":
#                     level = message.get("level", "INFO")
#                     self.log_textbox.configure(state="normal")
#                     self.log_textbox.insert("end", f"{message['message']}\n", level)
#                     self.log_textbox.configure(state="disabled")
#                     self.log_textbox.see("end")
#                 elif msg_type == "stats":
#                     self.update_stats_display(**message['data'])
#                 elif msg_type == "market_data":
#                     self.update_market_data_display(message['data'])
#                 elif msg_type == "opportunity_found":
#                     self.add_opportunity_to_history(message['data'])
#                 elif msg_type == "critical_error":
#                     messagebox.showerror("Critical Runtime Error", message['data'])
#                 elif msg_type == "stopped":
#                     if not (self.bot_thread and self.bot_thread.is_alive()):
#                         self.stop_bot()
#         except queue.Empty:
#             pass
#         finally:
#             self.after(100, self.process_queue)

#     def add_opportunity_to_history(self, data: Dict[str, Any]):
#         symbol = data.get('symbol', 'N/A')
#         spread = data.get('spread_pct', 0.0)
#         timestamp = time.strftime('%H:%M:%S')
#         log_line = f"[{timestamp}] {symbol:<10} | Spread: {spread:.3f}%\n"
#         self.opp_history_textbox.configure(state="normal")
#         self.opp_history_textbox.insert("1.0", log_line, "profit")
#         self.opp_history_textbox.configure(state="disabled")

#     def setup_log_colors(self):
#         self.log_textbox.tag_config("INFO", foreground="white")
#         self.log_textbox.tag_config("WARNING", foreground="yellow")
#         self.log_textbox.tag_config("ERROR", foreground="red")
#         self.log_textbox.tag_config("CRITICAL", foreground="#ff4d4d")
#         self.log_textbox.tag_config("TRADE", foreground="cyan")
#         self.log_textbox.tag_config("SUCCESS", foreground="green")

#     def start_bot(self):
#         if not self.bot:
#             messagebox.showerror("Error", "Bot could not be started.")
#             return
        
#         try:
#             sizing_mode = self.sizing_mode_var.get()
#             self.bot.config['trading_parameters']['sizing_mode'] = sizing_mode
            
#             if sizing_mode == 'fixed':
#                 trade_size = float(self.trade_size_entry.get())
#                 if trade_size <= 0: raise ValueError("Fixed trade size must be positive.")
#                 self.bot.config['trading_parameters']['trade_size_usdt'] = trade_size
#                 self.logger.info(f"Sizing Mode: FIXED @ ${trade_size:.2f}")
#             else: 
#                 pct = float(self.dynamic_pct_entry.get())
#                 max_size = float(self.dynamic_max_entry.get())
#                 if not (0 < pct <= 100): raise ValueError("Percentage must be between 0 and 100.")
#                 if max_size <= 0: raise ValueError("Max size must be positive.")
#                 self.bot.config['trading_parameters']['dynamic_size_percentage'] = pct
#                 self.bot.config['trading_parameters']['dynamic_size_max_usdt'] = max_size
#                 self.logger.info(f"Sizing Mode: DYNAMIC ({pct}% of balance, max ${max_size:.2f})")
            
#         except (ValueError, TypeError) as e:
#             messagebox.showerror("Invalid Input", f"Please enter valid numbers for sizing parameters.\n\n{e}")
#             return

#         is_dry_run = self.dry_run_checkbox.get() == 1
#         self.bot.config['trading_parameters']['dry_run'] = is_dry_run
#         selected_symbols = [symbol for symbol, checkbox in self.symbol_checkboxes.items() if checkbox.get() == 1]
#         if not selected_symbols:
#             messagebox.showerror("Invalid Input", "Please select at least one symbol to trade.")
#             return
        
#         self.logger.info(f"--- Starting New Session ---")
#         self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if is_dry_run else 'LIVE TRADING'}")
#         self.logger.info(f"Symbols: {', '.join(selected_symbols)}")

#         self.start_button.configure(state="disabled")
#         self.stop_button.configure(state="normal")
#         for radio in [self.fixed_radio, self.dynamic_radio]: radio.configure(state="disabled")
#         self.trade_size_entry.configure(state="disabled")
#         self.dynamic_pct_entry.configure(state="disabled")
#         self.dynamic_max_entry.configure(state="disabled")
#         self.dry_run_checkbox.configure(state="disabled")
#         for checkbox in self.symbol_checkboxes.values():
#             checkbox.configure(state="disabled")

#         self.initial_portfolio_snapshot = None 
#         with self.bot.state_lock:
#             self.bot.session_profit, self.bot.trade_count, self.bot.successful_trades = 0.0, 0, 0
#             self.bot.failed_trades, self.bot.neutralized_trades, self.bot.critical_failures = 0, 0, 0
#         self.update_stats_display(**self.bot._get_current_stats())
#         self.bot_thread = threading.Thread(target=self.bot.run, args=(selected_symbols,), daemon=True)
#         self.bot_thread.start()
#         self.update_runtime_clock()

#     def stop_bot(self):
#         self.start_button.configure(state="normal")
#         self.stop_button.configure(state="disabled")
#         for radio in [self.fixed_radio, self.dynamic_radio]: radio.configure(state="normal")
#         self.trade_size_entry.configure(state="normal")
#         self.dynamic_pct_entry.configure(state="normal")
#         self.dynamic_max_entry.configure(state="normal")
#         self.dry_run_checkbox.configure(state="normal")
#         for checkbox in self.symbol_checkboxes.values():
#             checkbox.configure(state="normal")

#         self.status_label.configure(text="Status: STOPPING...", text_color="orange")
#         if self.bot:
#             self.bot.stop()
#             if self.bot_thread and self.bot_thread.is_alive():
#                 self.logger.info("Waiting for bot thread to terminate...")
#                 self.bot_thread.join(timeout=10)
#         self.status_label.configure(text="Status: STOPPED", text_color="red")
#         self.runtime_label.configure(text="00:00:00")
#         self.logger.info("Bot shutdown complete.")

#     def update_stats_display(self, trades: int, successful: int, failed: int, neutralized: int, critical: int, profit: float):
#         self.trades_value.configure(text=f"{trades}")
#         completed_trades = successful + failed + neutralized
#         win_rate = (successful / completed_trades * 100) if completed_trades > 0 else 0
#         avg_profit = (profit / successful) if successful > 0 else 0
#         self.win_rate_value.configure(text=f"{win_rate:.2f}%")
#         self.avg_profit_value.configure(text=f"${avg_profit:,.4f}")
#         profit_color = "green" if profit >= 0 else "red"
#         self.profit_value.configure(text=f"${profit:,.2f}", text_color=profit_color)
#         self.failed_value.configure(text=f"{failed} / {neutralized}")
#         self.critical_value.configure(text=f"{critical}")

#     def update_runtime_clock(self):
#         if self.bot and self.bot.running:
#             uptime_seconds = int(time.time() - self.bot.start_time)
#             hours, remainder = divmod(uptime_seconds, 3600)
#             minutes, seconds = divmod(remainder, 60)
#             self.runtime_label.configure(text=f"{hours:02}:{minutes:02}:{seconds:02}")
#             self.after(1000, self.update_runtime_clock)
    
#     def update_balance_display(self, balance_data: Dict[str, Any]):
#         """
#         Rewrites the balance frame to display balances in a dynamic grid/table format.
#         """
#         # 1. Clear the previous content
#         for widget in self.balance_frame.winfo_children():
#             widget.destroy()

#         # 2. Collect all unique assets and exchanges
#         all_assets = set()
#         exchange_names = sorted(balance_data.keys())
#         for ex_name in exchange_names:
#             all_assets.update(balance_data[ex_name].keys())
        
#         sorted_assets = sorted(list(all_assets))

#         # 3. Configure the grid layout
#         num_cols = len(exchange_names) + 1
#         self.balance_frame.grid_columnconfigure(list(range(num_cols)), weight=1)

#         # 4. Create Headers
#         # Empty top-left corner
#         ctk.CTkLabel(self.balance_frame, text="").grid(row=0, column=0) 
#         for col_idx, ex_name in enumerate(exchange_names, 1):
#             header = ctk.CTkLabel(self.balance_frame, text=ex_name.capitalize(), font=ctk.CTkFont(weight="bold"))
#             header.grid(row=0, column=col_idx, padx=5, pady=2, sticky="ew")

#         # 5. Populate the grid with data
#         for row_idx, asset in enumerate(sorted_assets, 1):
#             # Asset name column
#             asset_label = ctk.CTkLabel(self.balance_frame, text=asset, font=ctk.CTkFont(weight="bold"), anchor="w")
#             asset_label.grid(row=row_idx, column=0, padx=5, pady=2, sticky="w")

#             # Balance data for each exchange
#             for col_idx, ex_name in enumerate(exchange_names, 1):
#                 balance = balance_data.get(ex_name, {}).get(asset, 0.0)
                
#                 # Check if balance is a valid number
#                 balance_val = balance if isinstance(balance, (int, float)) else 0.0
                
#                 # Use a smaller font for the numbers to fit more
#                 balance_label = ctk.CTkLabel(self.balance_frame, text=f"{balance_val:.4f}", font=ctk.CTkFont(size=11), anchor="e")
#                 balance_label.grid(row=row_idx, column=col_idx, padx=5, pady=2, sticky="ew")

#     def update_market_data_display(self, data: Dict[str, Any]):
#         if not self.bot: return
#         try:
#             symbol = data.get('symbol')
#             if hasattr(self, 'market_data_labels') and self.market_data_labels and symbol in self.market_data_labels:
#                 labels = self.market_data_labels[symbol]
#                 clients = self.bot.exchange_manager.get_all_clients()
                
#                 for ex_name in clients:
#                     bid_val = data.get(f'{ex_name}_bid')
#                     ask_val = data.get(f'{ex_name}_ask')
#                     if f'{ex_name}_bid' in labels: labels[f'{ex_name}_bid'].configure(text=f"{bid_val:.4f}" if bid_val is not None else "-")
#                     if f'{ex_name}_ask' in labels: labels[f'{ex_name}_ask'].configure(text=f"{ask_val:.4f}" if ask_val is not None else "-")

#                 spread_pct = data.get('spread_pct')
#                 is_profitable = data.get('is_profitable', False)
#                 spread_label = labels['spread']
                
#                 if spread_pct is not None:
#                     default_text_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
#                     spread_color = "green" if spread_pct > 0 else "red"
#                     if spread_pct == 0: spread_color = default_text_color
#                     spread_label.configure(text=f"{spread_pct:.3f}%", text_color=spread_color)
#                 else:
#                     spread_label.configure(text="-")

#                 highlight_color = "#1E4D2B" if is_profitable else "transparent" 
                
#                 # Highlight the entire row
#                 for label_widget in labels.values():
#                    label_widget.configure(fg_color=highlight_color)

#         except Exception as e:
#             self.logger.warning(f"Failed to update GUI for market data. Error: {e}", exc_info=False)


# # # gui_application.py

# # import threading
# # import queue
# # import logging
# # import time
# # from typing import Any, Dict, List, Optional
# # import customtkinter as ctk
# # from tkinter import messagebox
# # from matplotlib.figure import Figure
# # from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
# # import pandas as pd

# # from bot_engine import ArbitrageBot
# # from utils import ConfigError, ExchangeInitError
# # from performance_analyzer import PerformanceAnalyzer

# # class QueueHandler(logging.Handler):
# #     def __init__(self, queue: queue.Queue):
# #         super().__init__()
# #         self.queue = queue
# #     def emit(self, record):
# #         self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

# # class App(ctk.CTk):
# #     def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any]):
# #         super().__init__()
# #         self.title("Arbitrage Bot Control Center")
# #         self.geometry("1600x900")
# #         ctk.set_appearance_mode("dark")
        
# #         self.config = config
# #         self.update_queue: queue.Queue = queue.Queue()
# #         self.logger = logging.getLogger()
# #         self.add_gui_handler_to_logger()

# #         self.bot: Optional[ArbitrageBot] = None
# #         self.bot_thread: Optional[threading.Thread] = None
# #         self.symbol_checkboxes: Dict[str, ctk.CTkCheckBox] = {}
# #         self.kpi_labels: Dict[str, ctk.CTkLabel] = {}
# #         self.portfolio_labels: Dict[str, ctk.CTkLabel] = {}
# #         self.analysis_canvas_widgets: Dict[str, Any] = {}
# #         self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None
        
# #         try:
# #             self.bot = ArbitrageBot(config, exchanges_config, self.update_queue)
# #         except (ConfigError, ExchangeInitError) as e:
# #             messagebox.showerror("Initialization Failed", str(e))
        
# #         self.grid_columnconfigure(1, weight=1)
# #         self.grid_rowconfigure(0, weight=1)
        
# #         self.create_widgets()

# #         if not self.bot:
# #             self.logger.critical("Bot initialization failed. Please check config and restart.")
# #             self.start_button.configure(state="disabled")

# #         self.process_queue()

# #     def add_gui_handler_to_logger(self):
# #         queue_handler = QueueHandler(self.update_queue)
# #         queue_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
# #         logging.getLogger().addHandler(queue_handler)

# #     def create_widgets(self):
# #         self.left_frame = ctk.CTkFrame(self, width=320, corner_radius=0)
# #         self.left_frame.grid(row=0, column=0, sticky="nsw")
        
# #         self.right_frame = ctk.CTkFrame(self)
# #         self.right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
# #         self.right_frame.grid_rowconfigure(0, weight=1)
# #         self.right_frame.grid_columnconfigure(0, weight=1)

# #         self.tab_view = ctk.CTkTabview(self.right_frame)
# #         self.tab_view.pack(expand=True, fill="both", padx=5, pady=5)
# #         self.tab_view.add("Live Operations")
# #         self.tab_view.add("Performance Analysis")

# #         self.create_live_operations_tab(self.tab_view.tab("Live Operations"))
# #         self.create_analysis_tab(self.tab_view.tab("Performance Analysis"))
# #         self.populate_left_frame()

# #     def populate_left_frame(self):
# #         self.left_frame.grid_rowconfigure(4, weight=1)
# #         ctk.CTkLabel(self.left_frame, text="Arbitrage Bot", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10))
        
# #         control_frame = ctk.CTkFrame(self.left_frame)
# #         control_frame.grid(row=1, column=0, padx=20, pady=(10,0), sticky="ew")
# #         self.start_button = ctk.CTkButton(control_frame, text="Start Bot", command=self.start_bot)
# #         self.start_button.pack(side="left", expand=True, padx=5, pady=5)
# #         self.stop_button = ctk.CTkButton(control_frame, text="Stop Bot", command=self.stop_bot, state="disabled")
# #         self.stop_button.pack(side="left", expand=True, padx=5, pady=5)
        
# #         sizing_frame = ctk.CTkFrame(self.left_frame)
# #         sizing_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
# #         sizing_frame.grid_columnconfigure(0, weight=1)
        
# #         ctk.CTkLabel(sizing_frame, text="Sizing Mode", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(5,0))
# #         self.sizing_mode_var = ctk.StringVar(value=self.config['trading_parameters'].get('sizing_mode', 'fixed'))
        
# #         self.fixed_radio = ctk.CTkRadioButton(sizing_frame, text="Fixed", variable=self.sizing_mode_var, value="fixed", command=self._toggle_sizing_frames)
# #         self.fixed_radio.grid(row=1, column=0, padx=(10,5), pady=5, sticky="w")
# #         self.dynamic_radio = ctk.CTkRadioButton(sizing_frame, text="Dynamic", variable=self.sizing_mode_var, value="dynamic", command=self._toggle_sizing_frames)
# #         self.dynamic_radio.grid(row=1, column=1, padx=(5,10), pady=5, sticky="w")

# #         self.fixed_sizing_frame = ctk.CTkFrame(sizing_frame)
# #         self.fixed_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
# #         self.fixed_sizing_frame.grid_columnconfigure(1, weight=1)
# #         ctk.CTkLabel(self.fixed_sizing_frame, text="Size (USDT):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
# #         self.trade_size_entry = ctk.CTkEntry(self.fixed_sizing_frame)
# #         self.trade_size_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
# #         self.trade_size_entry.insert(0, str(self.config['trading_parameters'].get('trade_size_usdt', 20.0)))
        
# #         self.dynamic_sizing_frame = ctk.CTkFrame(sizing_frame)
# #         self.dynamic_sizing_frame.grid_columnconfigure(1, weight=1)
# #         ctk.CTkLabel(self.dynamic_sizing_frame, text="Balance (%):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
# #         self.dynamic_pct_entry = ctk.CTkEntry(self.dynamic_sizing_frame)
# #         self.dynamic_pct_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
# #         self.dynamic_pct_entry.insert(0, str(self.config['trading_parameters'].get('dynamic_size_percentage', 5.0)))
        
# #         ctk.CTkLabel(self.dynamic_sizing_frame, text="Max Size (USDT):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
# #         self.dynamic_max_entry = ctk.CTkEntry(self.dynamic_sizing_frame)
# #         self.dynamic_max_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
# #         self.dynamic_max_entry.insert(0, str(self.config['trading_parameters'].get('dynamic_size_max_usdt', 100.0)))

# #         self.dry_run_checkbox = ctk.CTkCheckBox(sizing_frame, text="Dry Run (Simulation Mode)")
# #         self.dry_run_checkbox.grid(row=4, column=0, columnspan=2, padx=10, pady=10, sticky="w")
# #         if self.config['trading_parameters'].get('dry_run', True):
# #             self.dry_run_checkbox.select()
        
# #         self._toggle_sizing_frames()
            
# #         symbol_frame = ctk.CTkFrame(self.left_frame)
# #         symbol_frame.grid(row=3, column=0, padx=20, pady=10, sticky="nsew")
# #         ctk.CTkLabel(symbol_frame, text="Symbol Selection", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(5,0))
# #         symbol_scroll_frame = ctk.CTkScrollableFrame(symbol_frame, height=150)
# #         symbol_scroll_frame.pack(fill="x", expand=True, padx=5, pady=5)
# #         for symbol in self.config['trading_parameters']['symbols_to_scan']:
# #             checkbox = ctk.CTkCheckBox(symbol_scroll_frame, text=symbol)
# #             checkbox.pack(anchor="w", padx=10, pady=2)
# #             checkbox.select()
# #             self.symbol_checkboxes[symbol] = checkbox
            
# #         left_tab_view = ctk.CTkTabview(self.left_frame)
# #         left_tab_view.grid(row=4, column=0, padx=20, pady=10, sticky="nsew")
# #         left_tab_view.add("Session Stats")
# #         left_tab_view.add("Wallet Balances")

# #         stats_tab = left_tab_view.tab("Session Stats")
# #         self.stats_frame = ctk.CTkFrame(stats_tab, fg_color="transparent")
# #         self.stats_frame.pack(fill="both", expand=True, padx=5, pady=5)
# #         self.stats_frame.grid_columnconfigure(1, weight=1)
        
# #         self.status_label = ctk.CTkLabel(self.stats_frame, text="Status: STOPPED", text_color="red", font=ctk.CTkFont(weight="bold"))
# #         self.status_label.grid(row=0, column=0, columnspan=2, padx=10, pady=(5,10))
# #         ctk.CTkLabel(self.stats_frame, text="Session P/L:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
# #         self.profit_value = ctk.CTkLabel(self.stats_frame, text="$0.00")
# #         self.profit_value.grid(row=1, column=1, padx=10, pady=5, sticky="e")
# #         ctk.CTkLabel(self.stats_frame, text="Total Trades:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
# #         self.trades_value = ctk.CTkLabel(self.stats_frame, text="0")
# #         self.trades_value.grid(row=2, column=1, padx=10, pady=5, sticky="e")
# #         ctk.CTkLabel(self.stats_frame, text="Win Rate:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
# #         self.win_rate_value = ctk.CTkLabel(self.stats_frame, text="N/A")
# #         self.win_rate_value.grid(row=3, column=1, padx=10, pady=5, sticky="e")
# #         ctk.CTkLabel(self.stats_frame, text="Avg Profit/Trade:").grid(row=4, column=0, padx=10, pady=5, sticky="w")
# #         self.avg_profit_value = ctk.CTkLabel(self.stats_frame, text="$0.00")
# #         self.avg_profit_value.grid(row=4, column=1, padx=10, pady=5, sticky="e")
# #         ctk.CTkLabel(self.stats_frame, text="Failed / Neutralized:", text_color="gray").grid(row=5, column=0, padx=10, pady=5, sticky="w")
# #         self.failed_value = ctk.CTkLabel(self.stats_frame, text="0 / 0")
# #         self.failed_value.grid(row=5, column=1, padx=10, pady=5, sticky="e")
# #         ctk.CTkLabel(self.stats_frame, text="Critical Failures:", text_color="gray").grid(row=6, column=0, padx=10, pady=5, sticky="w")
# #         self.critical_value = ctk.CTkLabel(self.stats_frame, text="0", text_color="red")
# #         self.critical_value.grid(row=6, column=1, padx=10, pady=5, sticky="e")
# #         ctk.CTkLabel(self.stats_frame, text="Runtime:").grid(row=7, column=0, padx=10, pady=5, sticky="w")
# #         self.runtime_label = ctk.CTkLabel(self.stats_frame, text="00:00:00")
# #         self.runtime_label.grid(row=7, column=1, padx=10, pady=5, sticky="e")
        
# #         balances_tab = left_tab_view.tab("Wallet Balances")
# #         balances_tab.grid_columnconfigure(0, weight=1)
# #         balances_tab.grid_rowconfigure(0, weight=1)
# #         self.balance_frame = ctk.CTkScrollableFrame(balances_tab, label_text="")
# #         self.balance_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")

# #     def _toggle_sizing_frames(self):
# #         mode = self.sizing_mode_var.get()
# #         if mode == "fixed":
# #             self.fixed_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
# #             self.dynamic_sizing_frame.grid_remove()
# #         elif mode == "dynamic":
# #             self.fixed_sizing_frame.grid_remove()
# #             self.dynamic_sizing_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

# #     def create_live_operations_tab(self, tab):
# #         tab.grid_rowconfigure(2, weight=1)
# #         tab.grid_columnconfigure(0, weight=1)
# #         self.build_market_scan_panel(tab)
# #         self.build_opportunity_history_panel(tab)
# #         self.log_textbox = ctk.CTkTextbox(tab, state="disabled", font=("Courier New", 12))
# #         self.log_textbox.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
# #         self.setup_log_colors()

# #     def create_analysis_tab(self, tab):
# #         tab.grid_columnconfigure(1, weight=1)
# #         tab.grid_rowconfigure(1, weight=1)
        
# #         control_frame = ctk.CTkFrame(tab)
# #         control_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
# #         refresh_button = ctk.CTkButton(control_frame, text="Load/Refresh Trade Data", command=self._on_refresh_analysis_data)
# #         refresh_button.pack(side="left", padx=10, pady=5)
# #         self.analysis_status_label = ctk.CTkLabel(control_frame, text="Waiting for session data...", text_color="gray")
# #         self.analysis_status_label.pack(side="left", padx=10, pady=5)

# #         left_panel = ctk.CTkScrollableFrame(tab)
# #         left_panel.grid(row=1, column=0, sticky="ns", padx=10, pady=10)

# #         kpi_frame = ctk.CTkFrame(left_panel)
# #         kpi_frame.pack(fill="x", expand=True, padx=5, pady=5)
# #         ctk.CTkLabel(kpi_frame, text="Trade Performance KPIs", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
# #         kpi_list = ["Total Trades", "Successful Trades", "Win Rate (%)", "Net P/L ($)", "Profit Factor", "Max Drawdown ($)", "Sharpe Ratio"]
# #         for kpi_name in kpi_list:
# #             frame = ctk.CTkFrame(kpi_frame, fg_color="transparent")
# #             frame.pack(fill="x", padx=10, pady=5)
# #             ctk.CTkLabel(frame, text=f"{kpi_name}:", anchor="w").pack(side="left")
# #             value_label = ctk.CTkLabel(frame, text="N/A", anchor="e")
# #             value_label.pack(side="right")
# #             self.kpi_labels[kpi_name] = value_label

# #         portfolio_frame = ctk.CTkFrame(left_panel)
# #         portfolio_frame.pack(fill="x", expand=True, padx=5, pady=15)
# #         ctk.CTkLabel(portfolio_frame, text="Portfolio Performance", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
# #         portfolio_list = {"Starting Value ($)": "N/A", "Current Value ($)": "N/A", "Portfolio P/L ($)": "N/A", "Portfolio Growth (%)": "N/A"}
# #         for name, default_val in portfolio_list.items():
# #             frame = ctk.CTkFrame(portfolio_frame, fg_color="transparent")
# #             frame.pack(fill="x", padx=10, pady=5)
# #             ctk.CTkLabel(frame, text=f"{name}:", anchor="w").pack(side="left")
# #             value_label = ctk.CTkLabel(frame, text=default_val, anchor="e")
# #             value_label.pack(side="right")
# #             self.portfolio_labels[name] = value_label
        
# #         self.portfolio_asset_breakdown_frame = ctk.CTkFrame(portfolio_frame)
# #         self.portfolio_asset_breakdown_frame.pack(fill="x", expand=True, padx=10, pady=10)
# #         ctk.CTkLabel(self.portfolio_asset_breakdown_frame, text="Asset Breakdown:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")

# #         chart_tab_view = ctk.CTkTabview(tab)
# #         chart_tab_view.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
# #         chart_tab_view.add("P/L Curve")
# #         chart_tab_view.add("Profit By Symbol")
# #         chart_tab_view.add("Trade Log")
        
# #         self.chart_frames = {
# #             "P/L Curve": chart_tab_view.tab("P/L Curve"),
# #             "Profit By Symbol": chart_tab_view.tab("Profit By Symbol"),
# #         }
# #         self.trade_log_frame = ctk.CTkScrollableFrame(chart_tab_view.tab("Trade Log"))
# #         self.trade_log_frame.pack(fill="both", expand=True)

# #     def build_market_scan_panel(self, parent):
# #         self.scan_outer_frame = ctk.CTkFrame(parent)
# #         self.scan_outer_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
# #         self.scan_outer_frame.grid_columnconfigure(0, weight=1)
# #         ctk.CTkLabel(self.scan_outer_frame, text="Live Market Scan", font=ctk.CTkFont(weight="bold")).pack()
# #         self.scan_frame = ctk.CTkScrollableFrame(self.scan_outer_frame, height=200)
# #         self.scan_frame.pack(fill="x", expand=True, padx=5, pady=5)
# #         if not self.bot: return
# #         self.market_data_labels: Dict[str, Dict[str, ctk.CTkLabel]] = {}
# #         clients = self.bot.exchange_manager.get_all_clients()
# #         headers = ["Symbol"] + [f"{name.capitalize()} {val}" for name in clients for val in ["Bid", "Ask"]] + ["Spread %"]
# #         self.scan_frame.grid_columnconfigure(list(range(len(headers))), weight=1)
# #         for i, header in enumerate(headers):
# #             ctk.CTkLabel(self.scan_frame, text=header, font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=5)
# #         for i, symbol in enumerate(self.config['trading_parameters']['symbols_to_scan']):
# #             row_index = i + 1
# #             self.market_data_labels[symbol] = {}
# #             symbol_label = ctk.CTkLabel(self.scan_frame, text=symbol, fg_color="transparent")
# #             symbol_label.grid(row=row_index, column=0, padx=5, pady=2, sticky="ew")
# #             self.market_data_labels[symbol]['symbol'] = symbol_label
# #             col_idx = 1
# #             for ex_name in clients:
# #                 for val in ["bid", "ask"]:
# #                     label = ctk.CTkLabel(self.scan_frame, text="-", fg_color="transparent")
# #                     label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
# #                     self.market_data_labels[symbol][f"{ex_name}_{val}"] = label
# #                     col_idx += 1
# #             spread_label = ctk.CTkLabel(self.scan_frame, text="-", fg_color="transparent")
# #             spread_label.grid(row=row_index, column=col_idx, padx=5, pady=2, sticky="ew")
# #             self.market_data_labels[symbol]['spread'] = spread_label

# #     def build_opportunity_history_panel(self, parent):
# #         self.opp_history_frame = ctk.CTkFrame(parent)
# #         self.opp_history_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
# #         ctk.CTkLabel(self.opp_history_frame, text="Recent Profitable Opportunities", font=ctk.CTkFont(weight="bold")).pack(pady=(5,5))
# #         self.opp_history_textbox = ctk.CTkTextbox(self.opp_history_frame, state="disabled", height=120, font=("Calibri", 12))
# #         self.opp_history_textbox.pack(fill="x", expand=True, padx=5, pady=5)
# #         self.opp_history_textbox.tag_config("profit", foreground="cyan")
    
# #     def _on_refresh_analysis_data(self):
# #         self.analysis_status_label.configure(text="Loading and analyzing trade data...")
# #         analyzer = PerformanceAnalyzer()
        
# #         if not analyzer.load_data():
# #             self.analysis_status_label.configure(text="Could not load trade data. Run bot to generate trades.csv.", text_color="orange")
# #             return

# #         kpis = analyzer.calculate_kpis()
# #         for name, label in self.kpi_labels.items():
# #             value = kpis.get(name, "N/A")
# #             label.configure(text=str(value))
# #             if name == "Net P/L ($)":
# #                 try:
# #                     profit_val = float(str(value).replace("$","").replace(",",""))
# #                     label.configure(text_color="green" if profit_val >= 0 else "red")
# #                 except (ValueError, TypeError):
# #                     label.configure(text_color="gray")
        
# #         self._embed_chart(analyzer.generate_equity_curve(), "P/L Curve")
# #         self._embed_chart(analyzer.generate_profit_by_symbol_chart(), "Profit By Symbol")
# #         self._populate_trade_log_table(analyzer.trades_df)
# #         self.analysis_status_label.configure(text="Analysis complete.", text_color="green")

# #     def _embed_chart(self, fig: Figure, chart_name: str):
# #         if chart_name in self.analysis_canvas_widgets and self.analysis_canvas_widgets[chart_name]:
# #             self.analysis_canvas_widgets[chart_name].get_tk_widget().destroy()
        
# #         parent_frame = self.chart_frames.get(chart_name)
# #         if parent_frame:
# #             canvas = FigureCanvasTkAgg(fig, master=parent_frame)
# #             canvas_widget = canvas.get_tk_widget()
# #             canvas_widget.pack(side="top", fill="both", expand=True, padx=5, pady=5)
# #             canvas.draw()
# #             self.analysis_canvas_widgets[chart_name] = canvas
    
# #     def _populate_trade_log_table(self, df: pd.DataFrame):
# #         for widget in self.trade_log_frame.winfo_children():
# #             widget.destroy()
            
# #         headers = ['Timestamp', 'Symbol', 'Buy Ex', 'Sell Ex', 'Net Profit ($)']
# #         self.trade_log_frame.grid_columnconfigure((0,1,2,3,4), weight=1)
# #         for i, header in enumerate(headers):
# #             ctk.CTkLabel(self.trade_log_frame, text=header, font=ctk.CTkFont(weight="bold")).grid(row=0, column=i, padx=5, pady=2)
        
# #         df_display = df[df['status'] == 'SUCCESS'].reset_index()
# #         for index, row in df_display.iterrows():
# #             ctk.CTkLabel(self.trade_log_frame, text=row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')).grid(row=index+1, column=0, padx=5, pady=2, sticky="w")
# #             ctk.CTkLabel(self.trade_log_frame, text=row['symbol']).grid(row=index+1, column=1, padx=5, pady=2)
# #             ctk.CTkLabel(self.trade_log_frame, text=row['buy_exchange']).grid(row=index+1, column=2, padx=5, pady=2)
# #             ctk.CTkLabel(self.trade_log_frame, text=row['sell_exchange']).grid(row=index+1, column=3, padx=5, pady=2)
# #             profit_label = ctk.CTkLabel(self.trade_log_frame, text=f"{row['net_profit_usd']:.4f}")
# #             profit_label.grid(row=index+1, column=4, padx=5, pady=2, sticky="e")
# #             profit_label.configure(text_color="green" if row['net_profit_usd'] > 0 else "red")
    
# #     def _update_portfolio_display(self, current_data: Dict):
# #         if not self.initial_portfolio_snapshot: return

# #         start_val = self.initial_portfolio_snapshot.get("total_usd_value", 0.0)
# #         current_val = current_data.get("total_usd_value", 0.0)
# #         pnl = current_val - start_val
# #         growth = (pnl / start_val * 100) if start_val > 0 else 0.0
        
# #         self.portfolio_labels["Starting Value ($)"].configure(text=f"${start_val:,.2f}")
# #         self.portfolio_labels["Current Value ($)"].configure(text=f"${current_val:,.2f}")
# #         self.portfolio_labels["Portfolio P/L ($)"].configure(text=f"${pnl:,.2f}", text_color="green" if pnl >= 0 else "red")
# #         self.portfolio_labels["Portfolio Growth (%)"].configure(text=f"{growth:.2f}%", text_color="green" if growth >= 0 else "red")

# #         for widget in self.portfolio_asset_breakdown_frame.winfo_children():
# #             if not isinstance(widget, ctk.CTkLabel) or widget.cget("text") != "Asset Breakdown:":
# #                 widget.destroy()

# #         all_assets = sorted(list(set(self.initial_portfolio_snapshot.get("assets", {}).keys()) | set(current_data.get("assets", {}).keys())))
# #         for asset in all_assets:
# #             start_asset = self.initial_portfolio_snapshot.get("assets", {}).get(asset, {"balance": 0.0, "value_usd": 0.0})
# #             current_asset = current_data.get("assets", {}).get(asset, {"balance": 0.0, "value_usd": 0.0})
            
# #             asset_frame = ctk.CTkFrame(self.portfolio_asset_breakdown_frame)
# #             asset_frame.pack(fill="x", pady=2)
# #             ctk.CTkLabel(asset_frame, text=asset, font=ctk.CTkFont(weight="bold"), width=60).pack(side="left", padx=5)
# #             ctk.CTkLabel(asset_frame, text=f"Start: ${start_asset['value_usd']:,.2f} ({start_asset['balance']:.4f})").pack(side="left", padx=10)
# #             ctk.CTkLabel(asset_frame, text=f"Now: ${current_asset['value_usd']:,.2f} ({current_asset['balance']:.4f})").pack(side="left", padx=10)
    
# #     def process_queue(self):
# #         try:
# #             for _ in range(100):
# #                 message = self.update_queue.get_nowait()
# #                 msg_type = message.get("type")
# #                 if msg_type == "initial_portfolio":
# #                     self.initial_portfolio_snapshot = message['data']
# #                     self._update_portfolio_display(message['data'])
# #                 elif msg_type == "portfolio_update":
# #                     self.update_balance_display(message['data']['balances'])
# #                     self._update_portfolio_display(message['data']['portfolio'])
# #                 elif msg_type == "balance_update":
# #                     self.update_balance_display(message['data'])
# #                 elif msg_type == "log":
# #                     level = message.get("level", "INFO")
# #                     self.log_textbox.configure(state="normal")
# #                     self.log_textbox.insert("end", f"{message['message']}\n", level)
# #                     self.log_textbox.configure(state="disabled")
# #                     self.log_textbox.see("end")
# #                 elif msg_type == "stats":
# #                     self.update_stats_display(**message['data'])
# #                 elif msg_type == "market_data":
# #                     self.update_market_data_display(message['data'])
# #                 elif msg_type == "opportunity_found":
# #                     self.add_opportunity_to_history(message['data'])
# #                 elif msg_type == "critical_error":
# #                     messagebox.showerror("Critical Runtime Error", message['data'])
# #                 elif msg_type == "stopped":
# #                     if not (self.bot_thread and self.bot_thread.is_alive()):
# #                         self.stop_bot()
# #         except queue.Empty:
# #             pass
# #         finally:
# #             self.after(100, self.process_queue)

# #     def add_opportunity_to_history(self, data: Dict[str, Any]):
# #         symbol = data.get('symbol', 'N/A')
# #         spread = data.get('spread_pct', 0.0)
# #         timestamp = time.strftime('%H:%M:%S')
# #         log_line = f"[{timestamp}] {symbol:<10} | Spread: {spread:.3f}%\n"
# #         self.opp_history_textbox.configure(state="normal")
# #         self.opp_history_textbox.insert("1.0", log_line, "profit")
# #         self.opp_history_textbox.configure(state="disabled")

# #     def setup_log_colors(self):
# #         self.log_textbox.tag_config("INFO", foreground="white")
# #         self.log_textbox.tag_config("WARNING", foreground="yellow")
# #         self.log_textbox.tag_config("ERROR", foreground="red")
# #         self.log_textbox.tag_config("CRITICAL", foreground="#ff4d4d")
# #         self.log_textbox.tag_config("TRADE", foreground="cyan")
# #         self.log_textbox.tag_config("SUCCESS", foreground="green")

# #     def start_bot(self):
# #         if not self.bot:
# #             messagebox.showerror("Error", "Bot could not be started.")
# #             return
        
# #         try:
# #             sizing_mode = self.sizing_mode_var.get()
# #             self.bot.config['trading_parameters']['sizing_mode'] = sizing_mode
            
# #             if sizing_mode == 'fixed':
# #                 trade_size = float(self.trade_size_entry.get())
# #                 if trade_size <= 0: raise ValueError("Fixed trade size must be positive.")
# #                 self.bot.config['trading_parameters']['trade_size_usdt'] = trade_size
# #                 self.logger.info(f"Sizing Mode: FIXED @ ${trade_size:.2f}")
# #             else: 
# #                 pct = float(self.dynamic_pct_entry.get())
# #                 max_size = float(self.dynamic_max_entry.get())
# #                 if not (0 < pct <= 100): raise ValueError("Percentage must be between 0 and 100.")
# #                 if max_size <= 0: raise ValueError("Max size must be positive.")
# #                 self.bot.config['trading_parameters']['dynamic_size_percentage'] = pct
# #                 self.bot.config['trading_parameters']['dynamic_size_max_usdt'] = max_size
# #                 self.logger.info(f"Sizing Mode: DYNAMIC ({pct}% of balance, max ${max_size:.2f})")
            
# #         except (ValueError, TypeError) as e:
# #             messagebox.showerror("Invalid Input", f"Please enter valid numbers for sizing parameters.\n\n{e}")
# #             return

# #         is_dry_run = self.dry_run_checkbox.get() == 1
# #         self.bot.config['trading_parameters']['dry_run'] = is_dry_run
# #         selected_symbols = [symbol for symbol, checkbox in self.symbol_checkboxes.items() if checkbox.get() == 1]
# #         if not selected_symbols:
# #             messagebox.showerror("Invalid Input", "Please select at least one symbol to trade.")
# #             return
        
# #         self.logger.info(f"--- Starting New Session ---")
# #         self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if is_dry_run else 'LIVE TRADING'}")
# #         self.logger.info(f"Symbols: {', '.join(selected_symbols)}")

# #         self.start_button.configure(state="disabled")
# #         self.stop_button.configure(state="normal")
# #         for radio in [self.fixed_radio, self.dynamic_radio]: radio.configure(state="disabled")
# #         self.trade_size_entry.configure(state="disabled")
# #         self.dynamic_pct_entry.configure(state="disabled")
# #         self.dynamic_max_entry.configure(state="disabled")
# #         self.dry_run_checkbox.configure(state="disabled")
# #         for checkbox in self.symbol_checkboxes.values():
# #             checkbox.configure(state="disabled")

# #         self.initial_portfolio_snapshot = None 
# #         with self.bot.state_lock:
# #             self.bot.session_profit, self.bot.trade_count, self.bot.successful_trades = 0.0, 0, 0
# #             self.bot.failed_trades, self.bot.neutralized_trades, self.bot.critical_failures = 0, 0, 0
# #         self.update_stats_display(**self.bot._get_current_stats())
# #         self.bot_thread = threading.Thread(target=self.bot.run, args=(selected_symbols,), daemon=True)
# #         self.bot_thread.start()
# #         self.update_runtime_clock()

# #     def stop_bot(self):
# #         self.start_button.configure(state="normal")
# #         self.stop_button.configure(state="disabled")
# #         for radio in [self.fixed_radio, self.dynamic_radio]: radio.configure(state="normal")
# #         self.trade_size_entry.configure(state="normal")
# #         self.dynamic_pct_entry.configure(state="normal")
# #         self.dynamic_max_entry.configure(state="normal")
# #         self.dry_run_checkbox.configure(state="normal")
# #         for checkbox in self.symbol_checkboxes.values():
# #             checkbox.configure(state="normal")

# #         self.status_label.configure(text="Status: STOPPING...", text_color="orange")
# #         if self.bot:
# #             self.bot.stop()
# #             if self.bot_thread and self.bot_thread.is_alive():
# #                 self.logger.info("Waiting for bot thread to terminate...")
# #                 self.bot_thread.join(timeout=10)
# #         self.status_label.configure(text="Status: STOPPED", text_color="red")
# #         self.runtime_label.configure(text="00:00:00")
# #         self.logger.info("Bot shutdown complete.")

# #     def update_stats_display(self, trades: int, successful: int, failed: int, neutralized: int, critical: int, profit: float):
# #         self.trades_value.configure(text=f"{trades}")
# #         completed_trades = successful + failed + neutralized
# #         win_rate = (successful / completed_trades * 100) if completed_trades > 0 else 0
# #         avg_profit = (profit / successful) if successful > 0 else 0
# #         self.win_rate_value.configure(text=f"{win_rate:.2f}%")
# #         self.avg_profit_value.configure(text=f"${avg_profit:,.4f}")
# #         profit_color = "green" if profit >= 0 else "red"
# #         self.profit_value.configure(text=f"${profit:,.2f}", text_color=profit_color)
# #         self.failed_value.configure(text=f"{failed} / {neutralized}")
# #         self.critical_value.configure(text=f"{critical}")

# #     def update_runtime_clock(self):
# #         if self.bot and self.bot.running:
# #             uptime_seconds = int(time.time() - self.bot.start_time)
# #             hours, remainder = divmod(uptime_seconds, 3600)
# #             minutes, seconds = divmod(remainder, 60)
# #             self.runtime_label.configure(text=f"{hours:02}:{minutes:02}:{seconds:02}")
# #             self.after(1000, self.update_runtime_clock)
    
# #     def update_balance_display(self, balance_data: Dict[str, Any]):
# #         for widget in self.balance_frame.winfo_children():
# #             widget.destroy()

# #         self.balance_frame.grid_columnconfigure(0, weight=1)

# #         row_counter = 0
# #         for ex_name, assets in sorted(balance_data.items()):
# #             ex_label = ctk.CTkLabel(self.balance_frame, text=f"{ex_name.capitalize()}", font=ctk.CTkFont(underline=True))
# #             ex_label.grid(row=row_counter, column=0, padx=10, pady=(8, 2), sticky="w")
# #             row_counter += 1
            
# #             if not assets:
# #                 no_funds_label = ctk.CTkLabel(self.balance_frame, text="  - No funds found", text_color="gray")
# #                 no_funds_label.grid(row=row_counter, column=0, padx=15, sticky="w")
# #                 row_counter += 1
# #             else:
# #                 for asset, amount in sorted(assets.items()):
# #                     # Ensure amount is a number before formatting
# #                     amount_val = amount if isinstance(amount, (int, float)) else 0.0
# #                     asset_label = ctk.CTkLabel(self.balance_frame, text=f"  - {asset}: {amount_val:.6f}")
# #                     asset_label.grid(row=row_counter, column=0, padx=15, pady=1, sticky="w")
# #                     row_counter += 1
                    
# #     def update_market_data_display(self, data: Dict[str, Any]):
# #         if not self.bot: return
# #         try:
# #             symbol = data.get('symbol')
# #             if hasattr(self, 'market_data_labels') and self.market_data_labels and symbol in self.market_data_labels:
# #                 labels = self.market_data_labels[symbol]
# #                 clients = self.bot.exchange_manager.get_all_clients()
                
# #                 for ex_name in clients:
# #                     bid_val = data.get(f'{ex_name}_bid')
# #                     ask_val = data.get(f'{ex_name}_ask')
# #                     if f'{ex_name}_bid' in labels: labels[f'{ex_name}_bid'].configure(text=f"{bid_val:.4f}" if bid_val is not None else "-")
# #                     if f'{ex_name}_ask' in labels: labels[f'{ex_name}_ask'].configure(text=f"{ask_val:.4f}" if ask_val is not None else "-")

# #                 spread_pct = data.get('spread_pct')
# #                 is_profitable = data.get('is_profitable', False)
# #                 spread_label = labels['spread']
                
# #                 if spread_pct is not None:
# #                     default_text_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]
# #                     spread_color = "green" if spread_pct > 0 else "red"
# #                     if spread_pct == 0: spread_color = default_text_color
# #                     spread_label.configure(text=f"{spread_pct:.3f}%", text_color=spread_color)
# #                 else:
# #                     spread_label.configure(text="-")

# #                 highlight_color = "#1E4D2B" if is_profitable else "transparent" 
                
# #                 # Highlight the entire row
# #                 for label_widget in labels.values():
# #                    label_widget.configure(fg_color=highlight_color)

# #         except Exception as e:
# #             self.logger.warning(f"Failed to update GUI for market data. Error: {e}", exc_info=False)