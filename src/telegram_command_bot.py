from __future__ import annotations

import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config import Settings
from kakao_scraper import scrape_today_post
from telegram_sender import TelegramSender
from time_utils import parse_delay_arg


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


async def do_scrape_and_send(mode: str, settings: Settings):
    sender = TelegramSender(settings.tg_bot_token, settings.tg_chat_id)

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 명령어 안내\n"
        "/menu            : 즉시 전송(텍스트+이미지)\n"
        "/preview         : 즉시 전송(텍스트만)\n"
        "/image           : 즉시 전송(이미지만)\n"
        "/send <초|HH:MM>  : 예약 전송(KST)\n"
        "  예) /send 10\n"
        "  예) /send 12:30\n"
    )


async def job_runner(context: ContextTypes.DEFAULT_TYPE):
    settings: Settings = context.job.data["settings"]
    mode: str = context.job.data["mode"]
    await do_scrape_and_send(mode=mode, settings=settings)


async def send_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = Settings.load()

    if not context.args:
        await update.message.reply_text("사용법: /send <초|HH:MM>\n예: /send 10 또는 /send 12:30")
        return

    arg = context.args[0].strip()

    try:
        delay = parse_delay_arg(arg)
    except Exception:
        await update.message.reply_text("시간 형식이 올바르지 않습니다.\n예: /send 10 또는 /send 12:30")
        return

    # 예약 등록
    context.job_queue.run_once(
        callback=job_runner,
        when=delay,
        data={"settings": settings, "mode": "full"},
        name=f"send_full_{arg}",
    )

    await update.message.reply_text(f"⏳ 예약 완료: {arg} (약 {delay}초 후 전송)")


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = Settings.load()
    await update.message.reply_text("🚀 즉시 전송(텍스트+이미지) 시작...")
    await do_scrape_and_send(mode="full", settings=settings)
    await update.message.reply_text("✅ 완료")


async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = Settings.load()
    await update.message.reply_text("📝 텍스트만 전송 시작...")
    await do_scrape_and_send(mode="text", settings=settings)
    await update.message.reply_text("✅ 완료")


async def image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = Settings.load()
    await update.message.reply_text("🖼️ 이미지만 전송 시작...")
    await do_scrape_and_send(mode="image", settings=settings)
    await update.message.reply_text("✅ 완료")


def main():
    settings = Settings.load()
    app = ApplicationBuilder().token(settings.tg_bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("send", send_cmd))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("preview", preview))
    app.add_handler(CommandHandler("image", image))

    app.run_polling()


if __name__ == "__main__":
    main()
