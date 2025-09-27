import ccxt
import os
from dotenv import load_dotenv

# Load API keys from .env
load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_TESTNET_SECRET")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")

def test_binance():
    try:
        binance = ccxt.binance({
            "apiKey": BINANCE_API_KEY,
            "secret": BINANCE_API_SECRET,
        })
        binance.set_sandbox_mode(True)  # IMPORTANT for testnet
        balance = binance.fetch_balance()
        print("✅ Binance testnet connection successful")
        print("Balances:", balance['total'])
    except Exception as e:
        print("❌ Binance failed:", str(e))

def test_bybit():
    try:
        bybit = ccxt.bybit({
            "apiKey": BYBIT_API_KEY,
            "secret": BYBIT_API_SECRET,
        })
        bybit.set_sandbox_mode(True)  # Use testnet
        balance = bybit.fetch_balance()
        print("✅ Bybit testnet connection successful")
        print("Balances:", balance['total'])
    except Exception as e:
        print("❌ Bybit failed:", str(e))

if __name__ == "__main__":
    print("🔑 Testing Binance API...")
    test_binance()
    print("\n🔑 Testing Bybit API...")
    test_bybit()
