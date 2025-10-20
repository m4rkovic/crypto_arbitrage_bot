import ccxt
import time
import logging
from typing import Any, Dict, Optional
from core.utils import retry_ccxt_call, ExchangeInitError
import threading


class ExchangeManager:
    """Manages all exchange clients, API calls, and cached data — optimized for speed and thread safety."""

    def __init__(self, exchanges_config: Dict[str, Any]):
        self.logger = logging.getLogger(__name__)
        self.clients: Dict[str, ccxt.Exchange] = {}

        # Cache and throttling
        self.cached_balances: Dict[str, Dict[str, Any]] = {}
        self.last_balance_fetch_time: Dict[str, float] = {}
        self.balance_cache_duration: float = 60.0  # seconds

        self.cached_orderbooks: Dict[str, Dict[str, Any]] = {}
        self.last_orderbook_fetch_time: Dict[str, float] = {}
        self.orderbook_cache_duration: float = 2.0  # seconds

        self._lock = threading.RLock()

        # Initialize clients
        self._initialize_clients(exchanges_config)

    # ----------------------------------------------------------------------
    # CLIENT INIT
    # ----------------------------------------------------------------------
    def _initialize_clients(self, exchanges_config: Dict[str, Any]):
        for ex_name, config_data in exchanges_config.items():
            try:
                exchange_class = getattr(ccxt, ex_name)
                client = exchange_class(config_data)
                if hasattr(client, "set_sandbox_mode"):
                    client.set_sandbox_mode(True)
                retry_ccxt_call(client.load_markets)()
                self.clients[ex_name] = client
                self.logger.info(f"Initialized {ex_name.capitalize()} client.")
            except Exception as e:
                self.logger.critical(f"Error initializing {ex_name.capitalize()}: {e}")
                raise ExchangeInitError(f"Failed to initialize {ex_name.capitalize()}: {e}")

    def get_all_clients(self) -> Dict[str, ccxt.Exchange]:
        return self.clients

    # ----------------------------------------------------------------------
    # BALANCES (cached and throttled)
    # ----------------------------------------------------------------------
    def get_balance(self, client: ccxt.Exchange, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch and cache per-exchange balances safely."""
        with self._lock:
            now = time.time()
            cid = client.id
            if not force_refresh and (now - self.last_balance_fetch_time.get(cid, 0)) < self.balance_cache_duration:
                return self.cached_balances.get(cid)

            try:
                balance = retry_ccxt_call(client.fetch_balance)()
                self.cached_balances[cid] = balance
                self.last_balance_fetch_time[cid] = now
                return balance
            except Exception as e:
                self.logger.warning(f"[{cid}] Balance fetch failed: {e}")
                return self.cached_balances.get(cid)

    def get_all_balances(self, force_refresh: bool = False) -> Dict[str, Dict[str, float]]:
        """Return a unified dict of balances for all exchanges (cached)."""
        results = {}
        for name, client in self.clients.items():
            try:
                bal = self.get_balance(client, force_refresh=force_refresh) or {}
                totals = bal.get("total", {})
                results[name] = {
                    asset: round(float(amount or 0.0), 4)
                    for asset, amount in totals.items()
                    if amount and amount > 0
                }
            except Exception as e:
                self.logger.debug(f"Balance fetch error for {name}: {e}")
                results[name] = {}
        return results

    # ----------------------------------------------------------------------
    # MARKET DATA (thread-safe and cached)
    # ----------------------------------------------------------------------
    @retry_ccxt_call
    def _fetch_order_book_raw(self, client: ccxt.Exchange, symbol: str) -> Dict[str, Any]:
        return client.fetch_order_book(symbol, limit=10)

    def _fetch_order_book(self, client: ccxt.Exchange, symbol: str) -> Optional[Dict[str, Any]]:
        """Cached, fast, thread-safe order book fetch."""
        cache_key = f"{client.id}:{symbol}"
        now = time.time()

        with self._lock:
            if cache_key in self.cached_orderbooks and (now - self.last_orderbook_fetch_time.get(cache_key, 0)) < self.orderbook_cache_duration:
                return self.cached_orderbooks.get(cache_key)

        try:
            ob = self._fetch_order_book_raw(client, symbol)
            if not ob:
                raise ValueError("Empty order book")

            ob["exchange"] = client.id
            ob["symbol"] = symbol

            with self._lock:
                self.cached_orderbooks[cache_key] = ob
                self.last_orderbook_fetch_time[cache_key] = now

            return ob
        except Exception as e:
            self.logger.debug(f"[{client.id}] Order book fetch failed for {symbol}: {e}")
            return self.cached_orderbooks.get(cache_key)

    def get_market_data(self, symbol: str, trade_size_usdt: float = 0.0) -> Dict[str, Dict[str, Optional[float]]]:
        """Fetches market bids/asks across exchanges, cached for ~2s."""
        prices: Dict[str, Dict[str, Optional[float]]] = {}
        for ex_name, client in self.clients.items():
            try:
                ob = self._fetch_order_book(client, symbol)
                if not ob or not ob.get("bids") or not ob.get("asks"):
                    prices[ex_name] = {"bid": None, "ask": None}
                    continue

                bid = float(ob["bids"][0][0]) if ob["bids"] else None
                ask = float(ob["asks"][0][0]) if ob["asks"] else None
                prices[ex_name] = {"bid": bid, "ask": ask}
            except Exception as e:
                self.logger.debug(f"Market data error for {ex_name}/{symbol}: {e}")
                prices[ex_name] = {"bid": None, "ask": None}
        return prices

    # ----------------------------------------------------------------------
    # SHUTDOWN
    # ----------------------------------------------------------------------
    def close_all_clients(self):
        self.logger.info("Closing all exchange connections...")
        for name, client in self.clients.items():
            try:
                if hasattr(client, "close"):
                    client.close()
                    self.logger.info(f"Closed {name}.")
            except Exception as e:
                self.logger.warning(f"Failed to close {name}: {e}")
