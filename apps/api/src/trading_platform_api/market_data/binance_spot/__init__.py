"""Opt-in public Binance Spot research adapter; no trading endpoints."""

from .adapter import BinanceSpotProvider, BinanceSpotSettings
from .archive import BinanceSpotArchive

__all__ = ["BinanceSpotArchive", "BinanceSpotProvider", "BinanceSpotSettings"]
