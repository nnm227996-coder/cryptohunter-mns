"""
Scoring orchestrator - runs all 5 engines for a symbol and sums scores.
Max possible total: 100 pts (5 engines x 20 each).
"""

from engines import (
    volume_engine,
    orderbook_engine,
    whale_candle_engine,
    momentum_engine,
    breakout_engine,
)

ENGINES = [
    ("volume", volume_engine),
    ("orderbook", orderbook_engine),
    ("whale", whale_candle_engine),
    ("momentum", momentum_engine),
    ("breakout", breakout_engine),
]


async def calculate_score(session, symbol, client):
    """
    Run every engine sequentially (so we share the aiohttp connection
    cleanly without flooding Binance). Returns (total_score, details_dict).
    Engines that raise are skipped with 0 pts (logged).
    """
    total = 0
    details = {}

    for name, engine in ENGINES:
        try:
            pts, det = await engine.score(session, symbol, client)
            total += pts
            details[f"{name}_pts"] = pts
            if det:
                details.update(det)
        except Exception as e:
            print(f"[{symbol}] engine '{name}' error: {e}")
            details[f"{name}_pts"] = 0

    return total, details
