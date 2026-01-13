from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    tg_bot_token: str
    tg_chat_id: str
    kakao_posts_url: str
    headless: bool

    @staticmethod
    def load() -> "Settings":
        token = os.getenv("TG_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TG_CHAT_ID", "").strip()
        url = os.getenv("KAKAO_POSTS_URL", "https://pf.kakao.com/_sIJCxj/posts").strip()
        headless = os.getenv("HEADLESS", "true").lower() == "true"

        if not token:
            raise RuntimeError("TG_BOT_TOKEN is empty")
        if not chat_id:
            raise RuntimeError("TG_CHAT_ID is empty")

        return Settings(
            tg_bot_token=token,
            tg_chat_id=chat_id,
            kakao_posts_url=url,
            headless=headless,
        )
