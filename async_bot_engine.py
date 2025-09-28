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

        # --- Bot Parameters ---
        self.params = self.config.get('trading_parameters', {})
        self.symbols_to_scan = self.params.get('symbols_to_scan', [])
        self.scan_interval_s = self.params.get('scan_interval_s', 5.0)
        self.min_profit_usd = self.params.get('min_profit_usd', 0.10)
        self.trade_size_usdt = self.params.get('trade_size_usdt', 20.0)
        
        # --- Cooldown Logic ---
        self.cooldown_duration_s = self.params.get('cooldown_duration_s', 300) # 5 minutes default
        self.opportunity_cooldowns = {}

        # --- Bot State ---
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
                if self._check_stop_conditions():
                    self.is_running = False
                    continue

                portfolio = await self.exchange_manager.get_portfolio_snapshot()
                logging.info(f"Current Portfolio Value: ${portfolio.get('total_usd_value', 0.0):.2f}")

                if self.risk_manager.check_kill_switch(portfolio):
                    self.is_running = False
                    logging.critical("Risk kill switch activated. Shutting down.")
                    continue
                
                opportunities = await self._scan_for_opportunities()

                if opportunities:
                    best_opportunity = opportunities[0]
                    logging.info(f"Profitable opportunity found: Expect ${best_opportunity['profit_usd']:.4f} profit on a ${self.trade_size_usdt} trade.")
                    await self._execute_arbitrage(best_opportunity, portfolio)
                else:
                    logging.info("No profitable opportunities found in this cycle.")

                logging.info(f"Waiting for {self.scan_interval_s} seconds until next scan...")
                await asyncio.sleep(self.scan_interval_s)

            except asyncio.CancelledError:
                logging.info("Bot run task was cancelled.")
                self.is_running = False
            except Exception as e:
                logging.error(f"An error occurred in the main bot loop: {e}", exc_info=True)
                self.is_running = False

        logging.info("Bot loop finished.")

    def _check_stop_conditions(self) -> bool:
        stop_conditions = self.config.get('stop_conditions')
        if not stop_conditions: return False

        max_trades = stop_conditions.get('max_trades')
        if max_trades is not None and self.trades_executed >= max_trades:
            logging.info(f"Stop condition met: Maximum trades ({max_trades}) reached.")
            return True

        run_duration_s = stop_conditions.get('run_duration_s')
        if run_duration_s is not None and (time.time() - self.start_time) >= run_duration_s:
            logging.info(f"Stop condition met: Maximum run duration ({run_duration_s}s) reached.")
            return True
        
        return False

    async def _scan_for_opportunities(self) -> List[Dict[str, Any]]:
        """
        Scans all symbols across all exchanges to find potential arbitrage
        opportunities. Returns a list of profitable opportunities, sorted.
        """
        opportunities = []
        ex_ids = list(self.exchange_manager.exchanges.keys())
        if len(ex_ids) < 2:
            return []

        current_time = time.time()

        for symbol in self.symbols_to_scan:
            tasks = {ex_id: self.exchange_manager.get_order_book(ex_id, symbol) for ex_id in ex_ids}
            order_books_results = await asyncio.gather(*tasks.values())
            order_books = dict(zip(tasks.keys(), order_books_results))

            for i in range(len(ex_ids)):
                for j in range(i + 1, len(ex_ids)):
                    ex1_id, ex2_id = ex_ids[i], ex_ids[j]
                    book1, book2 = order_books.get(ex1_id), order_books.get(ex2_id)
                    base_currency, _ = symbol.split('/')

                    # Opportunity: Buy on ex1, Sell on ex2
                    if book1 and book2 and book1.get('asks') and book1['asks'] and book2.get('bids') and book2['bids']:
                        buy_price, sell_price = book1['asks'][0][0], book2['bids'][0][0]
                        cooldown_key = f"sell-{base_currency}-{ex2_id}"

                        if sell_price > buy_price and self.opportunity_cooldowns.get(cooldown_key, 0) < current_time:
                            amount_to_buy = self.trade_size_usdt / buy_price
                            profit = (sell_price - buy_price) * amount_to_buy
                            if profit > self.min_profit_usd:
                                opportunities.append({
                                    "symbol": symbol, "profit_usd": profit,
                                    "buy_exchange": ex1_id, "buy_price": buy_price,
                                    "sell_exchange": ex2_id, "sell_price": sell_price,
                                })
                    
                    # Opportunity: Buy on ex2, Sell on ex1
                    if book1 and book2 and book2.get('asks') and book2['asks'] and book1.get('bids') and book1['bids']:
                        buy_price, sell_price = book2['asks'][0][0], book1['bids'][0][0]
                        cooldown_key = f"sell-{base_currency}-{ex1_id}"

                        if sell_price > buy_price and self.opportunity_cooldowns.get(cooldown_key, 0) < current_time:
                            amount_to_buy = self.trade_size_usdt / buy_price
                            profit = (sell_price - buy_price) * amount_to_buy
                            if profit > self.min_profit_usd:
                                opportunities.append({
                                    "symbol": symbol, "profit_usd": profit,
                                    "buy_exchange": ex2_id, "buy_price": buy_price,
                                    "sell_exchange": ex1_id, "sell_price": sell_price,
                                })

        return sorted(opportunities, key=lambda x: x['profit_usd'], reverse=True)


    async def _execute_arbitrage(self, opportunity: Dict[str, Any], portfolio: Dict[str, Any]):
        """
        Executes an arbitrage trade with pre-trade checks and neutralization.
        """
        symbol = opportunity['symbol']
        buy_ex = opportunity['buy_exchange']
        sell_ex = opportunity['sell_exchange']
        buy_price = opportunity['buy_price']
        base_currency, quote_currency = symbol.split('/')
        
        trade_amount_base = self.trade_size_usdt / buy_price
        
        # --- 1. Pre-Trade Balance Check ---
        buy_ex_balance = portfolio.get('by_exchange', {}).get(buy_ex, {}).get('assets', {}).get(quote_currency, 0)
        sell_ex_balance = portfolio.get('by_exchange', {}).get(sell_ex, {}).get('assets', {}).get(base_currency, 0)

        if buy_ex_balance < self.trade_size_usdt:
            logging.warning(f"Skipping trade: Insufficient {quote_currency} on {buy_ex}. Have {buy_ex_balance}, need {self.trade_size_usdt}.")
            return
        if sell_ex_balance < trade_amount_base:
            logging.warning(f"Skipping trade: Insufficient {base_currency} on {sell_ex}. Have {sell_ex_balance}, need {trade_amount_base:.6f}.")
            cooldown_key = f"sell-{base_currency}-{sell_ex}"
            self.opportunity_cooldowns[cooldown_key] = time.time() + self.cooldown_duration_s
            logging.info(f"Placed {cooldown_key} on cooldown for {self.cooldown_duration_s} seconds.")
            return
            
        logging.info(f"Executing arbitrage: BUY {trade_amount_base:.6f} {symbol} on {buy_ex} and SELL on {sell_ex}")
        
        # --- THIS IS THE FIX: The create_order arguments are now in the correct order ---
        buy_task = self.exchange_manager.create_order(
            ex_id=buy_ex, symbol=symbol, order_type='market', side='buy', amount=trade_amount_base
        )
        sell_task = self.exchange_manager.create_order(
            ex_id=sell_ex, symbol=symbol, order_type='market', side='sell', amount=trade_amount_base
        )
        
        results = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
        buy_result, sell_result = results
        
        # --- 2. Trade Neutralization Logic ---
        buy_succeeded = not isinstance(buy_result, Exception)
        sell_succeeded = not isinstance(sell_result, Exception)

        if buy_succeeded and not sell_succeeded:
            logging.critical(f"SELL leg failed on {sell_ex}. NEUTRALIZING successful BUY on {buy_ex}.")
            await self._neutralize_trade('sell', buy_ex, symbol, trade_amount_base, buy_result)
        
        if not buy_succeeded and sell_succeeded:
            logging.critical(f"BUY leg failed on {buy_ex}. NEUTRALIZING successful SELL on {sell_ex}.")
            await self._neutralize_trade('buy', sell_ex, symbol, trade_amount_base, sell_result)

        if buy_succeeded:
             logging.info(f"Successfully placed BUY order on {buy_ex}: {buy_result.get('id', 'N/A')}")
        else:
             logging.error(f"BUY order on {buy_ex} FAILED: {buy_result}")

        if sell_succeeded:
             logging.info(f"Successfully placed SELL order on {sell_ex}: {sell_result.get('id', 'N/A')}")
        else:
             logging.error(f"SELL order on {sell_ex} FAILED: {sell_result}")
        
        if buy_succeeded or sell_succeeded:
            self.trades_executed += 1

    async def _neutralize_trade(self, side: str, ex_id: str, symbol: str, amount: float, original_trade: Dict):
        """
        Places a reverse market order to neutralize a partially failed trade.
        """
        try:
            logging.info(f"Attempting to place a neutralizing {side} order on {ex_id} for {amount:.6f} {symbol}.")
            neutralize_amount = original_trade.get('filled', amount) if isinstance(original_trade, dict) else amount
            if neutralize_amount > 0:
                await self.exchange_manager.create_order(
                    ex_id=ex_id, symbol=symbol, order_type='market', side=side, amount=neutralize_amount
                )
                logging.critical(f"SUCCESSFULLY placed neutralizing {side} order on {ex_id}.")
            else:
                logging.warning("Original trade amount was 0, no neutralization needed.")
        except Exception as e:
            logging.error(f"CRITICAL FAILURE: Could not neutralize trade on {ex_id}. MANUAL INTERVENTION REQUIRED. Error: {e}")