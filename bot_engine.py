# bot_engine.py

import ccxt
import time
import threading
import logging
import itertools
from typing import Any, Dict, List, Optional

from data_models import Opportunity
from exchange_manager import ExchangeManager
from trade_logger import TradeLogger
from trade_executor import TradeExecutor
from risk_manager import RiskManager
from rebalancer import Rebalancer
from utils import retry_ccxt_call

class ArbitrageBot:
    def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any], update_queue: Any):
        self.config = config
        self.update_queue = update_queue
        self.logger = logging.getLogger(__name__)
        self.exchange_manager = ExchangeManager(exchanges_config)
        self.trade_logger = TradeLogger()
        self.trade_executor = TradeExecutor(config, self.exchange_manager, self.trade_logger)
        self.risk_manager = RiskManager(config, self.exchange_manager)
        self.rebalancer = Rebalancer(config, self.exchange_manager)
        self.running = False
        self.state_lock = threading.Lock()
        self.session_id = f"session_{int(time.time())}"
        self.start_time: float = 0.0
        self.last_portfolio_update: float = 0.0
        self.last_activity_time: float = 0.0
        self.trade_count: int = 0
        self.successful_trades: int = 0
        self.failed_trades: int = 0
        self.neutralized_trades: int = 0
        self.critical_failures: int = 0
        self.session_profit: float = 0.0
        self.logger.info(f"New bot instance created with Session ID: {self.session_id}")


    def _get_current_stats(self) -> Dict[str, Any]:
        return {
            'trades': self.trade_count, 'successful': self.successful_trades,
            'failed': self.failed_trades, 'neutralized': self.neutralized_trades,
            'critical': self.critical_failures, 'profit': self.session_profit
        }

    def send_gui_update(self, update_type: str, data: Any):
        self.update_queue.put({"type": update_type, "data": data})

    def _get_taker_fee(self, client: ccxt.Exchange, symbol: str) -> float:
        try:
            market = client.markets.get(symbol, {})
            return market.get('taker', self.config['trading_parameters']['fee_percent'] / 100)
        except (KeyError, AttributeError):
            return self.config['trading_parameters']['fee_percent'] / 100

    def check_for_opportunity(self, prices: Dict, symbol: str, trade_size: float) -> Optional[Opportunity]:
        params = self.config['trading_parameters']
        best_opportunity = None

        for buy_ex, sell_ex in itertools.permutations(self.exchange_manager.get_all_clients().keys(), 2):
            buy_price = prices.get(buy_ex, {}).get('ask')
            sell_price = prices.get(sell_ex, {}).get('bid')
            
            if not all([buy_price, sell_price]): continue

            buy_client = self.exchange_manager.get_client(buy_ex)
            sell_client = self.exchange_manager.get_client(sell_ex)
            if not buy_client or not sell_client: continue

            buy_fee_rate = self._get_taker_fee(buy_client, symbol)
            sell_fee_rate = self._get_taker_fee(sell_client, symbol)
            amount = trade_size / buy_price
            
            cost_of_buy = trade_size
            fee_on_buy = cost_of_buy * buy_fee_rate
            proceeds_from_sell = (amount * sell_price)
            fee_on_sell = proceeds_from_sell * sell_fee_rate
            net_profit = proceeds_from_sell - cost_of_buy - fee_on_buy - fee_on_sell

            if net_profit > params['min_profit_usd']:
                current_opp = Opportunity(symbol, buy_ex, sell_ex, buy_price, sell_price, amount, net_profit)
                if not best_opportunity or net_profit > best_opportunity.net_profit_usd:
                    best_opportunity = current_opp
        return best_opportunity

    def _get_full_portfolio(self, active_symbols: List[str]) -> Dict[str, Any]:
        full_portfolio = {"total_usd_value": 0.0, "assets": {}}
        assets_to_check = set(['USDT'])
        for symbol in active_symbols:
            assets_to_check.add(symbol.split('/')[0])
        for ex_name, client in self.exchange_manager.get_all_clients().items():
            balances = self.exchange_manager.get_balance(client, force_refresh=True)
            if balances:
                for asset in assets_to_check:
                    if asset in balances['total'] and balances['total'][asset] > 0:
                        if asset not in full_portfolio["assets"]:
                            full_portfolio["assets"][asset] = {"balance": 0.0, "value_usd": 0.0}
                        full_portfolio["assets"][asset]["balance"] += balances['total'][asset]
        primary_client = next(iter(self.exchange_manager.get_all_clients().values()), None)
        if not primary_client: return full_portfolio
        for asset, data in full_portfolio["assets"].items():
            if asset == 'USDT':
                data["value_usd"] = data["balance"]
            else:
                try:
                    price = self.exchange_manager.get_market_price(primary_client, f"{asset}/USDT")
                    data["value_usd"] = (data["balance"] * price) if price else 0.0
                except Exception:
                    data["value_usd"] = 0.0
            full_portfolio["total_usd_value"] += data["value_usd"]
        return full_portfolio

    def _take_and_send_initial_portfolio_snapshot(self, active_symbols: List[str]):
        """Takes and sends the initial portfolio snapshot to the GUI."""
        self.logger.info("Taking initial portfolio snapshot for performance analysis...")
        initial_portfolio = self._get_full_portfolio(active_symbols)
        self.send_gui_update('initial_portfolio', initial_portfolio)
        self.last_portfolio_update = time.time()
        return initial_portfolio

    def _update_and_send_portfolio_state(self, active_symbols: List[str]) -> Dict[str, Any]:
        """Gets portfolio, sends GUI updates, and returns data for rebalancer."""
        current_portfolio = self._get_full_portfolio(active_symbols)
        balances_only = {}
        all_assets = set(current_portfolio.get("assets", {}).keys())
        for ex_name, client in self.exchange_manager.get_all_clients().items():
            balance_data = self.exchange_manager.get_balance(client, force_refresh=False)
            if balance_data:
                balances_only[ex_name] = {k: v for k, v in balance_data.get('total', {}).items() if v > 0 and k in all_assets}
        
        if balances_only:
            payload = {"portfolio": current_portfolio, "balances": balances_only}
            self.send_gui_update('portfolio_update', payload)

        self.last_portfolio_update = time.time()
        return current_portfolio

    def run(self, symbols_to_scan: Optional[List[str]] = None):
        self.running = True
        self.start_time = time.time()
        self.last_activity_time = self.start_time
        self.logger.info("Bot started. Scanning for opportunities...")
        symbols = symbols_to_scan if symbols_to_scan is not None else self.config['trading_parameters']['symbols_to_scan']
        
        self._take_and_send_initial_portfolio_snapshot(symbols)
        current_portfolio = self._update_and_send_portfolio_state(symbols)
        
        try:
            while self.running:
                now = time.time()
                rebalance_interval = self.config.get('rebalancing', {}).get('rebalance_interval_s', 3600)
                if now - self.last_portfolio_update > rebalance_interval:
                    current_portfolio = self._update_and_send_portfolio_state(symbols)
                    if self.config.get('rebalancing', {}).get('enabled', False):
                        self.logger.info("Running periodic rebalancing check...")
                        self.rebalancer.run_rebalancing_check(current_portfolio)

                trade_size_usdt = self.config['trading_parameters']['trade_size_usdt']
                
                for symbol in symbols:
                    if not self.running: break
                    try:
                        prices = self.exchange_manager.get_market_data(symbol, trade_size_usdt)
                        self.trade_logger.log_scan_data(symbol, prices)
                        opportunity = self.check_for_opportunity(prices, symbol, trade_size_usdt)

                        market_data_payload = {'symbol': symbol, 'is_profitable': opportunity is not None}
                        all_bids = [p['bid'] for p in prices.values() if p.get('bid')]
                        all_asks = [p['ask'] for p in prices.values() if p.get('ask')]
                        best_bid = max(all_bids) if all_bids else 0
                        best_ask = min(all_asks) if all_asks else 0
                        spread_pct = ((best_bid - best_ask) / best_ask) * 100 if best_ask > 0 else 0
                        market_data_payload['spread_pct'] = spread_pct
                        for ex_name, price_data in prices.items():
                            market_data_payload[f'{ex_name}_bid'] = price_data['bid']
                            market_data_payload[f'{ex_name}_ask'] = price_data['ask']
                        self.send_gui_update('market_data', market_data_payload)
                        
                        if opportunity:
                            self.logger.info(f"Opportunity found for {symbol}! Est Profit: ${opportunity.net_profit_usd:.4f}")
                            self.send_gui_update('opportunity_found', {'symbol': symbol, 'spread_pct': (opportunity.net_profit_usd / trade_size_usdt) * 100})
                            
                            if self.risk_manager.check_balances(opportunity, trade_size_usdt):
                                with self.state_lock: self.trade_count += 1
                                result = self.trade_executor.execute_and_monitor(opportunity, self.session_id)
                                with self.state_lock:
                                    if result.get('status') == 'SUCCESS':
                                        self.successful_trades += 1
                                        self.session_profit += result.get('profit', 0.0)
                                        self.last_activity_time = time.time()
                                    else:
                                        self.failed_trades += 1
                                        if result.get('status') == 'CRITICAL_STUCK_ORDER':
                                            self.critical_failures += 1
                                self.send_gui_update('stats', self._get_current_stats())
                                current_portfolio = self._update_and_send_portfolio_state(symbols)
                                time.sleep(self.config['trading_parameters'].get('post_trade_delay_s', 5))
                    except Exception as e:
                        self.logger.error(f"CRITICAL UNHANDLED ERROR in symbol loop for {symbol}: {e}", exc_info_True)
                        self.send_gui_update('critical_error', f"A critical error occurred: {e}")
                        time.sleep(10)
                
                now = time.time()
                if now - self.last_activity_time > 15:
                    self.logger.info("Status: No profitable trades found recently. Still scanning markets...")
                    self.last_activity_time = now
                
                time.sleep(self.config['trading_parameters']['scan_interval_s'])
        finally:
            self.logger.info("Bot run loop finished. Cleaning up resources.")
            self.exchange_manager.close_all_clients()
            self.send_gui_update('stopped', {})

    def stop(self):
        self.logger.info("Stop command received. Shutting down...")
        self.running = False
        
# # bot_engine.py

# import ccxt
# import time
# import threading
# import logging
# import itertools
# from typing import Any, Dict, List, Optional

# from data_models import Opportunity
# from exchange_manager import ExchangeManager
# from trade_logger import TradeLogger
# from trade_executor import TradeExecutor
# from risk_manager import RiskManager
# from rebalancer import Rebalancer
# from utils import retry_ccxt_call

# class ArbitrageBot:
#     def __init__(self, config: Dict[str, Any], exchanges_config: Dict[str, Any], update_queue: Any):
#         self.config = config
#         self.update_queue = update_queue
#         self.logger = logging.getLogger(__name__)
#         self.exchange_manager = ExchangeManager(exchanges_config)
#         self.trade_logger = TradeLogger()
#         self.trade_executor = TradeExecutor(config, self.exchange_manager, self.trade_logger)
#         self.risk_manager = RiskManager(config, self.exchange_manager)
#         self.rebalancer = Rebalancer(config, self.exchange_manager)
#         self.running = False
#         self.state_lock = threading.Lock()
#         self.session_id = f"session_{int(time.time())}"
#         self.start_time: float = 0.0
#         self.last_portfolio_update: float = 0.0
#         self.last_activity_time: float = 0.0
#         self.trade_count: int = 0
#         self.successful_trades: int = 0
#         self.failed_trades: int = 0
#         self.neutralized_trades: int = 0
#         self.critical_failures: int = 0
#         self.session_profit: float = 0.0
#         self.logger.info(f"New bot instance created with Session ID: {self.session_id}")


#     def _get_current_stats(self) -> Dict[str, Any]:
#         return {
#             'trades': self.trade_count, 'successful': self.successful_trades,
#             'failed': self.failed_trades, 'neutralized': self.neutralized_trades,
#             'critical': self.critical_failures, 'profit': self.session_profit
#         }

#     def send_gui_update(self, update_type: str, data: Any):
#         self.update_queue.put({"type": update_type, "data": data})

#     def _get_taker_fee(self, client: ccxt.Exchange, symbol: str) -> float:
#         try:
#             market = client.markets.get(symbol, {})
#             return market.get('taker', self.config['trading_parameters']['fee_percent'] / 100)
#         except (KeyError, AttributeError):
#             return self.config['trading_parameters']['fee_percent'] / 100

#     def check_for_opportunity(self, prices: Dict, symbol: str, trade_size: float) -> Optional[Opportunity]:
#         params = self.config['trading_parameters']
#         best_opportunity = None

#         for buy_ex, sell_ex in itertools.permutations(self.exchange_manager.get_all_clients().keys(), 2):
#             buy_price = prices.get(buy_ex, {}).get('ask')
#             sell_price = prices.get(sell_ex, {}).get('bid')
            
#             if not all([buy_price, sell_price]): continue

#             buy_client = self.exchange_manager.get_client(buy_ex)
#             sell_client = self.exchange_manager.get_client(sell_ex)
#             if not buy_client or not sell_client: continue

#             buy_fee_rate = self._get_taker_fee(buy_client, symbol)
#             sell_fee_rate = self._get_taker_fee(sell_client, symbol)
#             amount = trade_size / buy_price
            
#             cost_of_buy = trade_size
#             fee_on_buy = cost_of_buy * buy_fee_rate
#             proceeds_from_sell = (amount * sell_price)
#             fee_on_sell = proceeds_from_sell * sell_fee_rate
#             net_profit = proceeds_from_sell - cost_of_buy - fee_on_buy - fee_on_sell

#             if net_profit > params['min_profit_usd']:
#                 current_opp = Opportunity(symbol, buy_ex, sell_ex, buy_price, sell_price, amount, net_profit)
#                 if not best_opportunity or net_profit > best_opportunity.net_profit_usd:
#                     best_opportunity = current_opp
#         return best_opportunity

#     def _get_full_portfolio(self, active_symbols: List[str]) -> Dict[str, Any]:
#         full_portfolio = {"total_usd_value": 0.0, "assets": {}}
#         assets_to_check = set(['USDT'])
#         for symbol in active_symbols:
#             assets_to_check.add(symbol.split('/')[0])
#         for ex_name, client in self.exchange_manager.get_all_clients().items():
#             balances = self.exchange_manager.get_balance(client, force_refresh=True)
#             if balances:
#                 for asset in assets_to_check:
#                     if asset in balances['total'] and balances['total'][asset] > 0:
#                         if asset not in full_portfolio["assets"]:
#                             full_portfolio["assets"][asset] = {"balance": 0.0, "value_usd": 0.0}
#                         full_portfolio["assets"][asset]["balance"] += balances['total'][asset]
#         primary_client = next(iter(self.exchange_manager.get_all_clients().values()), None)
#         if not primary_client: return full_portfolio
#         for asset, data in full_portfolio["assets"].items():
#             if asset == 'USDT':
#                 data["value_usd"] = data["balance"]
#             else:
#                 try:
#                     price = self.exchange_manager.get_market_price(primary_client, f"{asset}/USDT")
#                     data["value_usd"] = (data["balance"] * price) if price else 0.0
#                 except Exception:
#                     data["value_usd"] = 0.0
#             full_portfolio["total_usd_value"] += data["value_usd"]
#         return full_portfolio

#     def _take_and_send_initial_portfolio_snapshot(self, active_symbols: List[str]):
#         """Takes and sends the initial portfolio snapshot to the GUI."""
#         self.logger.info("Taking initial portfolio snapshot for performance analysis...")
#         initial_portfolio = self._get_full_portfolio(active_symbols)
#         self.send_gui_update('initial_portfolio', initial_portfolio)
#         self.last_portfolio_update = time.time()
#         return initial_portfolio

#     def _update_and_send_portfolio_state(self, active_symbols: List[str]) -> Dict[str, Any]:
#         """Gets portfolio, sends GUI updates, and returns data for rebalancer."""
#         current_portfolio = self._get_full_portfolio(active_symbols)
#         balances_only = {}
#         all_assets = set(current_portfolio.get("assets", {}).keys())
#         for ex_name, client in self.exchange_manager.get_all_clients().items():
#             balance_data = self.exchange_manager.get_balance(client, force_refresh=False)
#             if balance_data:
#                 balances_only[ex_name] = {k: v for k, v in balance_data.get('total', {}).items() if v > 0 and k in all_assets}
        
#         # Send a more complete update that the GUI expects
#         if balances_only:
#             payload = {"portfolio": current_portfolio, "balances": balances_only}
#             self.send_gui_update('portfolio_update', payload)

#         self.last_portfolio_update = time.time()
#         return current_portfolio

#     def run(self, symbols_to_scan: Optional[List[str]] = None):
#             self.running = True
#             self.start_time = time.time()
#             self.last_activity_time = self.start_time
#             self.logger.info("Bot started. Scanning for opportunities...")
#             symbols = symbols_to_scan if symbols_to_scan is not None else self.config['trading_parameters']['symbols_to_scan']
            
#             # --- THIS IS THE FIX ---
#             # We now take the initial snapshot AND perform the initial state/balance update right at the start.
#             self._take_and_send_initial_portfolio_snapshot(symbols)
#             current_portfolio = self._update_and_send_portfolio_state(symbols)
            
#             try:
#                 while self.running:
#                     now = time.time()
#                     rebalance_interval = self.config.get('rebalancing', {}).get('rebalance_interval_s', 3600)
#                     if now - self.last_portfolio_update > rebalance_interval:
#                         current_portfolio = self._update_and_send_portfolio_state(symbols)
#                         if self.config.get('rebalancing', {}).get('enabled', False):
#                             self.logger.info("Running periodic rebalancing check...")
#                             self.rebalancer.run_rebalancing_check(current_portfolio)

#                     trade_size_usdt = self.config['trading_parameters']['trade_size_usdt']
                    
#                     for symbol in symbols:
#                         if not self.running: break
#                         try:
#                             prices = self.exchange_manager.get_market_data(symbol, trade_size_usdt)
#                             self.trade_logger.log_scan_data(symbol, prices)
#                             opportunity = self.check_for_opportunity(prices, symbol, trade_size_usdt)

#                             market_data_payload = {'symbol': symbol, 'is_profitable': opportunity is not None}
#                             all_bids = [p['bid'] for p in prices.values() if p.get('bid')]
#                             all_asks = [p['ask'] for p in prices.values() if p.get('ask')]
#                             best_bid = max(all_bids) if all_bids else 0
#                             best_ask = min(all_asks) if all_asks else 0
#                             spread_pct = ((best_bid - best_ask) / best_ask) * 100 if best_ask > 0 else 0
#                             market_data_payload['spread_pct'] = spread_pct
#                             for ex_name, price_data in prices.items():
#                                 market_data_payload[f'{ex_name}_bid'] = price_data['bid']
#                                 market_data_payload[f'{ex_name}_ask'] = price_data['ask']
#                             self.send_gui_update('market_data', market_data_payload)
                            
#                             if opportunity:
#                                 self.logger.info(f"Opportunity found for {symbol}! Est Profit: ${opportunity.net_profit_usd:.4f}")
#                                 self.send_gui_update('opportunity_found', {'symbol': symbol, 'spread_pct': (opportunity.net_profit_usd / trade_size_usdt) * 100})
                                
#                                 if self.risk_manager.check_balances(opportunity, trade_size_usdt):
#                                     with self.state_lock: self.trade_count += 1
#                                     result = self.trade_executor.execute_and_monitor(opportunity, self.session_id)
#                                     with self.state_lock:
#                                         if result.get('status') == 'SUCCESS':
#                                             self.successful_trades += 1
#                                             self.session_profit += result.get('profit', 0.0)
#                                             self.last_activity_time = time.time()
#                                         else:
#                                             self.failed_trades += 1
#                                             if result.get('status') == 'CRITICAL_STUCK_ORDER':
#                                                 self.critical_failures += 1
#                                     self.send_gui_update('stats', self._get_current_stats())
#                                     current_portfolio = self._update_and_send_portfolio_state(symbols)
#                                     time.sleep(self.config['trading_parameters'].get('post_trade_delay_s', 5))
#                         except Exception as e:
#                             self.logger.error(f"CRITICAL UNHANDLED ERROR in symbol loop for {symbol}: {e}", exc_info_True)
#                             self.send_gui_update('critical_error', f"A critical error occurred: {e}")
#                             time.sleep(10)
                    
#                     now = time.time()
#                     if now - self.last_activity_time > 15:
#                         self.logger.info("Status: No profitable trades found recently. Still scanning markets...")
#                         self.last_activity_time = now
                    
#                     time.sleep(self.config['trading_parameters']['scan_interval_s'])
#             finally:
#                 self.logger.info("Bot run loop finished. Cleaning up resources.")
#                 self.exchange_manager.close_all_clients()
#                 self.send_gui_update('stopped', {})

#     def stop(self):
#             self.logger.info("Stop command received. Shutting down...")
#             self.running = False 
                
#     # def run(self, symbols_to_scan: Optional[List[str]] = None):
#     #     self.running = True
#     #     self.start_time = time.time()
#     #     self.last_activity_time = self.start_time
#     #     self.logger.info("Bot started. Scanning for opportunities...")
#     #     symbols = symbols_to_scan if symbols_to_scan is not None else self.config['trading_parameters']['symbols_to_scan']
        
#     #     # --- THIS IS THE FIX ---
#     #     # Take the initial snapshot for the Analysis tab before the main loop starts
#     #     current_portfolio = self._take_and_send_initial_portfolio_snapshot(symbols)
        
#     #     try:
#     #         while self.running:
#     #             now = time.time()
#     #             rebalance_interval = self.config.get('rebalancing', {}).get('rebalance_interval_s', 3600)
#     #             if now - self.last_portfolio_update > rebalance_interval:
#     #                 current_portfolio = self._update_and_send_portfolio_state(symbols)
#     #                 if self.config.get('rebalancing', {}).get('enabled', False):
#     #                     self.logger.info("Running periodic rebalancing check...")
#     #                     self.rebalancer.run_rebalancing_check(current_portfolio)

#     #             trade_size_usdt = self.config['trading_parameters']['trade_size_usdt']
                
#     #             for symbol in symbols:
#     #                 if not self.running: break
#     #                 try:
#     #                     prices = self.exchange_manager.get_market_data(symbol, trade_size_usdt)
#     #                     self.trade_logger.log_scan_data(symbol, prices)
#     #                     opportunity = self.check_for_opportunity(prices, symbol, trade_size_usdt)

#     #                     market_data_payload = {'symbol': symbol, 'is_profitable': opportunity is not None}
#     #                     all_bids = [p['bid'] for p in prices.values() if p.get('bid')]
#     #                     all_asks = [p['ask'] for p in prices.values() if p.get('ask')]
#     #                     best_bid = max(all_bids) if all_bids else 0
#     #                     best_ask = min(all_asks) if all_asks else 0
#     #                     spread_pct = ((best_bid - best_ask) / best_ask) * 100 if best_ask > 0 else 0
#     #                     market_data_payload['spread_pct'] = spread_pct
#     #                     for ex_name, price_data in prices.items():
#     #                         market_data_payload[f'{ex_name}_bid'] = price_data['bid']
#     #                         market_data_payload[f'{ex_name}_ask'] = price_data['ask']
#     #                     self.send_gui_update('market_data', market_data_payload)
                        
#     #                     if opportunity:
#     #                         self.logger.info(f"Opportunity found for {symbol}! Est Profit: ${opportunity.net_profit_usd:.4f}")
#     #                         self.send_gui_update('opportunity_found', {'symbol': symbol, 'spread_pct': (opportunity.net_profit_usd / trade_size_usdt) * 100})
                            
#     #                         if self.risk_manager.check_balances(opportunity, trade_size_usdt):
#     #                             with self.state_lock: self.trade_count += 1
#     #                             result = self.trade_executor.execute_and_monitor(opportunity, self.session_id)
#     #                             with self.state_lock:
#     #                                 if result.get('status') == 'SUCCESS':
#     #                                     self.successful_trades += 1
#     #                                     self.session_profit += result.get('profit', 0.0)
#     #                                     self.last_activity_time = time.time()
#     #                                 else:
#     #                                     self.failed_trades += 1
#     #                                     if result.get('status') == 'CRITICAL_STUCK_ORDER':
#     #                                         self.critical_failures += 1
#     #                             self.send_gui_update('stats', self._get_current_stats())
#     #                             current_portfolio = self._update_and_send_portfolio_state(symbols)
#     #                             time.sleep(self.config['trading_parameters'].get('post_trade_delay_s', 5))
#     #                 except Exception as e:
#     #                     self.logger.error(f"CRITICAL UNHANDLED ERROR in symbol loop for {symbol}: {e}", exc_info_True)
#     #                     self.send_gui_update('critical_error', f"A critical error occurred: {e}")
#     #                     time.sleep(10)
                
#     #             now = time.time()
#     #             if now - self.last_activity_time > 15:
#     #                 self.logger.info("Status: No profitable trades found recently. Still scanning markets...")
#     #                 self.last_activity_time = now
                
#     #             time.sleep(self.config['trading_parameters']['scan_interval_s'])
#     #     finally:
#     #         self.logger.info("Bot run loop finished. Cleaning up resources.")
#     #         self.exchange_manager.close_all_clients()
#     #         self.send_gui_update('stopped', {})

#     # def stop(self):
#     #     self.logger.info("Stop command received. Shutting down...")
#     #     self.running = False