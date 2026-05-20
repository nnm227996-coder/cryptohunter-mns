"""
CryptoHunter v2 - SINGLE-CYCLE scanner for GitHub Actions.
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
TRADES_FILE = "docs/trades.json"
FAILS_FILE = "consecutive_fails.json"

RECENT_SIGNALS_KEEP = 20
TOP_PAIRS_KEEP = 10
RECENT_SCORES_KEEP = 50
TRADE_TIMEOUT_HOURS = 48
MAX_CONSECUTIVE_FAILS = 3


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


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


def load_dash():
    if os.path.exists(DASH_FILE):
        try:
            with open(DASH_FILE) as f:
                return json.load(f)
        except Exception as e:
            log(f"WARN: dash load failed: {e}")
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
        "bot_uptime": {"started_at": datetime.now(timezone.utc).isoformat(), "scans_total": 0},
        "last_error": None,
        "min_score": MIN_SCORE,
        "pairs_count": len(PAIRS),
        "scan_interval_minutes": 5,
        "recent_max_scores": [],
        "avg_score_last_50_scans": 0,
    }


def save_dash(dash):
    os.makedirs(os.path.dirname(DASH_FILE), exist_ok=True)
    tmp = DASH_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(dash, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DASH_FILE)
        log(f"Dashboard → {DASH_FILE}")
    except Exception as e:
        log(f"WARN: dash save failed: {e}")


def recount_window(signals, hours):
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


def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE) as f:
                data = json.load(f)
                data.setdefault("active", [])
                data.setdefault("closed", [])
                data.setdefault("meta", {})
                return data
        except Exception as e:
            log(f"WARN: trades load failed: {e}")
    return {"active": [], "closed": [], "meta": {}}


def save_trades(trades):
    os.makedirs(os.path.dirname(TRADES_FILE), exist_ok=True)
    trades["meta"] = {
        "total_active": len(trades.get("active", [])),
        "total_closed": len(trades.get("closed", [])),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    tmp = TRADES_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(trades, f, indent=2, ensure_ascii=False)
        os.replace(tmp, TRADES_FILE)
        log(f"Trades → {TRADES_FILE} (active={trades['meta']['total_active']}, closed={trades['meta']['total_closed']})")
    except Exception as e:
        log(f"WARN: trades save failed: {e}")


def _close_trade(trade, exit_type, exit_price, exit_dt, pnl_pct):
    closed = dict(trade)
    closed["status"] = "closed"
    closed["exit_type"] = exit_type
    closed["exit_price"] = round(float(exit_price), 8)
    closed["exit_time"] = exit_dt.isoformat() if hasattr(exit_dt, "isoformat") else str(exit_dt)
    closed["pnl_pct"] = round(float(pnl_pct), 2)
    try:
        entry_ts = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
        exit_ts = exit_dt if isinstance(exit_dt, datetime) else datetime.fromisoformat(closed["exit_time"])
        closed["duration_minutes"] = int((exit_ts - entry_ts).total_seconds() / 60)
    except Exception:
        closed["duration_minutes"] = 0
    return closed


async def evaluate_active_trade(session, client, trade):
    try:
        entry_ts = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
    except Exception:
        return None
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    klines = await client.get_klines(session, trade["symbol"], "15m", 200)
    if not klines:
        return None

    entry_ms = int(entry_ts.timestamp() * 1000)
    relevant = [k for k in klines if int(k[0]) >= entry_ms]

    sl = float(trade["sl"])
    tp1, tp2, tp3 = float(trade["tp1"]), float(trade["tp2"]), float(trade["tp3"])
    entry_price = float(trade["entry_price"])

    best_tp_hit = 0
    best_tp_ts = None

    for k in relevant:
        try:
            high = float(k[2]); low = float(k[3])
        except (ValueError, IndexError):
            continue
        candle_ts = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc)

        if low <= sl and best_tp_hit == 0:
            return _close_trade(trade, "sl_hit", sl, candle_ts, -3.0)

        if high >= tp3:
            return _close_trade(trade, "tp3_hit", tp3, candle_ts, 10.0)
        if high >= tp2 and best_tp_hit < 2:
            best_tp_hit = 2; best_tp_ts = candle_ts
        if high >= tp1 and best_tp_hit < 1:
            best_tp_hit = 1; best_tp_ts = candle_ts

        if low <= sl and best_tp_hit >= 1:
            level_pct = {1: 3.0, 2: 6.0, 3: 10.0}[best_tp_hit]
            level_price = {1: tp1, 2: tp2, 3: tp3}[best_tp_hit]
            return _close_trade(trade, f"tp{best_tp_hit}_hit", level_price, best_tp_ts, level_pct)

    elapsed_h = (now - entry_ts).total_seconds() / 3600
    if elapsed_h >= TRADE_TIMEOUT_HOURS:
        current_price = await client.get_ticker_price(session, trade["symbol"])
        if current_price == 0:
            current_price = float(klines[-1][4])
        pnl = (current_price / entry_price - 1.0) * 100.0
        return _close_trade(trade, "timeout", current_price, now, round(pnl, 2))

    return None


def bump_fails(success):
    n = 0
    if os.path.exists(FAILS_FILE):
        try:
            with open(FAILS_FILE) as f:
                n = int(json.load(f).get("consecutive_fails", 0))
        except Exception:
            n = 0
    n = 0 if success else (n + 1)
    try:
        with open(FAILS_FILE, "w") as f:
            json.dump({"consecutive_fails": n, "updated_at": datetime.now(timezone.utc).isoformat()}, f)
    except Exception:
        pass
    return n


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

    cooldown = load_cooldown()
    dash = load_dash()
    trades = load_trades()
    last_error = None

    log(f"Cooldown: {len(cooldown)} · scans so far: {dash.get('total_scans', 0)} "
        f"· active trades: {len(trades.get('active', []))} · closed: {len(trades.get('closed', []))}")

    client = BinanceClient()
    timeout = aiohttp.ClientTimeout(total=15)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        me = await test_token(session, BOT_TOKEN)
        if not me.get("ok"):
            last_error = f"invalid BOT_TOKEN: {me}"
            log(f"FATAL: {last_error}")
            dash["last_error"] = last_error
            save_dash(dash); save_trades(trades); bump_fails(False)
            sys.exit(1)
        bot_username = me.get("result", {}).get("username", "?")
        log(f"Bot: @{bot_username}")

        # evaluate existing active trades
        still_active = []
        for t in trades.get("active", []):
            try:
                closed = await evaluate_active_trade(session, client, t)
                if closed:
                    trades["closed"].append(closed)
                    log(f"  TRADE CLOSED: {t['symbol']} {closed['exit_type']} pnl={closed['pnl_pct']:+.2f}%")
                else:
                    still_active.append(t)
            except Exception as e:
                log(f"  trade-eval error {t.get('symbol')}: {e}")
                still_active.append(t)
        trades["active"] = still_active

        start = time.time()
        tasks = [scan_pair(session, sym, client) for sym in PAIRS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        signals_sent_now = 0

        for res in results:
            if not res or isinstance(res, Exception):
                continue
            symbol, score, details, price = res
            if price > 0:
                scored.append({
                    "symbol": symbol, "score": int(score), "price": float(price),
                    "time": datetime.now(timezone.utc).isoformat(),
                })

            if score >= MIN_SCORE and price > 0:
                now_ts = time.time()
                last = cooldown.get(symbol, 0)
                if now_ts - last < COOLDOWN_SECONDS:
                    log(f"  - {symbol} score={score} (cooldown skip)")
                    continue

                msg = format_signal(symbol, price, score, details)
                resp = await send_signal(session, BOT_TOKEN, CHANNEL_ID, msg)
                if resp.get("ok"):
                    cooldown[symbol] = now_ts
                    signals_sent_now += 1

                    for engine_name, _ in ENGINES:
                        if details.get(f"{engine_name}_pts", 0) > 0:
                            dash["engine_performance"][engine_name] = \
                                dash["engine_performance"].get(engine_name, 0) + 1

                    entry_iso = datetime.now(timezone.utc).isoformat()
                    sig_entry = {
                        "symbol": symbol,
                        "entry": round(float(price), 8),
                        "sl": round(float(price) * 0.97, 8),
                        "tp1": round(float(price) * 1.03, 8),
                        "tp2": round(float(price) * 1.06, 8),
                        "tp3": round(float(price) * 1.10, 8),
                        "score": int(score),
                        "timestamp": entry_iso,
                    }
                    dash["recent_signals"].append(sig_entry)
                    if len(dash["recent_signals"]) > RECENT_SIGNALS_KEEP:
                        dash["recent_signals"] = dash["recent_signals"][-RECENT_SIGNALS_KEEP:]

                    new_trade = {
                        "id": f"{symbol}-{entry_iso}",
                        "symbol": symbol,
                        "entry_price": sig_entry["entry"],
                        "sl": sig_entry["sl"],
                        "tp1": sig_entry["tp1"],
                        "tp2": sig_entry["tp2"],
                        "tp3": sig_entry["tp3"],
                        "score": int(score),
                        "entry_time": entry_iso,
                        "status": "active",
                        "engines": {n: details.get(f"{n}_pts", 0) for n, _ in ENGINES},
                    }
                    trades["active"].append(new_trade)

                    log(f"  ✓ SIGNAL: {symbol} score={score}")
                else:
                    last_error = f"telegram_failed_{symbol}: {resp.get('description') or resp.get('error')}"
                    log(f"  ✗ {last_error}")

        scan_succeeded = (last_error is None)

        dash["last_scan_time"] = datetime.now(timezone.utc).isoformat()
        dash["last_scan_time_human"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        dash["total_scans"] = int(dash.get("total_scans", 0)) + 1
        dash["total_signals_sent"] = int(dash.get("total_signals_sent", 0)) + signals_sent_now
        dash["signals_today"] = recount_window(dash["recent_signals"], 24)
        dash["signals_this_week"] = recount_window(dash["recent_signals"], 24 * 7)
        if not dash.get("bot_uptime") or not dash["bot_uptime"].get("started_at"):
            dash["bot_uptime"] = {"started_at": datetime.now(timezone.utc).isoformat(), "scans_total": 0}
        dash["bot_uptime"]["scans_total"] = dash["total_scans"]
        scored.sort(key=lambda x: -x["score"])
        dash["top_scoring_pairs"] = scored[:TOP_PAIRS_KEEP]
        dash["min_score"] = MIN_SCORE
        dash["pairs_count"] = len(PAIRS)
        dash["scan_interval_minutes"] = 5

        recent_max = list(dash.get("recent_max_scores", []))
        current_max = scored[0]["score"] if scored else 0
        recent_max.append(current_max)
        if len(recent_max) > RECENT_SCORES_KEEP:
            recent_max = recent_max[-RECENT_SCORES_KEEP:]
        dash["recent_max_scores"] = recent_max
        dash["avg_score_last_50_scans"] = round(sum(recent_max) / len(recent_max), 1) if recent_max else 0

        dash["last_error"] = last_error
        dash["active_trades_count"] = len(trades.get("active", []))
        dash["closed_trades_count"] = len(trades.get("closed", []))

        elapsed = time.time() - start
        log(f"DONE: scanned {len(PAIRS)}, signals_now {signals_sent_now}, "
            f"top_score {current_max}, elapsed {elapsed:.1f}s")

        fails = bump_fails(scan_succeeded)
        log(f"Consecutive fails: {fails}")
        if fails == MAX_CONSECUTIVE_FAILS:
            alert = (f"🚨 <b>CryptoHunter Alert</b>\n"
                     f"{fails} consecutive scan failures.\n"
                     f"Last error: <code>{last_error or 'unknown'}</code>\n"
                     f"Time: <code>{datetime.now(timezone.utc).isoformat()}</code>")
            try:
                await send_signal(session, BOT_TOKEN, CHANNEL_ID, alert)
                log("Alert sent.")
            except Exception as e:
                log(f"WARN: alert send failed: {e}")

    save_cooldown(cooldown)
    save_dash(dash)
    save_trades(trades)
    gc.collect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Stopped by user.")
    except Exception as e:
        log(f"FATAL unhandled: {e}")
        try:
            d = load_dash()
            d["last_error"] = f"unhandled: {e}"
            save_dash(d)
            bump_fails(False)
        except Exception:
            pass
        sys.exit(1)
