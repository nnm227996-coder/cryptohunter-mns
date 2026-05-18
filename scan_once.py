"""
CryptoHunter v2 - SINGLE-CYCLE scanner for GitHub Actions.

One run = one scan of all PAIRS, then exit.
Cooldown state is persisted to cooldown_state.json (restored by actions/cache).

Env vars expected:
  BOT_TOKEN  - Telegram bot token
  CHANNEL_ID - Telegram channel id (negative, starts with -100)
  MIN_SCORE  - default 70

This file replaces main.py for GitHub Actions deployment.
main.py is kept for local 24/7 testing.
"""

import os
import sys
import json
import time
import asyncio
import gc
from datetime import datetime

import aiohttp
from dotenv import load_dotenv

from config import PAIRS, COOLDOWN_SECONDS
from binance_client import BinanceClient
from scoring import calculate_score
from signal_formatter import format_signal
from telegram_sender import send_signal, test_token


load_dotenv()  # local .env fallback; in CI env vars come from Secrets

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
MIN_SCORE = int(os.getenv("MIN_SCORE", "70"))

STATE_FILE = "cooldown_state.json"


def log(msg: str):
    """Stdout only — GitHub Actions captures it."""
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state():
    """Return { symbol: last_unix_ts }. Empty dict if first run or cache miss."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
            return {k: float(v) for k, v in data.items()}
    except Exception as e:
        log(f"WARN: could not load state ({e}); starting fresh.")
        return {}


def save_state(state):
    """Persist cooldown state for next run."""
    # Prune entries older than 6 hours (no need to remember them)
    now = time.time()
    cutoff = now - (6 * 60 * 60)
    cleaned = {k: v for k, v in state.items() if v >= cutoff}
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(cleaned, f, indent=2)
        log(f"State saved: {len(cleaned)} entries")
    except Exception as e:
        log(f"WARN: could not save state ({e})")


async def scan_pair(session, symbol, client):
    try:
        score, details = await calculate_score(session, symbol, client)
        price = await client.get_ticker_price(session, symbol)
        return (symbol, score, details, price)
    except Exception as e:
        log(f"[{symbol}] error: {e}")
        return None


async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log("FATAL: BOT_TOKEN or CHANNEL_ID missing.")
        sys.exit(1)

    state = load_state()
    log(f"Loaded cooldown state: {len(state)} entries")

    client = BinanceClient()
    timeout = aiohttp.ClientTimeout(total=15)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # Verify token (cheap sanity check)
        me = await test_token(session, BOT_TOKEN)
        if not me.get("ok"):
            log(f"FATAL: invalid BOT_TOKEN - {me}")
            sys.exit(1)
        bot_username = me.get("result", {}).get("username", "?")
        log(f"Bot: @{bot_username}")

        # Run one scan across all pairs
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

                now = time.time()
                last = state.get(symbol, 0)
                if now - last < COOLDOWN_SECONDS:
                    log(f"  - {symbol} score={score} (cooldown, skip)")
                    continue

                msg = format_signal(symbol, price, score, details)
                resp = await send_signal(session, BOT_TOKEN, CHANNEL_ID, msg)
                if resp.get("ok"):
                    state[symbol] = now
                    signals_sent += 1
                    log(f"  ✓ SIGNAL SENT: {symbol} score={score}")
                else:
                    log(f"  ✗ Telegram failed for {symbol}: {resp}")

        elapsed = time.time() - start
        top = ", ".join(f"{s}:{sc}" for s, sc in sorted(high_scores, key=lambda x: -x[1])[:5])
        log(f"DONE: scanned {len(PAIRS)}, signals {signals_sent}, "
            f"elapsed {elapsed:.1f}s, top: {top or 'none'}")

    save_state(state)
    gc.collect()


if __name__ == "__main__":
    asyncio.run(main())
