#Performance_Analyzer.py

import pandas as pd
import numpy as np
import os
from typing import Any, Dict, Optional
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import logging

class PerformanceAnalyzer:
    """
    Analyzes trade data from trades.csv to calculate performance metrics and generate charts.
    """
    TRADE_LOG_FILE = 'trades.csv'

    def __init__(self):
        self.trades_df: Optional[pd.DataFrame] = None
        self.logger = logging.getLogger(__name__)
        # Use a style compatible with our dark theme
        plt.style.use('dark_background')

    def load_data(self) -> bool:
        """
        Loads and preprocesses data from the trades CSV file with enhanced error handling.
        Returns True on success, False on failure.
        """
        try:
            if not os.path.exists(self.TRADE_LOG_FILE):
                self.logger.warning(f"'{self.TRADE_LOG_FILE}' not found. No data to analyze.")
                return False
            
            self.trades_df = pd.read_csv(self.TRADE_LOG_FILE)
            if self.trades_df.empty:
                self.logger.warning("trades.csv is empty. No data to analyze.")
                return False
            
            # --- MERGED: Check for required columns from your new script ---
            required_cols = ['status', 'net_profit_usd', 'timestamp', 'symbol']
            if not all(col in self.trades_df.columns for col in required_cols):
                self.logger.error("trades.csv is missing one or more required columns.")
                return False

            # Convert timestamp to datetime objects for proper plotting and analysis
            self.trades_df['timestamp'] = pd.to_datetime(self.trades_df['timestamp'])
            self.trades_df = self.trades_df.sort_values(by='timestamp')
            return True
        except Exception as e:
            self.logger.error(f"Error loading or processing trade data: {e}", exc_info=True)
            self.trades_df = None
            return False

    def calculate_kpis(self) -> Dict[str, Any]:
        """Calculates a dictionary of Key Performance Indicators (KPIs) with improved structure."""
        if self.trades_df is None or self.trades_df.empty:
            return {}

        all_trades = self.trades_df
        successful_trades = all_trades[all_trades['status'] == 'SUCCESS']
        
        # --- MERGED: More robust handling of cases with no successful trades ---
        if successful_trades.empty:
            return {
                "Total Trades": len(all_trades), "Successful Trades": 0, "Win Rate (%)": "0.00",
                "Net P/L ($)": "$0.00", "Profit Factor": "0.00", "Max Drawdown ($)": "$0.00", "Sharpe Ratio": "0.00"
            }

        total_trades = len(all_trades)
        num_successful = len(successful_trades)
        win_rate = (num_successful / total_trades * 100) if total_trades > 0 else 0
        net_pl = successful_trades['net_profit_usd'].sum()
        
        gross_profit = successful_trades[successful_trades['net_profit_usd'] > 0]['net_profit_usd'].sum()
        gross_loss = abs(successful_trades[successful_trades['net_profit_usd'] < 0]['net_profit_usd'].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        cumulative_pl = successful_trades['net_profit_usd'].cumsum()
        peak = cumulative_pl.cummax()
        drawdown = peak - cumulative_pl
        max_drawdown = drawdown.max()

        daily_returns = successful_trades.set_index('timestamp')['net_profit_usd'].resample('D').sum()
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365) if daily_returns.std() != 0 else 0.0

        return {
            "Total Trades": total_trades,
            "Successful Trades": num_successful,
            "Win Rate (%)": f"{win_rate:.2f}",
            "Net P/L ($)": f"${net_pl:,.2f}",
            "Profit Factor": f"{profit_factor:.2f}" if profit_factor != float('inf') else "inf",
            "Max Drawdown ($)": f"${max_drawdown:,.2f}",
            "Sharpe Ratio": f"{sharpe_ratio:.2f}"
        }

    def _create_figure(self) -> Figure:
        """Helper to create a consistently styled matplotlib Figure for GUI embedding."""
        fig = Figure(figsize=(10, 6), dpi=100, facecolor='#2B2B2B')
        return fig

    def generate_equity_curve(self) -> Figure:
        """Generates a chart showing the cumulative profit over time."""
        fig = self._create_figure()
        ax = fig.add_subplot(111)

        if self.trades_df is not None:
            successful_trades = self.trades_df[self.trades_df['status'] == 'SUCCESS'].copy()
            if not successful_trades.empty:
                successful_trades['cumulative_profit'] = successful_trades['net_profit_usd'].cumsum()
                ax.plot(successful_trades['timestamp'], successful_trades['cumulative_profit'], color='cyan', marker='o', linestyle='-', markersize=4)

        ax.set_title('Portfolio P/L Curve', color='white')
        ax.set_ylabel('Cumulative Profit (USD)', color='white')
        ax.set_xlabel('Timestamp', color='white')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        fig.autofmt_xdate()
        ax.tick_params(colors='white')
        ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='#777777')
        fig.tight_layout()
        return fig

    def generate_profit_by_symbol_chart(self) -> Figure:
        """Generates a bar chart showing net profit for each symbol with conditional coloring."""
        fig = self._create_figure()
        ax = fig.add_subplot(111)

        if self.trades_df is not None:
            successful_trades = self.trades_df[self.trades_df['status'] == 'SUCCESS'].copy()
            if not successful_trades.empty:
                profit_by_symbol = successful_trades.groupby('symbol')['net_profit_usd'].sum().sort_values(ascending=False)
                
                # --- MERGED: Conditional bar coloring from your new script ---
                colors = ['#00BCD4' if x >= 0 else '#E57373' for x in profit_by_symbol.values]
                profit_by_symbol.plot(kind='bar', ax=ax, color=colors)

        ax.set_title('Net Profit by Symbol', color='white')
        ax.set_ylabel('Total Net Profit (USD)', color='white')
        ax.set_xlabel('Symbol', color='white')
        ax.tick_params(axis='x', labelrotation=45, colors='white')
        ax.tick_params(axis='y', colors='white')
        ax.grid(axis='y', linestyle='--', alpha=0.5, color='#777777')
        fig.tight_layout()
        return fig

