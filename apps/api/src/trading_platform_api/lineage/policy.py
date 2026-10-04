"""Bounded data eligibility for the approved personal cold archive."""

from trading_platform_api.market_data.contracts import MarketData

PERSONAL_SPOT_INSTRUMENTS = frozenset(
    {
        "BTC-USDT-SPOT",
        "ETH-USDT-SPOT",
        "BNB-USDT-SPOT",
        "SOL-USDT-SPOT",
        "XRP-USDT-SPOT",
    }
)
PERSONAL_SPOT_VENUE = "BINANCE-SPOT"


def is_personal_spot_ohlcv(record: object) -> bool:
    if type(record) is not MarketData:
        return False
    return (
        record.venue_id == PERSONAL_SPOT_VENUE
        and record.instrument_id in PERSONAL_SPOT_INSTRUMENTS
        and record.observation_type == "OHLCV"
    )
