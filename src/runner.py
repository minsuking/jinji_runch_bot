from __future__ import annotations

import asyncio
import os

from config import Settings
from kakao_scraper import scrape_today_post
from telegram_sender import TelegramSender


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
    settings = Settings.load()
    sender = TelegramSender(settings.tg_bot_token, settings.tg_chat_id)

    mode = os.getenv("MODE", "full").strip().lower()  # full|text|image
    result = await scrape_today_post(
        posts_url=settings.kakao_posts_url,
        download_dir="downloads",
        headless=settings.headless,
    )

    msg = build_message(result)
    imgs = result.get("downloaded", [])

    if mode in ("full", "text"):
        sender.send_text(msg)

    if mode in ("full", "image"):
        for i in range(0, len(imgs), 10):
            sender.send_media_group(imgs[i:i + 10])


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
