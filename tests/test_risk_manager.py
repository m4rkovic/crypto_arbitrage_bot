# tests/test_risk_manager.py

import pytest
from unittest.mock import MagicMock

# Import the classes we need for the test
from risk_manager import RiskManager
from data_models import Opportunity
from exchange_manager import ExchangeManager

@pytest.fixture
def mock_config():
    """Provides a basic mock config for the RiskManager."""
    return {} # The methods we're testing don't need config values yet

@pytest.fixture
def sample_opportunity():
    """Creates a sample Opportunity that requires 100 USDT and 0.0025 BTC."""
    return Opportunity(
        symbol='BTC/USDT',
        buy_exchange='binance',
        sell_exchange='okx',
        buy_price=40000.0,
        sell_price=40100.0,
        amount=0.0025, # This is the required base currency
        net_profit_usd=0.02
    )

def test_check_balances_insufficient_funds(mock_config, sample_opportunity):
    """
    Tests that risk_manager.check_balances returns False when funds are insufficient.
    """
    # Arrange: Create a mock ExchangeManager
    mock_exchange_manager = MagicMock(spec=ExchangeManager)
    
    # Arrange: Configure the mock clients
    mock_buy_client = MagicMock()
    mock_sell_client = MagicMock()
    
    # Arrange: Simulate the get_client method returning our mock clients
    def get_client_side_effect(exchange_name):
        if exchange_name == 'binance':
            return mock_buy_client
        if exchange_name == 'okx':
            return mock_sell_client
        return None
    mock_exchange_manager.get_client.side_effect = get_client_side_effect

    # Arrange: Simulate INSUFFICIENT balances being returned
    # The opportunity requires 100 USDT, but we only have 90.
    mock_exchange_manager.get_balance.return_value = {
        'free': {
            'USDT': 90.0, # Not enough quote currency
            'BTC': 0.0020 # Not enough base currency either
        }
    }

    # Arrange: Create the RiskManager instance with our mocks
    risk_manager = RiskManager(mock_config, mock_exchange_manager)
    
    # Act: Call the method we want to test
    # The trade size is 100 USDT (buy_price * amount)
    is_safe = risk_manager.check_balances(sample_opportunity, trade_size_usdt=100.0)
    
    # Assert: The result should be False because we don't have enough funds
    assert is_safe is False