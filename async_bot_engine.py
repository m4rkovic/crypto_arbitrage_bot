import asyncio
import logging
import time
from typing import Dict, Any, List, Optional

from exchange_manager_async import AsyncExchangeManager
from risk_manager import RiskManager
from rebalancer import Rebalancer
from trade_logger import TradeLogger

class AsyncArbitrageBot:
    """
    The core asynchronous bot engine. It orchestrates the entire process:
    scanning for opportunities, checking risk, executing trades, and logging.
    """
    def __init__(
        self,
        config: Dict[str, Any],
        exchange_manager: AsyncExchangeManager,
        risk_manager: RiskManager,
        rebalancer: Rebalancer,
        trade_logger: TradeLogger
    ):
        self.config = config
        self.exchange_manager = exchange_manager
        self.risk_manager = risk_manager
        self.rebalancer = rebalancer
        self.trade_logger = trade_logger

        # Extract parameters from the config for easier access
        self.params = self.config.get('trading_parameters', {})
        self.symbols_to_scan = self.params.get('symbols_to_scan', [])
        self.scan_interval_s = self.params.get('scan_interval_s', 5.0)
        self.min_profit_usd = self.params.get('min_profit_usd', 0.10)
        self.trade_size_usdt = self.params.get('trade_size_usdt', 20.0)

        self.is_running = False
        self.start_time = None
        self.trades_executed = 0

    async def run(self):
        """The main async execution loop of the bot."""
        self.is_running = True
        self.start_time = time.time()
        logging.info("Starting Asynchronous Arbitrage Bot...")

        while self.is_running:
            logging.info("--- Starting new scan cycle ---")
            
            try:
                # 1. Check stop conditions
                if self._check_stop_conditions():
                    self.is_running = False
                    continue

                # 2. Get portfolio snapshot and check risk
                portfolio = await self.exchange_manager.get_portfolio_snapshot()
                logging.info(f"Current Portfolio Value: ${portfolio['total_usd_value']:.2f}")

                # --- THIS IS THE FIX ---
                # Changed from check_kill_switches to check_kill_switch
                if self.risk_manager.check_kill_switch(portfolio):
                    self.is_running = False
                    logging.critical("Risk kill switch activated. Shutting down.")
                    continue
                
                # 3. Scan for opportunities
                opportunities = await self._scan_for_opportunities()

                if opportunities:
                    best_opportunity = opportunities[0] # List is sorted by profit
                    logging.info(f"Profitable opportunity found: Expect ${best_opportunity['profit_usd']:.4f} profit on a ${self.trade_size_usdt} trade.")
                    
                    # 4. Execute trade
                    await self._execute_arbitrage(best_opportunity)
                else:
                    logging.info("No profitable opportunities found in this cycle.")

                # 5. Wait for the next scan cycle
                logging.info(f"Waiting for {self.scan_interval_s} seconds until next scan...")
                await asyncio.sleep(self.scan_interval_s)

            except asyncio.CancelledError:
                logging.info("Bot run task was cancelled.")
                self.is_running = False
            except Exception as e:
                logging.error(f"An error occurred in the main bot loop: {e}", exc_info=True)
                self.is_running = False # Stop on critical error

        logging.info("Bot loop finished.")

    def _check_stop_conditions(self) -> bool:
        """
        Checks if any configured stop conditions have been met.
        This is now safe to run even if 'stop_conditions' is missing from config.
        """
        stop_conditions = self.config.get('stop_conditions')
        if not stop_conditions:
            return False # No stop conditions defined, so nothing to check.

        # Safely check for max_trades
        max_trades = stop_conditions.get('max_trades')
        if max_trades is not None and self.trades_executed >= max_trades:
            logging.info(f"Stop condition met: Maximum trades ({max_trades}) reached.")
            return True

        # Safely check for run_duration_s
        run_duration_s = stop_conditions.get('run_duration_s')
        if run_duration_s is not None:
            elapsed_time = time.time() - self.start_time
            if elapsed_time >= run_duration_s:
                logging.info(f"Stop condition met: Maximum run duration ({run_duration_s}s) reached.")
                return True
        
        # NOTE: min_balance_usd check would be added here in the future
        return False

    async def _scan_for_opportunities(self) -> List[Dict[str, Any]]:
        """
        Scans all symbols across all exchanges to find potential arbitrage
        opportunities. Returns a list of profitable opportunities, sorted.
        """
        opportunities = []
        ex_ids = list(self.exchange_manager.exchanges.keys())
        if len(ex_ids) < 2:
            return [] # Need at least two exchanges for arbitrage

        for symbol in self.symbols_to_scan:
            # Fetch all order books for this symbol concurrently
            tasks = {ex_id: self.exchange_manager.get_order_book(ex_id, symbol) for ex_id in ex_ids}
            order_books_results = await asyncio.gather(*tasks.values())
            order_books = dict(zip(tasks.keys(), order_books_results))

            # Compare every exchange with every other exchange
            for i in range(len(ex_ids)):
                for j in range(i + 1, len(ex_ids)):
                    ex1_id, ex2_id = ex_ids[i], ex_ids[j]
                    
                    book1 = order_books.get(ex1_id)
                    book2 = order_books.get(ex2_id)

                    # Check for valid book structure
                    if not book1 or not book2 or not book1.get('asks') or not book1['asks'] or not book2.get('bids') or not book2['bids']:
                        continue

                    # Opportunity: Buy on ex1, Sell on ex2
                    buy_price = book1['asks'][0][0]
                    sell_price = book2['bids'][0][0]
                    
                    if sell_price > buy_price:
                        # Simple profit calculation in USD
                        amount_to_buy = self.trade_size_usdt / buy_price
                        gross_profit_usd = (sell_price - buy_price) * amount_to_buy
                        # A more realistic version would subtract fees here
                        if gross_profit_usd > self.min_profit_usd:
                            opportunities.append({
                                "symbol": symbol, "profit_usd": gross_profit_usd,
                                "buy_exchange": ex1_id, "buy_price": buy_price,
                                "sell_exchange": ex2_id, "sell_price": sell_price,
                            })
                    
                    # Check the reverse opportunity
                    if not book2.get('asks') or not book2['asks'] or not book1.get('bids') or not book1['bids']:
                        continue
                        
                    # Opportunity: Buy on ex2, Sell on ex1
                    buy_price = book2['asks'][0][0]
                    sell_price = book1['bids'][0][0]
                    
                    if sell_price > buy_price:
                        amount_to_buy = self.trade_size_usdt / buy_price
                        gross_profit_usd = (sell_price - buy_price) * amount_to_buy
                        if gross_profit_usd > self.min_profit_usd:
                            opportunities.append({
                                "symbol": symbol, "profit_usd": gross_profit_usd,
                                "buy_exchange": ex2_id, "buy_price": buy_price,
                                "sell_exchange": ex1_id, "sell_price": sell_price,
                            })

        # Sort by most profitable first
        return sorted(opportunities, key=lambda x: x['profit_usd'], reverse=True)


    async def _execute_arbitrage(self, opportunity: Dict[str, Any]):
        """
        Executes the buy and sell orders for a found opportunity.
        Places both orders concurrently to minimize price movement risk.
        """
        symbol = opportunity['symbol']
        buy_ex = opportunity['buy_exchange']
        sell_ex = opportunity['sell_exchange']
        buy_price = opportunity['buy_price']
        
        # Calculate amount of base currency to buy for the configured USDT size
        trade_amount_base = self.trade_size_usdt / buy_price
        
        logging.info(
            f"Executing arbitrage: BUY {trade_amount_base:.6f} {symbol} on {buy_ex} and SELL on {sell_ex}"
        )
        
        # Create buy and sell tasks to run them in parallel
        buy_task = self.exchange_manager.create_order(
            ex_id=buy_ex, symbol=symbol, order_type='market', side='buy', amount=trade_amount_base
        )
        sell_task = self.exchange_manager.create_order(
            ex_id=sell_ex, symbol=symbol, order_type='market', side='sell', amount=trade_amount_base
        )
        
        # Use return_exceptions=True to ensure both tasks complete even if one fails
        results = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
        buy_result, sell_result = results
        
        # Proper logging and neutralization logic would go here
        if isinstance(buy_result, Exception):
            logging.error(f"BUY order on {buy_ex} FAILED: {buy_result}")
        else:
            logging.info(f"Successfully placed BUY order on {buy_ex}: {buy_result.get('id', 'N/A')}")

        if isinstance(sell_result, Exception):
            logging.error(f"SELL order on {sell_ex} FAILED: {sell_result}")
        else:
            logging.info(f"Successfully placed SELL order on {sell_ex}: {sell_result.get('id', 'N/A')}")

        if isinstance(buy_result, Exception) != isinstance(sell_result, Exception):
            logging.critical("TRADE IMBALANCE! One leg failed. Neutralization required.")
            # In a full implementation, call an async trade neutralization function here.

        self.trades_executed += 1



# import asyncio
# import logging
# import time
# from typing import Dict, Any, Optional

# from exchange_manager_async import AsyncExchangeManager
# from risk_manager import RiskManager
# from rebalancer import Rebalancer
# from trade_logger import TradeLogger

# class AsyncArbitrageBot:
#     """
#     The core asynchronous bot engine. It orchestrates the entire process:
#     scanning for opportunities, checking risk, executing trades, and logging.
#     """
#     def __init__(
#         self,
#         config: Dict[str, Any],
#         exchange_manager: AsyncExchangeManager,
#         risk_manager: RiskManager,
#         rebalancer: Rebalancer,
#         trade_logger: TradeLogger
#     ):
#         self.config = config
#         self.exchange_manager = exchange_manager
#         self.risk_manager = risk_manager
#         self.rebalancer = rebalancer
#         self.trade_logger = trade_logger

#         self.is_running = False
#         self.start_time = None
#         self.trades_executed = 0

#     async def run(self):
#         """
#         The main async execution loop of the bot.
#         """
#         self.is_running = True
#         self.start_time = time.time()
#         logging.info("Starting Asynchronous Arbitrage Bot...")

#         try:
#             while self.is_running:
#                 logging.info("--- Starting new scan cycle ---")

#                 # 1. Check stop conditions
#                 if self._check_stop_conditions():
#                     break

#                 # 2. Get portfolio snapshot and check risk
#                 portfolio = await self.exchange_manager.get_portfolio_snapshot()
#                 logging.info(f"Current Portfolio Value: ${portfolio['total_usd_value']:.2f}")

#                 if self.risk_manager.check_kill_switches(portfolio):
#                     self.is_running = False
#                     logging.critical("Risk kill switch activated. Shutting down.")
#                     break
                
#                 # Note: Rebalancer check could be added here if needed
#                 # self.rebalancer.is_rebalance_needed(portfolio)

#                 # 3. Scan for opportunities
#                 opportunity = await self._find_arbitrage_opportunity()

#                 if opportunity:
#                     logging.info(f"Arbitrage opportunity found: {opportunity}")
#                     # 4. Execute trade
#                     await self._execute_arbitrage(opportunity)
#                 else:
#                     logging.info("No profitable arbitrage opportunities found in this cycle.")

#                 # 5. Wait for the next scan cycle
#                 interval = self.config['scan_interval_s']
#                 logging.info(f"Waiting for {interval} seconds until next scan...")
#                 await asyncio.sleep(interval)

#         except asyncio.CancelledError:
#             logging.info("Bot run task cancelled.")
#         finally:
#             logging.info("Bot shutting down...")
#             await self.exchange_manager.close()
#             self.is_running = False

#     def _check_stop_conditions(self) -> bool:
#         """Checks if any configured stop conditions have been met."""
#         if self.trades_executed >= self.config['stop_conditions']['max_trades']:
#             logging.info("Stop condition met: Maximum number of trades reached.")
#             return True

#         run_duration = time.time() - self.start_time
#         if run_duration >= self.config['stop_conditions']['run_duration_s']:
#             logging.info("Stop condition met: Maximum run duration reached.")
#             return True
        
#         return False

#     async def _find_arbitrage_opportunity(self) -> Optional[Dict[str, Any]]:
#         """
#         Scans all configured pairs across all configured exchanges for an arbitrage opportunity.
#         This version fetches all necessary order books concurrently for maximum speed.
#         """
#         ex_ids = list(self.config['exchanges'].keys())
#         # We assume a two-exchange arbitrage for this implementation
#         ex1_id, ex2_id = ex_ids[0], ex_ids[1]

#         for pair in self.config['trading_pairs']:
#             # Fetch order books for the current pair from both exchanges at the same time
#             tasks = {
#                 ex1_id: self.exchange_manager.get_order_book(ex1_id, pair),
#                 ex2_id: self.exchange_manager.get_order_book(ex2_id, pair)
#             }
#             results = await asyncio.gather(*tasks.values())
            
#             order_book1, order_book2 = results
            
#             if not order_book1 or not order_book2 or not order_book1['bids'] or not order_book2['asks']:
#                 continue

#             # Opportunity: Buy on ex1, Sell on ex2
#             ex1_ask = order_book1['asks'][0][0]
#             ex2_bid = order_book2['bids'][0][0]
            
#             profit_pct_1 = ((ex2_bid - ex1_ask) / ex1_ask) * 100
#             if profit_pct_1 > self.config['min_profit_pct']:
#                 return self._create_opportunity(pair, ex1_id, ex1_ask, ex2_id, ex2_bid, profit_pct_1)

#             # Opportunity: Buy on ex2, Sell on ex1
#             ex2_ask = order_book2['asks'][0][0]
#             ex1_bid = order_book1['bids'][0][0]
            
#             profit_pct_2 = ((ex1_bid - ex2_ask) / ex2_ask) * 100
#             if profit_pct_2 > self.config['min_profit_pct']:
#                 return self._create_opportunity(pair, ex2_id, ex2_ask, ex1_id, ex1_bid, profit_pct_2)

#         return None

#     def _create_opportunity(self, pair, buy_ex, buy_price, sell_ex, sell_price, profit_pct):
#         """Helper to structure the opportunity dictionary."""
#         return {
#             "pair": pair,
#             "buy_exchange": buy_ex,
#             "buy_price": buy_price,
#             "sell_exchange": sell_ex,
#             "sell_price": sell_price,
#             "profit_pct": profit_pct
#         }

#     async def _execute_arbitrage(self, opportunity: Dict[str, Any]):
#         """
#         Executes the buy and sell orders for a found opportunity.
#         Places both orders concurrently to minimize price movement risk.
#         """
#         pair = opportunity['pair']
#         buy_ex = opportunity['buy_exchange']
#         sell_ex = opportunity['sell_exchange']
        
#         trade_amount_base = self.config['trade_amount_base_currency']
        
#         logging.info(
#             f"Executing arbitrage: BUY {trade_amount_base} {pair} on {buy_ex} and "
#             f"SELL on {sell_ex} for a potential profit of {opportunity['profit_pct']:.4f}%"
#         )
        
#         # Create buy and sell tasks to run them in parallel
#         buy_task = self.exchange_manager.create_order(
#             ex_id=buy_ex, symbol=pair, order_type='market', side='buy', amount=trade_amount_base
#         )
#         sell_task = self.exchange_manager.create_order(
#             ex_id=sell_ex, symbol=pair, order_type='market', side='sell', amount=trade_amount_base
#         )

#         trade_time = time.time()
#         # Use return_exceptions=True to ensure both tasks complete even if one fails
#         results = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
        
#         buy_result, sell_result = results

#         # --- Handle results and logging ---
#         trade_log_entry = {
#             "timestamp": trade_time,
#             "pair": pair,
#             "profit_pct_expected": opportunity['profit_pct'],
#             "buy_leg": {"exchange": buy_ex, "order": None, "status": "failed"},
#             "sell_leg": {"exchange": sell_ex, "order": None, "status": "failed"},
#         }

#         if not isinstance(buy_result, Exception):
#             trade_log_entry['buy_leg']['order'] = buy_result
#             trade_log_entry['buy_leg']['status'] = 'success'
#             logging.info(f"Successfully placed BUY order on {buy_ex}: {buy_result['id']}")
#         else:
#             logging.error(f"BUY order on {buy_ex} FAILED: {buy_result}")
        
#         if not isinstance(sell_result, Exception):
#             trade_log_entry['sell_leg']['order'] = sell_result
#             trade_log_entry['sell_leg']['status'] = 'success'
#             logging.info(f"Successfully placed SELL order on {sell_ex}: {sell_result['id']}")
#         else:
#             logging.error(f"SELL order on {sell_ex} FAILED: {sell_result}")
        
#         self.trade_logger.log_trade(trade_log_entry)
        
#         # CRITICAL: If one leg failed, trade neutralization should be triggered here.
#         if isinstance(buy_result, Exception) != isinstance(sell_result, Exception):
#             logging.critical("TRADE IMBALANCE DETECTED! One leg failed. Manual intervention may be required.")
#             # In a full implementation, call an async trade neutralization function here.
            
#         self.trades_executed += 1
