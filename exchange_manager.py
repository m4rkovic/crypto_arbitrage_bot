# crypto_arbitrage_bot/exchange_manager.py

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt  # Use the async_support library

# Assuming you have this custom error defined
class ExchangeInitError(Exception):
    pass

class ExchangeManager:
    """Manages all async exchange clients, API calls, and cached data."""

    def __init__(self, exchanges_config: Dict[str, Any]):
            self.logger = logging.getLogger(__name__)
            self.clients: Dict[str, ccxt.Exchange] = {}
            # ... (rest of the attributes)

            for ex_name, config_data in exchanges_config.items():
                try:
                    exchange_class = getattr(ccxt, ex_name)
                    client = exchange_class(config_data) # Pass the config directly
                    
                    # --- FINAL TESTNET LOGIC ---
                    if ex_name == 'binance':
                        # Binance testnet via ccxt often requires specifying the futures market
                        client.options['defaultType'] = 'future'
                    
                    # Enable sandbox mode for all exchanges
                    client.set_sandbox_mode(True)
                    # -----------------------------
                    
                    self.clients[ex_name] = client
                    self.logger.info(f"Initialized async client for {ex_name.capitalize()} in TESTNET mode.")
                except Exception as e:
                    self.logger.critical(f"Fatal error initializing {ex_name.capitalize()}: {e}")
                    raise ExchangeInitError(f"Failed to initialize {ex_name.capitalize()}: {e}")

    def get_client(self, exchange_name: str) -> Optional[ccxt.Exchange]:
        """Returns the client instance for a given exchange name."""
        return self.clients.get(exchange_name)

    # --- ADD THIS MISSING METHOD ---
    def get_all_clients(self) -> Dict[str, ccxt.Exchange]:
        """Returns the dictionary of all initialized client instances."""
        return self.clients
    # -----------------------------

    async def fetch_all_tickers_async(self, symbols: list) -> Dict[str, Any]:
        """Asynchronously fetches tickers for specified symbols from all exchanges."""
        tasks = [client.fetch_tickers(symbols=symbols) for client in self.clients.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        market_data = {}
        for exchange_name, result in zip(self.clients.keys(), results):
            if isinstance(result, Exception):
                self.logger.error(f"Failed to fetch async tickers for {exchange_name}: {result}")
            elif not result:
                self.logger.warning(f"No ticker data returned from {exchange_name}.")
            else:
                market_data[exchange_name] = result
        return market_data

    async def get_balance_async(self, client: ccxt.Exchange, force_refresh: bool = False) -> Dict[str, Any]:
        """Asynchronously fetches balance for a single exchange, using a cache."""
        now = time.time()
        client_id = client.id
        last_fetch = self.last_balance_fetch_time.get(client_id, 0)
        
        if not force_refresh and (now - last_fetch) < self.BALANCE_CACHE_DURATION_S:
            return self.cached_balances.get(client_id, {})
        try:
            balance = await client.fetch_balance()
            self.cached_balances[client_id] = balance
            self.last_balance_fetch_time[client_id] = now
            return balance
        except Exception as e:
            self.logger.error(f"Could not fetch balance for {client_id}: {e}")
            return self.cached_balances.get(client_id, {})

    async def get_portfolio_summary(self) -> Dict[str, Dict[str, float]]:
        """Asynchronously fetches and aggregates balances from all exchanges."""
        portfolio: Dict[str, Dict[str, float]] = {}
        balance_tasks = [self.get_balance_async(client) for client in self.clients.values()]
        results = await asyncio.gather(*balance_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception) or not result:
                continue
            
            for asset, amounts in result.get('total', {}).items():
                if amounts > 0:
                    if asset not in portfolio:
                        portfolio[asset] = {'total': 0.0, 'free': 0.0}
                    portfolio[asset]['total'] += result.get('total', {}).get(asset, 0.0)
                    portfolio[asset]['free'] += result.get('free', {}).get(asset, 0.0)

        return portfolio

    async def close_all_connections(self):
        """Asynchronously closes all exchange connections."""
        self.logger.info("Closing all exchange connections...")
        tasks = [client.close() for client in self.clients.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self.logger.info("All exchange connections have been closed.")

# # exchange_manager.py

# import ccxt
# import time
# import logging
# from typing import Any, Dict, Optional

# from utils import retry_ccxt_call, ExchangeInitError

# class ExchangeManager:
#     """Manages all exchange clients, API calls, and cached data."""

#     def __init__(self, exchanges_config: Dict[str, Any]):
#         self.logger = logging.getLogger(__name__)
#         self.clients: Dict[str, ccxt.Exchange] = {}
#         self.cached_balances: Dict[str, Dict[str, Any]] = {}
#         self.last_balance_fetch_time: Dict[str, float] = {}
#         self.BALANCE_CACHE_DURATION: int = 30

#         self._initialize_clients(exchanges_config)

#     def _initialize_clients(self, exchanges_config: Dict[str, Any]):
#         for ex_name, config_data in exchanges_config.items():
#             try:
#                 exchange_class = getattr(ccxt, ex_name)
#                 client = exchange_class(config_data)
#                 if hasattr(client, 'set_sandbox_mode'):
#                     client.set_sandbox_mode(True)
#                 retry_ccxt_call(client.load_markets)()
#                 self.clients[ex_name] = client
#                 self.logger.info(f"Initialized {ex_name.capitalize()} client.")
#             except Exception as e:
#                 self.logger.critical(f"Error initializing {ex_name.capitalize()}: {e}")
#                 raise ExchangeInitError(f"Failed to initialize {ex_name.capitalize()}: {e}")

#     def get_client(self, exchange_name: str) -> Optional[ccxt.Exchange]:
#         return self.clients.get(exchange_name)

#     def get_all_clients(self) -> Dict[str, ccxt.Exchange]:
#         return self.clients

#     async def fetch_all_tickers_async(self) -> dict:
#         """
#         Asynchronously fetches tickers from all exchanges concurrently.
#         """
#         tasks = [
#             self.exchanges[name].fetch_tickers() for name in self.exchanges
#         ]
#         results = await asyncio.gather(*tasks, return_exceptions=True)
        
#         market_data = {}
#         for exchange_name, result in zip(self.exchanges.keys(), results):
#             if isinstance(result, Exception):
#                 self.logger.error(f"Failed to fetch async tickers for {exchange_name}: {result}")
#             else:
#                 market_data[exchange_name] = result
#         return market_data

#     async def close_all_connections(self):
#         """
#         Asynchronously closes all exchange connections.
#         """
#         tasks = [
#             self.exchanges[name].close() for name in self.exchanges
#         ]
#         await asyncio.gather(*tasks, return_exceptions=True)
#         self.logger.info("All exchange connections have been closed.")

#     def get_balance(self, client: ccxt.Exchange, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
#         now = time.time()
#         client_id = client.id
#         last_fetch = self.last_balance_fetch_time.get(client_id, 0)
        
#         if not force_refresh and (now - last_fetch) < self.BALANCE_CACHE_DURATION:
#             return self.cached_balances.get(client_id)
#         try:
#             balance = retry_ccxt_call(client.fetch_balance)()
#             self.cached_balances[client_id] = balance
#             self.last_balance_fetch_time[client_id] = now
#             return balance
#         except Exception as e:
#             self.logger.error(f"Could not fetch balance for {client_id}: {e}")
#             return self.cached_balances.get(client_id)

#     def get_total_balance_usdt(self) -> Optional[float]:
#         total_usdt = 0.0
#         try:
#             for client in self.clients.values():
#                 balance_data = self.get_balance(client, force_refresh=True)
#                 if balance_data and 'total' in balance_data and 'USDT' in balance_data['total']:
#                     total_usdt += balance_data['total']['USDT']
#             return total_usdt
#         except Exception as e:
#             self.logger.error(f"Error calculating total USDT balance: {e}")
#             return None

#     @retry_ccxt_call
#     def get_market_price(self, client: ccxt.Exchange, symbol: str) -> Optional[float]:
#         ticker = client.fetch_ticker(symbol)
#         if ticker and ticker.get('bid') and ticker.get('ask'):
#             return (ticker['bid'] + ticker['ask']) / 2
#         return None

#     @retry_ccxt_call
#     def _fetch_order_book(self, client: ccxt.Exchange, symbol: str) -> Dict[str, Any]:
#         return client.fetch_order_book(symbol, limit=20)

#     def get_price_for_size(self, order_book_side: list, size_in_quote: float) -> Optional[float]:
#         cumulative_size, cumulative_cost = 0.0, 0.0
#         for price, volume, *_ in order_book_side:
#             price = float(price)
#             volume = float(volume)
#             cost = price * volume
#             if cumulative_cost + cost >= size_in_quote:
#                 remaining_cost = size_in_quote - cumulative_cost
#                 remaining_volume = remaining_cost / price
#                 cumulative_cost += remaining_cost
#                 cumulative_size += remaining_volume
#                 return cumulative_cost / cumulative_size if cumulative_size > 0 else None
#             cumulative_cost += cost
#             cumulative_size += volume
#         self.logger.warning(f"Insufficient liquidity to meet trade size of ${size_in_quote:.2f}.")
#         return None

#     def get_market_data(self, symbol: str, trade_size_usdt: float) -> Dict[str, Dict[str, Optional[float]]]:
#         prices: Dict[str, Dict[str, Optional[float]]] = {}
#         for ex_name, client in self.clients.items():
#             try:
#                 # --- ADDED LOGGING ---
#                 self.logger.info(f"  Fetching order book for {symbol} on {ex_name.upper()}...")
#                 ob = self._fetch_order_book(client, symbol)
#                 # --- ADDED LOGGING ---
#                 self.logger.info(f"  ...Success for {ex_name.upper()}.")

#                 if not ob or not ob.get('bids') or not ob.get('asks'):
#                     self.logger.warning(f"Received empty or invalid order book from {ex_name} for {symbol}.")
#                     prices[ex_name] = {'bid': None, 'ask': None}
#                     continue
                
#                 prices[ex_name] = {
#                     'bid': self.get_price_for_size(ob['bids'], trade_size_usdt),
#                     'ask': self.get_price_for_size(ob['asks'], trade_size_usdt)
#                 }
#             except Exception as e:
#                 self.logger.error(f"Failed to fetch or process market data for {ex_name} on {symbol}. Error: {e}")
#                 prices[ex_name] = {'bid': None, 'ask': None}
#         return prices

#     def close_all_clients(self):
#         self.logger.info("Closing all exchange connections...")
#         for name, client in self.clients.items():
#             try:
#                 if hasattr(client, 'close'):
#                     client.close()
#                     self.logger.info(f"Closed connection to {name.capitalize()}.")
#             except Exception as e:
#                 self.logger.warning(f"Could not close connection for {name.capitalize()}: {e}")