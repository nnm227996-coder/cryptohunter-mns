"""
Format signals as Telegram HTML messages (bilingual: Arabic + English).
Entry / SL / TP1 / TP2 / TP3.
"""


def _fmt_price(p):
    """Pretty-print prices: more decimals for small caps."""
    if p == 0:
        return "0"
    if p < 0.001:
        return f"{p:.8f}"
    if p < 1:
        return f"{p:.6f}"
    if p < 100:
        return f"{p:.4f}"
    return f"{p:.2f}"


def format_signal(symbol, price, score, details):
    """
    Build a bilingual signal message.
    SL  = -3%
    TP1 = +3%
    TP2 = +6%
    TP3 = +10%
    """
    sl = price * 0.97
    tp1 = price * 1.03
    tp2 = price * 1.06
    tp3 = price * 1.10

    # Build a compact analytics tail (top 3 signals only, to keep message clean)
    extras = []
    if "vol_ratio" in details and details["vol_ratio"] >= 2:
        extras.append(f"Vol x{details['vol_ratio']}")
    if "ob_ratio" in details and details["ob_ratio"] >= 1.2:
        extras.append(f"OB {details['ob_ratio']}")
    if details.get("whale_candle"):
        extras.append(f"Whale ({details['whale_candle']})")
    if details.get("breakout") == "confirmed":
        extras.append("Breakout!")
    if details.get("rsi_confluence", 0) >= 2:
        extras.append(f"RSI {details['rsi_confluence']}/3")

    extras_line = " | ".join(extras) if extras else ""

    msg = (
        "🚨 <b>إشارة جديدة | New Signal</b> 🚨\n\n"
        f"💎 الزوج | Pair: <code>{symbol}</code>\n"
        f"📊 النقاط | Score: <b>{score}/100</b>\n\n"
        f"📍 الدخول | Entry: <code>${_fmt_price(price)}</code>\n"
        f"🛑 الوقف | SL: <code>${_fmt_price(sl)}</code> (-3%)\n"
        f"🎯 هدف 1 | TP1: <code>${_fmt_price(tp1)}</code> (+3%)\n"
        f"🎯 هدف 2 | TP2: <code>${_fmt_price(tp2)}</code> (+6%)\n"
        f"🎯 هدف 3 | TP3: <code>${_fmt_price(tp3)}</code> (+10%)\n"
    )

    if extras_line:
        msg += f"\n🔍 <i>{extras_line}</i>\n"

    msg += (
        "\n⚠️ ادر مخاطرك | Manage your risk\n"
        "🤖 <b>Bot MNS</b>"
    )
    return msg


def format_startup_message():
    """Sent once when the bot comes online."""
    return (
        "🚀 <b>CryptoHunter v2 يعمل الآن على Bot MNS</b>\n"
        "✅ المسح كل 90 ثانية\n"
        "✅ 25 زوج | 5 محركات\n"
        "✅ Min Score: 70/100\n\n"
        "<i>إشارات فقط - لا تنفيذ تلقائي.</i>"
    )
