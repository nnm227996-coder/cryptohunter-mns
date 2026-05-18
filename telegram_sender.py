"""
Telegram sender - direct aiohttp call to Bot API (no python-telegram-bot).
Keeps memory footprint tiny.
"""
import asyncio
import aiohttp


TG_BASE = "https://api.telegram.org"


async def send_signal(session: aiohttp.ClientSession, token: str,
                      channel_id: str, text: str, parse_mode: str = "HTML"):
    """
    Send a message to a channel/chat. Returns the parsed JSON response
    or {'ok': False, 'error': '...'} on failure.
    """
    url = f"{TG_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        async with session.post(url, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            return data
    except asyncio.TimeoutError:
        return {"ok": False, "error": "timeout"}
    except aiohttp.ClientError as e:
        return {"ok": False, "error": f"client_error: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"unknown: {e}"}


async def test_token(session: aiohttp.ClientSession, token: str):
    """Verify a BOT_TOKEN via getMe. Returns dict from Telegram."""
    url = f"{TG_BASE}/bot{token}/getMe"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            return await r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
