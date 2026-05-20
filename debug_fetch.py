"""
댓글 수집 시 Instagram이 실제로 호출하는 API URL 확인용 디버그 스크립트.

사용법:
  python3 debug_fetch.py <게시물URL>

예시:
  python3 debug_fetch.py https://www.instagram.com/p/ABC123/
"""
import sys
from playwright.sync_api import sync_playwright

if len(sys.argv) < 2:
    print("사용법: python3 debug_fetch.py <게시물URL>")
    sys.exit(1)

POST_URL = sys.argv[1]
print(f"대상 게시물: {POST_URL}\n")

PENDING = (
    "accounts/login", "accounts/onetap", "challenge",
    "emails/confirm", "two_factor", "checkpoint", "auth_platform",
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(viewport={"width": 430, "height": 820})
    page = context.new_page()

    page.goto("https://www.instagram.com/accounts/login/")
    print("브라우저에서 로그인해주세요. 자동으로 감지합니다...")

    # 로그인 완료 자동 감지 — 모든 인증 단계(이메일, auth_platform 등) 완료까지 대기
    prev_url = ""
    for _ in range(300):
        url = page.url
        if url != prev_url:
            print(f"  URL 변경: {url[:80]}")
            prev_url = url
        if not any(p in url for p in PENDING):
            break
        page.wait_for_timeout(1000)

    print(f"\n로그인 완료! 현재 URL: {page.url}\n")
    print(f"게시물로 이동 중: {POST_URL}\n")

    api_calls = []

    def handle(response):
        url = response.url
        if "instagram.com/api/graphql" not in url:
            return
        try:
            body = response.json()
            body_str = str(body)
            has_comments = any(k in body_str for k in ["comments", "edge_media_to_comment"])
            preview = body_str[:300].replace("\n", " ")
            print(f"  [{response.status}] {'[댓글있음!!]' if has_comments else '[       ]'} {preview}")
            api_calls.append((url, response.status, has_comments, body_str[:500]))
        except Exception:
            print(f"  [{response.status}] [non-json] {url[:100]}")

    page.on("response", handle)
    page.goto(POST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    print("\n--- 더보기 버튼 탐색 ---")
    for label in ["댓글 더 보기", "Load more comments", "View more comments"]:
        btn = page.query_selector(f"[aria-label='{label}']")
        if btn:
            print(f"버튼 발견: {label}")
            btn.click()
            page.wait_for_timeout(2000)
            break
    else:
        print("더보기 버튼 없음")

    print(f"\n총 캡처된 GraphQL 호출 수: {len(api_calls)}")

    # ── 직접 API 호출 테스트 ──────────────────────────────────────────
    print("\n--- 직접 API 호출 테스트 ---")
    cookies = context.cookies()
    csrf = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    print(f"csrf 토큰 있음: {'YES' if csrf else 'NO'}")

    # 1) 페이지 내 inline JSON에서 media_id 추출
    media_id = page.evaluate("""() => {
        for (const s of document.querySelectorAll('script[type="application/json"]')) {
            try {
                const d = JSON.parse(s.textContent);
                const str = JSON.stringify(d);
                const m = str.match(/"pk":"(\\d+)"/);
                if (m) return m[1];
            } catch {}
        }
        // __NEXT_DATA__ fallback
        const nd = document.getElementById('__NEXT_DATA__');
        if (nd) {
            const m = nd.textContent.match(/"pk":"(\\d+)"/);
            if (m) return m[1];
        }
        return null;
    }""")
    print(f"media_id: {media_id}")

    if media_id:
        # 2) api/v1/media/{id}/comments/ 직접 fetch
        result = page.evaluate("""async ([mediaId, csrf]) => {
            const res = await fetch(
                `https://www.instagram.com/api/v1/media/${mediaId}/comments/?can_support_threading=true&permalink_enabled=false`,
                {
                    headers: {
                        'x-ig-app-id': '936619743392459',
                        'x-csrftoken': csrf,
                        'x-requested-with': 'XMLHttpRequest',
                    },
                    credentials: 'include',
                }
            );
            const text = await res.text();
            return {status: res.status, body: text.slice(0, 800)};
        }""", [media_id, csrf])
        print(f"\napi/v1 댓글 직접 호출 결과:")
        print(f"  status: {result['status']}")
        print(f"  body: {result['body']}")

    page.wait_for_timeout(1000)
    browser.close()
