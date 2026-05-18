"""
Breakout Engine - detects 24h-high breakouts on 15m timeframe.
Max score: 20 points.
"""
import statistics


async def score(session, symbol, client):
    """
    Fetch 96 candles of 15m (24 hours).
    high_24h    = max of highs (excluding current candle)
    current     = last close
    volume_ma   = mean of last 20 volumes (excluding current)

    Real breakout: current > high_24h AND volume[-1] > 2x volume_ma => 20 pts
    Near breakout: current > 0.98 * high_24h                        => 10 pts
    """
    klines = await client.get_klines(session, symbol, "15m", 96)
    if len(klines) < 96:
        return 0, {}

    try:
        highs = [float(k[2]) for k in klines]
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
    except (ValueError, TypeError, IndexError):
        return 0, {}

    high_24h = max(highs[:-1])
    current = closes[-1]

    if high_24h == 0:
        return 0, {}

    # Volume MA over last 20 candles (excluding current)
    vol_ma = statistics.mean(volumes[-21:-1]) if len(volumes) >= 21 else statistics.mean(volumes[:-1])
    if vol_ma == 0:
        return 0, {}

    if current > high_24h and volumes[-1] > 2 * vol_ma:
        return 20, {
            "breakout": "confirmed",
            "high_24h": round(high_24h, 6),
            "vol_x": round(volumes[-1] / vol_ma, 2),
        }

    if current > 0.98 * high_24h:
        return 10, {
            "breakout": "near",
            "high_24h": round(high_24h, 6),
            "pct_of_high": round((current / high_24h) * 100, 2),
        }

    return 0, {"high_24h": round(high_24h, 6)}
