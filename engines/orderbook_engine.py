"""
Orderbook Engine - detects bid/ask imbalance (buy-side pressure).
Max score: 20 points.
"""


async def score(session, symbol, client):
    """
    Compare total USD value of top-20 bids vs top-20 asks.
    Bid/Ask ratio >= 2.0 => 20 pts (heavy buy wall)
    Bid/Ask ratio >= 1.5 => 12 pts (strong buy pressure)
    Bid/Ask ratio >= 1.2 =>  6 pts (mild buy pressure)
    """
    ob = await client.get_orderbook(session, symbol, 50)
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if len(bids) < 20 or len(asks) < 20:
        return 0, {}

    try:
        bid_val = sum(float(p) * float(q) for p, q in bids[:20])
        ask_val = sum(float(p) * float(q) for p, q in asks[:20])
    except (ValueError, TypeError):
        return 0, {}

    if ask_val == 0:
        return 0, {}

    ratio = bid_val / ask_val

    if ratio >= 2.0:
        return 20, {"ob_ratio": round(ratio, 2)}
    if ratio >= 1.5:
        return 12, {"ob_ratio": round(ratio, 2)}
    if ratio >= 1.2:
        return 6, {"ob_ratio": round(ratio, 2)}

    return 0, {"ob_ratio": round(ratio, 2)}
