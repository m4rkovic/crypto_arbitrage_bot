# rebalancer.py
"""
Rebalancer za Phase-3 (preuzет из Phase-4, али поједностављен):
- проверава периодично да ли неки asset прелази target+threshold
- продаје вишак преко доступних биржи (iterativno)
- користи retry decorator из utils за place-order позиве
"""

import logging
from typing import Any, Dict

from core.exchange_manager import ExchangeManager
from core.utils import retry_ccxt_call


class Rebalancer:
    def __init__(self, config: Dict[str, Any], exchange_manager: ExchangeManager):
        self.config = config.get("rebalancing", {}) if config else {}
        self.exchange_manager = exchange_manager
        self.logger = logging.getLogger(__name__)

    def run_rebalancing_check(self, portfolio: Dict[str, Any]) -> None:
        """
        portfolio: {
            "total_usd_value": float,
            "assets": {
                "BTC": {"value_usd": float, "amount": float},
                "ETH": {...},
                "USDT": {...}
            }
        }
        """
        try:
            if not self.config.get("enabled", False):
                self.logger.debug("Rebalancer disabled.")
                return

            total_value = float(portfolio.get("total_usd_value", 0.0) or 0.0)
            if total_value <= 0:
                self.logger.warning("Total portfolio value unknown or zero; skipping rebalancing.")
                return

            assets = portfolio.get("assets", {}) or {}
            targets = self.config.get("asset_inventory_targets_percent", {}) or {}
            default_max = float(self.config.get("default_max_inventory_percent", 10))
            threshold = float(self.config.get("rebalance_threshold_percent", 5))

            # obtain clients list
            try:
                clients = self.exchange_manager.get_all_clients() or {}
            except Exception:
                clients = getattr(self.exchange_manager, "clients", {}) or {}

            # primary client for price fetch
            primary_client = None
            if isinstance(clients, dict):
                primary_client = next(iter(clients.values()), None)
            elif isinstance(clients, (list, tuple)) and len(clients) > 0:
                primary_client = clients[0]
            if primary_client is None:
                self.logger.error("No exchange client available for price lookups.")
                return

            for asset, data in assets.items():
                if asset == "USDT":
                    continue

                current_pct = (float(data.get("value_usd", 0.0) or 0.0) / total_value) * 100.0
                target_pct = float(targets.get(asset, default_max) or default_max)

                if current_pct > (target_pct + threshold):
                    surplus_usd = float(data.get("value_usd", 0.0) or 0.0) - (total_value * target_pct / 100.0)
                    symbol = f"{asset}/USDT"

                    # try to get mid price
                    price = None
                    try:
                        price = self.exchange_manager.get_market_price(primary_client, symbol)
                    except Exception as e:
                        self.logger.debug(f"Price fetch for {symbol} failed: {e}")

                    if not price:
                        self.logger.warning(f"Cannot get price for {symbol}; skipping asset {asset}.")
                        continue

                    total_amount_to_sell = surplus_usd / float(price)
                    amount_left = total_amount_to_sell

                    self.logger.warning(
                        f"Rebalancing {asset}: at {current_pct:.2f}% (target {target_pct}%). "
                        f"Will attempt to sell {total_amount_to_sell:.6f} {asset} (surplus ${surplus_usd:,.2f})."
                    )

                    # iterate exchanges to sell
                    for ex_name, client in (clients.items() if isinstance(clients, dict) else enumerate(clients)):
                        if amount_left <= 0.00001:
                            break

                        try:
                            balance_info = self.exchange_manager.get_balance(client)
                            available = float(balance_info.get("free", {}).get(asset, 0.0) or 0.0) if balance_info else 0.0
                            if available <= 0.0:
                                continue

                            sell_amount = min(available, amount_left)
                            symbol = f"{asset}/USDT"

                            # check min order cost if present
                            market = {}
                            try:
                                market = client.markets.get(symbol, {}) if hasattr(client, "markets") else {}
                            except Exception:
                                market = {}

                            min_cost = market.get("limits", {}).get("cost", {}).get("min")
                            if min_cost and (sell_amount * price) < min_cost:
                                self.logger.info(f"Skipping {sell_amount:.6f} {asset} on {getattr(client, 'id', ex_name)}; below min cost.")
                                continue

                            self.logger.info(f"Selling {sell_amount:.6f} {asset} on {getattr(client, 'id', ex_name)}...")
                            try:
                                self._place_rebalance_order(client, asset, "sell", sell_amount)
                                amount_left -= sell_amount
                            except Exception as e:
                                self.logger.error(f"Failed to place rebalance order on {getattr(client, 'id', ex_name)}: {e}")
                                # continue trying on other exchanges
                        except Exception as e:
                            self.logger.debug(f"Error while checking exchange {getattr(client, 'id', 'UNKNOWN')}: {e}")

                    if amount_left > 0.00001:
                        self.logger.warning(f"Rebalance for {asset} partially done; {amount_left:.6f} {asset} could not be sold.")
        except Exception as e:
            self.logger.error(f"Unhandled error in rebalancer: {e}", exc_info=True)

    @retry_ccxt_call
    def _place_rebalance_order(self, client, asset: str, side: str, amount: float) -> None:
        """Places market (or fallback) order. Wrapped with retry for network resilience."""
        symbol = f"{asset}/USDT"
        try:
            try:
                amount_precise = client.amount_to_precision(symbol, amount)
            except Exception:
                amount_precise = amount

            if side == "sell":
                if hasattr(client, "create_market_sell_order"):
                    client.create_market_sell_order(symbol, amount_precise)
                else:
                    client.create_market_order(symbol, "sell", amount_precise)
            else:
                if hasattr(client, "create_market_buy_order"):
                    client.create_market_buy_order(symbol, amount_precise)
                else:
                    client.create_market_order(symbol, "buy", amount_precise)

            self.logger.info(f"Placed {side} rebalance order for {amount_precise} {asset} on {getattr(client, 'id', 'UNKNOWN').upper()}.")
        except Exception as e:
            self.logger.error(f"Failed to place rebalancing order for {asset} on {getattr(client, 'id', 'UNKNOWN')}: {e}", exc_info=True)
            raise
