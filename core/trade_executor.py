# core/trade_executor.py
from __future__ import annotations
import time
import threading
from typing import Any, Optional, Callable, Dict

from config.logging_config import get_logger


class TradeExecutor:
    """
    Synchronous trade executor with graceful stop & speed optimizations.

    Responsibilities:
    - Place & monitor orders (blocking, low-latency with adaptive backoff).
    - Expose `execute_and_monitor_opportunity(opportunity)` for engine.
    - Provide busy flag and request_stop() for lifecycle coordination.
    - Stream progress via an optional callback.
    - Directly uses ccxt clients via ExchangeManager.clients for speed.
    """

    def __init__(self, exchange_manager: Any):
        self.log = get_logger(__name__)
        self.exchange_manager = exchange_manager
        self._busy = False
        self._stop_evt = threading.Event()
        self._progress_cb: Optional[Callable[[str], None]] = None

        # Runtime params (can be tweaked at runtime via set_runtime_params)
        self.default_monitor_timeout_s: float = 30.0
        self.min_poll_s: float = 0.15
        self.max_poll_s: float = 0.75

    # -------- Lifecycle --------

    def set_progress_callback(self, cb: Optional[Callable[[str], None]]) -> None:
        self._progress_cb = cb

    def request_stop(self) -> None:
        """Ask long-running monitor loops to wind down ASAP."""
        self._stop_evt.set()
        self._emit("received stop signal")

    def reset_stop(self) -> None:
        self._stop_evt.clear()

    def is_stopping(self) -> bool:
        return self._stop_evt.is_set()

    def set_busy(self, value: bool) -> None:
        self._busy = bool(value)

    def is_busy(self) -> bool:
        return self._busy

    def set_runtime_params(
        self,
        *,
        monitor_timeout_s: Optional[float] = None,
        min_poll_s: Optional[float] = None,
        max_poll_s: Optional[float] = None,
    ) -> None:
        """Allow the engine/GUI to tune speed without code changes."""
        if monitor_timeout_s is not None:
            self.default_monitor_timeout_s = float(monitor_timeout_s)
        if min_poll_s is not None:
            self.min_poll_s = max(0.05, float(min_poll_s))
        if max_poll_s is not None:
            self.max_poll_s = max(self.min_poll_s, float(max_poll_s))

    # -------- Public trading API --------

    def execute_and_monitor_opportunity(self, opportunity: Any) -> Dict[str, Any]:
        """
        Main entry for the engine. Synchronous & blocking.
        Expects `opportunity` to carry all fields required for two legs.
        """
        self.reset_stop()
        self.set_busy(True)
        try:
            oid = getattr(opportunity, "id", None)
            self._emit(f"Executing opportunity {oid or '<no-id>'}")

            legs = self._build_legs(opportunity)

            # Leg 1
            leg1_res = self._place_and_wait(legs[0], opportunity)

            if self.is_stopping():
                self._emit("Stopping after leg1 due to stop request")
                return {"status": "stopped", "leg1": leg1_res}

            # Leg 2 (hedge/exit)
            leg2_res = self._place_and_wait(legs[1], opportunity)

            pnl = self._compute_pnl(opportunity, leg1_res, leg2_res)
            self._emit(f"Trade completed. PnL={pnl:.4f}")

            return {
                "status": "filled",
                "pnl": pnl,
                "leg1": leg1_res,
                "leg2": leg2_res,
            }

        except Exception as e:
            self.log.exception("Trade execution error: %s", e)
            return {"status": "failed", "error": str(e)}
        finally:
            self.set_busy(False)

    # -------- Internals --------

    def _client(self, exchange_id: str):
        clients = getattr(self.exchange_manager, "clients", {})
        if exchange_id not in clients:
            raise ValueError(f"Unknown exchange id: {exchange_id}")
        return clients[exchange_id]

    def _build_legs(self, opportunity: Any):
        """
        Translate an opportunity into two executable legs.
        Expected opportunity fields:
          - buy_exchange, sell_exchange
          - symbol, amount
          - buy_price, sell_price
          - order_type ('market'/'limit'), dry_run (optional)
        """
        symbol = getattr(opportunity, "symbol", "BTC/USDT")
        amount = float(getattr(opportunity, "amount", 0.001))
        order_type = str(getattr(opportunity, "order_type", "market")).lower()

        buy_ex = getattr(opportunity, "buy_exchange", None)
        sell_ex = getattr(opportunity, "sell_exchange", None)
        buy_price = getattr(opportunity, "buy_price", None)
        sell_price = getattr(opportunity, "sell_price", None)

        # Leg order: long first (buy), then hedge/exit (sell)
        leg_buy = {
            "side": "buy",
            "exchange": buy_ex,
            "symbol": symbol,
            "amount": amount,
            "type": order_type,
            "price": float(buy_price) if buy_price is not None else None,
        }
        leg_sell = {
            "side": "sell",
            "exchange": sell_ex,
            "symbol": symbol,
            "amount": amount,
            "type": order_type,
            "price": float(sell_price) if sell_price is not None else None,
        }
        return (leg_buy, leg_sell)

    def _place_and_wait(self, leg: Dict[str, Any], opportunity: Any) -> Dict[str, Any]:
        """
        Places an order on the target exchange and waits until it is filled (or stop/timeout).
        Ultra-fast loop with adaptive backoff and a hard timeout.
        """
        ex_id = str(leg["exchange"])
        symbol = leg["symbol"]
        side = leg["side"]
        amount = float(leg["amount"])
        otype = str(leg.get("type", "market")).lower()
        price = leg.get("price")
        dry_run = bool(getattr(opportunity, "dry_run", False))

        if not ex_id:
            raise ValueError("Missing exchange id for leg")

        # --- DRY RUN: simulate instantly ---
        if dry_run:
            self._emit(f"[DRY RUN] {otype} {side} {amount} {symbol} on {ex_id} (price={price})")
            return {
                "order_id": f"DRYRUN-{int(time.time()*1000)}",
                "exchange": ex_id,
                "symbol": symbol,
                "side": side,
                "status": "filled",
                "elapsed_sec": 0.0,
            }

        client = self._client(ex_id)
        self._emit(f"Placing {otype} {side} {amount} {symbol} on {ex_id} (price={price})")

        # ---- Place order (ccxt unified) ----
        order = None
        if otype == "market":
            # ccxt create_order accepts price=None for market orders
            order = client.create_order(symbol, "market", side, amount, None, {})
        else:
            if price is None:
                raise ValueError("Limit order requires a price.")
            order = client.create_order(symbol, "limit", side, amount, float(price), {})

        order_id = order.get("id") if isinstance(order, dict) else getattr(order, "id", None)
        self._emit(f"Order placed: {order_id}")

        # ---- Monitor until filled/canceled/stop/timeout ----
        timeout_s = float(
            getattr(opportunity, "order_monitor_timeout_s", self.default_monitor_timeout_s)
        )

        start = time.perf_counter()
        next_sleep = self.min_poll_s
        last_status = None
        status = "unknown"

        # Best-effort: if the exchange doesn't implement fetchOrder, we exit early
        has_fetch_order = getattr(client, "has", {}).get("fetchOrder", True)

        while not self.is_stopping():
            elapsed = time.perf_counter() - start
            if elapsed >= timeout_s:
                self._emit(f"Order timeout after {elapsed:.2f}s: {order_id}")
                status = "timeout"
                break

            try:
                if has_fetch_order:
                    info = client.fetch_order(order_id, symbol)
                    status = str(info.get("status", "unknown")).lower()
                else:
                    # Fallback: try fetch_open_orders to detect closure
                    open_list = client.fetch_open_orders(symbol=symbol)
                    still_open = any(o.get("id") == order_id for o in open_list)
                    status = "open" if still_open else "closed"
            except Exception as e:
                # Transient error: log & keep polling
                self._emit(f"fetch_order transient error: {e}")
                status = last_status or "open"

            if status != last_status:
                last_status = status
                self._emit(f"Order {order_id} status: {status}")

            if status in ("closed", "filled", "canceled", "rejected"):
                break

            time.sleep(next_sleep)
            # Adaptive backoff (capped)
            next_sleep = min(self.max_poll_s, max(self.min_poll_s, next_sleep * 1.5))

        # Stop requested: best-effort cancel if not filled yet
        if self.is_stopping() and status not in ("closed", "filled"):
            self._emit(f"Cancel due to stop: {order_id}")
            try:
                self._cancel_order_ccxt(client, symbol, order_id)
                status = "canceled"
            except Exception as e:
                self.log.warning("Cancel failed for %s: %s", order_id, e)

        elapsed = time.perf_counter() - start
        return {
            "order_id": order_id,
            "exchange": ex_id,
            "symbol": symbol,
            "side": side,
            "status": status,
            "elapsed_sec": elapsed,
        }

    def _cancel_order_ccxt(self, client: Any, symbol: str, order_id: str) -> None:
        if getattr(client, "has", {}).get("cancelOrder", True):
            client.cancel_order(order_id, symbol)
        else:
            # Some exchanges only expose cancel_all_orders or require params
            try:
                client.cancel_all_orders(symbol)
            except Exception:
                # best-effort; log and continue
                self.log.info("cancel_all_orders fallback used (may be unsupported)")

    # -------- Utility --------

    def _compute_pnl(self, opportunity: Any, leg1: Dict[str, Any], leg2: Dict[str, Any]) -> float:
        """
        Placeholder PnL calculation. Replace with your real fees/slippage logic.
        """
        # If your analyzer already computed expected_profit, you can use it here as a proxy
        expected = float(getattr(opportunity, "expected_profit", getattr(opportunity, "profit", 0.0)))
        return expected

    def _emit(self, msg: str) -> None:
        if self._progress_cb:
            try:
                self._progress_cb(msg)
            except Exception:
                self.log.exception("Progress callback failed")
        self.log.info("[Trade] %s", msg)
