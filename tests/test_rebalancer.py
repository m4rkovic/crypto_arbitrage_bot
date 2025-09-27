# tests/test_rebalancer.py

import pytest
from unittest.mock import MagicMock, ANY

from rebalancer import Rebalancer
from exchange_manager import ExchangeManager

@pytest.fixture
def mock_config_rebalancer():
    """Provides a mock config with rebalancing enabled."""
    return {
        "rebalancing": {
            "enabled": True,
            "asset_inventory_targets_percent": {
                "BTC": 15  # Target is 15% for BTC
            },
            "default_max_inventory_percent": 10,
            "rebalance_threshold_percent": 5 # Rebalance if BTC > 20% (15 + 5)
        }
    }

@pytest.fixture
def mock_portfolio_surplus():
    """Provides a mock portfolio with a clear BTC surplus."""
    return {
        "total_usd_value": 1000.0,
        "assets": {
            "USDT": {"value_usd": 700.0, "balance": 700.0},
            # BTC is at 30% ($300 / $1000), which is over the 20% trigger
            "BTC": {"value_usd": 300.0, "balance": 0.0075} 
        }
    }

def test_rebalancer_identifies_and_sells_surplus(
    mock_config_rebalancer,
    mock_portfolio_surplus,
    mocker # pytest-mock fixture
):
    """
    Tests that the Rebalancer correctly identifies an asset surplus
    and attempts to place a sell order for the correct amount.
    """
    # Arrange: Set up mock objects
    mock_exchange_manager = MagicMock(spec=ExchangeManager)
    mock_client = MagicMock()
    
    # --- THIS IS THE FIX ---
    # Configure the mock client to simulate the market structure,
    # specifically telling it there is no minimum order cost.
    mock_client.markets = {
        'BTC/USDT': {
            'limits': {
                'cost': {
                    'min': None 
                }
            }
        }
    }
    # ----------------------

    # Arrange: Configure mocks to return necessary values
    mock_exchange_manager.get_all_clients.return_value = {"mock_exchange": mock_client}
    mock_exchange_manager.get_market_price.return_value = 40000.0 # Mock BTC price
    mock_exchange_manager.get_balance.return_value = {"free": {"BTC": 0.0075}}

    # Arrange: Create the Rebalancer and patch its order placement method
    rebalancer = Rebalancer(mock_config_rebalancer, mock_exchange_manager)
    patch_place_order = mocker.patch.object(rebalancer, '_place_rebalance_order')

    # Act: Run the rebalancing check
    rebalancer.run_rebalancing_check(mock_portfolio_surplus)

    # Assert: Verify that an attempt was made to sell the surplus BTC
    patch_place_order.assert_called_once()
    
    # Assert: Check the details of the sell order
    # Surplus = $300 (current) - $150 (target) = $150
    # Amount to sell = $150 / $40,000/BTC = 0.00375 BTC
    call_args = patch_place_order.call_args[0]
    assert call_args[0] == mock_client  # client
    assert call_args[1] == "BTC"        # asset
    assert call_args[2] == "sell"       # side
    assert call_args[3] == pytest.approx(0.00375) # amount