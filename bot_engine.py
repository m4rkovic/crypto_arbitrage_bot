# bot_engine.py
"""
Synchronous, GUI-friendly engine that orchestrates:
- ExchangeManager (market data snapshot)
- Analyzer (opportunity detection)
- RiskManager (position & risk checks)
- TradeExecutor (blocking order placement/monitoring)
and streams lightweight updates back to the GUI via callbacks.

Design goals:
- No async. The engine runs in a dedicated background thread so GUI never freezes.
- Single-trade-at-a-time safeguard (engine-level lock).
- Graceful start/stop with strict state transitions.
- Backward-compatible: uses duck-typing to call existing methods if names differ.
"""

from __future__ import annotations
import threading
import time
import traceback
from typing import Callable, Dict, Optional, Any, List

from config.logging_config import get_logger

# Optional types (keeps imports flexible)
try:
    from data_models import Opportunity  # type: ignore
except Exception:
    class Opportunity:  # fallback
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


class ArbitrageBot:
    """
    Synchronous engine that runs its loop on a dedicated thread (spawned by GUI).
    GUI calls engine.run(symbols) inside its own thread and controls stop().
    """

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

        # YAML config (GUI mutates trading_parameters at runtime)
        self.config: Dict[str, Any] = config or {"trading_parameters": {}}

        self.poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._gui: Dict[str, Callable[..., None]] = gui_callbacks or {}

        # Threading/state
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._state_lock = threading.RLock()
        self.state_lock = self._state_lock       # public alias expected by GUI
        self._running = False
        self.start_time = 0.0                     # GUI uses for runtime clock

        # Session stats (GUI reads via _get_current_stats)
        self.session_profit = 0.0
        self.trade_count = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.neutralized_trades = 0
        self.critical_failures = 0

        # Trade concurrency
        self._trade_lock = threading.RLock()
        self._last_status = "initialized"

        # Diagnostics
        self._loop_tick = 0

        self.log.info("SyncArbitrageEngine initialized (poll=%.2fs)", self.poll_interval_sec)

    # ---------- Public API expected by GUI ----------

    @property
    def running(self) -> bool:
        return self.is_running()

    def run(self, selected_symbols: Optional[List[str]] = None) -> None:
        """
        Thread entry-point used by GUI. Blocks until stopped.
        Keeps full backward-compatibility with the previous sync engine.
        """
        # apply selected symbols if provided
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
            self._run_loop()  # blocking loop (runs inside GUI-created thread)
        finally:
            with self._state_lock:
                self._running = False
            self._emit("on_status", "engine_stopped")

    def stop(self, join_timeout: float = 5.0) -> None:
        with self._state_lock:
            if not self._running:
                self.log.warning("Engine not running; ignoring stop()")
                return
            self._stop_evt.set()
            self._emit("on_status", "engine_stopping")

            # Request graceful stop from executor if supported
            try:
                if hasattr(self.trade_executor, "request_stop"):
                    self.trade_executor.request_stop()
            except Exception as e:
                self.log.exception("TradeExecutor.request_stop failed: %s", e)

        # If GUI created a thread around run(), it will exit once _run_loop returns.
        # We still try to join if we internally created a thread via start() (not used by GUI).
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=join_timeout)
            if t.is_alive():
                self.log.warning("Engine loop did not stop within %.1fs", join_timeout)
        self.log.info("Engine stopped")

    # Optional: if ever used directly instead of run()
    def start(self) -> None:
        with self._state_lock:
            if self._running:
                self.log.warning("Engine already running; ignoring start()")
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

    # ---------- Main loop ----------

    def _run_loop(self) -> None:
        try:
            self._safe_emit_status("warming_up")
            self._maybe_call(self.rebalancer, "on_engine_start")
            self._maybe_call(self.performance_analyzer, "on_engine_start")

            while not self._stop_evt.is_set():
                start_ts = time.perf_counter()
                self._loop_tick += 1
                try:
                    snapshot = self._fetch_market_snapshot()
                    if snapshot is not None:
                        self._emit("on_market_snapshot", snapshot)

                        opps = self._find_opportunities(snapshot)
                        if opps:
                            self._emit("on_opportunities", [self._opp_to_gui(o) for o in opps])
                            self._try_execute_first_safe(opps)

                    self._maybe_call(self.rebalancer, "maybe_rebalance")
                    if self.performance_analyzer and hasattr(self.performance_analyzer, "tick"):
                        self.performance_analyzer.tick()

                    self._safe_emit_status("ok")

                except Exception as loop_err:
                    err_txt = f"Engine loop error: {loop_err}"
                    self.log.exception(err_txt)
                    self._emit("on_error", err_txt)
                    self._safe_emit_status("error")

                elapsed = time.perf_counter() - start_ts
                time.sleep(max(0.0, self.poll_interval_sec - elapsed))

        except Exception as fatal:
            self.log.exception("Engine fatal error: %s", fatal)
            self._emit("on_error", f"Engine fatal error: {fatal}")
        finally:
            try:
                self._maybe_call(self.rebalancer, "on_engine_stop")
                self._maybe_call(self.performance_analyzer, "on_engine_stop")
            except Exception:
                pass
            self._safe_emit_status("stopped")

    # ---------- Helpers ----------

    def _fetch_market_snapshot(self) -> Optional[dict]:
        em = self.exchange_manager
        snapshot: dict = {"timestamp": time.time()}

        prices = self._maybe_call(em, "get_prices") or self._maybe_call(em, "fetch_prices") or self._maybe_call(em, "fetch_tickers")
        snapshot["prices"] = prices

        orderbooks = self._maybe_call(em, "get_orderbooks") or self._maybe_call(em, "fetch_orderbooks")
        snapshot["orderbooks"] = orderbooks

        balances = self._maybe_call(em, "get_balances") or self._maybe_call(em, "fetch_balances")
        snapshot["balances"] = balances

        return snapshot

    def _find_opportunities(self, snapshot: dict) -> List[Opportunity]:
        if self.analyzer is None:
            return []
        if hasattr(self.analyzer, "find_opportunities"):
            opps = self.analyzer.find_opportunities(snapshot)
        elif hasattr(self.analyzer, "analyze_opportunities"):
            opps = self.analyzer.analyze_opportunities(snapshot)
        else:
            opps = self.analyzer.analyze(snapshot)  # type: ignore

        result: List[Opportunity] = []
        if isinstance(opps, list):
            for o in opps:
                if isinstance(o, Opportunity):
                    result.append(o)
                elif isinstance(o, dict):
                    result.append(Opportunity(**o))
                else:
                    result.append(Opportunity(value=o))
        return result

    def _try_execute_first_safe(self, opps: List[Opportunity]) -> None:
        if self._is_trade_in_progress():
            return

        best = self._pick_best(opps)
        if best is None:
            return

        try:
            approved = True
            if hasattr(self.risk_manager, "approve"):
                approved = bool(self.risk_manager.approve(best))
            elif hasattr(self.risk_manager, "check"):
                approved = bool(self.risk_manager.check(best))
            if not approved:
                self.log.debug("Opportunity rejected by risk manager.")
                return
        except Exception as e:
            self.log.exception("RiskManager error: %s", e)
            return

        with self._trade_lock:
            self._emit("on_trade_started", self._opp_to_gui(best))
            self._safe_emit_status("trade_executing")

            try:
                if hasattr(self.trade_executor, "set_progress_callback"):
                    self.trade_executor.set_progress_callback(
                        lambda msg: self._emit("on_trade_update", {"message": msg})
                    )
                if hasattr(self.trade_executor, "set_busy"):
                    self.trade_executor.set_busy(True)

                if hasattr(self.trade_executor, "execute_and_monitor_opportunity"):
                    result = self.trade_executor.execute_and_monitor_opportunity(best)
                elif hasattr(self.trade_executor, "execute_opportunity"):
                    result = self.trade_executor.execute_opportunity(best)
                else:
                    raise RuntimeError("TradeExecutor lacks execute_* method")

                payload = result if isinstance(result, dict) else {"result": result}
                payload.setdefault("opportunity", self._opp_to_gui(best))
                self._emit("on_trade_finished", payload)
                self._safe_emit_status("ok")

                # naive stats (customize as needed)
                self.trade_count += 1
                if isinstance(result, dict) and result.get("status") == "filled":
                    self.successful_trades += 1
                    self.session_profit += float(result.get("pnl", 0.0))
                elif isinstance(result, dict) and result.get("status") == "neutralized":
                    self.neutralized_trades += 1
                else:
                    self.failed_trades += 1

            except Exception as exec_err:
                self.critical_failures += 1
                self.log.exception("Trade execution failed: %s", exec_err)
                self._emit("on_trade_finished", {
                    "status": "failed",
                    "error": str(exec_err),
                    "traceback": traceback.format_exc(),
                    "opportunity": self._opp_to_gui(best),
                })
                self._safe_emit_status("error")

            finally:
                try:
                    if hasattr(self.trade_executor, "set_busy"):
                        self.trade_executor.set_busy(False)
                except Exception:
                    pass

    def _is_trade_in_progress(self) -> bool:
        try:
            if hasattr(self.trade_executor, "is_busy"):
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

    def _opp_to_gui(self, o: Opportunity) -> dict:
        d = dict(vars(o))
        for k in list(d.keys()):
            if k in ("raw", "orderbook_a", "orderbook_b", "snapshot"):
                d[k] = "<omitted>"
        return d

    def _maybe_call(self, obj: Any, method: str, *args, **kwargs):
        if obj is None:
            return None
        fn = getattr(obj, method, None)
        if callable(fn):
            return fn(*args, **kwargs)
        return None

    def _emit(self, name: str, *args, **kwargs) -> None:
        cb = self._gui.get(name)
        if cb is None:
            return
        try:
            cb(*args, **kwargs)
        except Exception as e:
            self.log.exception("GUI callback %s error: %s", name, e)

    def _safe_emit_status(self, status: str) -> None:
        self._last_status = status
        self._emit("on_status", status)

    # --------- Stats for GUI left panel ---------
    def _get_current_stats(self) -> Dict[str, Any]:
        with self._state_lock:
            win_trades = self.successful_trades
            total = max(1, self.trade_count)  # avoid div by zero
            win_rate = (win_trades / total) * 100.0
            avg_profit = (self.session_profit / total)
            return {
                "session_profit": self.session_profit,
                "trade_count": self.trade_count,
                "win_rate": win_rate if self.trade_count else None,
                "avg_profit": avg_profit if self.trade_count else 0.0,
                "failed_trades": self.failed_trades,
                "neutralized_trades": self.neutralized_trades,
                "critical_failures": self.critical_failures,
            }

# # bot_engine.py
# """
# Synchronous, GUI-friendly engine that orchestrates:
# - ExchangeManager (market data snapshot)
# - Analyzer (opportunity detection)
# - RiskManager (position & risk checks)
# - TradeExecutor (blocking order placement/monitoring)
# and streams lightweight updates back to the GUI via callbacks.

# Design goals:
# - No async. The engine runs in a dedicated background thread so GUI never freezes.
# - Single-trade-at-a-time safeguard (engine-level lock).
# - Graceful start/stop with strict state transitions.
# - Backward-compatible: uses duck-typing to call existing methods if names differ.
# """

# from __future__ import annotations
# import threading
# import time
# import traceback
# from typing import Callable, Dict, Optional, Any, List

# from config.logging_config import get_logger

# # Optional types (not strictly required if your project already provides them)
# try:
#     from data_models import Opportunity  # type: ignore
# except Exception:
#     class Opportunity:  # minimal fallback to avoid import errors
#         def __init__(self, **kwargs):
#             self.__dict__.update(kwargs)


# class ArbitrageBot:
#     """
#     Synchronous engine that runs its own loop on a background thread.
#     GUI calls engine.start() / engine.stop() and receives updates via callbacks.
#     """

#     # ---- Public callbacks interface (all optional) ----
#     # on_status(str)                  -> short human-readable status string
#     # on_market_snapshot(dict)        -> latest market snapshot used by analyzer
#     # on_opportunities(list[dict])    -> list of found opportunities (lightweight)
#     # on_trade_started(dict)          -> trade/opportunity just kicked off
#     # on_trade_update(dict)           -> progress updates from TradeExecutor
#     # on_trade_finished(dict)         -> final outcome (filled/failed/canceled)
#     # on_error(str)                   -> error message

#     def __init__(
#         self,
#         exchange_manager: Any,
#         analyzer: Any,
#         risk_manager: Any,
#         trade_executor: Any,
#         *,
#         config: Optional[Dict[str, Any]] = None,
#         rebalancer: Optional[Any] = None,
#         performance_analyzer: Optional[Any] = None,
#         poll_interval_sec: float = 0.75,
#         gui_callbacks: Optional[Dict[str, Callable[..., None]]] = None,

#     ):
#         self.log = get_logger(__name__)
#         self.exchange_manager = exchange_manager
#         self.analyzer = analyzer
#         self.risk_manager = risk_manager
#         self.trade_executor = trade_executor
#         self.rebalancer = rebalancer
#         self.performance_analyzer = performance_analyzer

#         self.poll_interval_sec = max(0.05, float(poll_interval_sec))
#         self._gui: Dict[str, Callable[..., None]] = gui_callbacks or {}

#         self._thread: Optional[threading.Thread] = None
#         self._stop_evt = threading.Event()
#         self._state_lock = threading.RLock()
#         self.state_lock = self._state_lock  
#         self.config = config or {"trading_parameters": {}}
#         self._running = False

#         # Engine-level trade lock: prevents concurrent trade attempts.
#         self._trade_lock = threading.RLock()
#         self._last_status = "initialized"

#         # For lightweight health diagnostics
#         self._loop_tick = 0

#         self.log.info("SyncArbitrageEngine initialized (poll=%.2fs)", self.poll_interval_sec)

#     # --------------- Public API ---------------

#     def start(self) -> None:
#         with self._state_lock:
#             if self._running:
#                 self.log.warning("Engine already running; ignoring start()")
#                 return
#             self._stop_evt.clear()
#             self._running = True
#             self._thread = threading.Thread(
#                 target=self._run_loop,
#                 name="arb-engine-loop",
#                 daemon=True,
#             )
#             self._thread.start()
#             self._emit("on_status", "engine_started")
#             self.log.info("Engine started")

#     def stop(self, join_timeout: float = 5.0) -> None:
#         with self._state_lock:
#             if not self._running:
#                 self.log.warning("Engine not running; ignoring stop()")
#                 return

#             self._stop_evt.set()
#             self._emit("on_status", "engine_stopping")

#             # Ask executor to gracefully wind down
#             try:
#                 if hasattr(self.trade_executor, "request_stop"):
#                     self.trade_executor.request_stop()
#             except Exception as e:
#                 self.log.exception("TradeExecutor.request_stop failed: %s", e)

#             t = self._thread
#             self._thread = None
#             self._running = False

#         if t and t.is_alive():
#             t.join(timeout=join_timeout)
#             if t.is_alive():
#                 self.log.warning("Engine loop did not stop within %.1fs", join_timeout)
#         self._emit("on_status", "engine_stopped")
#         self.log.info("Engine stopped")

#     def is_running(self) -> bool:
#         with self._state_lock:
#             return self._running

#     def get_status(self) -> str:
#         return self._last_status

#     # --------------- Internal loop ---------------

#     def _run_loop(self) -> None:
#         try:
#             self._safe_emit_status("warming_up")

#             # Optional: warm-up rebalancer or performance analyzer if present
#             self._maybe_call(self.rebalancer, "on_engine_start")
#             self._maybe_call(self.performance_analyzer, "on_engine_start")

#             # Main loop
#             while not self._stop_evt.is_set():
#                 start_ts = time.perf_counter()
#                 self._loop_tick += 1
#                 try:
#                     snapshot = self._fetch_market_snapshot()
#                     if snapshot is not None:
#                         self._emit("on_market_snapshot", snapshot)

#                         # Analyze
#                         opps = self._find_opportunities(snapshot)
#                         if opps:
#                             self._emit("on_opportunities", [self._opp_to_gui(o) for o in opps])

#                             # Try to execute at most one opportunity at a time
#                             self._try_execute_first_safe(opps)

#                     # Optional: continuous portfolio maintenance
#                     self._maybe_call(self.rebalancer, "maybe_rebalance")

#                     # Optional: performance tracking
#                     if self.performance_analyzer and hasattr(self.performance_analyzer, "tick"):
#                         self.performance_analyzer.tick()

#                     self._safe_emit_status("ok")

#                 except Exception as loop_err:
#                     err_txt = f"Engine loop error: {loop_err}"
#                     self.log.exception(err_txt)
#                     self._emit("on_error", err_txt)
#                     self._safe_emit_status("error")

#                 # pacing
#                 elapsed = time.perf_counter() - start_ts
#                 sleep_for = max(0.0, self.poll_interval_sec - elapsed)
#                 time.sleep(sleep_for)

#         except Exception as fatal:
#             self.log.exception("Engine fatal error: %s", fatal)
#             self._emit("on_error", f"Engine fatal error: {fatal}")
#         finally:
#             # Finalizers
#             try:
#                 self._maybe_call(self.rebalancer, "on_engine_stop")
#                 self._maybe_call(self.performance_analyzer, "on_engine_stop")
#             except Exception:
#                 pass
#             self._safe_emit_status("stopped")

#     # --------------- Helpers ---------------

#     def _fetch_market_snapshot(self) -> Optional[dict]:
#         """
#         Produces a lightweight snapshot for the analyzer. The engine is tolerant to
#         different ExchangeManager APIs by trying common method names.
#         Expected keys (best effort): prices, orderbooks, balances, timestamp
#         """
#         em = self.exchange_manager
#         snapshot: dict = {"timestamp": time.time()}

#         # prices
#         prices = self._maybe_call(em, "get_prices")
#         if prices is None:
#             prices = self._maybe_call(em, "fetch_prices")
#         if prices is None:
#             prices = self._maybe_call(em, "fetch_tickers")
#         snapshot["prices"] = prices

#         # orderbooks (optional)
#         orderbooks = self._maybe_call(em, "get_orderbooks")
#         if orderbooks is None:
#             orderbooks = self._maybe_call(em, "fetch_orderbooks")
#         snapshot["orderbooks"] = orderbooks

#         # balances (optional)
#         balances = self._maybe_call(em, "get_balances")
#         if balances is None:
#             balances = self._maybe_call(em, "fetch_balances")
#         snapshot["balances"] = balances

#         return snapshot

#     def _find_opportunities(self, snapshot: dict) -> List[Opportunity]:
#         # Prefer an explicit analyzer method if it exists
#         if hasattr(self.analyzer, "find_opportunities"):
#             opps = self.analyzer.find_opportunities(snapshot)
#         elif hasattr(self.analyzer, "analyze_opportunities"):
#             opps = self.analyzer.analyze_opportunities(snapshot)
#         else:
#             # Last resort: call analyze(snapshot) expecting it returns list-like
#             opps = self.analyzer.analyze(snapshot)  # type: ignore

#         # Normalize: keep only list of Opportunity / dict-like
#         result: List[Opportunity] = []
#         if isinstance(opps, list):
#             for o in opps:
#                 if isinstance(o, Opportunity):
#                     result.append(o)
#                 else:
#                     result.append(Opportunity(**o) if isinstance(o, dict) else Opportunity(value=o))
#         return result

#     def _try_execute_first_safe(self, opps: List[Opportunity]) -> None:
#         # do not overlap trades
#         if self._is_trade_in_progress():
#             return

#         best = self._pick_best(opps)
#         if best is None:
#             return

#         # Risk checks
#         try:
#             approved = True
#             if hasattr(self.risk_manager, "approve"):
#                 approved = bool(self.risk_manager.approve(best))
#             elif hasattr(self.risk_manager, "check"):
#                 approved = bool(self.risk_manager.check(best))
#             if not approved:
#                 self.log.debug("Opportunity rejected by risk manager.")
#                 return
#         except Exception as e:
#             self.log.exception("RiskManager error: %s", e)
#             return

#         # Execute within engine's background thread but protected by lock
#         with self._trade_lock:
#             self._emit("on_trade_started", self._opp_to_gui(best))
#             self._safe_emit_status("trade_executing")

#             try:
#                 # Inform executor about GUI callback if it supports progress streaming
#                 if hasattr(self.trade_executor, "set_progress_callback"):
#                     self.trade_executor.set_progress_callback(
#                         lambda msg: self._emit("on_trade_update", {"message": msg})
#                     )

#                 # Mark busy before call (if executor supports it)
#                 if hasattr(self.trade_executor, "set_busy"):
#                     self.trade_executor.set_busy(True)

#                 # Execute synchronously (blocking) – engine thread is separate from GUI
#                 if hasattr(self.trade_executor, "execute_and_monitor_opportunity"):
#                     result = self.trade_executor.execute_and_monitor_opportunity(best)
#                 elif hasattr(self.trade_executor, "execute_opportunity"):
#                     result = self.trade_executor.execute_opportunity(best)
#                 else:
#                     raise RuntimeError("TradeExecutor lacks execute_* method")

#                 payload = result if isinstance(result, dict) else {"result": result}
#                 payload.setdefault("opportunity", self._opp_to_gui(best))
#                 self._emit("on_trade_finished", payload)
#                 self._safe_emit_status("ok")

#             except Exception as exec_err:
#                 self.log.exception("Trade execution failed: %s", exec_err)
#                 self._emit("on_trade_finished", {
#                     "status": "failed",
#                     "error": str(exec_err),
#                     "traceback": traceback.format_exc(),
#                     "opportunity": self._opp_to_gui(best),
#                 })
#                 self._safe_emit_status("error")

#             finally:
#                 # Clear busy
#                 try:
#                     if hasattr(self.trade_executor, "set_busy"):
#                         self.trade_executor.set_busy(False)
#                 except Exception:
#                     pass

#     def _is_trade_in_progress(self) -> bool:
#         # If executor exposes busy flag, use it; else consult our lock
#         try:
#             if hasattr(self.trade_executor, "is_busy"):
#                 return bool(self.trade_executor.is_busy())
#         except Exception:
#             pass
#         # Non-blocking check of lock: if we can acquire+release, it's free
#         locked = not self._trade_lock.acquire(blocking=False)
#         if not locked:
#             self._trade_lock.release()
#         return locked

#     @staticmethod
#     def _pick_best(opps: List[Opportunity]) -> Optional[Opportunity]:
#         # Pick the highest expected profit opportunity if available
#         if not opps:
#             return None
#         try:
#             return max(opps, key=lambda o: getattr(o, "expected_profit", getattr(o, "profit", 0.0)))
#         except Exception:
#             return opps[0]

#     def _opp_to_gui(self, o: Opportunity) -> dict:
#         # Make a lightweight, JSON-serializable dict for GUI updates
#         d = dict(vars(o))
#         # Avoid dumping heavy objects (orderbooks, raw snapshots etc.)
#         for k in list(d.keys()):
#             if k in ("raw", "orderbook_a", "orderbook_b", "snapshot"):
#                 d[k] = "<omitted>"
#         return d

#     # --------------- Generic utilities ---------------

#     def _maybe_call(self, obj: Any, method: str, *args, **kwargs):
#         if obj is None:
#             return None
#         fn = getattr(obj, method, None)
#         if callable(fn):
#             return fn(*args, **kwargs)
#         return None

#     def _emit(self, name: str, *args, **kwargs) -> None:
#         cb = self._gui.get(name)
#         if cb is None:
#             return
#         try:
#             cb(*args, **kwargs)
#         except Exception as e:
#             # never break the loop because of GUI callback errors
#             self.log.exception("GUI callback %s error: %s", name, e)

#     def _safe_emit_status(self, status: str) -> None:
#         self._last_status = status
#         self._emit("on_status", status)
