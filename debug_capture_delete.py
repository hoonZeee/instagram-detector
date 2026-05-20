"""
직접 댓글을 삭제할 때 Instagram이 보내는 API 요청을 캡처하는 스크립트.
실행 후 브라우저에서 댓글 하나를 직접 삭제하면 URL/method/body/headers가 출력됨.
"""
import sys
import json
from playwright.sync_api import sync_playwright
from pathlib import Path

POST_URL = sys.argv[1] if len(sys.argv) > 1 else input("게시물 URL: ").strip()
PROFILE_DIR = str(Path.home() / ".instagram_detector" / "browser_profile")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else context.new_page()

    def on_request(request):
        if "/api/v1/" in request.url:
            print(f"\n{'='*60}")
            print(f"METHOD : {request.method}")
            print(f"URL    : {request.url}")
            headers = dict(request.headers)
            interesting = {k: v for k, v in headers.items() if k.startswith("x-") or k in ("content-type", "referer")}
            print(f"HEADERS: {json.dumps(interesting, indent=2)}")
            body = request.post_data
            if body:
                print(f"BODY   : {body!r}")

    page.on("request", on_request)

    page.goto(POST_URL, wait_until="domcontentloaded")
    print("\n브라우저에서 댓글 하나를 직접 삭제해주세요. (60초 대기)")
    print("삭제 버튼 누르면 터미널에 API 요청 정보가 출력됩니다.\n")
    page.wait_for_timeout(60_000)
    context.close()
