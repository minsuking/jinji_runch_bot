from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

import requests
from playwright.async_api import async_playwright, Page


TODAY_LIKE_PATTERNS = [
    r"방금",
    r"\d+\s*분\s*전",
    r"\d+\s*시간\s*전",
    r"오늘",
]


def _is_today_like(date_text: str) -> bool:
    t = (date_text or "").strip()
    if not t:
        return False
    for p in TODAY_LIKE_PATTERNS:
        if re.search(p, t):
            return True
    # 가끔 "2026.01.13."처럼 절대 날짜로 나올 수 있음 -> 오늘 판정은 runner에서 확장 가능
    return False


def _extract_bg_image_urls_from_style(style_value: str) -> List[str]:
    """
    style="background-image: url("...")" 에서 url(...) 추출
    """
    if not style_value:
        return []
    urls = []
    # url("...") or url('...') or url(...)
    for m in re.finditer(r"url\((['\"]?)(.*?)\1\)", style_value):
        u = (m.group(2) or "").strip()
        if u:
            urls.append(u)
    return urls


async def _pick_today_post_link(page: Page, base_url: str) -> Optional[str]:
    """
    목록 페이지에서 '오늘'로 보이는 첫 카드의 링크를 선택.
    (프로필/댓글/다른소식 같은 카드들은 제외)
    """
    await page.wait_for_selector(".wrap_webview .area_card", timeout=15000)

    cards = page.locator(".wrap_webview .area_card")
    count = await cards.count()

    for i in range(count):
        card = cards.nth(i)

        # 포스트 카드에는 보통 a.link_title 또는 a.link_board 가 있음
        link = card.locator("a.link_title")
        if await link.count() == 0:
            link = card.locator("a.link_board")
        if await link.count() == 0:
            continue

        # 날짜 텍스트가 있는 카드만
        date_loc = card.locator(".item_date .txt_date")
        if await date_loc.count() == 0:
            continue

        date_text = (await date_loc.first.inner_text()).strip()

        # 오늘로 보이는 것만
        if not _is_today_like(date_text):
            continue

        href = await link.first.get_attribute("href")
        if not href:
            continue

        return urljoin(base_url, href)

    return None


async def _extract_detail_only(page: Page) -> Dict:
    """
    상세 페이지에서 .area_card.type_archive_detail 내부만 파싱
    """
    await page.wait_for_selector(".area_card.type_archive_detail", timeout=15000)
    detail = page.locator(".area_card.type_archive_detail").first

    # title
    title = ""
    title_loc = detail.locator(".wrap_archive_txt .tit_card")
    if await title_loc.count() > 0:
        title = (await title_loc.first.inner_text()).strip()

    # body text (있으면)
    text = ""
    desc_loc = detail.locator(".wrap_archive_txt .desc_card")
    if await desc_loc.count() > 0:
        text = (await desc_loc.first.inner_text()).strip()

    # images: img src + background-image url(...)
    image_urls: List[str] = []

    img_loc = detail.locator("img")
    img_count = await img_loc.count()
    for i in range(img_count):
        src = await img_loc.nth(i).get_attribute("src")
        if src:
            image_urls.append(src.strip())

    styled = detail.locator("[style*='background-image']")
    styled_count = await styled.count()
    for i in range(styled_count):
        style_val = await styled.nth(i).get_attribute("style")
        if style_val:
            image_urls.extend(_extract_bg_image_urls_from_style(style_val))

    # 정리: 중복 제거
    dedup = []
    seen = set()
    for u in image_urls:
        u = u.strip()
        if not u or u in seen:
            continue
        seen.add(u)
        dedup.append(u)

    return {
        "title": title,
        "text": text,
        "image_urls": dedup,
    }


def _download_images(image_urls: List[str], download_dir: str) -> List[str]:
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    saved_paths: List[str] = []

    for idx, url in enumerate(image_urls, start=1):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()

            # 확장자 추정
            ext = ".jpg"
            ct = (r.headers.get("content-type") or "").lower()
            if "png" in ct:
                ext = ".png"
            elif "webp" in ct:
                ext = ".webp"

            out = Path(download_dir) / f"img_{idx:02d}{ext}"
            out.write_bytes(r.content)
            saved_paths.append(str(out))
        except Exception:
            # 실패해도 다음 이미지 계속
            continue

    return saved_paths


async def scrape_today_post(
    posts_url: str,
    download_dir: str = "downloads",
    headless: bool = True,
) -> Dict:
    """
    반환 예:
    {
      "url": "https://pf.kakao.com/_sIJCxj/112111714",
      "title": "...",
      "text": "...",
      "image_urls": [...],
      "downloaded": ["downloads/img_01.jpg", ...]
    }
    """
    base_url = "https://pf.kakao.com"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
                headless=headless,
                channel="chrome",  # ✅ 로컬에 설치된 Google Chrome 사용
                args=["--disable-dev-shm-usage"]
            )

        context = await browser.new_context(
            locale="ko-KR",
            ignore_https_errors=True,  # 기업망/인증서 꼬임에 조금 더 강함
        )
        page = await context.new_page()

        await page.goto(posts_url, wait_until="domcontentloaded", timeout=45000)

        # 목록에서 오늘 링크 1개 고르기
        best_link, reason = await pick_best_post_link(page, base_url=base_url)
        if not best_link:
            await browser.close()
            raise RuntimeError("포스트 링크를 하나도 찾지 못했습니다. (로그인/차단/DOM 변경 가능)")

        print(f"[INFO] Selected post ({reason}): {best_link}")
        # 상세 페이지 이동
        await page.goto(best_link, wait_until="domcontentloaded", timeout=45000)

        detail_data = await _extract_detail_only(page)
        img_urls = detail_data.get("image_urls", [])
        downloaded = _download_images(img_urls, download_dir=download_dir)

        await browser.close()

        return {
            "url": best_link,
            "title": detail_data.get("title", ""),
            "text": detail_data.get("text", ""),
            "image_urls": img_urls,
            "downloaded": downloaded,
        }

def _is_today_label(text: str) -> bool:
    """카카오 채널 소식 목록의 날짜 라벨이 '오늘'인지 판정"""
    t = (text or "").strip()
    # 예: "5분 전", "2시간 전", "방금"
    if "분 전" in t or "시간 전" in t or t in ("방금",):
        return True

    # 예: "2026.01.02."
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\.", t)
    if m:
        y, mo, d = map(int, m.groups())
        now = datetime.now(KST)
        return (y, mo, d) == (now.year, now.month, now.day)

    # 예: "3일 전" 같은 건 오늘 아님
    return False

async def pick_best_post_link(page: Page, base_url: str) -> tuple[Optional[str], str]:
    """
    우선순위:
      1) 오늘로 보이는 포스트
      2) 고정됨
      3) 첫 번째(최신) 포스트
    반환: (absolute_url, reason)
    """
    await page.wait_for_selector(".wrap_webview .area_card", timeout=15000)

    cards = page.locator(".wrap_webview .area_card")
    n = await cards.count()

    candidates_today: List[str] = []
    candidates_pinned: List[str] = []
    candidates_any: List[str] = []

    for i in range(n):
        card = cards.nth(i)

        # 링크 찾기: link_title 우선, 없으면 link_board
        link = card.locator("a.link_title")
        if await link.count() == 0:
            link = card.locator("a.link_board")
        if await link.count() == 0:
            continue

        href = await link.first.get_attribute("href")
        if not href:
            continue

        # 절대 URL로 변환
        abs_url = urljoin(base_url, href)

        # 날짜 텍스트
        date_text = ""
        date_loc = card.locator(".wrap_bottom_util .item_date .txt_date")
        if await date_loc.count() > 0:
            date_text = (await date_loc.first.inner_text()).strip()

        # 고정 여부
        pinned = False
        pin_loc = card.locator(".wrap_bottom_util .item_date .icon_pin")
        if await pin_loc.count() > 0:
            pin_text = (await pin_loc.first.inner_text()).strip()
            if "고정" in pin_text:
                pinned = True

        candidates_any.append(abs_url)

        if _is_today_label(date_text):
            candidates_today.append(abs_url)

        if pinned:
            candidates_pinned.append(abs_url)

    if candidates_today:
        return candidates_today[0], "today"
    if candidates_pinned:
        return candidates_pinned[0], "pinned"
    if candidates_any:
        return candidates_any[0], "latest"

    return None, "none"
