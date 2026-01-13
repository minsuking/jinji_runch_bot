# Jinji-lunch-bot

카카오톡 채널 포스트(오늘 게시물 1건)를 Playwright로 긁어서 텔레그램으로 전송합니다.

## 기능
- /menu: 즉시 전송(텍스트+이미지)
- /preview: 텍스트만
- /image: 이미지만
- /send 12:30: KST 기준 해당 시각에 전송(지났으면 내일)

또는 GitHub Actions로 매일 11:30(KST) 자동 전송 가능.

---

## 1) 로컬 준비(Windows)
### 1-1. 가상환경
```bash
python -m venv .venv
.venv\Scripts\activate
