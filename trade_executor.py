#trade_executor.py

import logging
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt  # <-- CRITICAL: Use the async_support library

from data_models import Opportunity, Trade  # Assuming Trade is a Pydantic model or dataclass
from exchange_manager import ExchangeManager
from trade_logger import TradeLogger


class TradeExecutor:
    """
    Handles the execution of an arbitrage trade asynchronously.
    """

    def __init__(self, config: Dict[str, Any], exchange_manager: ExchangeManager, trade_logger: TradeLogger):
        self.config = config
        self.trading_params = config.get('trading_parameters', {})
        self.exchange_manager = exchange_manager
        self.trade_logger = trade_logger
        self.logger = logging.getLogger(__name__)

    async def execute_trade(self, opportunity: Opportunity) -> Optional[Trade]:
        """
        Executes the two legs of the arbitrage trade using market orders.
        This is the primary method called by the bot engine.
        """
        symbol = opportunity.symbol
        amount = opportunity.amount
        buy_exchange_name = opportunity.buy_exchange
        sell_exchange_name = opportunity.sell_exchange

        buy_client = self.exchange_manager.get_client(buy_exchange_name)
        sell_client = self.exchange_manager.get_client(sell_exchange_name)

        if not buy_client or not sell_client:
            self.logger.error(f"Could not get exchange clients for trade on {symbol}.")
            return None

        # Handle dry run mode from the config
        if self.trading_params.get('dry_run', True):
            self.logger.info(f"DRY RUN: Would BUY {amount:.6f} {symbol} on {buy_exchange_name} and SELL on {sell_exchange_name}")
            return Trade(
                symbol=symbol, amount=amount, buy_price=opportunity.buy_price, 
                sell_price=opportunity.sell_price, buy_exchange=buy_exchange_name, 
                sell_exchange=sell_exchange_name, status="DRY_RUN"
            )

        try:
            self.logger.info(f"PLACING: BUY {amount:.6f} {symbol} on {buy_exchange_name.upper()}")
            # <-- CRITICAL: Use await for all network calls
            buy_order = await buy_client.create_market_buy_order(symbol, amount)
            self.logger.success(f"FILLED: BUY order {buy_order['id']} on {buy_exchange_name.upper()}")

            self.logger.info(f"PLACING: SELL {amount:.6f} {symbol} on {sell_exchange_name.upper()}")
            # <-- CRITICAL: Use await for all network calls
            sell_order = await sell_client.create_market_sell_order(symbol, amount)
            self.logger.success(f"FILLED: SELL order {sell_order['id']} on {sell_exchange_name.upper()}")
            
            # Create a Trade object for successful logging
            trade_log = Trade(
                symbol=symbol,
                amount=float(buy_order.get('filled', amount)),
                buy_price=float(buy_order.get('average', opportunity.buy_price)),
                sell_price=float(sell_order.get('average', opportunity.sell_price)),
                buy_exchange=buy_exchange_name,
                sell_exchange=sell_exchange_name,
                status="SUCCESS"
            )
            return trade_log

        except ccxt.InsufficientFunds as e:
            self.logger.error(f"Insufficient funds for trade on {symbol} on {e.exchange.id if hasattr(e, 'exchange') else 'N/A'}: {e}")
        except ccxt.NetworkError as e:
            self.logger.error(f"Network error during trade on {symbol}: {e}")
        except ccxt.ExchangeError as e:
            self.logger.error(f"Exchange error during trade on {symbol}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error during trade execution for {symbol}: {e}", exc_info=True)
            
        return None
    
# # trade_executor.py

# import ccxt
# import time
# import logging
# from typing import Any, Dict, Optional

# from data_models import Opportunity, TradeLogData
# from exchange_manager import ExchangeManager
# from utils import retry_ccxt_call
# from trade_logger import TradeLogger

# class TradeExecutor:
#     """
#     Handles the entire lifecycle of an arbitrage trade:
#     placement, monitoring, and handling of stuck orders. This class is stateless.
#     """
#     def __init__(self, config: Dict[str, Any], exchange_manager: ExchangeManager, trade_logger: TradeLogger):
#         self.config = config
#         self.trading_params = config.get('trading_parameters', {})
#         self.exchange_manager = exchange_manager
#         self.trade_logger = trade_logger
#         self.logger = logging.getLogger(__name__)

#     async def execute_trade(self, opportunity: dict) -> bool: # <-- Make the method async
#             """
#             Executes the two legs of the arbitrage trade.
#             Now an async method to avoid blocking the bot's main event loop.
#             """
#             symbol = opportunity['symbol']
#             buy_exchange_name = opportunity['buy_on']
#             sell_exchange_name = opportunity['sell_on']
#             amount = opportunity['amount']
            
#             buy_exchange = self.exchanges[buy_exchange_name]
#             sell_exchange = self.exchanges[sell_exchange_name]

#             try:
#                 self.logger.info(f"Executing trade: BUY {amount} {symbol} on {buy_exchange_name}")
#                 # In a truly async implementation, these would be awaited async methods
#                 # e.g., await buy_exchange.create_market_buy_order(symbol, amount)
#                 # For now, we wrap synchronous calls in the async method definition
#                 buy_order = buy_exchange.create_market_buy_order(symbol, amount)
#                 self.logger.info(f"Buy order successful: {buy_order['id']}")

#                 self.logger.info(f"Executing trade: SELL {amount} {symbol} on {sell_exchange_name}")
#                 sell_order = sell_exchange.create_market_sell_order(symbol, amount)
#                 self.logger.info(f"Sell order successful: {sell_order['id']}")
                
#                 return True

#             except ccxt.InsufficientFunds as e:
#                 self.logger.error(f"Insufficient funds to execute trade for {symbol}: {e}")
#                 # Potentially trigger a balance refresh or notification
#             except ccxt.NetworkError as e:
#                 self.logger.error(f"Network error during trade execution for {symbol}: {e}")
#                 # Implement retry logic or a circuit breaker here
#             except ccxt.ExchangeError as e:
#                 self.logger.error(f"Exchange error during trade execution for {symbol}: {e}")
#             except Exception as e:
#                 self.logger.error(f"An unexpected error occurred during trade execution for {symbol}: {e}", exc_info=True)
                
#             return False

#     def execute_and_monitor(self, opportunity: Opportunity, session_id: str) -> Dict[str, Any]:
#         buy_client = self.exchange_manager.get_client(opportunity.buy_exchange)
#         sell_client = self.exchange_manager.get_client(opportunity.sell_exchange)
#         if not buy_client or not sell_client:
#             self.logger.error("Could not get exchange clients for trade execution.")
#             return {'status': 'FAILED_CLIENT_ERROR', 'profit': 0.0}

#         buy_order, sell_order = self._place_orders(opportunity)
#         if not buy_order or not sell_order:
#             self.logger.error(f"Order placement failed for {opportunity.symbol}. Trade not executed.")
#             return {'status': 'FAILED_PLACEMENT', 'profit': 0.0}

#         monitor_result = self._monitor_orders(buy_order, sell_order, buy_client, sell_client, opportunity)
#         log_entry = self._create_log_entry(opportunity, session_id, monitor_result)

#         if monitor_result.get("success"):
#             log_entry.status = 'SUCCESS'
#             self.trade_logger.log_trade(log_entry)
#             return {'status': 'SUCCESS', 'profit': log_entry.net_profit_usd}
#         else:
#             self.logger.warning("Monitoring failed or timed out. Handling stuck order scenario.")
#             final_status = self._handle_stuck_order(buy_order, sell_order, log_entry)
#             log_entry.status = final_status
#             self.trade_logger.log_trade(log_entry)
#             return {'status': final_status, 'profit': 0.0}

#     def _place_orders(self, opportunity: Opportunity) -> tuple[Optional[Dict], Optional[Dict]]:
#         symbol, base, amount = opportunity.symbol, opportunity.symbol.split('/')[0], opportunity.amount
#         log_msg = (
#             f"⚡ Arbitrage on {symbol}! Est. Profit: ${opportunity.net_profit_usd:.4f}\n"
#             f"  ➡️ BUY {amount:.6f} {base} on {opportunity.buy_exchange.upper()} @ {opportunity.buy_price}\n"
#             f"  ⬅️ SELL {amount:.6f} {base} on {opportunity.sell_exchange.upper()} @ {opportunity.sell_price}"
#         )

#         if self.trading_params.get('dry_run', True):
#             self.logger.trade(f"DRY RUN: {log_msg}")
#             return {"id": f"dry_buy_{int(time.time())}"}, {"id": f"dry_sell_{int(time.time())}"}
        
#         try:
#             self.logger.trade(log_msg)
#             buy_client = self.exchange_manager.get_client(opportunity.buy_exchange)
#             sell_client = self.exchange_manager.get_client(opportunity.sell_exchange)
#             buy_order = retry_ccxt_call(buy_client.create_limit_buy_order)(symbol, amount, opportunity.buy_price)
#             sell_order = retry_ccxt_call(sell_client.create_limit_sell_order)(symbol, amount, opportunity.sell_price)
#             return buy_order, sell_order
#         except Exception as e:
#             self.logger.error(f"An unexpected error occurred during order placement for {symbol}: {e}", exc_info=True)
#             return None, None

#     def _monitor_orders(self, buy_order: Dict, sell_order: Dict, buy_client: ccxt.Exchange, sell_client: ccxt.Exchange, opportunity: Opportunity) -> Dict[str, Any]:
#         if self.trading_params.get('dry_run', True):
#             time.sleep(1)
#             self.logger.success("DRY RUN: Both orders simulated as filled.")
#             return {"success": True, "latency_ms": 1000, "fees_paid": 0.02, "fill_ratio": 1.0}
            
#         time.sleep(1.5)
#         start_time = time.time()
#         timeout = self.trading_params.get('order_monitor_timeout_s', 45)
#         symbol = opportunity.symbol
        
#         while time.time() - start_time < timeout:
#             try:
#                 buy_open_orders = retry_ccxt_call(buy_client.fetch_open_orders)(symbol)
#                 sell_open_orders = retry_ccxt_call(sell_client.fetch_open_orders)(symbol)
#                 buy_open_ids = {o['id'] for o in buy_open_orders}
#                 sell_open_ids = {o['id'] for o in sell_open_orders}
#                 is_buy_open = buy_order['id'] in buy_open_ids
#                 is_sell_open = sell_order['id'] in sell_open_ids

#                 if not is_buy_open and not is_sell_open:
#                     self.logger.success("Both orders are no longer open, assuming filled.")
                    
#                     final_buy_order, final_sell_order = None, None
#                     try:
#                         final_buy_order = retry_ccxt_call(buy_client.fetch_order)(buy_order['id'], symbol)
#                     except Exception as e:
#                         self.logger.warning(f"Could not fetch final buy order details from {buy_client.id}. Falling back to estimates. Error: {e}")
#                     try:
#                         final_sell_order = retry_ccxt_call(sell_client.fetch_order)(sell_order['id'], symbol)
#                     except Exception as e:
#                         self.logger.warning(f"Could not fetch final sell order details from {sell_client.id}. Falling back to estimates. Error: {e}")

#                     latency = int((time.time() - start_time) * 1000)
                    
#                     # --- NEW ROBUST PARSING LOGIC ---
#                     buy_fee, sell_fee, fill_ratio = 0.0, 0.0, 1.0
                    
#                     if final_buy_order:
#                         buy_fee = (final_buy_order.get('fee') or {}).get('cost', 0.0)
#                         filled = final_buy_order.get('filled', 0.0)
#                         amount = final_buy_order.get('amount', 1.0)
#                         if filled and amount:
#                             fill_ratio = filled / amount
#                     else: # Fallback to estimation
#                         buy_fee = opportunity.buy_price * opportunity.amount * 0.001

#                     if final_sell_order:
#                         sell_fee = (final_sell_order.get('fee') or {}).get('cost', 0.0)
#                     else: # Fallback to estimation
#                         sell_fee = opportunity.sell_price * opportunity.amount * 0.001

#                     fees = (buy_fee or 0.0) + (sell_fee or 0.0)
#                     # ------------------------------------
                    
#                     return {"success": True, "latency_ms": latency, "fees_paid": fees, "fill_ratio": fill_ratio}

#                 time.sleep(2.5)
#             except Exception as e:
#                 self.logger.warning(f"Error monitoring orders: {e}. Retrying...")
#                 time.sleep(2.5)
                
#         self.logger.error(f"Timeout reached while monitoring orders for {symbol}.")
#         return {"success": False, "latency_ms": int(timeout * 1000), "fees_paid": 0, "fill_ratio": 0}

#     def _handle_stuck_order(self, buy_order: Dict, sell_order: Dict, log_data: TradeLogData) -> str:
#         self.logger.critical(f"STUCK ORDER DETECTED for {log_data.symbol}. Manual intervention may be required.")
#         self.logger.critical(f"  Buy Order ID: {buy_order['id']} on {log_data.buy_exchange}")
#         self.logger.critical(f"  Sell Order ID: {sell_order['id']} on {log_data.sell_exchange}")
#         return 'CRITICAL_STUCK_ORDER'

#     def _create_log_entry(self, opportunity: Opportunity, session_id: str, monitor_result: Dict) -> TradeLogData:
#         return TradeLogData(
#             session_id=session_id, timestamp=int(time.time()),
#             symbol=opportunity.symbol, buy_exchange=opportunity.buy_exchange,
#             sell_exchange=opportunity.sell_exchange, buy_price=opportunity.buy_price,
#             sell_price=opportunity.sell_price, amount=opportunity.amount,
#             net_profit_usd=opportunity.net_profit_usd, status='PENDING',
#             latency_ms=monitor_result.get('latency_ms', 0),
#             fees_paid=monitor_result.get('fees_paid', 0),
#             fill_ratio=monitor_result.get('fill_ratio', 0)
#         )