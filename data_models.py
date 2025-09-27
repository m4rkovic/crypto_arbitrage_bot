#data_models.py

from dataclasses import dataclass, asdict

@dataclass
class Opportunity:
    """A dataclass to hold all information about a potential arbitrage opportunity."""
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    amount: float
    net_profit_usd: float

@dataclass
class TradeLogData:
    """A dataclass for structured trade log entries."""
    session_id: str
    timestamp: int
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    amount: float
    net_profit_usd: float
    status: str
    latency_ms: int = 0
    fees_paid: float = 0.0
    fill_ratio: float = 0.0
    running_profit_usd: float = 0.0

    def to_dict(self):
        return asdict(self)