"""
Synchronous, GUI-friendly engine that orchestrates:
- ExchangeManager (market data snapshot)
- Analyzer (opportunity detection)
- RiskManager (position & risk checks)
- TradeExecutor (blocking order placement/monitoring)
and streams lightweight updates back to the GUI via callbacks.

Optimized for speed (threaded market fetch + caching)
and smooth GUI updates.
"""

from __future__ import annotations
import threading
import time
import traceback
import concurrent.futures
from typing import Callable, Dict, Optional, Any, List

from config.logging_config import get_logger

# Optional types (keeps imports flexible)
try:
    from data_models import Opportunity  # type: ignore
except Exception:
    class Opportunity:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


class ArbitrageBot:
    """Synchronous arbitrage engine that runs on a background thread."""

    def __init__(
        self,
        exchange_manager: Any,
        analyzer: Any,
        risk_manager: Any,
        trade_executor: Any,
        *,
        config: Optional[Dict[str, Any]] = None,
        rebalancer: Optional[Any] = None,
        performance_analyzer: Optional[Any] = None,
        poll_interval_sec: float = 0.75,
        gui_callbacks: Optional[Dict[str, Callable[..., None]]] = None,
    ):
        self.log = get_logger(__name__)
        self.exchange_manager = exchange_manager
        self.analyzer = analyzer
        self.risk_manager = risk_manager
        self.trade_executor = trade_executor
        self.rebalancer = rebalancer
        self.performance_analyzer = performance_analyzer

        self.config: Dict[str, Any] = config or {"trading_parameters": {}}
        self.poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._gui: Dict[str, Callable[..., None]] = gui_callbacks or {}

        # State
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._state_lock = threading.RLock()
        self._running = False
        self.start_time = 0.0

        # Stats
        self.session_profit = 0.0
        self.trade_count = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.neutralized_trades = 0
        self.critical_failures = 0

        # Internals
        self._trade_lock = threading.RLock()
        self._loop_tick = 0
        self._last_status = "initialized"

        self.log.info("SyncArbitrageEngine initialized (poll=%.2fs)", self.poll_interval_sec)

    # ---------------- GUI API ----------------

    @property
    def running(self) -> bool:
        return self.is_running()

    def run(self, selected_symbols: Optional[List[str]] = None) -> None:
        """Entry point called from GUI (blocking inside its thread)."""
        if selected_symbols:
            self.config.setdefault("trading_parameters", {})
            self.config["trading_parameters"]["symbols_to_scan"] = list(selected_symbols)

        with self._state_lock:
            if self._running:
                self.log.warning("Engine already running; ignoring run()")
                return
            self._stop_evt.clear()
            self._running = True
            self.start_time = time.time()

        self._emit("on_status", "engine_started")

        try:
            self._run_loop()
        finally:
            with self._state_lock:
                self._running = False
            self._emit("on_status", "engine_stopped")

    def stop(self, join_timeout: float = 5.0) -> None:
        with self._state_lock:
            if not self._running:
                return
            self._stop_evt.set()
            self._emit("on_status", "engine_stopping")

            try:
                if hasattr(self.trade_executor, "request_stop"):
                    self.trade_executor.request_stop()
            except Exception:
                self.log.warning("TradeExecutor.request_stop failed")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)

        self.log.info("Engine stopped")

    def start(self) -> None:
        """Optional threaded start (not used by GUI)."""
        with self._state_lock:
            if self._running:
                return
            self._stop_evt.clear()
            self._running = True
            self.start_time = time.time()
            self._thread = threading.Thread(target=self._run_loop, name="arb-engine-loop", daemon=True)
            self._thread.start()
        self._emit("on_status", "engine_started")

    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    # ---------------- MAIN LOOP (OPTIMIZED) ----------------

    def _run_loop(self):
        """Fast trading loop with throttling, caching, and threaded market updates."""
        market_cache: Dict[str, Any] = {}
        last_market_update = 0
        last_balance_fetch = 0

        MARKET_UPDATE_INTERVAL = 2.0
        BALANCE_REFRESH_INTERVAL = 60.0
        POLL_INTERVAL = self.poll_interval_sec

        symbols = self.config["trading_parameters"].get("symbols_to_scan", [])
        if not symbols:
            self.log.warning("No symbols configured; engine will idle.")

        self._emit("on_status", "warming_up")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            while not self._stop_evt.is_set():
                start = time.time()

                try:
                    now = time.time()

                    # --- Market data refresh ---
                    if now - last_market_update >= MARKET_UPDATE_INTERVAL:
                        futures = []
                        for symbol in symbols:
                            for ex_name, client in self.exchange_manager.clients.items():
                                futures.append(
                                    pool.submit(self.exchange_manager._fetch_order_book, client, symbol)
                                )
                        results = []
                        for f in futures:
                            try:
                                results.append(f.result(timeout=5))
                            except Exception as e:
                                self.log.debug(f"Fetch failed: {e}")
                        market_cache = self._build_snapshot_from_results(results)
                        last_market_update = now

                    # --- Analyze opportunities ---
                    opportunities = self._find_opportunities(market_cache)
                    if opportunities:
                        self._try_execute_first_safe(opportunities)

                    # --- Update GUI (lightweight) ---
                    self._emit("on_status", "ok")
                    if "on_stats" in self._gui:
                        self._gui["on_stats"](self._get_current_stats())

                    # --- Balance refresh every 60s ---
                    if now - last_balance_fetch >= BALANCE_REFRESH_INTERVAL:
                        balances = self.exchange_manager.get_all_balances()
                        if "on_wallets" in self._gui:
                            self._gui["on_wallets"](balances)
                        last_balance_fetch = now

                    elapsed = time.time() - start
                    if elapsed < POLL_INTERVAL:
                        time.sleep(POLL_INTERVAL - elapsed)

                except Exception as e:
                    self.log.warning(f"Engine loop error: {e}")
                    time.sleep(1)

        self._emit("on_status", "stopped")

    # ---------------- LOGIC HELPERS ----------------

    def _find_opportunities(self, snapshot: dict) -> List[Opportunity]:
        if self.analyzer is None:
            return []
        try:
            if hasattr(self.analyzer, "find_opportunities"):
                opps = self.analyzer.find_opportunities(snapshot)
            elif hasattr(self.analyzer, "analyze_opportunities"):
                opps = self.analyzer.analyze_opportunities(snapshot)
            else:
                opps = self.analyzer.analyze(snapshot)
        except Exception as e:
            self.log.warning(f"Analyzer error: {e}")
            return []

        result = []
        if isinstance(opps, list):
            for o in opps:
                if isinstance(o, Opportunity):
                    result.append(o)
                elif isinstance(o, dict):
                    result.append(Opportunity(**o))
        return result

    def _try_execute_first_safe(self, opps: List[Opportunity]) -> None:
        if self._is_trade_in_progress():
            return

        best = self._pick_best(opps)
        if not best:
            return

        approved = True
        try:
            if hasattr(self.risk_manager, "approve"):
                approved = bool(self.risk_manager.approve(best))
        except Exception as e:
            self.log.warning(f"Risk check failed: {e}")
            return

        if not approved:
            return

        with self._trade_lock:
            try:
                if hasattr(self.trade_executor, "execute_and_monitor_opportunity"):
                    result = self.trade_executor.execute_and_monitor_opportunity(best)
                elif hasattr(self.trade_executor, "execute_opportunity"):
                    result = self.trade_executor.execute_opportunity(best)
                else:
                    self.log.error("TradeExecutor has no execute_* method")
                    return

                self._process_trade_result(best, result)
            except Exception as e:
                self.critical_failures += 1
                self.log.exception(f"Trade failed: {e}")

    def _process_trade_result(self, opp: Opportunity, result: Any):
        self.trade_count += 1
        if isinstance(result, dict) and result.get("status") == "filled":
            self.successful_trades += 1
            self.session_profit += float(result.get("pnl", 0.0))
        elif isinstance(result, dict) and result.get("status") == "neutralized":
            self.neutralized_trades += 1
        else:
            self.failed_trades += 1

    # ---------------- MISC HELPERS ----------------

    def _build_snapshot_from_results(self, results: list) -> dict:
        """Convert multi-exchange order book list into dict form."""
        snapshot = {}
        for res in results:
            if not isinstance(res, dict) or "bids" not in res or "asks" not in res:
                continue
            # simple structure {exchange: {symbol: {"bid": , "ask": }}}
            exchange = getattr(res, "exchange", "unknown")
            symbol = getattr(res, "symbol", "unknown")
            bid = res["bids"][0][0] if res["bids"] else None
            ask = res["asks"][0][0] if res["asks"] else None
            snapshot.setdefault(exchange, {})[symbol] = {"bid": bid, "ask": ask}
        return snapshot

    def _is_trade_in_progress(self) -> bool:
        if hasattr(self.trade_executor, "is_busy"):
            try:
                return bool(self.trade_executor.is_busy())
            except Exception:
                pass
        locked = not self._trade_lock.acquire(blocking=False)
        if not locked:
            self._trade_lock.release()
        return locked

    @staticmethod
    def _pick_best(opps: List[Opportunity]) -> Optional[Opportunity]:
        if not opps:
            return None
        try:
            return max(opps, key=lambda o: getattr(o, "expected_profit", getattr(o, "profit", 0.0)))
        except Exception:
            return opps[0]

    # ---------------- GUI EMIT ----------------

    def _emit(self, name: str, *args, **kwargs):
        cb = self._gui.get(name)
        if not cb:
            return
        try:
            cb(*args, **kwargs)
        except Exception as e:
            self.log.debug(f"GUI callback {name} error: {e}")

    def _get_current_stats(self) -> Dict[str, Any]:
        with self._state_lock:
            win_trades = self.successful_trades
            total = max(1, self.trade_count)
            return {
                "session_profit": self.session_profit,
                "trade_count": self.trade_count,
                "win_rate": (win_trades / total) * 100.0 if self.trade_count else None,
                "avg_profit": (self.session_profit / total) if self.trade_count else 0.0,
                "failed_trades": self.failed_trades,
                "neutralized_trades": self.neutralized_trades,
                "critical_failures": self.critical_failures,
            }
