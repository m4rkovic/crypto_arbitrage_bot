# main.py

import yaml
import os
import logging.config
from dotenv import load_dotenv
from tkinter import messagebox

from gui_application import App
from utils import ConfigError, ExchangeInitError

def load_and_merge_config() -> (dict, dict):
    """
    Loads the base config from YAML and injects secrets from the .env file.
    """
    with open('config.yaml', 'r') as f:
        full_config = yaml.safe_load(f)

    bot_config = full_config.get('bot_config', {})
    exchanges_config = full_config.get('exchanges_config', {})

    load_dotenv()

    for ex_name in exchanges_config.keys():
        upper_ex_name = ex_name.upper()
        
        # --- THIS IS THE UPDATED LOGIC ---
        # It now checks for both _TESTNET_ and regular names.

        # Try to get the testnet key first, if not found, try the mainnet key name.
        api_key = os.getenv(f"{upper_ex_name}_TESTNET_API_KEY") or os.getenv(f"{upper_ex_name}_API_KEY")
        
        # In your screenshot, the secret key is named _TESTNET_SECRET
        secret_key = os.getenv(f"{upper_ex_name}_TESTNET_SECRET") or os.getenv(f"{upper_ex_name}_SECRET_KEY")
        
        # In your screenshot, the passphrase is named _TESTNET_PASSPHRASE
        password = os.getenv(f"{upper_ex_name}_TESTNET_PASSPHRASE") or os.getenv(f"{upper_ex_name}_PASSWORD")

        if api_key:
            exchanges_config[ex_name]['api_key'] = api_key
        if secret_key:
            exchanges_config[ex_name]['secret_key'] = secret_key
        if password:
            exchanges_config[ex_name]['password'] = password
            
    return bot_config, exchanges_config

def setup_logging(config: dict):
    """Sets up logging based on the provided configuration."""
    logging_config = config.get('logging')
    if logging_config:
        try:
            logging.config.dictConfig(logging_config)
            logging.info("Logging configured successfully.")
        except Exception as e:
            messagebox.showwarning("Logging Error", f"Could not configure logging: {e}")
            logging.basicConfig(level=logging.INFO) # Fallback to basic config
    else:
        logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    try:
        config, exchanges_config = load_and_merge_config()
        setup_logging(config)
        
        app = App(config=config, exchanges_config=exchanges_config)
        app.mainloop()

    except FileNotFoundError:
        messagebox.showerror("Config Error", "config.yaml not found. Please ensure the file exists.")
    except Exception as e:
        messagebox.showerror("Fatal Error", f"An unexpected error occurred: {e}")
        logging.critical(f"A fatal error occurred on startup: {e}", exc_info=True)