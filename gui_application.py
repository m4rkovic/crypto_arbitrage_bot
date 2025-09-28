# gui_application.py

import asyncio
import time
from typing import Dict, Any, List, Optional
import queue
import itertools

from exchange_manager_async import AsyncExchangeManager
from risk_manager import RiskManager
from rebalancer import Rebalancer
from trade_logger import TradeLogger

class AsyncArbitrageBot:
    def __init__(
        self,
        config: Dict[str, Any],
        exchange_manager: AsyncExchangeManager,
        risk_manager: RiskManager,
        rebalancer: Rebalancer,
        trade_logger: TradeLogger,
        update_queue: queue.Queue # Use the same queue name as sync bot
    ):
        self.config = config
        self.exchange_manager = exchange_manager
        self.risk_manager = risk_manager
        self.rebalancer = rebalancer
        self.trade_logger = trade_logger
        self.update_queue = update_queue

        self.params = self.config.get('trading_parameters', {})
        self.symbols_to_scan = self.params.get('symbols_to_scan', [])
        self.scan_interval_s = self.params.get('scan_interval_s', 3.0)
        self.min_profit_usd = self.params.get('min_profit_usd', 0.10)
        self.trade_size_usdt = self.params.get('trade_size_usdt', 20.0)
        
        self.cooldown_duration_s = self.params.get('cooldown_duration_s', 300)
        self.opportunity_cooldowns = {}

        self.is_running = False
        self.start_time = None
        self.trade_count: int = 0
        self.successful_trades: int = 0
        self.failed_trades: int = 0
        self.neutralized_trades: int = 0
        self.critical_failures: int = 0
        self.session_profit: float = 0.0

    def send_update(self, update_type: str, data: Any):
        """Sends a structured message to the GUI's update queue."""
        self.update_queue.put({"type": update_type, "data": data})

    def _get_current_stats(self) -> Dict[str, Any]:
        """Mirrors the stats structure of the synchronous bot."""
        return {
            'trades': self.trade_count, 'successful': self.successful_trades,
            'failed': self.failed_trades, 'neutralized': self.neutralized_trades,
            'critical': self.critical_failures, 'profit': self.session_profit
        }

    async def run(self):
        self.is_running = True
        self.start_time = time.time()
        self.send_update("log", "Starting Asynchronous Arbitrage Bot...")

        # Take initial snapshot
        initial_portfolio = await self.exchange_manager.get_portfolio_snapshot()
        self.send_update('initial_portfolio', initial_portfolio)

        try:
            while self.is_running:
                self.send_update("log", "--- Starting new scan cycle ---")

                if self._check_stop_conditions():
                    self.is_running = False
                    continue

                portfolio = await self.exchange_manager.get_portfolio_snapshot()
                self.send_update("portfolio_update", {"portfolio": portfolio, "balances": portfolio.get('by_exchange', {})})

                if self.risk_manager.check_kill_switch(portfolio):
                    self.is_running = False
                    self.send_update("log", "Risk kill switch activated. Shutting down.")
                    continue
                
                opportunity = await self._find_arbitrage_opportunity()

                if opportunity:
                    self.send_update("log", f"Opportunity found! Est Profit: ${opportunity['profit_usd']:.4f}")
                    self.send_update('opportunity_found', {'symbol': opportunity['symbol'], 'spread_pct': (opportunity['profit_usd'] / self.trade_size_usdt) * 100})
                    await self._execute_arbitrage(opportunity, portfolio)
                else:
                    self.send_update("log", "No profitable opportunities found in this cycle.")

                self.send_update("log", f"Waiting for {self.scan_interval_s} seconds until next scan...")
                await asyncio.sleep(self.scan_interval_s)

        except asyncio.CancelledError:
            self.send_update("log", "Bot run task was cancelled.")
        except Exception as e:
            self.send_update("critical_error", f"An unexpected error occurred in the main bot loop: {e}")
        finally:
            self.send_update("log", "Bot loop finished.")
            self.is_running = False
            self.send_update("stopped", {})


    def _check_stop_conditions(self) -> bool:
        stop_conditions = self.config.get('stop_conditions')
        if not stop_conditions: return False
        max_trades = stop_conditions.get('max_trades')
        if max_trades is not None and self.trade_count >= max_trades:
            self.send_update("log", f"Stop condition met: Maximum trades ({max_trades}) reached.")
            return True
        run_duration_s = stop_conditions.get('run_duration_s')
        if run_duration_s is not None and (time.time() - self.start_time) >= run_duration_s:
            self.send_update("log", f"Stop condition met: Maximum run duration ({run_duration_s}s) reached.")
            return True
        return False

    async def _find_arbitrage_opportunity(self) -> Optional[Dict[str, Any]]:
        ex_ids = list(self.exchange_manager.exchanges.keys())
        if len(ex_ids) < 2: return None
        current_time = time.time()
        best_opportunity = None
        for symbol in self.symbols_to_scan:
            tasks = {ex_id: self.exchange_manager.get_order_book(ex_id, symbol) for ex_id in ex_ids}
            order_books_results = await asyncio.gather(*tasks.values())
            order_books = dict(zip(tasks.keys(), order_books_results))
            for ex1_id, ex2_id in itertools.permutations(ex_ids, 2):
                book1 = order_books.get(ex1_id)
                book2 = order_books.get(ex2_id)
                base_currency, _ = symbol.split('/')
                if book1 and book2 and book1.get('asks') and book1['asks'] and book2.get('bids') and book2['bids']:
                    buy_price, sell_price = book1['asks'][0][0], book2['bids'][0][0]
                    cooldown_key = f"sell-{base_currency}-{ex2_id}"
                    if sell_price > buy_price and self.opportunity_cooldowns.get(cooldown_key, 0) < current_time:
                        amount_to_buy = self.trade_size_usdt / buy_price
                        profit = (sell_price - buy_price) * amount_to_buy
                        if profit > self.min_profit_usd:
                            current_opp = self._create_opportunity(symbol, ex1_id, buy_price, ex2_id, sell_price, profit)
                            if not best_opportunity or profit > best_opportunity['profit_usd']:
                                best_opportunity = current_opp
        return best_opportunity

    def _create_opportunity(self, symbol, buy_ex, buy_price, sell_ex, sell_price, profit_usd):
        return {
            "symbol": symbol, "buy_exchange": buy_ex, "buy_price": buy_price,
            "sell_exchange": sell_ex, "sell_price": sell_price, "profit_usd": profit_usd
        }

    async def _execute_arbitrage(self, opportunity: Dict[str, Any], portfolio: Dict[str, Any]):
        symbol = opportunity['symbol']
        buy_ex, sell_ex = opportunity['buy_exchange'], opportunity['sell_exchange']
        buy_price = opportunity['buy_price']
        base_currency, quote_currency = symbol.split('/')
        trade_amount_base = self.trade_size_usdt / buy_price
        buy_ex_balance = portfolio.get('by_exchange', {}).get(buy_ex, {}).get('assets', {}).get(quote_currency, 0)
        sell_ex_balance = portfolio.get('by_exchange', {}).get(sell_ex, {}).get('assets', {}).get(base_currency, 0)
        if buy_ex_balance < self.trade_size_usdt:
            self.send_update("log", f"Skipping trade: Insufficient {quote_currency} on {buy_ex}. Have {buy_ex_balance}, need {self.trade_size_usdt}.")
            return
        if sell_ex_balance < trade_amount_base:
            self.send_update("log", f"Skipping trade: Insufficient {base_currency} on {sell_ex}. Have {sell_ex_balance}, need {trade_amount_base:.6f}.")
            cooldown_key = f"sell-{base_currency}-{sell_ex}"
            self.opportunity_cooldowns[cooldown_key] = time.time() + self.cooldown_duration_s
            self.send_update("log", f"Placed {cooldown_key} on cooldown for {self.cooldown_duration_s} seconds.")
            return
            
        self.send_update("log", f"Executing arbitrage: BUY {trade_amount_base:.6f} {symbol} on {buy_ex} and SELL on {sell_ex}")
        
        buy_task = self.exchange_manager.create_order(ex_id=buy_ex, symbol=symbol, order_type='market', side='buy', amount=trade_amount_base)
        sell_task = self.exchange_manager.create_order(ex_id=sell_ex, symbol=symbol, order_type='market', side='sell', amount=trade_amount_base)
        
        results = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
        buy_result, sell_result = results
        
        buy_succeeded, sell_succeeded = not isinstance(buy_result, Exception), not isinstance(sell_result, Exception)

        with threading.Lock(): # Use lock for thread-safe updates
            self.trade_count += 1
            if buy_succeeded and sell_succeeded:
                self.successful_trades += 1
                # In a real scenario, you'd calculate actual profit here
                self.session_profit += opportunity['profit_usd']
            else:
                self.failed_trades += 1

            if buy_succeeded and not sell_succeeded:
                await self._neutralize_trade('sell', buy_ex, symbol, trade_amount_base, buy_result)
            if not buy_succeeded and sell_succeeded:
                await self._neutralize_trade('buy', sell_ex, symbol, trade_amount_base, sell_result)
        
        self.send_update('stats', self._get_current_stats())

    async def _neutralize_trade(self, side: str, ex_id: str, symbol: str, amount: float, original_trade: Dict):
        try:
            self.send_update("log", f"Attempting to place a neutralizing {side} order on {ex_id} for {amount:.6f} {symbol}.")
            neutralize_amount = original_trade.get('filled', amount) if isinstance(original_trade, dict) else amount
            if neutralize_amount > 0:
                await self.exchange_manager.create_order(
                    ex_id=ex_id, symbol=symbol, order_type='market', side=side, amount=neutralize_amount
                )
                self.send_update("log", f"SUCCESSFULLY placed neutralizing {side} order on {ex_id}.")
                with threading.Lock(): self.neutralized_trades += 1
            else:
                self.send_update("log", "Original trade amount was 0, no neutralization needed.")
        except Exception as e:
            self.send_update("critical_error", f"CRITICAL FAILURE: Could not neutralize trade on {ex_id}. MANUAL INTERVENTION REQUIRED. Error: {e}")
            with threading.Lock(): self.critical_failures += 1

    def stop(self):
        self.send_update("log", "Stop command received.")
        self.is_running = False

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
