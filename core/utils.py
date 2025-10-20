# utils.py

import os
import yaml
import ccxt
import logging
from logging import getLogger

# --- Custom Exceptions ---
class ConfigError(Exception):
    """Custom exception for configuration file errors."""
    pass

class ExchangeInitError(Exception):
    """Custom exception for errors during exchange client initialization."""
    pass

# --- Decorator for CCXT Retries ---
def retry_ccxt_call(func):
    """Decorator to retry CCXT API calls with exponential backoff."""
    def wrapper(*args, **kwargs):
        max_retries = 3
        delay = 1
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
                getLogger(__name__).warning(f"CCXT call failed (network issue): {e}. Retrying... ({i+1}/{max_retries})")
                if i == max_retries - 1:
                    getLogger(__name__).error(f"CCXT call failed after {max_retries} retries.")
                    raise
                import time
                time.sleep(delay)
                delay *= 2
            except ccxt.ExchangeError as e:
                getLogger(__name__).error(f"CCXT call failed (non-recoverable): {e}")
                raise
    return wrapper

# --- Configuration Loading ---
def validate_config(config):
    """Validates the structure of the simplified config file."""
    if "trading_parameters" not in config or not isinstance(config["trading_parameters"], dict):
        raise ConfigError("CRITICAL ERROR: Missing or invalid section 'trading_parameters' in config.yaml.")
    
    required_keys = ['symbols_to_scan', 'trade_size_usdt', 'scan_interval_s']
    for key in required_keys:
        if key not in config['trading_parameters']:
            raise ConfigError(f"CRITICAL ERROR: Missing required key '{key}' in 'trading_parameters'.")
            
    return True

def load_config(filepath: str = None):
    if filepath is None:
        base_dir = os.path.dirname(os.path.dirname(__file__))  # project root
        filepath = os.path.join(base_dir, "config", "config.yaml")
    """Loads and validates the configuration file."""
    try:
        with open(filepath, 'r') as f:
            config = yaml.safe_load(f)
        validate_config(config)
        return config
    except FileNotFoundError:
        raise ConfigError(f"CRITICAL ERROR: Configuration file '{filepath}' not found.")
    except yaml.YAMLError as e:
        raise ConfigError(f"CRITICAL ERROR: Could not decode '{filepath}'. YAML error: {e}")