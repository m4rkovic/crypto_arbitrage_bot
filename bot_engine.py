# bot_engine.py

import asyncio
import time
import logging
import os

from queue import Queue
from dotenv import load_dotenv

from exchange_manager import ExchangeManager
from trade_executor import TradeExecutor
from performance_analyzer import PerformanceAnalyzer
from risk_manager import RiskManager
from trade_logger import TradeLogger
from data_models import Opportunity
import threading 

class ArbitrageBot:
    """
    The core asynchronous engine for the crypto arbitrage bot.
    """
    def __init__(self, config: dict, exchanges_config: dict, update_queue: Queue):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing asynchronous bot engine...")
        
        self.config = config
        self.update_queue = update_queue
        self.is_running = False
        self.start_time = 0
        self.state_lock = threading.Lock()

        # This now uses the dictionary passed directly from main.py
        self.exchange_manager = ExchangeManager(exchanges_config)
        
        # The rest of the components
        self.analyzer = PerformanceAnalyzer()
        self.risk_manager = RiskManager(config, self.exchange_manager)
        self.trade_logger = TradeLogger("trades.csv")
        self.trade_executor = TradeExecutor(config, self.exchange_manager, self.trade_logger)

        self.last_update_time = 0
        self.update_interval = self.config['trading_parameters'].get('update_frequency', 1.0)

    # def __init__(self, config: dict, update_queue: Queue):
    #     self.logger = logging.getLogger(__name__)
    #     self.logger.info("Initializing asynchronous bot engine...")
    #     self.start_time = 0
        
    #     load_dotenv()

    #     # --- MODIFIED SECTION ---
    #     # The names here MUST match your .env prefixes
    #     # I've added 'bybit' and 'okx' based on your screenshot
    #     EXCHANGES_TO_LOAD = ['bybit', 'binance', 'okx'] 

    #     config['exchanges'] = {}
    #     for exchange_name in EXCHANGES_TO_LOAD:
    #         # CORRECTED: Added "_TESTNET" to match your .env file
    #         api_key = os.getenv(f'{exchange_name.upper()}_TESTNET_API_KEY')
    #         secret = os.getenv(f'{exchange_name.upper()}_TESTNET_SECRET')

    #         if api_key and secret:
    #             config['exchanges'][exchange_name] = {
    #                 'apiKey': api_key,
    #                 'secret': secret
    #             }
    #             # Handle special case for OKX passphrase
    #             if exchange_name == 'okx':
    #                 passphrase = os.getenv('OKX_TESTNET_PASSPHRASE')
    #                 if passphrase:
    #                     config['exchanges'][exchange_name]['password'] = passphrase
    #                 else:
    #                     self.logger.warning("OKX credentials found but passphrase is missing.")

    #             self.logger.info(f"Loaded TESTNET credentials for {exchange_name}.")
    #         else:
    #             self.logger.warning(f"TESTNET credentials for {exchange_name} not found in .env file.")
    #     # --- END OF MODIFIED SECTION ---

    #     self.config = config
    #     self.update_queue = update_queue
    #     self.is_running = False

    #     self.state_lock = threading.Lock()

    #     # This line will now work correctly
    #     self.exchange_manager = ExchangeManager(config['exchanges'])
    #     self.analyzer = PerformanceAnalyzer()
    #     self.risk_manager = RiskManager(config, self.exchange_manager)
    #     self.trade_logger = TradeLogger("trades.csv")
    #     self.trade_executor = TradeExecutor(config, self.exchange_manager, self.trade_logger)

    #     self.last_update_time = 0
    #     self.update_interval = self.config.get('gui_update_interval', 1.0)

    def _get_current_stats(self) -> dict:
        """
        Returns a dictionary of the bot's current stats with keys
        that match the GUI's update_stats_display method.
        """
        # These are the initial, zeroed-out values the GUI needs
        # when the bot first starts.
        return {
            'trades': 0,
            'successful': 0,
            'failed': 0,
            'neutralized': 0,
            'critical': 0,
            'profit': 0.0
        }

    def run(self):
        """
        Synchronous entry point called by the GUI thread.
        """
        self.is_running = True
        self.start_time = time.time() 
        self.logger.info("Bot engine thread started. Starting asyncio event loop.")
        try:
            asyncio.run(self.main_async_loop())
        except Exception as e:
            self.logger.error(f"Critical error in async loop: {e}", exc_info=True)
        finally:
            self.logger.info("Asyncio event loop finished. Bot engine shutting down.")
            self.is_running = False
            asyncio.run(self.exchange_manager.close_all_connections())

    def reset_session_stats(self):
        """Resets the statistics for the new trading session."""
        with self.state_lock:
            self.session_profit = 0.0
            self.trades = 0
            self.successful = 0
            self.failed = 0
            self.neutralized = 0
            self.critical = 0

    async def main_async_loop(self):
        """
        The main asynchronous loop for the bot's operations.
        """
        # Get symbols from the correct config sub-dictionary
        symbols = self.config['trading_parameters'].get('symbols_to_scan', [])
        if not symbols:
            self.logger.error("'symbols_to_scan' is empty or not found in config.yaml. Stopping bot.")
            self.is_running = False
            return

        self.logger.info(f"Bot starting main loop. Monitoring symbols: {symbols}")

        while self.is_running:
            try:
                start_time = time.monotonic()

                # Fetch market data for only the selected symbols
                market_data = await self.exchange_manager.fetch_all_tickers_async(symbols)
                if not market_data:
                    self.logger.warning("No market data fetched in this cycle.")
                    sleep_duration = self.config['trading_parameters'].get('update_frequency', 5)
                    await asyncio.sleep(sleep_duration)
                    continue
                
                # Find arbitrage opportunities
                opportunities = self.analyzer.find_opportunities(market_data)

                # Process the best opportunity
                if opportunities:
                    best_opportunity = opportunities[0]
                    if self.risk_manager.is_trade_safe(best_opportunity):
                        trade_result = await self.trade_executor.execute_trade(best_opportunity)
                        
                        # Update session stats after a trade
                        with self.state_lock:
                            self.trades += 1
                            if trade_result and trade_result.status == "SUCCESS":
                                self.trade_logger.log_trade(trade_result)
                                self.successful += 1
                                actual_profit = (trade_result.sell_price - trade_result.buy_price) * trade_result.amount
                                self.session_profit += actual_profit
                                self.logger.success(f"Trade successful. Actual Profit: ${actual_profit:.4f}")
                                await asyncio.sleep(self.config['trading_parameters'].get('post_trade_delay_s', 5))
                            else:
                                self.failed += 1
                                self.logger.warning("Trade failed or was a dry run.")
                    else:
                        self.logger.warning(f"Trade for {best_opportunity.symbol} blocked by risk manager.")
                
                # Push all relevant data to GUI
                self._update_gui_data(market_data, opportunities)

                # Wait for the next cycle
                elapsed_time = time.monotonic() - start_time
                sleep_duration = max(0, self.config['trading_parameters'].get('update_frequency', 5) - elapsed_time)
                await asyncio.sleep(sleep_duration)

            except Exception as e:
                self.logger.error(f"An error occurred in the main async loop: {e}", exc_info=True)
                await asyncio.sleep(10)
                    
    def _update_gui_data(self, market_data, opportunities):
        """
        Prepares and pushes all live data to the GUI queue.
        """
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            return 

        # --- UPDATE: Include live session stats for the GUI panel ---
        with self.state_lock:
            stats_data = {
                'trades': self.trades,
                'successful': self.successful,
                'failed': self.failed,
                'neutralized': self.neutralized,
                'critical': self.critical,
                'profit': self.session_profit
            }

        # This data is for the tables and charts in other tabs
        portfolio = self.exchange_manager.get_portfolio_summary() # Note: This needs to become async in the future
        
        gui_data = {
            'type': 'bot_update',
            'stats': stats_data, # Live stats for the left panel
            'market_data': market_data,
            'opportunities': [opp.to_dict() for opp in opportunities],
            'portfolio': portfolio,
        }
        self.update_queue.put(gui_data)
        self.last_update_time = current_time
    
    # def _update_gui_data(self, market_data, opportunities):
    #     current_time = time.time()
    #     if current_time - self.last_update_time < self.update_interval:
    #         return 

    #     flat_market_data = []
    #     for exchange, tickers in market_data.items():
    #         if not tickers: continue
    #         for symbol, ticker in tickers.items():
    #             flat_market_data.append({
    #                 'exchange': exchange, 'symbol': symbol,
    #                 'bid': ticker.get('bid'), 'ask': ticker.get('ask'),
    #             })
        
    #     portfolio = self.exchange_manager.get_portfolio_summary()

    #     gui_data = {
    #         'type': 'bot_update',
    #         'market_data': flat_market_data,
    #         'opportunities': [opp.to_dict() for opp in opportunities],
    #         'portfolio': portfolio,
    #     }
    #     self.update_queue.put(gui_data)
    #     self.last_update_time = current_time

    def stop(self):
        self.logger.info("Stop signal received. Engine will shut down after the current cycle.")
        self.is_running = False