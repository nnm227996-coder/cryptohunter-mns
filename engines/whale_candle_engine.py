"""
Whale Candle Engine - detects unusually large candles (smart-money activity).
Max score: 20 points.
"""
import statistics


async def score(session, symbol, client):
    """
    Fetch 50 5-min candles. A 'whale candle' has:
      - body  > 3x average body
      - volume > 5x average volume

    If found in last 6 candles (30 min) => 20 pts
    If found in last 12 candles (1 hr)  => 12 pts
    """
    klines = await client.get_klines(session, symbol, "5m", 50)
    if len(klines) < 50:
        return 0, {}

    try:
        bodies = [abs(float(k[4]) - float(k[1])) for k in klines]
        volumes = [float(k[5]) for k in klines]
    except (ValueError, TypeError, IndexError):
        return 0, {}

    avg_body = statistics.mean(bodies)
    avg_volume = statistics.mean(volumes)

    if avg_body == 0 or avg_volume == 0:
        return 0, {}

    # Scan last 12 candles (1 hour) from most recent backwards
    for i, k in enumerate(reversed(klines[-12:])):
        body = abs(float(k[4]) - float(k[1]))
        vol = float(k[5])

        if body > 3 * avg_body and vol > 5 * avg_volume:
            if i < 6:  # within last 30 min
                return 20, {"whale_candle": "last_30m"}
            else:      # within last 1h
                return 12, {"whale_candle": "last_1h"}

    return 0, {}
