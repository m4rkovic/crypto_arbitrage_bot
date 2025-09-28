import asyncio
import logging
import sys
import os
from dotenv import load_dotenv
import ccxt.async_support as ccxt

from utils import load_config, ConfigError
from exchange_manager_async import AsyncExchangeManager
from risk_manager import RiskManager
from rebalancer import Rebalancer
from trade_logger import TradeLogger
from async_bot_engine import AsyncArbitrageBot

# --- Basic Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

def inject_api_keys(config: dict) -> dict:
    """
    Loads API keys from the .env file and injects them into the config dictionary.
    """
    load_dotenv()
    logging.info("Loading API keys from .env file...")

    enabled_exchanges_str = os.getenv("ENABLED_EXCHANGES")
    if not enabled_exchanges_str:
        raise ConfigError("CRITICAL ERROR: ENABLED_EXCHANGES not found in .env file.")

    enabled_exchanges = [ex.strip() for ex in enabled_exchanges_str.lower().split(',')]
    
    config['exchanges'] = {}
    for ex_id in enabled_exchanges:
        # Looks for variables like BINANCE_TESTNET_API_KEY
        api_key_var = f"{ex_id.upper()}_TESTNET_API_KEY"
        api_secret_var = f"{ex_id.upper()}_TESTNET_SECRET"
        
        api_key = os.getenv(api_key_var)
        api_secret = os.getenv(api_secret_var)
        
        if not api_key or not api_secret:
            raise ConfigError(f"CRITICAL ERROR: Missing API credentials for exchange '{ex_id}'. "
                              f"Please ensure {api_key_var} and {api_secret_var} are set in your .env file.")
                             
        config["exchanges"][ex_id] = {
            "api_key": api_key,
            "api_secret": api_secret
        }
    
    logging.info(f"Loaded API keys for: {', '.join(enabled_exchanges)}")
    return config

async def main():
    """
    The main entry point for the asynchronous bot.
    Initializes all components and starts the bot.
    """
    exchange_manager = None # Define here to be accessible in finally block
    try:
        # 1. Load configuration and secrets
        config = load_config()
        config = inject_api_keys(config)

        # 2. Initialize components
        exchange_manager = AsyncExchangeManager(config)
        risk_manager = RiskManager(config, exchange_manager)
        rebalancer = Rebalancer(config, exchange_manager)
        trade_logger = TradeLogger()
        
        # 3. Load markets (this is where auth errors are caught)
        await exchange_manager.init_exchanges()

        # 4. If initialization succeeds, create and run the bot
        bot = AsyncArbitrageBot(config, exchange_manager, risk_manager, rebalancer, trade_logger)
        
        bot_task = asyncio.create_task(bot.run())
        await bot_task

    except (ConfigError, ValueError) as e:
        logging.error(f"Configuration Error: {e}")
    except ccxt.AuthenticationError as e:
        # Catch the specific API key error
        logging.error(f"Authentication Failed: {e}. Please check your API keys and permissions.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during startup: {e}", exc_info=True)
    finally:
        # This block will run NO MATTER WHAT, ensuring connections are always closed.
        if exchange_manager:
            logging.info("Closing all exchange connections...")
            await exchange_manager.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutdown signal received (Ctrl+C). Exiting gracefully.")

