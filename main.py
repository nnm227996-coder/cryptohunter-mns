"""
CryptoHunter v2 - main loop.
- Scans 25 pairs every SCAN_INTERVAL seconds (default 90s)
- 5 detection engines per pair
- Sends signals to Telegram channel when score >= MIN_SCORE
- Cooldown of 30 minutes per pair to avoid spam
- Tiny memory footprint (256MB target)
- Log rotation: keeps only last 500 lines
"""

import os
import sys
import time
import asyncio
import gc
from datetime import datetime
from collections import deque

import aiohttp
from dotenv import load_dotenv

from config import PAIRS, COOLDOWN_SECONDS, LOG_MAX_LINES, LOG_FILE
from binance_client import BinanceClient
from scoring import calculate_score
from signal_formatter import format_signal, format_startup_message
from telegram_sender import send_signal, test_token


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
MIN_SCORE = int(os.getenv("MIN_SCORE", "70"))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "90"))


# In-memory cooldown registry: { symbol: last_signal_unix_ts }
last_signal_at: dict = {}

# In-memory log buffer (capped) for rotation
_log_buffer: deque = deque(maxlen=LOG_MAX_LINES)


def log(msg: str):
    """Print + buffer + periodic flush (rotated)."""
    line = f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    _log_buffer.append(line)
    # Flush every line; cheap and gives us crash-safe logs
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(_log_buffer) + "\n")
    except Exception:
        pass


def get_rss_mb():
    """Best-effort RSS read on Linux. Returns 0 elsewhere."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except Exception:
        return 0
    return 0


async def scan_pair(session, symbol, client):
    """Score a single pair; return (symbol, score, details, price) or None on error."""
    try:
        score, details = await calculate_score(session, symbol, client)
        price = await client.get_ticker_price(session, symbol)
        return (symbol, score, details, price)
    except Exception as e:
        log(f"[{symbol}] scan error: {e}")
        return None


async def process_cycle(session, client, cycle_n):
    """Run one full scan across all PAIRS."""
    start = time.time()
    tasks = [scan_pair(session, sym, client) for sym in PAIRS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    signals_sent = 0
    high_scores = []

    for res in results:
        if not res or isinstance(res, Exception):
            continue
        symbol, score, details, price = res

        if score >= MIN_SCORE and price > 0:
            high_scores.append((symbol, score))

            # Cooldown check
            now = time.time()
            last = last_signal_at.get(symbol, 0)
            if now - last < COOLDOWN_SECONDS:
                continue

            msg = format_signal(symbol, price, score, details)
            resp = await send_signal(session, BOT_TOKEN, CHANNEL_ID, msg)
            if resp.get("ok"):
                last_signal_at[symbol] = now
                signals_sent += 1
                log(f"  ✓ signal sent: {symbol} score={score}")
            else:
                log(f"  ✗ telegram failed for {symbol}: {resp.get('description') or resp.get('error')}")

    elapsed = time.time() - start
    ram = get_rss_mb()
    top = ", ".join(f"{s}:{sc}" for s, sc in sorted(high_scores, key=lambda x: -x[1])[:3])
    log(f"[cycle {cycle_n}] scanned {len(PAIRS)}, signals {signals_sent}, "
        f"ram {ram}MB, elapsed {elapsed:.1f}s, top: {top or 'none'}")

    # Free anything that lingered
    gc.collect()


async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log("FATAL: BOT_TOKEN or CHANNEL_ID missing. Check .env / env vars.")
        sys.exit(1)

    client = BinanceClient()
    timeout = aiohttp.ClientTimeout(total=15)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # Step 1: verify token
        me = await test_token(session, BOT_TOKEN)
        if not me.get("ok"):
            log(f"FATAL: invalid BOT_TOKEN - {me}")
            sys.exit(1)
        bot_username = me.get("result", {}).get("username", "?")
        log(f"Bot authenticated: @{bot_username}")

        # Step 2: send startup announcement
        startup = await send_signal(session, BOT_TOKEN, CHANNEL_ID, format_startup_message())
        if startup.get("ok"):
            log(f"Startup message posted to {CHANNEL_ID}")
        else:
            log(f"WARN: startup send failed - {startup.get('description') or startup.get('error')}")
            log("Continuing anyway... will retry signals as they come.")

        # Step 3: main scan loop
        cycle_n = 0
        while True:
            cycle_n += 1
            try:
                await process_cycle(session, client, cycle_n)
            except Exception as e:
                log(f"[cycle {cycle_n}] FATAL inside cycle: {e}")
            await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Stopped by user.")
