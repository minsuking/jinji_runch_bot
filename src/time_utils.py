from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

KST = ZoneInfo("Asia/Seoul")


def parse_delay_arg(arg: str) -> int:
    """
    지원:
    - "10"       -> 10초 후
    - "12:30"    -> 다음 12:30(KST)까지 초 계산 (이미 지났으면 내일)
    """
    arg = arg.strip()

    if re.fullmatch(r"\d+", arg):
        return int(arg)

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", arg)
    if not m:
        raise ValueError("Invalid arg")

    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("Invalid time")

    now = datetime.now(KST)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    return int((target - now).total_seconds())
