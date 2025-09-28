
# risk_manager.py
"""
Комбиновани RiskManager (Phase-3 stability + Phase-4 features).
- задржава основне провере из Phase-3 (check_balances, check_kill_switch)
- додаје portfolio tracking, deployment limits, dynamic sizing, commit/release механизам
- ради са твојим ExchangeManager-ом (get_client, get_balance, get_all_clients, get_total_balance_usdt)
"""

import logging
import time
from typing import Any, Dict, Optional

from data_models import Opportunity
from exchange_manager import ExchangeManager


class RiskManager:
    def __init__(self, config: Dict[str, Any], exchange_manager: ExchangeManager):
        self.config = config or {}
        self.risk_config = self.config.get("risk_management", {}) or {}
        self.exchange_manager = exchange_manager
        self.logger = logging.getLogger(__name__)

        # portfolio deployment tracking
        self.capital_deployed_usd: float = 0.0
        self.total_portfolio_value_usd: float = 0.0
        self.last_portfolio_update_ts: float = 0.0
        self._portfolio_ttl_s: int = int(self.risk_config.get("portfolio_recalc_ttl_s", 30))

    # -------------------------
    # Portfolio / deployment
    # -------------------------
    def _update_total_portfolio_value(self) -> None:
        """Recalculate total portfolio value in USD. Prefer exchange_manager.get_total_balance_usdt if available."""
        try:
            now = time.time()
            if (now - self.last_portfolio_update_ts) < self._portfolio_ttl_s and self.total_portfolio_value_usd > 0:
                return

            # Try to use a helper on ExchangeManager if it exists
            try:
                total = self.exchange_manager.get_total_balance_usdt()
                if total is not None:
                    self.total_portfolio_value_usd = float(total)
                    self.last_portfolio_update_ts = now
                    self.logger.info(f"Total portfolio value updated (via helper): ${self.total_portfolio_value_usd:,.2f}")
                    return
            except Exception:
                # fallback to manual aggregation
                self.logger.debug("exchange_manager.get_total_balance_usdt() unavailable or failed; falling back to manual calculation.")

            total_value = 0.0
            clients = {}
            try:
                clients = self.exchange_manager.get_all_clients() or {}
            except Exception:
                clients = getattr(self.exchange_manager, "clients", {}) or {}

            for client in (clients.values() if isinstance(clients, dict) else clients):
                try:
                    balance = self.exchange_manager.get_balance(client)
                    if balance and "free" in balance:
                        total_value += float(balance["free"].get("USDT", 0.0) or 0.0)
                except Exception as e:
                    self.logger.debug(f"Skipping client for portfolio calc due to: {e}")

            if total_value > 0:
                self.total_portfolio_value_usd = total_value
                self.last_portfolio_update_ts = now
                self.logger.info(f"Total portfolio value updated (manual): ${self.total_portfolio_value_usd:,.2f}")
        except Exception as e:
            self.logger.error(f"Failed to update portfolio value: {e}", exc_info=True)

    def can_deploy_capital(self, trade_size_usdt: float) -> bool:
        """Check if committing this trade would exceed configured capital deployment percentage."""
        try:
            self._update_total_portfolio_value()
            max_pct = float(self.risk_config.get("max_capital_deployment_percentage", 25.0))
            if self.total_portfolio_value_usd <= 0:
                # if unknown, be conservative and allow small trades
                self.logger.warning("Total portfolio unknown — allowing deployment cautiously.")
                return True

            max_deployable = self.total_portfolio_value_usd * (max_pct / 100.0)
            potential = self.capital_deployed_usd + float(trade_size_usdt)

            if potential > max_deployable:
                self.logger.warning(
                    f"DEPLOYMENT LIMIT: Cannot commit ${trade_size_usdt:,.2f}. "
                    f"Would exceed ${max_deployable:,.2f} ({max_pct}% of portfolio). "
                    f"Currently deployed: ${self.capital_deployed_usd:,.2f}"
                )
                return False
            return True
        except Exception as e:
            self.logger.error(f"Error in can_deploy_capital: {e}", exc_info=True)
            return False

    def commit_capital(self, trade_size_usdt: float) -> None:
        """Mark capital as deployed (should be called once both orders placed / reserved)."""
        try:
            self.capital_deployed_usd += float(trade_size_usdt)
            self.logger.info(f"Capital COMMITTED (+${trade_size_usdt:,.2f}). Total deployed: ${self.capital_deployed_usd:,.2f}")
        except Exception as e:
            self.logger.error(f"Failed to commit capital: {e}", exc_info=True)

    def release_capital(self, trade_size_usdt: float) -> None:
        """Release capital after trade completion/cancellation."""
        try:
            self.capital_deployed_usd -= float(trade_size_usdt)
            if self.capital_deployed_usd < 0:
                self.capital_deployed_usd = 0.0
            self.logger.info(f"Capital RELEASED (-${trade_size_usdt:,.2f}). Total deployed: ${self.capital_deployed_usd:,.2f}")
        except Exception as e:
            self.logger.error(f"Failed to release capital: {e}", exc_info=True)

    # -------------------------
    # Dynamic sizing
    # -------------------------
    def calculate_dynamic_trade_size(self, buy_exchange_id: str, quote_currency: str) -> float:
        """
        Compute trade size from a percentage of available quote balance on buy exchange,
        capped by max_trade_size_usdt.
        """
        try:
            pct = float(self.risk_config.get("balance_percentage_per_trade", 1.0))
            max_size = float(self.risk_config.get("max_trade_size_usdt", 20.0))

            client = self.exchange_manager.get_client(buy_exchange_id)
            if not client:
                self.logger.debug("No buy client found for dynamic size.")
                return 0.0

            balance = self.exchange_manager.get_balance(client)
            if not balance:
                self.logger.debug("No balance for dynamic size calculation.")
                return 0.0

            available = float(balance.get("free", {}).get(quote_currency, 0.0) or 0.0)
            size_from_balance = available * (pct / 100.0)
            final = min(size_from_balance, max_size)
            if final < 1.0:
                return 0.0

            self.logger.info(f"Dynamic size: ${final:.2f} ({pct}% of ${available:.2f}, capped at ${max_size:.2f})")
            return final
        except Exception as e:
            self.logger.error(f"Error calculating dynamic trade size: {e}", exc_info=True)
            return 0.0

    # -------------------------
    # Balance checks (merged)
    # -------------------------
    # In risk_manager.py

    def check_balances(self, opportunity: Opportunity, trade_size_usdt: float) -> bool:
        """
        Checks if sufficient funds are available on the specific exchanges
        required for the arbitrage trade.
        """
        try:
            buy_exchange_id = opportunity.buy_exchange
            sell_exchange_id = opportunity.sell_exchange
            
            buy_client = self.exchange_manager.get_client(buy_exchange_id)
            sell_client = self.exchange_manager.get_client(sell_exchange_id)
            if not buy_client or not sell_client:
                self.logger.warning("One or both exchange clients unavailable for balance check.")
                return False

            base, quote = opportunity.symbol.split("/")
            
            # Fetch balances for the specific exchanges
            buy_bal = self.exchange_manager.get_balance(buy_client, force_refresh=True)
            sell_bal = self.exchange_manager.get_balance(sell_client, force_refresh=True)

            if not buy_bal or not sell_bal:
                self.logger.warning("Could not obtain fresh balances for pre-trade check.")
                return False

            # Get available (free) balances
            available_quote = float(buy_bal.get("free", {}).get(quote, 0.0) or 0.0)
            available_base = float(sell_bal.get("free", {}).get(base, 0.0) or 0.0)
            
            required_quote = float(trade_size_usdt)
            required_base = opportunity.amount

            # --- NEW: SEPARATE CHECKS FOR CLEARER LOGGING ---

            # 1. Check quote currency balance on the BUY exchange
            if available_quote < required_quote:
                self.logger.warning(
                    f"Insufficient {quote} on {buy_exchange_id.upper()}. "
                    f"Need: {required_quote:.2f}, Have: {available_quote:.2f}"
                )
                return False

            # 2. Check base currency balance on the SELL exchange
            if available_base < required_base:
                self.logger.warning(
                    f"Insufficient {base} on {sell_exchange_id.upper()}. "
                    f"Need: {required_base:.6f}, Have: {available_base:.6f}"
                )
                return False

            return True
        except Exception as e:
            self.logger.error(f"Error during balance check for {opportunity.symbol}: {e}", exc_info=True)
            return False

    # -------------------------
    # Kill switch
    # -------------------------

    def check_kill_switch(self, portfolio: dict) -> bool:
        """
        If total portfolio value < configured threshold -> return True (kill).
        This version accepts the portfolio snapshot as an argument.
        """
        try:
            # Assumes self.risk_config is available from __init__
            threshold = float(self.risk_config.get("balance_kill_switch_usd", 0) or 0)
            if threshold <= 0:
                return False  # Kill switch is disabled in the config.

            current_value = portfolio.get('total_usd_value', 0.0)

            if current_value <= 0:
                self.logger.warning("Cannot evaluate kill switch: portfolio value is zero or missing.")
                return False

            if current_value < threshold:
                self.logger.critical(
                    f"KILL SWITCH: Total portfolio value (${current_value:,.2f}) is below the threshold of ${threshold:,.2f}."
                )
                return True
            
            return False  # All clear.
        except Exception as e:
            self.logger.error(f"Error checking kill switch: {e}", exc_info=True)
            return False