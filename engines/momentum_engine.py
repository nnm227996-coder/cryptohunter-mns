"""
Momentum Engine - RSI multi-timeframe confluence (no numpy/pandas).
Max score: 20 points.
"""


def calc_rsi(closes, period=14):
    """Manual RSI calculation. Returns 50 if not enough data."""
    if len(closes) < period + 1:
        return 50.0

    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period

    if avg_l == 0:
        return 100.0

    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


async def score(session, symbol, client):
    """
    Get RSI on 5m, 15m, 1h. Bullish band = [50, 70].
    3 timeframes bullish => 20 pts (perfect confluence)
    2 timeframes bullish => 12 pts (good)
    < 2                  =>  0 pts
    """
    k5 = await client.get_klines(session, symbol, "5m", 20)
    k15 = await client.get_klines(session, symbol, "15m", 20)
    k1h = await client.get_klines(session, symbol, "1h", 20)

    if len(k5) < 15 or len(k15) < 15 or len(k1h) < 15:
        return 0, {}

    try:
        c5 = [float(k[4]) for k in k5]
        c15 = [float(k[4]) for k in k15]
        c1h = [float(k[4]) for k in k1h]
    except (ValueError, TypeError, IndexError):
        return 0, {}

    rsi_5m = calc_rsi(c5)
    rsi_15m = calc_rsi(c15)
    rsi_1h = calc_rsi(c1h)

    bullish = sum(1 for r in [rsi_5m, rsi_15m, rsi_1h] if 50 <= r <= 70)
    det = {
        "rsi_5m": round(rsi_5m, 1),
        "rsi_15m": round(rsi_15m, 1),
        "rsi_1h": round(rsi_1h, 1),
        "rsi_confluence": bullish,
    }

    if bullish == 3:
        return 20, det
    if bullish == 2:
        return 12, det
    return 0, det
