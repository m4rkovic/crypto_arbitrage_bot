# gui_components/gui_application.py
import threading
import queue
import logging
import time
from typing import Any, Dict, Optional
import customtkinter as ctk
from tkinter import messagebox

from bot_engine import ArbitrageBot
from core.utils import ConfigError, ExchangeInitError
from gui_components.left_panel import LeftPanel
from gui_components.live_ops_tab import LiveOpsTab
from core.trade_executor import TradeExecutor
from core.exchange_manager import ExchangeManager
from core.risk_manager import RiskManager

class QueueHandler(logging.Handler):
    def __init__(self, queue: queue.Queue):
        super().__init__()
        self.queue = queue
    def emit(self, record):
        self.queue.put({"type": "log", "level": record.levelname, "message": self.format(record)})

class App(ctk.CTk):
    def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any]):
        super().__init__()

        # --- Window setup ---
        self.title("Arbitrage Bot Control Center")
        self.geometry("1600x900")
        ctk.set_appearance_mode("dark")

        # --- Config & logging ---
        self.config = config
        self.update_queue: queue.Queue = queue.Queue()
        self.logger = logging.getLogger()
        self.add_gui_handler_to_logger()

        # --- Core components ---
        self.exchange_manager = ExchangeManager(exchanges_config)
        self.risk_manager = RiskManager(self.config, self.exchange_manager)
        self.analyzer = None
        self.trade_executor = TradeExecutor(self.exchange_manager)

        # --- Engine ---
        self.engine = ArbitrageBot(
            exchange_manager=self.exchange_manager,
            analyzer=self.analyzer,
            risk_manager=self.risk_manager,
            trade_executor=self.trade_executor,
            poll_interval_sec=0.75,
            gui_callbacks={
                "on_status": self.on_engine_status,
                "on_market_snapshot": self.on_market_snapshot,
                "on_opportunities": self.on_opportunities,
                "on_trade_started": self.on_trade_started,
                "on_trade_update": self.on_trade_update,
                "on_trade_finished": self.on_trade_finished,
                "on_error": self.on_engine_error,
            },
        )
        self.engine.config = dict(config)  # allow param updates

        # --- UI ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.create_widgets()
        self.process_queue()

    # ---------- ENGINE CALLBACKS ----------
    def on_engine_status(self, status: str):
        self.logger.info(f"[ENGINE STATUS] {status}")
        self.left_panel.set_status(status.upper(), "green" if status == "ok" else "orange")

    def on_engine_error(self, error: str):
        self.logger.error(f"[ENGINE ERROR] {error}")
        messagebox.showerror("Engine Error", error)

    def on_market_snapshot(self, snapshot: dict):
        # Optional: keep for future analyzer output
        pass

    def on_opportunities(self, opps: list[dict]):
        for o in opps:
            self.live_ops_tab.add_opportunity_to_history(o)

    def on_trade_started(self, data: dict):
        self.logger.info(f"Trade started: {data}")
        self.live_ops_tab.add_log_message("INFO", f"Trade started: {data}")

    def on_trade_update(self, data: dict):
        msg = data.get("message", str(data))
        self.live_ops_tab.add_log_message("INFO", msg)

    def on_trade_finished(self, result: dict):
        self.logger.info(f"Trade finished: {result}")
        self.live_ops_tab.add_log_message("SUCCESS", f"Trade finished: {result}")

    # ---------- UI WIRING ----------
    def add_gui_handler_to_logger(self):
        queue_handler = QueueHandler(self.update_queue)
        queue_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logging.getLogger().addHandler(queue_handler)

    def create_widgets(self):
        self.left_panel = LeftPanel(self, self.config, self.start_bot, self.stop_bot)
        self.left_panel.grid(row=0, column=0, sticky="nsw")

        right_frame = ctk.CTkFrame(self)
        right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        tab_view = ctk.CTkTabview(right_frame)
        tab_view.pack(expand=True, fill="both", padx=5, pady=5)
        tab_view.add("Live Operations")
        self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"), self.config, self.engine)

    def process_queue(self):
        try:
            for _ in range(100):
                message = self.update_queue.get_nowait()
                msg_type = message.get("type")

                if msg_type == "balance_update":
                    self.left_panel.update_balance_display(message["data"])
                elif msg_type == "log":
                    self.live_ops_tab.add_log_message(message.get("level", "INFO"), message["message"])
                elif msg_type == "stats":
                    self.left_panel.update_stats_display(**message["data"])
                elif msg_type == "market_data":
                    self.live_ops_tab.update_market_data_display(message["data"])
                elif msg_type == "opportunity_found":
                    self.live_ops_tab.add_opportunity_to_history(message["data"])
                elif msg_type == "critical_error":
                    messagebox.showerror("Critical Runtime Error", message["data"])
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    # ---------- START / STOP ----------
    def start_bot(self):
        # 1) Pull parameters
        try:
            params = self.left_panel.get_start_parameters()
            self.engine.config.setdefault("trading_parameters", {}).update(params)
            self.logger.info("--- Starting New Session ---")
            self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if params['dry_run'] else 'LIVE TRADING'}")
            if params["sizing_mode"] == "fixed":
                self.logger.info(f"Sizing Mode: FIXED @ ${params['trade_size_usdt']:.2f}")
            else:
                self.logger.info(
                    f"Sizing Mode: DYNAMIC ({params['dynamic_size_percentage']}% of balance, max ${params['dynamic_size_max_usdt']:.2f})"
                )
            self.logger.info(f"Symbols: {', '.join(params['selected_symbols'])}")
        except (ValueError, TypeError) as e:
            messagebox.showerror("Invalid Input", str(e))
            return

        # 2) Immediate UI hydration (balances + zeroed stats)
        try:
            balances = self.exchange_manager.get_all_balances()
            if balances:
                self.left_panel.update_balance_display(balances)
        except Exception as e:
            self.logger.warning(f"Could not update wallet balances: {e}")

        self.left_panel.update_stats_display(
            session_profit=0.0, trade_count=0, win_rate=None, avg_profit=0.0,
            failed_trades=0, neutralized_trades=0, critical_failures=0
        )

        # 3) Disable controls and start engine
        self.left_panel.set_controls_state(False)
        self.engine.start()

        # 4) Start periodic refresh for balances + live scan table
        self.after(1000, self._refresh_gui_data)

    def stop_bot(self):
        self.left_panel.set_status("STOPPING...", "orange")
        if self.engine:
            self.engine.stop()
        self.left_panel.set_controls_state(True)
        self.left_panel.set_status("STOPPED", "red")
        self.left_panel.update_runtime_clock(0)
        self.logger.info("Bot shutdown complete.")

    # ---------- PERIODIC REFRESH ----------
    def _refresh_gui_data(self):
        """Refresh wallet balances and live market table while engine runs."""
        try:
            # Balances
            balances = self.exchange_manager.get_all_balances()
            if balances:
                self.left_panel.update_balance_display(balances)

            # Live scan rows
            tp = self.engine.config.get("trading_parameters", {})
            trade_size = float(
                tp.get("trade_size_usdt")
                if tp.get("sizing_mode", "fixed") == "fixed"
                else tp.get("dynamic_size_max_usdt", 50.0)  # fallback
            )

            symbols = tp.get("selected_symbols") or tp.get("symbols_to_scan") or []
            clients = self.exchange_manager.get_all_clients().keys()

            for sym in symbols:
                md = self.exchange_manager.get_market_data(sym, trade_size)
                # flatten for the LiveOpsTab
                row: Dict[str, Any] = {"symbol": sym}
                best_bid = None
                best_ask = None
                for ex in clients:
                    bid = md.get(ex, {}).get("bid")
                    ask = md.get(ex, {}).get("ask")
                    if bid is not None:
                        best_bid = bid if best_bid is None else max(best_bid, bid)
                    if ask is not None:
                        best_ask = ask if best_ask is None else min(best_ask, ask)
                    row[f"{ex}_bid"] = bid
                    row[f"{ex}_ask"] = ask

                spread_pct = None
                is_profitable = False
                if best_bid is not None and best_ask is not None and best_ask > 0:
                    spread_pct = (best_bid - best_ask) / best_ask * 100.0
                    is_profitable = spread_pct > float(tp.get("min_profit_usd", 0))  # simple flag

                row["spread_pct"] = spread_pct
                row["is_profitable"] = is_profitable
                self.live_ops_tab.update_market_data_display(row)

            # Runtime clock
            if getattr(self.engine, "is_running", None) and self.engine.is_running():
                uptime_seconds = int(time.time() - getattr(self.engine, "start_time", time.time()))
                self.left_panel.update_runtime_clock(uptime_seconds)
                self.after(2000, self._refresh_gui_data)
        except Exception as e:
            self.logger.warning(f"GUI refresh failed: {e}")
            if self.engine.is_running():
                self.after(3000, self._refresh_gui_data)

# #gui_application.py

# import threading
# import queue
# import logging
# import time
# from typing import Any, Dict, Optional
# import customtkinter as ctk
# from tkinter import messagebox

# from bot_engine import ArbitrageBot
# from core.utils import ConfigError, ExchangeInitError
# from gui_components.left_panel import LeftPanel
# from gui_components.live_ops_tab import LiveOpsTab
# # from gui_components.analysis_tab import AnalysisTab
# from core.trade_executor import TradeExecutor
# from core.exchange_manager import ExchangeManager
# # from core.analyzer import Analyzer
# from core.risk_manager import RiskManager


# class QueueHandler(logging.Handler):
#     """Custom logging handler to route log records to the GUI queue."""
#     def __init__(self, queue: queue.Queue):
#         super().__init__()
#         self.queue = queue

#     def emit(self, record):
#         self.queue.put({
#             "type": "log",
#             "level": record.levelname,
#             "message": self.format(record)
#         })


# class App(ctk.CTk):
#     """
#     The main application class. It initializes the bot engine, builds the main UI structure,
#     and handles communication between the engine and GUI components.
#     """

#     def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any]):
#         super().__init__()

#         # --- Window setup ---
#         self.title("Arbitrage Bot Control Center")
#         self.geometry("1600x900")
#         ctk.set_appearance_mode("dark")

#         # --- Config & logging ---
#         self.config = config
#         self.update_queue: queue.Queue = queue.Queue()
#         self.logger = logging.getLogger()
#         self.add_gui_handler_to_logger()

#         # --- Core trading components (before engine) ---
#         self.exchange_manager = ExchangeManager(exchanges_config)
#         self.risk_manager = RiskManager(self.config, self.exchange_manager)
#         self.analyzer = None  # disabled for now
#         self.trade_executor = TradeExecutor(self.exchange_manager)

#         # --- Engine initialization ---
#         self.engine = ArbitrageBot(
#             exchange_manager=self.exchange_manager,
#             analyzer=self.analyzer,
#             risk_manager=self.risk_manager,
#             trade_executor=self.trade_executor,
#             poll_interval_sec=0.75,
#             gui_callbacks={
#                 "on_status": self.on_engine_status,
#                 "on_market_snapshot": self.on_market_snapshot,
#                 "on_opportunities": self.on_opportunities,
#                 "on_trade_started": self.on_trade_started,
#                 "on_trade_update": self.on_trade_update,
#                 "on_trade_finished": self.on_trade_finished,
#                 "on_error": self.on_engine_error,
#             },
#             config=self.config
#         )

#         # --- State ---
#         self.bot_thread: Optional[threading.Thread] = None
#         self.initial_portfolio_snapshot: Optional[Dict[str, Any]] = None

#         # --- Layout setup ---
#         self.grid_columnconfigure(1, weight=1)
#         self.grid_rowconfigure(0, weight=1)
#         self.create_widgets()
#         self.process_queue()

#     # ---------------------------------------------------
#     # ENGINE CALLBACKS
#     # ---------------------------------------------------
#     def on_engine_status(self, status: str):
#         """Called by engine when status changes."""
#         self.logger.info(f"[ENGINE STATUS] {status}")
#         self.left_panel.set_status(status.upper(), "green" if status == "ok" else "orange")

#     def on_engine_error(self, error: str):
#         """Called by engine when an error occurs."""
#         self.logger.error(f"[ENGINE ERROR] {error}")
#         messagebox.showerror("Engine Error", error)

#     def on_market_snapshot(self, snapshot: dict):
#         """Market data update (optional)."""
#         try:
#             self.live_ops_tab.update_market_data_display(snapshot)
#         except Exception:
#             pass

#     def on_opportunities(self, opps: list[dict]):
#         """List of detected opportunities."""
#         for o in opps:
#             self.live_ops_tab.add_opportunity_to_history(o)

#     def on_trade_started(self, data: dict):
#         self.logger.info(f"Trade started: {data}")
#         self.live_ops_tab.add_log_message("INFO", f"Trade started: {data}")

#     def on_trade_update(self, data: dict):
#         msg = data.get("message", str(data))
#         self.live_ops_tab.add_log_message("INFO", msg)

#     def on_trade_finished(self, result: dict):
#         self.logger.info(f"Trade finished: {result}")
#         self.live_ops_tab.add_log_message("SUCCESS", f"Trade finished: {result}")

#     # ---------------------------------------------------

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

#         # --- Instantiate Tabs ---
#         self.live_ops_tab = LiveOpsTab(tab_view.tab("Live Operations"), self.config, self.engine)

#     def process_queue(self):
#         """
#         The heart of the GUI. Processes messages from the engine's queue
#         and dispatches them to the appropriate UI component for updates.
#         """
#         try:
#             for _ in range(100):  # Process up to 100 messages per cycle
#                 message = self.update_queue.get_nowait()
#                 msg_type = message.get("type")

#                 if msg_type == "balance_update":
#                     self.left_panel.update_balance_display(message["data"])
#                 elif msg_type == "log":
#                     self.live_ops_tab.add_log_message(message.get("level", "INFO"), message["message"])
#                 elif msg_type == "stats":
#                     self.left_panel.update_stats_display(**message["data"])
#                 elif msg_type == "market_data":
#                     self.live_ops_tab.update_market_data_display(message["data"])
#                 elif msg_type == "opportunity_found":
#                     self.live_ops_tab.add_opportunity_to_history(message["data"])
#                 elif msg_type == "critical_error":
#                     messagebox.showerror("Critical Runtime Error", message["data"])
#                 elif msg_type == "stopped":
#                     if not (self.bot_thread and self.bot_thread.is_alive()):
#                         self.stop_bot()

#         except queue.Empty:
#             pass
#         finally:
#             self.after(100, self.process_queue)

#     def start_bot(self):
#         try:
#             balances = self.exchange_manager.get_all_balances()
#             if balances:
#                 self.left_panel.update_balance_display(balances)
#         except Exception as e:
#             print(f"[WARN] Could not update wallet balances: {e}")

#         # Initialize stats immediately
#         try:
#             stats = self.engine._get_current_stats()
#             if stats:
#                 self.left_panel.update_stats_display(**stats)
#         except Exception as e:
#             print(f"[WARN] Could not update stats: {e}")

#         """Handles the logic for starting the arbitrage bot thread."""
#         try:
#             params = self.left_panel.get_start_parameters()
#             self.engine.config["trading_parameters"].update(params)

#             self.logger.info("--- Starting New Session ---")
#             self.logger.info(f"Mode: {'DRY RUN (SIMULATION)' if params['dry_run'] else 'LIVE TRADING'}")

#             if params["sizing_mode"] == "fixed":
#                 self.logger.info(f"Sizing Mode: FIXED @ ${params['trade_size_usdt']:.2f}")
#             else:
#                 self.logger.info(
#                     f"Sizing Mode: DYNAMIC ({params['dynamic_size_percentage']}% of balance, max ${params['dynamic_size_max_usdt']:.2f})"
#                 )

#             self.logger.info(f"Symbols: {', '.join(params['selected_symbols'])}")

#         except (ValueError, TypeError) as e:
#             messagebox.showerror("Invalid Input", str(e))
#             return

#         # Disable UI controls
#         self.left_panel.set_controls_state(False)

#         # Reset bot stats and start thread
#         self.initial_portfolio_snapshot = None
#         with self.engine.state_lock:
#             self.engine.session_profit = 0.0
#             self.engine.trade_count = 0
#             self.engine.successful_trades = 0
#             self.engine.failed_trades = 0
#             self.engine.neutralized_trades = 0
#             self.engine.critical_failures = 0

#         self.left_panel.update_stats_display(**self.engine._get_current_stats())

#         self.bot_thread = threading.Thread(
#             target=self.engine.run,
#             args=(params["selected_symbols"],),
#             daemon=True
#         )
#         self.bot_thread.start()
#         self.update_runtime_clock()
#         self.after(5000, self._refresh_gui_data)


#     def stop_bot(self):
#         """Handles the logic for stopping the arbitrage bot."""
#         self.left_panel.set_status("STOPPING...", "orange")
#         if self.engine:
#             self.engine.stop()
#             if self.bot_thread and self.bot_thread.is_alive():
#                 self.logger.info("Waiting for bot thread to terminate...")
#                 self.bot_thread.join(timeout=10)

#         self.left_panel.set_controls_state(True)
#         self.left_panel.set_status("STOPPED", "red")
#         self.left_panel.update_runtime_clock(0)
#         self.logger.info("Bot shutdown complete.")

#     def _refresh_gui_data(self):
#         """Periodically refresh balances and market data."""
#         if not self.engine or not self.engine.running:
#             return

#         try:
#             # --- Update wallet balances ---
#             balances = self.exchange_manager.get_all_balances()
#             if balances:
#                 self.left_panel.update_balance_display(balances)
#         except Exception as e:
#             self.logger.warning(f"GUI refresh: Failed to fetch balances: {e}")

#         try:
#             # --- Update live market data ---
#             for symbol in self.config["trading_parameters"]["symbols_to_scan"]:
#                 market_data = self.exchange_manager.get_market_data(symbol, 20.0)
#                 snapshot = {"symbol": symbol}
#                 for ex_name, values in market_data.items():
#                     snapshot[f"{ex_name}_bid"] = values.get("bid")
#                     snapshot[f"{ex_name}_ask"] = values.get("ask")
#                 self.live_ops_tab.update_market_data_display(snapshot)
#         except Exception as e:
#             self.logger.warning(f"GUI refresh: Failed to fetch market data: {e}")

#         self.after(6000, self._refresh_gui_data)


#     def update_runtime_clock(self):
#         """Periodically updates the runtime clock on the GUI."""
#         if self.engine and self.engine.running:
#             uptime_seconds = int(time.time() - self.engine.start_time)
#             self.left_panel.update_runtime_clock(uptime_seconds)
#             self.after(1000, self.update_runtime_clock)
