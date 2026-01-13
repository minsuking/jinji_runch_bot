import argparse
import asyncio
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright


BASE = "https://pf.kakao.com"


def sanitize_filename(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120] if len(s) > 120 else s


def parse_bg_image(style: str) -> str | None:
    # style="background-image: url("https://.../img_xl.jpg");"
    if not style:
        return None
    m = re.search(r'background-image:\s*url\(["\']?(.*?)["\']?\)', style)
    return m.group(1) if m else None


def guess_ext(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    ext = ext.lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "jpg" if ext == "jpeg" else ext
    return "jpg"


def is_today(date_text: str, seoul_today: datetime) -> bool:
    t = (date_text or "").strip()

    # 상대시간: 오늘로 간주
    if any(x in t for x in ["방금", "분 전", "시간 전", "오늘"]):
        return True

    # "3일 전"은 오늘 아님
    if "일 전" in t:
        return False

    # 절대 날짜: 2026.01.02. 같은 형태
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\.", t)
    if m:
        y, mo, d = map(int, m.groups())
        return (y, mo, d) == (seoul_today.year, seoul_today.month, seoul_today.day)

    return False


async def download_file(request_ctx, url: str, path: str) -> bool:
    try:
        r = await request_ctx.get(url)
        if not r.ok:
            return False
        data = await r.body()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


async def extract_detail(page) -> tuple[str, list[str]]:
    """
    상세 페이지에서 'area_card type_archive_detail'만 본문으로 간주하고:
    - 제목(tit_card)
    - 본문 텍스트(있으면)
    - 이미지(img/src + background-image)
    만 수집한다.
    """
    await page.wait_for_selector("div.area_card.type_archive_detail", timeout=10000)

    detail = page.locator("div.area_card.type_archive_detail").first

    # ✅ 1) 제목
    title = ""
    try:
        title = (await detail.locator(".tit_card").first.inner_text()).strip()
    except Exception:
        pass

    # ✅ 2) 본문 텍스트 (메뉴 글 같은 건 desc_card가 있을 수도, 없을 수도)
    body = ""
    for sel in [".desc_card", ".wrap_archive_txt", ".wrap_archive_content"]:
        try:
            t = (await detail.locator(sel).first.inner_text(timeout=2000)).strip()
            # 제목이랑 중복되는 텍스트는 제거
            if t:
                body = t
                break
        except Exception:
            pass

    # body에서 title 중복 제거 (예: wrap_archive_txt에 제목만 있는 케이스)
    if title and body == title:
        body = ""

    # 최종 본문: title + body (원하면 title은 따로 출력해도 됨)
    content = (title + ("\n" + body if body else "")).strip()

    # ✅ 3) 이미지 URL 수집: detail 영역 내부만!
    img_urls = set()

    # 3-1) <img>
    imgs = detail.locator("img")
    n = await imgs.count()
    for i in range(min(n, 50)):
        img = imgs.nth(i)
        for attr in ["src", "data-src"]:
            v = await img.get_attribute(attr)
            if not v:
                continue
            if v.startswith("//"):
                v = "https:" + v
            if v.startswith("http://"):
                # https로 바꾸고 싶으면 아래 한 줄 활성화
                # v = v.replace("http://", "https://", 1)
                pass
            img_urls.add(v)

    # 3-2) background-image (detail 내부만)
    bg_candidates = detail.locator("[style*='background-image']")
    m = await bg_candidates.count()
    for i in range(min(m, 100)):
        el = bg_candidates.nth(i)
        style = await el.get_attribute("style") or ""
        u = parse_bg_image(style)
        if not u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        img_urls.add(u)

    return content, sorted(img_urls)



async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://pf.kakao.com/_sIJCxj/posts")
    parser.add_argument("--out", default="kakao_posts_today")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-scroll", type=int, default=10)
    parser.add_argument("--max-today", type=int, default=5, help="오늘 글 최대 몇 개까지 처리할지")
    args = parser.parse_args()

    seoul_now = datetime.now(ZoneInfo("Asia/Seoul"))
    os.makedirs(args.out, exist_ok=True)

    async with async_playwright() as p:
        # ✅ Playwright 브라우저 설치가 막힌 환경 대비: 로컬 Chrome 사용
        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        chrome_path = next((x for x in chrome_candidates if os.path.exists(x)), None)

        launch_kwargs = {"headless": args.headless}
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path

        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"[INFO] Open: {args.url}")
        await page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1200)

        # 스크롤로 더 로딩
        for _ in range(args.max_scroll):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(650)

        cards = page.locator("div.area_card")
        n = await cards.count()
        print(f"[INFO] cards found: {n}")

        today_items = []
        for i in range(n):
            card = cards.nth(i)

            # 제목
            if not await card.locator("a.link_title strong.tit_card").count():
                continue
            title = (await card.locator("a.link_title strong.tit_card").first.inner_text()).strip()
            if not title:
                continue

            # 날짜
            date_text = ""
            if await card.locator(".wrap_bottom_util .item_date .txt_date").count():
                date_text = (await card.locator(".wrap_bottom_util .item_date .txt_date").first.inner_text()).strip()

            if not is_today(date_text, seoul_now):
                continue

            # 링크
            href = await card.locator("a.link_title").first.get_attribute("href") or ""
            link = urljoin(BASE, href)

            today_items.append({"title": title, "date_text": date_text, "link": link})
            if len(today_items) >= args.max_today:
                break

        if not today_items:
            print("[ERROR] 오늘 카드가 0개입니다. (날짜 표기/스크롤 범위 확인)")
            await browser.close()
            return

        print(f"[INFO] today cards: {len(today_items)}")

        # ✅ 상세 페이지 방문해서 본문/이미지 추출
        for idx, item in enumerate(today_items, start=1):
            title = item["title"]
            date_text = item["date_text"]
            link = item["link"]

            safe = sanitize_filename(title)
            post_dir = os.path.join(args.out, f"{idx:02d}_{safe}")
            img_dir = os.path.join(post_dir, "images")
            os.makedirs(img_dir, exist_ok=True)

            print("\n" + "=" * 80)
            print(f"[POST] {title}")
            print(f"[DATE] {date_text}")
            print(f"[LINK] {link}")

            # 상세로 이동
            # target=_blank여도 우리는 직접 goto로 들어가면 됨
            await page.goto(link, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1000)

            content, img_urls = await extract_detail(page)

            # 저장 + 출력 일부
            with open(os.path.join(post_dir, "content.txt"), "w", encoding="utf-8") as f:
                f.write(f"{title}\n{date_text}\n{link}\n\n{content}\n")

            print("-" * 80)
            print(content[:1400] + ("..." if len(content) > 1400 else ""))
            print(f"[IMAGES] found: {len(img_urls)}")

            # 이미지 다운로드
            for k, u in enumerate(img_urls, start=1):
                ext = guess_ext(u)
                save_path = os.path.join(img_dir, f"{k:02d}.{ext}")
                ok = await download_file(context.request, u, save_path)
                print(f"  - {'DOWNLOADED' if ok else 'FAILED'}: {u}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
