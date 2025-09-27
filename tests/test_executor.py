# tests/test_executor.py

import pytest
from unittest.mock import MagicMock
import logging_config
logging_config.setup_custom_log_levels() # <-- This only sets up the custom levels for the test

from data_models import Opportunity
# --- THIS IS THE FIX ---
# Import and run the setup function BEFORE any other imports from our app
import logging_config
logging_config.setup_custom_log_levels()
# ----------------------

from data_models import Opportunity
from exchange_manager import ExchangeManager
from trade_executor import TradeExecutor
from trade_logger import TradeLogger

@pytest.fixture
def mock_config():
    """Creates a mock configuration dictionary for tests."""
    return {
        'trading_parameters': {
            'dry_run': True,
            'fee_percent': 0.1,
            'order_monitor_timeout_s': 10
        }
    }

@pytest.fixture
def mock_exchange_manager():
    """Creates a mock ExchangeManager that doesn't make real API calls."""
    mock_manager = MagicMock(spec=ExchangeManager)
    mock_manager.get_client.return_value = MagicMock()
    return mock_manager

@pytest.fixture
def mock_trade_logger():
    """Creates a mock TradeLogger."""
    return MagicMock(spec=TradeLogger)

@pytest.fixture
def sample_opportunity():
    """Creates a sample Opportunity object for tests."""
    return Opportunity(
        symbol='BTC/USDT',
        buy_exchange='binance',
        sell_exchange='okx',
        buy_price=40000.0,
        sell_price=40100.0,
        amount=0.001,
        net_profit_usd=0.02
    )

def test_executor_dry_run_success(
    mock_config, 
    mock_exchange_manager, 
    mock_trade_logger, 
    sample_opportunity,
    mocker
):
    """
    Tests the "happy path" for the TradeExecutor in dry_run mode.
    """
    # Arrange
    executor = TradeExecutor(mock_config, mock_exchange_manager, mock_trade_logger)
    spy_place_orders = mocker.spy(executor, '_place_orders')
    spy_monitor_orders = mocker.spy(executor, '_monitor_orders')

    # Act
    result = executor.execute_and_monitor(sample_opportunity, "test_session_123")
    
    # Assert
    assert result['status'] == 'SUCCESS'
    assert result['profit'] == sample_opportunity.net_profit_usd
    
    spy_place_orders.assert_called_once()
    spy_monitor_orders.assert_called_once()
    mock_trade_logger.log_trade.assert_called_once()
    
    logged_trade = mock_trade_logger.log_trade.call_args[0][0]
    assert logged_trade.status == 'SUCCESS'
    assert logged_trade.symbol == 'BTC/USDT'