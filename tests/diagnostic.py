"""
CryptoHunter v2 — Diagnostic Tests
Run via workflow_dispatch: .github/workflows/diagnostic.yml
Or locally:  python -m tests.diagnostic

5 tests:
  1. Binance vs CoinGecko price sanity check
  2. Klines data freshness (lag check)
  3. All 5 engines on a volatile pair (DOGEUSDT)
  4. Top 10 scores across the 25-pair universe + threshold sanity
  5. Telegram delivery round-trip
"""

import os
import sys
import asyncio
import time
import statistics
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

# Make the project importable when running as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PAIRS
from binance_client import BinanceClient
from scoring import calculate_score, ENGINES
from telegram_sender import send_signal


load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()


# small color helpers (ANSI) – GitHub Actions renders these fine
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def banner(title):
    print(f"\n{CYAN}{'═' * 70}{RESET}")
    print(f"{BOLD}{CYAN}{title}{RESET}")
    print(f"{CYAN}{'═' * 70}{RESET}")


def passed(msg):  print(f"  {GREEN}✓ PASS{RESET} {msg}")
def warned(msg):  print(f"  {YELLOW}⚠ WARN{RESET} {msg}")
def failed(msg):  print(f"  {RED}✗ FAIL{RESET} {msg}")
def info(msg):    print(f"    {msg}")


# ──────────────────────────────────────────────────────────────────────────
# TEST 1 — Binance vs CoinGecko price sanity
# ──────────────────────────────────────────────────────────────────────────
async def test_1_price_sanity(session, client):
    banner("TEST 1 — Binance vs CoinGecko (BTCUSDT)")
    results = {"name": "price_sanity", "passed": False}

    try:
        binance_price = await client.get_ticker_price(session, "BTCUSDT")
        info(f"Binance BTCUSDT  = ${binance_price:,.2f}")
        results["binance"] = binance_price

        if binance_price == 0:
            failed("Binance returned 0 – API unreachable from this runner?")
            return results

        # CoinGecko free, no key
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                warned(f"CoinGecko HTTP {r.status} – sanity check skipped, but Binance OK.")
                results["passed"] = True   # Binance worked; CG is just a cross-check
                return results
            data = await r.json()
            cg_price = float(data.get("bitcoin", {}).get("usd", 0))

        info(f"CoinGecko BTCUSDT = ${cg_price:,.2f}")
        results["coingecko"] = cg_price

        if cg_price == 0:
            warned("CoinGecko returned 0 – skipping diff check.")
            results["passed"] = True
            return results

        diff_pct = abs(binance_price - cg_price) / cg_price * 100.0
        info(f"Spread = {diff_pct:.3f}%")
        results["spread_pct"] = round(diff_pct, 3)

        if diff_pct < 0.5:
            passed(f"Price spread {diff_pct:.3f}% < 0.5% – data sources agree.")
            results["passed"] = True
        elif diff_pct < 2:
            warned(f"Price spread {diff_pct:.3f}% (0.5–2%) – acceptable but watch.")
            results["passed"] = True
        else:
            failed(f"Price spread {diff_pct:.3f}% > 2% – something is wrong.")

    except Exception as e:
        failed(f"Exception: {e}")
        results["error"] = str(e)

    return results


# ──────────────────────────────────────────────────────────────────────────
# TEST 2 — Klines freshness
# ──────────────────────────────────────────────────────────────────────────
async def test_2_klines_lag(session, client):
    banner("TEST 2 — Binance klines freshness (BTCUSDT 1m)")
    results = {"name": "klines_lag", "passed": False}

    try:
        klines = await client.get_klines(session, "BTCUSDT", "1m", 5)
        if not klines:
            failed("get_klines returned empty list.")
            return results

        last = klines[-1]
        open_time_ms = int(last[0])
        last_dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        lag_sec = (now - last_dt).total_seconds()

        info(f"Last 1m candle open: {last_dt.isoformat()}")
        info(f"Now:                 {now.isoformat()}")
        info(f"Lag = {lag_sec:.1f} s")

        results["last_candle_open"] = last_dt.isoformat()
        results["lag_seconds"] = round(lag_sec, 1)

        if lag_sec <= 90:
            passed(f"Lag {lag_sec:.0f}s ≤ 90s – data is fresh.")
            results["passed"] = True
        elif lag_sec <= 180:
            warned(f"Lag {lag_sec:.0f}s in 90–180s – acceptable but borderline.")
            results["passed"] = True
        else:
            failed(f"Lag {lag_sec:.0f}s > 180s – data is stale, possible API issue.")

    except Exception as e:
        failed(f"Exception: {e}")
        results["error"] = str(e)

    return results


# ──────────────────────────────────────────────────────────────────────────
# TEST 3 — All 5 engines on a volatile pair
# ──────────────────────────────────────────────────────────────────────────
async def test_3_engines_on_doge(session, client):
    banner("TEST 3 — Run 5 engines on DOGEUSDT (volatile pair)")
    results = {"name": "engines_doge", "passed": False, "engines": {}}

    try:
        symbol = "DOGEUSDT"
        total = 0
        nonzero = 0

        for name, engine in ENGINES:
            try:
                pts, det = await engine.score(session, symbol, client)
                total += pts
                results["engines"][name] = {"pts": int(pts), "details": det}
                color = GREEN if pts > 0 else YELLOW
                print(f"    {color}{name:10s}{RESET}  pts={pts:>3}   {det}")
                if pts > 0:
                    nonzero += 1
            except Exception as e:
                failed(f"engine '{name}' raised: {e}")
                results["engines"][name] = {"error": str(e)}

        info(f"Total score on {symbol} = {total}/100  ·  engines>0: {nonzero}/5")
        results["total"] = total
        results["nonzero_engines"] = nonzero

        if nonzero >= 1:
            passed(f"At least one engine returned > 0 points – engines are alive.")
            results["passed"] = True
        else:
            warned("All engines returned 0 – market is unusually quiet, not necessarily a bug.")
            results["passed"] = True  # don't fail the suite – it's market dependent

    except Exception as e:
        failed(f"Exception: {e}")
        results["error"] = str(e)

    return results


# ──────────────────────────────────────────────────────────────────────────
# TEST 4 — Threshold reality check
# ──────────────────────────────────────────────────────────────────────────
async def test_4_threshold(session, client):
    banner("TEST 4 — Top 10 scores across all 25 pairs / threshold check")
    results = {"name": "threshold", "passed": False, "top10": []}

    try:
        scored = []
        for sym in PAIRS:
            try:
                score, det = await calculate_score(session, sym, client)
                scored.append((sym, int(score), det))
            except Exception as e:
                info(f"{sym}: error {e}")

        scored.sort(key=lambda x: -x[1])
        top10 = scored[:10]

        info("Top 10 right now:")
        for i, (sym, sc, _) in enumerate(top10, 1):
            color = GREEN if sc >= 70 else (YELLOW if sc >= 50 else RESET)
            print(f"    {i:>2}. {color}{sym:10s} {sc:>3}/100{RESET}")
            results["top10"].append({"symbol": sym, "score": sc})

        max_score = top10[0][1] if top10 else 0
        all_scores = [s for _, s, _ in scored]
        median_score = int(statistics.median(all_scores)) if all_scores else 0
        results["max_score"] = max_score
        results["median_score"] = median_score
        results["pairs_evaluated"] = len(scored)

        info(f"Max score = {max_score}  ·  Median = {median_score}  ·  Pairs = {len(scored)}")

        current = int(os.getenv("MIN_SCORE", "70"))
        # propose a threshold = max + small margin OR keep 70 if market is hot
        suggested = max(50, min(80, max_score + 5)) if max_score < 65 else current
        results["current_threshold"] = current
        results["suggested_threshold"] = suggested

        if max_score >= current:
            passed(f"At least one pair reaches MIN_SCORE={current} – threshold is achievable.")
            results["passed"] = True
        elif max_score >= 50:
            warned(f"Max={max_score} < MIN_SCORE={current}. Market is calm — consider lowering threshold to ~{suggested}.")
            results["passed"] = True
        else:
            warned(f"Max={max_score} – market is exceptionally quiet.")
            results["passed"] = True

    except Exception as e:
        failed(f"Exception: {e}")
        results["error"] = str(e)

    return results


# ──────────────────────────────────────────────────────────────────────────
# TEST 5 — Telegram delivery round-trip
# ──────────────────────────────────────────────────────────────────────────
async def test_5_telegram(session):
    banner("TEST 5 — Telegram delivery round-trip")
    results = {"name": "telegram", "passed": False}

    if not BOT_TOKEN or not CHANNEL_ID:
        failed("BOT_TOKEN or CHANNEL_ID missing in env.")
        return results

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = (
        f"🧪 <b>Diagnostic Test</b>\n"
        f"<i>{ts}</i>\n\n"
        f"If you can read this, Telegram delivery is healthy. ✅"
    )

    try:
        resp = await send_signal(session, BOT_TOKEN, CHANNEL_ID, msg)
        results["telegram_response_ok"] = resp.get("ok", False)
        if resp.get("ok"):
            mid = resp.get("result", {}).get("message_id")
            passed(f"Telegram delivered. message_id={mid}")
            results["message_id"] = mid
            results["passed"] = True
        else:
            failed(f"Telegram failed: {resp}")
            results["error"] = resp.get("description") or resp.get("error") or str(resp)
    except Exception as e:
        failed(f"Exception: {e}")
        results["error"] = str(e)

    return results


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n{BOLD}CryptoHunter v2 — Diagnostic Suite{RESET}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")

    timeout = aiohttp.ClientTimeout(total=20)
    connector = aiohttp.TCPConnector(limit=10)
    client = BinanceClient()

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        t1 = await test_1_price_sanity(session, client)
        t2 = await test_2_klines_lag(session, client)
        t3 = await test_3_engines_on_doge(session, client)
        t4 = await test_4_threshold(session, client)
        t5 = await test_5_telegram(session)

    # Final summary
    banner("SUMMARY")
    summary = [t1, t2, t3, t4, t5]
    n_passed = sum(1 for r in summary if r.get("passed"))
    n_total = len(summary)

    for r in summary:
        mark = f"{GREEN}✓{RESET}" if r.get("passed") else f"{RED}✗{RESET}"
        print(f"  {mark}  {r['name']}")

    print(f"\n  {BOLD}{n_passed}/{n_total} tests passed{RESET}\n")

    # Exit non-zero only if a *real* failure happened (telegram or binance broken)
    must_pass = {"price_sanity", "klines_lag", "telegram"}
    fatal = [r for r in summary if r["name"] in must_pass and not r.get("passed")]
    if fatal:
        print(f"{RED}FATAL: required tests failed: {[r['name'] for r in fatal]}{RESET}")
        sys.exit(1)

    print(f"{GREEN}Diagnostic suite OK.{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
