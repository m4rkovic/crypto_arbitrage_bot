import ccxt
import os
from dotenv import load_dotenv

def buy_shib_on_okx_testnet():
    """
    Connects to the OKX Demo (Testnet) and places a market buy order
    for exactly 100,000 SHIB tokens.
    """
    # --- 1. Load API Keys ---
    # Make sure you have a .env file with your OKX testnet keys.
    load_dotenv()
    api_key = os.getenv('OKX_TESTNET_API_KEY')
    api_secret = os.getenv('OKX_TESTNET_SECRET')
    passphrase = os.getenv('OKX_TESTNET_PASSPHRASE')

    if not all([api_key, api_secret, passphrase]):
        print("❌ Error: Please set OKX_TESTNET_API_KEY, OKX_TESTNET_SECRET, and OKX_TESTNET_PASSPHRASE in a .env file.")
        return

    # --- 2. Initialize Exchange Client ---
    try:
        exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
        })

        # ⚠️ CRITICAL: Set the exchange to use the Testnet sandbox (demo trading)
        exchange.set_sandbox_mode(True)
        print("✅ Successfully connected to OKX Testnet (Demo Trading).")

    except Exception as e:
        print(f"❌ Failed to initialize OKX exchange: {e}")
        return

    # --- 3. Define Trade Parameters ---
    symbol = 'SHIB/USDT'
    # This is the amount of the BASE currency (SHIB) to buy.
    amount_of_shib_to_buy = 100000  

    # --- 4. Execute Trade ---
    try:
        print(f"\nAttempting to buy {amount_of_shib_to_buy:,} {symbol.split('/')[0]}...")
        
        # For a market buy, the 'amount' parameter is the quantity of the base currency (SHIB).
        order = exchange.create_market_buy_order(symbol, amount_of_shib_to_buy)
        
        print("\n✅ Successfully placed market buy order!")
        print("------------------------------------------")
        print(f"  Order ID:    {order.get('id')}")
        print(f"  Timestamp:   {order.get('datetime')}")
        print(f"  Symbol:      {order.get('symbol')}")
        print(f"  Amount (SHIB): {order.get('filled')}")
        print(f"  Cost (USDT):   {order.get('cost')}")
        print(f"  Status:      {order.get('status')}")
        print("------------------------------------------")

    except ccxt.InsufficientFunds as e:
        print(f"\n❌ Error: Insufficient USDT funds on your OKX Testnet account.")
        print("   You may need to use the OKX demo faucet to add more funds.")
        print(f"   Full error: {e}")
    except ccxt.NetworkError as e:
        print(f"\n❌ Error: Network issue. Could not connect to OKX.")
        print(f"   Full error: {e}")
    except ccxt.ExchangeError as e:
        print(f"\n❌ Error: The exchange returned an error.")
        print(f"   It's possible SHIB/USDT is not available on the OKX demo platform.")
        print(f"   Full error: {e}")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    buy_shib_on_okx_testnet()


# import ccxt
# import os
# import time
# from dotenv import load_dotenv

# # --- Configuration ---
# # DO NOT MODIFY THIS LIST. It contains the coins you requested.
# COINS_TO_BUY = [
#     'SOL/USDT',   # Solana: A high-speed competitor to Ethereum.
#     'XRP/USDT',   # XRP: Known for its focus on cross-border payments.
#     'ADA/USDT',   # Cardano: A smart contract platform with a large community.
#     'AVAX/USDT',  # Avalanche: A fast L1 popular for DeFi and gaming.
#     'BNB/USDT',   # Binance Coin: The native token of the Binance ecosystem.
#     'LINK/USDT',  # Chainlink: The leading oracle network for DeFi.
#     'DOGE/USDT',  # Dogecoin: The original high-volume meme coin.
#     'SHIB/USDT',  # Shiba Inu: Another major meme coin with high volatility.
# ]
# # Amount of USDT to spend on each coin.
# AMOUNT_PER_COIN_USDT = 500.0

# def initialize_exchange(exchange_name: str):
#     """
#     Loads API keys from .env and initializes the specified CCXT exchange client
#     in TESTNET/SANDBOX mode.

#     Args:
#         exchange_name: The name of the exchange ('binance' or 'okx').

#     Returns:
#         An initialized ccxt exchange object or None if initialization fails.
#     """
#     print(f"--- Initializing {exchange_name.upper()} Testnet ---")
#     load_dotenv()

#     config = {
#         'binance': {
#             'apiKey': os.getenv('BINANCE_TESTNET_API_KEY'),
#             'secret': os.getenv('BINANCE_TESTNET_SECRET'),
#         },
#         'okx': {
#             'apiKey': os.getenv('OKX_TESTNET_API_KEY'),
#             'secret': os.getenv('OKX_TESTNET_SECRET'),
#             'password': os.getenv('OKX_TESTNET_PASSPHRASE'),
#         }
#     }

#     params = config.get(exchange_name)
#     if not all(params.values()):
#         print(f"❌ Error: Please set the required {exchange_name.upper()} testnet keys in your .env file.")
#         return None

#     try:
#         exchange_class = getattr(ccxt, exchange_name)
#         exchange = exchange_class(params)
        
#         # ⚠️ CRITICAL: Set the exchange to use the Testnet sandbox
#         exchange.set_sandbox_mode(True)
        
#         print(f"✅ Successfully connected to {exchange_name.upper()} Testnet.")
#         return exchange
#     except Exception as e:
#         print(f"❌ Failed to initialize {exchange_name.upper()}: {e}")
#         return None

# def execute_market_buy(exchange, symbol, amount_usdt):
#     """
#     Places a market buy order on the given exchange for a specified USDT amount.

#     Args:
#         exchange: The initialized ccxt exchange object.
#         symbol: The trading symbol (e.g., 'SOL/USDT').
#         amount_usdt: The amount in USDT to spend.
#     """
#     try:
#         print(f"\nAttempting to buy {amount_usdt} USDT worth of {symbol} on {exchange.id}...")
        
#         # CCXT's create_market_buy_order_with_cost uses the 'cost' (USDT) to determine the buy amount.
#         # This is the preferred method for spending a specific quote currency amount.
#         order = exchange.create_market_buy_order_with_cost(symbol, amount_usdt)
        
#         print("\n✅ Successfully placed market buy order!")
#         print("------------------------------------------")
#         print(f"  Order ID:   {order.get('id')}")
#         print(f"  Timestamp:  {order.get('datetime')}")
#         print(f"  Symbol:     {order.get('symbol')}")
#         print(f"  Amount Coin:{order.get('filled')}")
#         print(f"  Cost (USDT):{order.get('cost')}")
#         print(f"  Status:     {order.get('status')}")
#         print("------------------------------------------")
#         return True

#     except ccxt.InsufficientFunds as e:
#         print(f"❌ Error: Insufficient USDT funds on your {exchange.id} Testnet account.")
#         print("   You may need to use the exchange's Testnet faucet to get more funds.")
#     except ccxt.NetworkError as e:
#         print(f"❌ Error: Network issue. Could not connect to {exchange.id}.")
#     except ccxt.ExchangeError as e:
#         print(f"❌ Error: {exchange.id} returned an error. They may not support this pair on testnet.")
#         print(f"   Full error: {e}")
#     except Exception as e:
#         print(f"❌ An unexpected error occurred on {exchange.id}: {e}")
    
#     return False

# def main():
#     """
#     Main function to run the buying script.
#     """
#     exchanges_to_run = {
#         'binance': initialize_exchange('binance'),
#         'okx': initialize_exchange('okx')
#     }

#     for name, exchange in exchanges_to_run.items():
#         if not exchange:
#             print(f"\nSkipping {name.upper()} due to initialization failure.")
#             continue
        
#         print(f"\n--- Starting Buys on {name.upper()} ---")
#         successful_buys = 0
#         for coin in COINS_TO_BUY:
#             if execute_market_buy(exchange, coin, AMOUNT_PER_COIN_USDT):
#                 successful_buys += 1
#             # A small delay to respect exchange rate limits
#             time.sleep(1) 
            
#         print(f"\n--- {name.upper()} Summary ---")
#         print(f"Executed {successful_buys} / {len(COINS_TO_BUY)} successful buy orders.")

# if __name__ == "__main__":
#     main()


# # # buy_sol.py

# # import ccxt
# # import os
# # from dotenv import load_dotenv

# # def buy_sol_on_binance_testnet():
# #     """
# #     Connects to the Binance Testnet and places a market buy order
# #     for 1000 USDT worth of SOL.
# #     """
# #     # --- 1. Load API Keys ---
# #     # Make sure you have a .env file with your keys
# #     load_dotenv()
# #     api_key = os.getenv('BINANCE_TESTNET_API_KEY')
# #     api_secret = os.getenv('BINANCE_TESTNET_SECRET')

# #     if not api_key or not api_secret:
# #         print("Error: Please set BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_SECRET in a .env file.")
# #         return

# #     # --- 2. Initialize Exchange Client ---
# #     exchange = ccxt.binance({
# #         'apiKey': api_key,
# #         'secret': api_secret,
# #     })

# #     # ⚠️ CRITICAL: Set the exchange to use the Testnet sandbox
# #     exchange.set_sandbox_mode(True)
# #     print("Successfully connected to Binance Testnet.")

# #     # --- 3. Define Trade Parameters ---
# #     symbol = 'SOL/USDT'
# #     amount_to_spend_usdt = 1000
    
# #     # --- 4. Execute Trade ---
# #     try:
# #         print(f"\nAttempting to buy {amount_to_spend_usdt} USDT worth of {symbol}...")
        
# #         # For a market buy, the 'amount' parameter is the quantity of the quote currency (USDT) to spend.
# #         # CCXT handles the calculation of how much SOL you will receive.
# #         order = exchange.create_market_buy_order(symbol, amount_to_spend_usdt)
        
# #         print("\n✅ Successfully placed market buy order!")
# #         print("------------------------------------------")
# #         print(f"  Order ID:    {order.get('id')}")
# #         print(f"  Timestamp:   {order.get('datetime')}")
# #         print(f"  Symbol:      {order.get('symbol')}")
# #         print(f"  Amount (SOL):  {order.get('filled')}")
# #         print(f"  Cost (USDT):   {order.get('cost')}")
# #         print(f"  Status:      {order.get('status')}")
# #         print("------------------------------------------")

# #     except ccxt.InsufficientFunds as e:
# #         print(f"\n❌ Error: Insufficient USDT funds on your Testnet account.")
# #         print("You may need to use the Binance Testnet faucet to get more funds.")
# #         print(f"Full error: {e}")
# #     except ccxt.NetworkError as e:
# #         print(f"\n❌ Error: Network issue. Could not connect to Binance.")
# #         print(f"Full error: {e}")
# #     except ccxt.ExchangeError as e:
# #         print(f"\n❌ Error: The exchange returned an error.")
# #         print(f"Full error: {e}")
# #     except Exception as e:
# #         print(f"\n❌ An unexpected error occurred: {e}")


# # if __name__ == "__main__":
# #     buy_sol_on_binance_testnet()