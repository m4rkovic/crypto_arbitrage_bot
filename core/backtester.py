# backtester.py

import pandas as pd
from decimal import Decimal, getcontext
import itertools
import logging
import time
import matplotlib.pyplot as plt  # <-- NEW IMPORT
from core.performance_analyzer import PerformanceAnalyzer

# Set precision for decimal calculations
getcontext().prec = 28

# Use the application's logger
logger = logging.getLogger(__name__)

class BacktestPortfolio:
    """Manages the simulated portfolio's state, tracking balances and trades."""
    def __init__(self, initial_capital: dict):
        self.balances = {k: Decimal(str(v)) for k, v in initial_capital.items()}
        self.initial_capital = self.balances.copy()
        self.trades = []
        logger.info(f"Backtest Portfolio Initialized. Balances: {self.balances}")

    def update_balance(self, currency: str, amount: Decimal):
        self.balances[currency] = self.balances.get(currency, Decimal('0')) + amount

    def record_trade(self, trade_details: dict):
        self.trades.append(trade_details)
        base_currency, quote_currency = trade_details['symbol'].split('/')
        self.update_balance(quote_currency, -Decimal(str(trade_details['cost_of_buy'])))
        self.update_balance(base_currency, Decimal(str(trade_details['amount_bought_net'])))
        self.update_balance(base_currency, -Decimal(str(trade_details['amount_sold'])))
        self.update_balance(quote_currency, Decimal(str(trade_details['proceeds_from_sell'])))

class Backtester:
    """The main engine that orchestrates the backtest simulation."""
    def __init__(self, data_path: str, config: dict):
        self.data_path = data_path
        self.config = config
        self.trading_params = config.get('trading_parameters', {})
        self.fee_rate = Decimal(str(self.trading_params.get('fee_percent', 0.1))) / Decimal('100')
        self.data = None
        self.scans = None
        logger.info("Backtester Initialized.")

    def _load_data(self):
        """Loads and prepares historical data from the scans.csv file."""
        logger.info(f"Loading data from {self.data_path}...")
        try:
            cols_to_use = ['timestamp', 'symbol', 'exchange', 'bid', 'ask']
            self.data = pd.read_csv(self.data_path, usecols=cols_to_use)
            self.data.dropna(inplace=True)
            self.data['timestamp'] = pd.to_datetime(self.data['timestamp'], unit='s')
            self.scans = self.data.groupby('timestamp')
            logger.info(f"Data loaded successfully. {len(self.data)} rows, {self.scans.ngroups} unique timestamps.")
        except FileNotFoundError:
            logger.error(f"FATAL: Data file not found at {self.data_path}")
            self.data = pd.DataFrame()
        except ValueError as e:
            logger.error(f"FATAL: Column mismatch in {self.data_path}. Error: {e}")
            self.data = pd.DataFrame()

    def _find_opportunity_in_scan(self, current_scan_df: pd.DataFrame, symbol: str):
        """Processes a single timestamp's data for one symbol to find the best arbitrage opportunity."""
        best_opportunity = None
        exchanges = current_scan_df['exchange'].unique()
        
        for buy_ex, sell_ex in itertools.permutations(exchanges, 2):
            buy_row = current_scan_df[current_scan_df['exchange'] == buy_ex]
            sell_row = current_scan_df[current_scan_df['exchange'] == sell_ex]
            if buy_row.empty or sell_row.empty: continue

            buy_price = Decimal(str(buy_row['ask'].iloc[0]))
            sell_price = Decimal(str(sell_row['bid'].iloc[0]))

            if buy_price > 0 and sell_price > buy_price:
                spread_pct = (sell_price - buy_price) / buy_price
                if spread_pct > (self.fee_rate * 2):
                    opportunity = {
                        'symbol': symbol, 'buy_exchange': buy_ex, 'sell_exchange': sell_ex,
                        'buy_price': buy_price, 'sell_price': sell_price,
                    }
                    if best_opportunity is None or spread_pct > best_opportunity.get('spread_pct', 0):
                        opportunity['spread_pct'] = spread_pct
                        best_opportunity = opportunity
        return best_opportunity

    def _simulate_trade(self, portfolio: BacktestPortfolio, opportunity: dict):
        """Simulates trade execution, calculating costs, fees, and PnL."""
        trade_size_usdt = Decimal(str(self.trading_params.get('trade_size_usdt', 20.0)))
        symbol = opportunity['symbol']
        base, quote = symbol.split('/')

        if portfolio.balances.get(quote, Decimal('0')) < trade_size_usdt:
            return None
        amount_to_buy = trade_size_usdt / opportunity['buy_price']
        if portfolio.balances.get(base, Decimal('0')) < amount_to_buy:
            return None

        amount_bought_net = amount_to_buy * (Decimal('1') - self.fee_rate)
        proceeds_from_sell_gross = amount_to_buy * opportunity['sell_price']
        proceeds_from_sell_net = proceeds_from_sell_gross * (Decimal('1') - self.fee_rate)
        pnl = proceeds_from_sell_net - trade_size_usdt
        
        if pnl > 0:
            return {
                'timestamp': opportunity['timestamp'], 'symbol': symbol,
                'buy_exchange': opportunity['buy_exchange'], 'sell_exchange': opportunity['sell_exchange'],
                'buy_price': opportunity['buy_price'], 'sell_price': opportunity['sell_price'],
                'amount': amount_to_buy, 'net_profit_usd': pnl, 'status': 'SUCCESS',
                # Fields needed for portfolio update
                'cost_of_buy': trade_size_usdt, 'amount_bought_net': amount_bought_net,
                'amount_sold': amount_to_buy, 'proceeds_from_sell': proceeds_from_sell_net
            }
        return None

    def run(self, initial_capital: dict):
        """Runs the entire backtesting simulation."""
        self._load_data()
        if self.data is None or self.data.empty: return

        portfolio = BacktestPortfolio(initial_capital)
        symbols = self.data['symbol'].unique()
        
        logger.info("\n--- Starting Backtest Simulation ---")
        for timestamp, group in self.scans:
            for symbol in symbols:
                symbol_df = group[group['symbol'] == symbol]
                if len(symbol_df) < 2: continue
                
                opportunity = self._find_opportunity_in_scan(symbol_df, symbol)
                if opportunity:
                    opportunity['timestamp'] = timestamp
                    trade_details = self._simulate_trade(portfolio, opportunity)
                    if trade_details:
                        portfolio.record_trade(trade_details)
        
        logger.info("--- Simulation Complete ---\n")
        self.generate_report(portfolio)

    def generate_report(self, portfolio: BacktestPortfolio):
        """Generates a detailed performance report and chart."""
        print("\n--- Backtest Performance Report ---")
        
        total_trades = len(portfolio.trades)
        if total_trades == 0:
            print("No trades were executed during the backtest.")
            return
            
        trades_df = pd.DataFrame(portfolio.trades)
        trades_df['timestamp'] = trades_df['timestamp'].apply(lambda x: int(x.timestamp()))
        
        backtest_results_file = 'backtest_trades.csv'
        trades_df.to_csv(backtest_results_file, index=False)
        logger.info(f"Backtest trade results saved to '{backtest_results_file}'")
        
        analyzer = PerformanceAnalyzer(file_path=backtest_results_file)
        if analyzer.load_data():
            kpis = analyzer.calculate_kpis()
            print("\n## Key Performance Indicators (KPIs) ##")
            for key, value in kpis.items():
                print(f"  {key:<20}: {value}")

            print("\nGenerating equity curve chart...")
            equity_curve_fig = analyzer.generate_equity_curve()
            equity_curve_fig.suptitle('Backtest Equity Curve', fontsize=16)
            
            # --- MODIFIED: Use the blocking plt.show() to keep the window open ---
            plt.show()
        else:
            print("Could not analyze backtest results.")

if __name__ == '__main__':
    import config.logging_config as logging_config
    from core.utils import load_config
    import main

    main.setup_simple_logging()
    config = load_config()
    initial_capital = {
        'USDT': 1000.0, 'BTC': 2.0, 'ETH': 20.0, 'SOL': 100.0,
    }
    backtester = Backtester(data_path='scans.csv', config=config)
    backtester.run(initial_capital=initial_capital)