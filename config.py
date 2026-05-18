"""
CryptoHunter v2 - Configuration
25 high-liquidity USDT pairs on Binance Spot
"""

PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT",
    "LINKUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT", "NEARUSDT",
    "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT",
    "TIAUSDT", "SEIUSDT", "ORDIUSDT", "PEPEUSDT", "WIFUSDT",
]

# Cooldown: don't re-signal same pair within 30 minutes
COOLDOWN_SECONDS = 30 * 60

# HTTP timeout for Binance & Telegram requests
HTTP_TIMEOUT = 10

# Log rotation: keep only last N lines
LOG_MAX_LINES = 500
LOG_FILE = "cryptohunter.log"
