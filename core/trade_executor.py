# core/trade_executor.py
from __future__ import annotations
import time
import threading
from typing import Any, Optional, Callable, Dict

from config.logging_config import get_logger


class TradeExecutor:
    """
    Synchronous trade executor with graceful stop support.

    Responsibilities:
    - Place & monitor orders (blocking methods).
    - Expose `execute_and_monitor_opportunity(opportunity)` for engine.
    - Provide busy flag and request_stop() for lifecycle coordination.
    - Stream progress via an optional callback.
    """

    def __init__(self, exchange_manager: Any):
        self.log = get_logger(__name__)
        self.exchange_manager = exchange_manager
        self._busy = False
        self._stop_evt = threading.Event()
        self._progress_cb: Optional[Callable[[str], None]] = None

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

    # -------- Public trading API --------

    def execute_and_monitor_opportunity(self, opportunity: Any) -> Dict[str, Any]:
        """
        Main entry for the engine. Synchronous & blocking.
        Expects `opportunity` to carry all fields required for pair of legs.
        """
        self.reset_stop()
        self.set_busy(True)
        try:
            self._emit(f"Executing opportunity: {getattr(opportunity, 'id', '<no-id>')}")
            # 1) Prepare legs (buy on A, sell on B) or vice versa
            legs = self._build_legs(opportunity)

            # 2) Place first leg
            leg1_res = self._place_and_wait(legs[0])

            # Optional early exit if stopping requested
            if self.is_stopping():
                self._emit("Stopping after leg1 due to stop request")
                return {"status": "stopped", "leg1": leg1_res}

            # 3) Place second leg (hedge/exit)
            leg2_res = self._place_and_wait(legs[1])

            # 4) Post-trade checks / PnL calc
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

    # -------- Internals (adapt to your EM / CCXT specifics) --------

    def _build_legs(self, opportunity: Any):
        """
        Translate an opportunity into two executable legs.
        This method is intentionally simple and should be adapted to your data model.
        Expected opportunity fields (examples):
          - buy_exchange, sell_exchange
          - symbol, amount
          - buy_price, sell_price
          - order_type ('market'/'limit'), etc.
        """
        symbol = getattr(opportunity, "symbol", "BTC/USDT")
        amount = float(getattr(opportunity, "amount", 0.001))
        order_type = getattr(opportunity, "order_type", "market")

        buy_ex = getattr(opportunity, "buy_exchange", None)
        sell_ex = getattr(opportunity, "sell_exchange", None)
        buy_price = getattr(opportunity, "buy_price", None)
        sell_price = getattr(opportunity, "sell_price", None)

        leg_buy = {
            "side": "buy",
            "exchange": buy_ex,
            "symbol": symbol,
            "amount": amount,
            "type": order_type,
            "price": buy_price,
        }
        leg_sell = {
            "side": "sell",
            "exchange": sell_ex,
            "symbol": symbol,
            "amount": amount,
            "type": order_type,
            "price": sell_price,
        }
        return (leg_buy, leg_sell)

    def _place_and_wait(self, leg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Places an order using ExchangeManager and waits until it is filled (or stop requested).
        This is synchronous and should call your existing EM methods (duck-typed).
        """
        ex_id = leg["exchange"]
        symbol = leg["symbol"]
        side = leg["side"]
        amount = float(leg["amount"])
        otype = leg.get("type", "market")
        price = leg.get("price")

        if not ex_id:
            raise ValueError("Missing exchange id for leg")

        self._emit(f"Placing {otype} {side} {amount} {symbol} on {ex_id} (price={price})")

        # ---- Place order (support different EM method names) ----
        order = None
        em = self.exchange_manager
        if hasattr(em, "place_order"):
            order = em.place_order(ex_id, symbol, side, amount, price=price, order_type=otype)
        elif hasattr(em, "create_order"):
            order = em.create_order(ex_id, symbol, side, amount, price=price, order_type=otype)
        else:
            raise RuntimeError("ExchangeManager lacks place/create order API")

        order_id = order.get("id") if isinstance(order, dict) else getattr(order, "id", None)
        self._emit(f"Order placed: {order_id}")

        # ---- Monitor until filled/canceled/stop ----
        t0 = time.time()
        last_status = None
        while not self.is_stopping():
            status = self._fetch_order_status(ex_id, symbol, order_id)
            if status != last_status:
                last_status = status
                self._emit(f"Order {order_id} status: {status}")

            if status in ("closed", "filled", "canceled", "rejected"):
                break
            time.sleep(0.5)

        if self.is_stopping() and status not in ("closed", "filled"):
            self._emit(f"Cancel due to stop: {order_id}")
            try:
                self._cancel_order(ex_id, symbol, order_id)
            except Exception as e:
                self.log.warning("Cancel failed for %s: %s", order_id, e)

        filled = status in ("closed", "filled")
        elapsed = time.time() - t0
        return {
            "order_id": order_id,
            "exchange": ex_id,
            "symbol": symbol,
            "side": side,
            "status": status,
            "elapsed_sec": elapsed,
        }

    def _fetch_order_status(self, exchange_id: str, symbol: str, order_id: str) -> str:
        em = self.exchange_manager
        if hasattr(em, "fetch_order_status"):
            return str(em.fetch_order_status(exchange_id, symbol, order_id))
        if hasattr(em, "get_order_status"):
            return str(em.get_order_status(exchange_id, symbol, order_id))
        # Generic fallback (some EMs return full order)
        if hasattr(em, "fetch_order"):
            data = em.fetch_order(exchange_id, symbol, order_id)
            if isinstance(data, dict):
                return str(data.get("status", "unknown"))
        return "unknown"

    def _cancel_order(self, exchange_id: str, symbol: str, order_id: str) -> None:
        em = self.exchange_manager
        if hasattr(em, "cancel_order"):
            em.cancel_order(exchange_id, symbol, order_id)
        elif hasattr(em, "cancel"):
            em.cancel(exchange_id, symbol, order_id)
        else:
            self.log.warning("No cancel method on ExchangeManager for %s", order_id)

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
