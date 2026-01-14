from __future__ import annotations

import asyncio
import os
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import Settings
from kakao_scraper import scrape_today_post
from telegram_sender import TelegramSender


# ------------------ Dedup state (persisted via GitHub Actions cache) ------------------
STATE_DIR = Path(".state")
STATE_FILE = STATE_DIR / "sent.json"
KST = timezone(timedelta(hours=9))


def _today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _make_dedupe_key(result: dict) -> str:
    """
    Prefer URL as a stable unique key.
    Fallback: hash(title + text) when URL is missing.
    """
    url = (result.get("url") or "").strip()
    if url:
        return f"url:{url}"

    title = (result.get("title") or "").strip()
    text = (result.get("text") or "").strip()
    raw = f"{title}\n{text}".strip()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"hash:{digest}"


def _already_sent_today(dedupe_key: str) -> bool:
    st = _load_state()
    return st.get("date") == _today_kst() and st.get("dedupe_key") == dedupe_key


def _mark_sent_today(dedupe_key: str) -> None:
    _save_state({"date": _today_kst(), "dedupe_key": dedupe_key})


# -------------------------------------------------------------------------------------


def build_message(result: dict) -> str:
    title = (result.get("title") or "").strip()
    text = (result.get("text") or "").strip()
    url = (result.get("url") or "").strip()

    msg = f"📌 {title}".strip()
    if text:
        msg += f"\n\n{text}"
    if url:
        msg += f"\n\n🔗 {url}"
    return msg


async def main_async():
    now = datetime.now(KST)
    if (now.hour, now.minute) >= (11, 45):
        print(f"[SKIP] too late to send lunch menu. now={now.isoformat()}")
        return


    settings = Settings.load()
    sender = TelegramSender(settings.tg_bot_token, settings.tg_chat_id)

    mode = os.getenv("MODE", "full").strip().lower()  # full|text|image

    result = await scrape_today_post(
        posts_url=settings.kakao_posts_url,
        download_dir="downloads",
        headless=settings.headless,
    )

    # ✅ Dedup gate: skip if already sent today (KST)
    dedupe_key = _make_dedupe_key(result)
    if _already_sent_today(dedupe_key):
        print(f"[SKIP] already sent today (KST). dedupe_key={dedupe_key}")
        return

    msg = build_message(result)
    imgs = result.get("downloaded", [])

    # ✅ Send
    if mode in ("full", "text"):
        sender.send_text(msg)

    if mode in ("full", "image"):
        for i in range(0, len(imgs), 10):
            sender.send_media_group(imgs[i:i + 10])

    # ✅ Mark after successful sends
    _mark_sent_today(dedupe_key)
    print(f"[OK] sent and marked. dedupe_key={dedupe_key}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
