from __future__ import annotations

from pathlib import Path
from typing import List, Optional
import requests


class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base = f"https://api.telegram.org/bot{bot_token}"

    def send_text(self, text: str) -> None:
        r = requests.post(
            f"{self.base}/sendMessage",
            data={"chat_id": self.chat_id, "text": text},
            timeout=30,
        )
        r.raise_for_status()

    def send_photo(self, image_path: str, caption: Optional[str] = None) -> None:
        p = Path(image_path)
        with p.open("rb") as f:
            data = {"chat_id": self.chat_id}
            if caption:
                data["caption"] = caption
            r = requests.post(
                f"{self.base}/sendPhoto",
                data=data,
                files={"photo": f},
                timeout=60,
            )
        r.raise_for_status()

    def send_media_group(self, image_paths: List[str]) -> None:
        """
        Telegram media group: 최대 10장씩 전송
        """
        if not image_paths:
            return

        chunk = image_paths[:10]
        files = {}
        media = []

        for idx, path in enumerate(chunk):
            key = f"file{idx}"
            files[key] = open(path, "rb")
            media.append({"type": "photo", "media": f"attach://{key}"})

        try:
            r = requests.post(
                f"{self.base}/sendMediaGroup",
                data={"chat_id": self.chat_id, "media": str(media).replace("'", '"')},
                files=files,
                timeout=120,
            )
            r.raise_for_status()
        finally:
            for f in files.values():
                try:
                    f.close()
                except Exception:
                    pass
