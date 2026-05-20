"""
Binance Public API client (no API key needed - read-only endpoints).
Uses aiohttp for async requests. Robust error handling + timeouts.
"""

import asyncio
import aiohttp
from config import HTTP_TIMEOUT

BASE_URL = "https://data-api.binance.vision/api/v3"


class BinanceClient:
    """Thin async wrapper around Binance public REST endpoints."""

    @staticmethod
    async def get_klines(session: aiohttp.ClientSession, symbol: str,
                         interval: str, limit: int = 100):
        """
        Get candlestick data.
        Returns list of [open_time, open, high, low, close, volume, ...]
        We mainly use indices 1..5 (OHLCV).
        """
        url = f"{BASE_URL}/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as r:
                if r.status != 200:
                    return []
                data = await r.json()
                return data if isinstance(data, list) else []
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return []
        except Exception:
            return []

    @staticmethod
    async def get_orderbook(session: aiohttp.ClientSession, symbol: str,
                            limit: int = 50):
        """
        Get order book depth.
        Returns dict with 'bids' and 'asks' lists of [price, qty] strings.
        """
        url = f"{BASE_URL}/depth"
        params = {"symbol": symbol, "limit": limit}
        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as r:
                if r.status != 200:
                    return {"bids": [], "asks": []}
                data = await r.json()
                return {
                    "bids": data.get("bids", []),
                    "asks": data.get("asks", []),
                }
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return {"bids": [], "asks": []}
        except Exception:
            return {"bids": [], "asks": []}

    @staticmethod
    async def get_ticker_price(session: aiohttp.ClientSession, symbol: str):
        """Return current price as float, or 0.0 on failure."""
        url = f"{BASE_URL}/ticker/price"
        params = {"symbol": symbol}
        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as r:
                if r.status != 200:
                    return 0.0
                data = await r.json()
                return float(data.get("price", 0))
        except Exception:
            return 0.0
