"""
CryptoHunter v2 - SINGLE-CYCLE scanner for GitHub Actions.

One run = one scan of all PAIRS, then exit.
- Cooldown state persisted to cooldown_state.json (via actions/cache)
- Dashboard state persisted to docs/state.json (committed by workflow)

Env vars expected:
  BOT_TOKEN  - Telegram bot token
  CHANNEL_ID - Telegram channel id
  MIN_SCORE  - default 70
"""

import os
import sys
import json
import time
import asyncio
import gc
from datetime import datetime, timezone, timedelta

import aiohttp
from dotenv import load_dotenv

from config import PAIRS, COOLDOWN_SECONDS
from binance_client import BinanceClient
from scoring import calculate_score, ENGINES
from signal_formatter import format_signal
from telegram_sender import send_signal, test_token


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
MIN_SCORE = int(os.getenv("MIN_SCORE", "70"))

COOLDOWN_FILE = "cooldown_state.json"
DASH_FILE = "docs/state.json"

# Dashboard limits
RECENT_SIGNALS_KEEP = 20
TOP_PAIRS_KEEP = 10


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- cooldown state (per-pair throttle) ----------
def load_cooldown():
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    try:
        with open(COOLDOWN_FILE) as f:
            return {k: float(v) for k, v in json.load(f).items()}
    except Exception as e:
        log(f"WARN: cooldown load failed: {e}")
        return {}


def save_cooldown(state):
    now = time.time()
    cutoff = now - (6 * 60 * 60)
    cleaned = {k: v for k, v in state.items() if v >= cutoff}
    try:
        with open(COOLDOWN_FILE, "w") as f:
            json.dump(cleaned, f, indent=2)
    except Exception as e:
        log(f"WARN: cooldown save failed: {e}")


# ---------- dashboard state (persisted to docs/state.json) ----------
def load_dash():
    """Load existing dashboard state, or return a fresh skeleton."""
    if os.path.exists(DASH_FILE):
        try:
            with open(DASH_FILE) as f:
                return json.load(f)
        except Exception as e:
            log(f"WARN: dash state load failed: {e}")

    return {
        "last_scan_time": None,
        "last_scan_time_human": "—",
        "total_scans": 0,
        "total_signals_sent": 0,
        "signals_today": 0,
        "signals_this_week": 0,
        "top_scoring_pairs": [],
        "recent_signals": [],
        "engine_performance": {name: 0 for name, _ in ENGINES},
        "bot_uptime": {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "scans_total": 0,
        },
        "last_error": None,
        "min_score": MIN_SCORE,
        "pairs_count": len(PAIRS),
        "scan_interval_minutes": 5,
    }


def save_dash(dash):
    """Atomically write docs/state.json."""
    os.makedirs(os.path.dirname(DASH_FILE), exist_ok=True)
    tmp = DASH_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(dash, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DASH_FILE)
        log(f"Dashboard state written → {DASH_FILE}")
    except Exception as e:
        log(f"WARN: dash save failed: {e}")


def recount_window(signals, hours):
    """Count signals whose timestamp is within the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    n = 0
    for s in signals:
        try:
            ts = datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                n += 1
        except Exception:
            continue
    return n


# ---------- scan helpers ----------
async def scan_pair(session, symbol, client):
    try:
        score, details = await calculate_score(session, symbol, client)
        price = await client.get_ticker_price(session, symbol)
        return (symbol, score, details, price)
    except Exception as e:
        log(f"[{symbol}] error: {e}")
        return None


# ---------- main ----------
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log("FATAL: BOT_TOKEN or CHANNEL_ID missing.")
        sys.exit(1)

    cooldown = load_cooldown()
    dash = load_dash()
    last_error = None

    log(f"Cooldown entries: {len(cooldown)} · total scans so far: {dash.get('total_scans', 0)}")

    client = BinanceClient()
    timeout = aiohttp.ClientTimeout(total=15)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # token check
        me = await test_t
