"""
삭제할 댓글이 DOM에 어떤 구조로 렌더링되는지 확인하는 스크립트.
"""
import sys
from playwright.sync_api import sync_playwright

POST_URL = sys.argv[1] if len(sys.argv) > 1 else input("게시물 URL: ").strip()
from pathlib import Path
PROFILE_DIR = str(Path.home() / ".instagram_detector" / "browser_profile")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        PROFILE_DIR, headless=False,
        args=["--disable-blink-features=AutomationControlled"]
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(POST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # 댓글 링크 구조 확인
    links = page.evaluate("""() => {
        const links = Array.from(document.querySelectorAll('a[href*="/c/"]'));
        return links.slice(0, 5).map(a => ({
            href: a.href,
            text: a.textContent.trim().slice(0, 30),
            parentTag: a.parentElement?.tagName,
            grandTag: a.parentElement?.parentElement?.tagName,
        }));
    }""")
    print("\n[댓글 링크 구조]")
    for l in links:
        print(f"  {l}")

    # 호버했을 때 나타나는 버튼 확인
    if links:
        first_link = page.query_selector(f'a[href="{links[0]["href"]}"]')
        if first_link:
            first_link.hover()
            page.wait_for_timeout(600)
            buttons = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button, [role="button"]'))
                    .filter(b => b.offsetParent !== null)
                    .map(b => ({
                        ariaLabel: b.getAttribute('aria-label'),
                        text: b.textContent.trim().slice(0, 20),
                        tagName: b.tagName,
                    }))
                    .filter(b => b.ariaLabel || b.text);
            }""")
            print("\n[호버 후 보이는 버튼들]")
            for b in buttons[:15]:
                print(f"  {b}")

    page.wait_for_timeout(2000)
    context.close()
