# import pandas as pd
# import matplotlib.pyplot as plt
# import sys
# import os

# def analyze_trades(file_path='trades.csv'):
#     """
#     Loads trade data from a CSV file, calculates performance metrics,
#     and generates an equity curve chart.
#     """
#     print("--- 📈 Arbitrage Bot Performance Analysis ---")

#     # 1. Load the data using Pandas
#     try:
#         if not os.path.exists(file_path):
#             raise FileNotFoundError
#         trades_df = pd.read_csv(file_path)
#         if trades_df.empty:
#             print("\n⚠️ The trades.csv file is empty. No data to analyze.")
#             sys.exit()
#     except FileNotFoundError:
#         print(f"\n❌ ERROR: The file '{file_path}' was not found.")
#         print("Please ensure the bot has run and generated some trade data.")
#         sys.exit()
#     except Exception as e:
#         print(f"\n❌ An unexpected error occurred while reading the CSV file: {e}")
#         sys.exit()
        
#     successful_trades_df = trades_df[trades_df['status'] == 'SUCCESS'].copy()
#     if successful_trades_df.empty:
#         print("\n⚠️ No successful trades found in the log. Cannot generate performance report.")
#         sys.exit()

#     # 2. Calculate Key Performance Indicators (KPIs)
#     total_net_profit = successful_trades_df['net_profit_usd'].sum()

#     total_trades = len(trades_df)
#     successful_trades = len(successful_trades_df)
#     win_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0

#     gross_profit = successful_trades_df[successful_trades_df['net_profit_usd'] > 0]['net_profit_usd'].sum()
#     gross_loss = abs(successful_trades_df[successful_trades_df['net_profit_usd'] < 0]['net_profit_usd'].sum())
#     profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

#     # 3. Print the stats to the console
#     print("\n--- Overall Performance ---")
#     print(f"Total Trades Attempted: {total_trades}")
#     print(f"Successful Trades:      {successful_trades}")
#     print(f"Total Net Profit:       ${total_net_profit:,.4f}")
#     print(f"Win Rate:               {win_rate:.2f}%")
#     print(f"Profit Factor:          {profit_factor:.2f}")
#     print("---------------------------\n")

#     # 4. Generate and save the equity curve chart
#     successful_trades_df['timestamp'] = pd.to_datetime(successful_trades_df['timestamp'], unit='s')
    
#     plt.style.use('dark_background')
#     fig, ax = plt.subplots(figsize=(14, 7))

#     ax.plot(successful_trades_df['timestamp'], successful_trades_df['running_profit_usd'], color='cyan', marker='o', linestyle='-', markersize=4, label='Equity Curve')
    
#     ax.set_title('Bot Performance: Equity Curve', fontsize=16)
#     ax.set_xlabel('Date and Time', fontsize=12)
#     ax.set_ylabel('Cumulative Profit (USD)', fontsize=12)
#     ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='#444444')
#     ax.legend()
#     fig.autofmt_xdate()
#     plt.tight_layout()

#     output_filename = 'equity_curve.png'
#     try:
#         plt.savefig(output_filename)
#         print(f"✅ Equity curve chart saved successfully as '{output_filename}'")
#     except Exception as e:
#         print(f"❌ Could not save the chart. Error: {e}")

# if __name__ == "__main__":
#     analyze_trades()