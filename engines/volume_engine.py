"""
Volume Engine - detects abnormal volume spikes.
Max score: 20 points.
"""
import statistics


async def score(session, symbol, client):
    """
    Compare current 1m volume to MA20 of previous 20 minutes.
    Spike >= 5x  => 20 pts (extreme)
    Spike >= 3x  => 12 pts (strong)
    Spike >= 2x  =>  8 pts (notable)
    """
    klines = await client.get_klines(session, symbol, "1m", 21)
    if len(klines) < 21:
        return 0, {}

    volumes = [float(k[5]) for k in klines]
    ma20 = statistics.mean(volumes[:-1])
    if ma20 == 0:
        return 0, {}

    ratio = volumes[-1] / ma20

    if ratio >= 5:
        return 20, {"vol_ratio": round(ratio, 2)}
    if ratio >= 3:
        return 12, {"vol_ratio": round(ratio, 2)}
    if ratio >= 2:
        return 8, {"vol_ratio": round(ratio, 2)}

    return 0, {"vol_ratio": round(ratio, 2)}
