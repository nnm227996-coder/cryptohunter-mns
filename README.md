# CryptoHunter v2 🤖

Lightweight crypto-signal bot that posts Entry / SL / TP signals to the **Bot MNS** Telegram channel.

**Deployed on GitHub Actions** (free, no credit card, no server).

## What it does

- Scans 25 high-liquidity USDT pairs on Binance Spot every 5 minutes
- 5 detection engines: Volume, Orderbook, Whale Candle, Momentum (RSI confluence), Breakout
- Each engine scores 0–20 → total 0–100; signal fires at MIN_SCORE = 70
- 30-minute cooldown per pair (state persisted between runs via `actions/cache`)
- No pandas / numpy / ta-lib — pure Python + `statistics`
- **Signals only — no trades executed. No Binance API key needed.**

---

## 🚀 Deploy on GitHub Actions (recommended)

### 1. Create a new private GitHub repo

Go to https://github.com/new → name: `cryptohunter-mns` → **Private** → Create.

### 2. Upload these files

Push the entire `cryptohunter-v2/` folder contents to the repo root.

> The `.github/workflows/cryptohunter.yml` workflow runs the bot automatically every 5 minutes.

### 3. Add Secrets (Settings → Secrets and variables → Actions → New repository secret)

| Secret name | Value |
|---|---|
| `BOT_TOKEN` | Your Telegram bot token from @BotFather |
| `CHANNEL_ID` | Your channel id (starts with `-100`) |

Optional repo variable: `MIN_SCORE` (default 70).

### 4. Enable Actions

Repo → Actions tab → "I understand my workflows, go ahead and enable them".

### 5. Send startup announcement

Repo → Actions → **"CryptoHunter Startup Announcement"** → **Run workflow** (manual).
You should see a "🚀 CryptoHunter v2 يعمل الآن على Bot MNS" message in your channel within seconds.

### 6. Watch it run

The main workflow fires every 5 minutes automatically. Click any run to see logs.

---

## Local testing

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your token + channel
python scan_once.py    # one cycle
# OR
python main.py         # 24/7 loop (90s interval) — for local dev only
```

---

## File layout

```
cryptohunter-v2/
├── .github/workflows/
│   ├── cryptohunter.yml      # scheduled scan every 5 min
│   └── startup.yml           # one-shot startup announcement
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── config.py                 # 25 pairs + constants
├── binance_client.py         # async Binance public API
├── telegram_sender.py        # async Telegram Bot API
├── scoring.py                # orchestrator across engines
├── signal_formatter.py       # bilingual HTML message
├── scan_once.py              # ← GitHub Actions entry (one cycle)
├── main.py                   # ← 24/7 loop for local/VPS testing
└── engines/
    ├── __init__.py
    ├── volume_engine.py
    ├── orderbook_engine.py
    ├── whale_candle_engine.py
    ├── momentum_engine.py
    └── breakout_engine.py
```

---

## Trade-offs vs. always-on hosting

| Aspect | 90s loop (HeavenCloud) | 5-min Actions |
|---|---|---|
| Cost | Hard to find free tier without Discord | **$0** truly free |
| Setup | Account + ticket + waiting | 5 min, no card |
| Scan frequency | every 90s | every 5 min |
| Late signals | rare | up to 5 min delay |
| Reliability | depends on host | GitHub SLA |

For a swing-trade signal bot scanning 24h breakouts and whale candles, 5 min is more than enough — momentum on a 5m candle hasn't decayed.

---

## Safety

- **Signals only** — no trades. All decisions are yours.
- No API keys to Binance (we only call public read endpoints).
- Cooldown prevents spam on the same pair.
- Cron-only execution — bot is offline 99% of the time, can't drift or hang.
