import asyncio
import logging
import os
from typing import Dict, Any, List, Optional
import ccxt.async_support as ccxt

from utils import ExchangeInitError

class AsyncExchangeManager:
    """
    Asynchronous manager for all exchange interactions.
    This class abstracts away the ccxt library, providing a clean,
    async interface for the bot to use. It handles the creation of
    exchange connections, fetching data, and executing orders.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        
        # This is the single, correct place for initialization logic.
        for ex_id, ex_config in self.config['exchanges'].items():
            try:
                exchange_class = getattr(ccxt, ex_id)
                
                params = {
                    'apiKey': ex_config['api_key'],
                    'secret': ex_config['api_secret'],
                    'options': { 'defaultType': 'spot' },
                }
                # Special handling for OKX testnet which requires a password
                if ex_id == 'okx':
                    okx_pass = os.getenv("OKX_TESTNET_PASSPHRASE")
                    if not okx_pass:
                        raise ExchangeInitError("OKX requires OKX_TESTNET_PASSPHRASE in .env file for testnet.")
                    params['password'] = okx_pass

                exchange = exchange_class(params)
                
                # THIS IS THE FIX FOR THE SILENT CRASH
                # It safely attempts to set sandbox mode without crashing.
                try:
                    exchange.set_sandbox_mode(True)
                    logging.info(f"'{ex_id}' set to sandbox mode.")
                except ccxt.NotSupported:
                    logging.warning(f"Exchange '{ex_id}' does not support set_sandbox_mode().")
                except Exception as e:
                    logging.warning(f"Could not set sandbox mode for '{ex_id}': {e}")

                self.exchanges[ex_id] = exchange
                logging.info(f"Initialized async exchange client: {ex_id}")

            except AttributeError:
                raise ExchangeInitError(f"Exchange '{ex_id}' is not supported by ccxt.")
            except Exception as e:
                raise ExchangeInitError(f"Failed to initialize exchange '{ex_id}': {e}")
    
    async def init_exchanges(self):
        """Asynchronously loads markets for all initialized exchanges."""
        logging.info("Loading markets for all exchanges...")
        try:
            tasks = [ex.load_markets() for ex in self.exchanges.values()]
            await asyncio.gather(*tasks)
            logging.info("All markets loaded successfully.")
        except Exception as e:
            logging.error(f"Error loading markets: {e}", exc_info=True)
            raise 

    async def get_portfolio_snapshot(self) -> Dict[str, Any]:
        """
        Creates a detailed snapshot of the portfolio across all exchanges.
        Fetches balances and current ticker prices concurrently for performance.
        """
        snapshot = {
            'total_usd_value': 0.0,
            'assets': {},
            'by_exchange': {ex_id: {'total_usd_value': 0.0, 'assets': {}} for ex_id in self.exchanges}
        }

        # 1. Fetch all balances concurrently
        balance_tasks = {ex_id: ex.fetch_balance() for ex_id, ex in self.exchanges.items()}
        balances_results = await asyncio.gather(*balance_tasks.values(), return_exceptions=True)
        
        all_assets = set()
        balances = dict(zip(balance_tasks.keys(), balances_results))

        for ex_id, balance in balances.items():
            if isinstance(balance, Exception):
                logging.error(f"Failed to fetch balance for {ex_id}: {balance}")
                continue
            
            for currency, amount in balance['total'].items():
                if amount > 0:
                    all_assets.add(currency)
                    if currency not in snapshot['assets']:
                        snapshot['assets'][currency] = {'total_amount': 0.0, 'usd_value': 0.0, 'exchanges': {}}
                    
                    snapshot['assets'][currency]['total_amount'] += amount
                    snapshot['assets'][currency]['exchanges'][ex_id] = amount
                    snapshot['by_exchange'][ex_id]['assets'][currency] = amount

        # 2. Fetch all required tickers concurrently to get prices
        price_symbols = {f"{asset}/USDT" for asset in all_assets if asset != 'USDT'}
        # Use a single, consistent exchange for pricing
        price_exchange_id = list(self.exchanges.keys())[0]
        price_exchange = self.exchanges[price_exchange_id]
        
        ticker_tasks = {symbol: price_exchange.fetch_ticker(symbol) for symbol in price_symbols}
        tickers_results = await asyncio.gather(*ticker_tasks.values(), return_exceptions=True)
        
        prices = {'USDT': 1.0}
        for symbol, ticker in zip(ticker_tasks.keys(), tickers_results):
            asset = symbol.split('/')[0]
            if not isinstance(ticker, Exception) and ticker and 'last' in ticker:
                prices[asset] = ticker['last']
            else:
                logging.warning(f"Could not fetch price for {symbol}. It will be valued at 0.")
                prices[asset] = 0.0
        
        # 3. Calculate USD values for the entire portfolio
        for asset, data in snapshot['assets'].items():
            price = prices.get(asset, 0.0)
            usd_value = data['total_amount'] * price
            snapshot['assets'][asset]['usd_value'] = usd_value
            snapshot['total_usd_value'] += usd_value

            for ex_id, amount in data['exchanges'].items():
                  snapshot['by_exchange'][ex_id]['total_usd_value'] += amount * price

        return snapshot

    async def get_order_book(self, ex_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetches the order book for a given symbol on a specific exchange."""
        try:
            return await self.exchanges[ex_id].fetch_order_book(symbol)
        except Exception as e:
            logging.error(f"Could not fetch order book for {symbol} on {ex_id}: {e}")
            return None

    async def create_order(self, ex_id: str, symbol: str, order_type: str, side: str, amount: float, price: float = None):
        """Creates an order on a specific exchange."""
        logging.info(f"Placing {side} {order_type} order for {amount} {symbol} on {ex_id}")
        try:
            return await self.exchanges[ex_id].create_order(symbol, order_type, side, amount, price)
        except Exception as e:
            logging.error(f"Failed to place {side} order on {ex_id} for {symbol}: {e}")
            raise

    async def close(self):
        """Gracefully closes all exchange connections."""
        logging.info("Closing all exchange connections...")
        tasks = [ex.close() for ex in self.exchanges.values()]
        await asyncio.gather(*tasks)
        logging.info("All exchange connections closed.")

