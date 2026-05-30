import re
import json
from playwright.sync_api import BrowserContext


def _shortcode_to_media_id(shortcode: str) -> str | None:
    """Convert Instagram shortcode to numeric media ID."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    n = 0
    for char in shortcode:
        if char not in alphabet:
            return None
        n = n * 64 + alphabet.index(char)
    return str(n)


def _extract_shortcode(post_url: str) -> str:
    m = re.search(r"/p/([A-Za-z0-9_-]+)", post_url)
    if not m:
        raise ValueError("올바른 Instagram 게시물 URL이 아닙니다.")
    return m.group(1)


def _get_csrf(context: BrowserContext) -> str:
    cookies = context.cookies()
    return next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")


def fetch_comments(context: BrowserContext, post_url: str, on_progress=None) -> list[dict]:
    """
    Fetches all comments for the given post using Instagram's private API
    called from within the authenticated browser context.
    """
    page = context.new_page()

    try:
        page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2000)

        csrf = _get_csrf(context)
        media_id = _get_media_id(page)
        if not media_id:
            # Fallback: extract from page URL after possible redirect
            import re as _re
            m = _re.search(r"/p/([A-Za-z0-9_-]+)", page.url)
            if m:
                media_id = _shortcode_to_media_id(m.group(1))
            if not media_id:
                raise RuntimeError(f"게시물 ID를 가져올 수 없어요. 현재 URL: {page.url}")

        comments: list[dict] = []
        collected_ids: set[str] = set()
        cursor: str | None = None

        for _ in range(50):  # 안전 상한: 댓글 50페이지(수천 개) 초과 방지
            url = (
                f"https://www.instagram.com/api/v1/media/{media_id}/comments/"
                f"?can_support_threading=true&permalink_enabled=false"
            )
            if cursor:
                url += f"&min_id={cursor}"

            result = page.evaluate(
                """async ([url, csrf]) => {
                    const res = await fetch(url, {
                        headers: {
                            'x-ig-app-id': '936619743392459',
                            'x-csrftoken': csrf,
                            'x-requested-with': 'XMLHttpRequest',
                        },
                        credentials: 'include',
                    });
                    return {status: res.status, body: await res.text()};
                }""",
                [url, csrf]
            )

            if result["status"] != 200:
                raise RuntimeError(f"댓글 API 오류 (status {result['status']}): {result['body'][:200]}")

            body = result["body"].strip()
            if not body:
                raise RuntimeError("댓글 API가 빈 응답을 반환했어요. 세션이 만료됐을 수 있어요.")
            if body.startswith("<!"):
                raise RuntimeError("댓글 API가 HTML을 반환했어요. media_id가 잘못됐거나 세션이 만료됐을 수 있어요.")

            data = json.loads(body)
            page_comments = data.get("comments", [])

            before = len(collected_ids)
            for c in page_comments:
                cid = str(c.get("pk") or c.get("id") or "")
                if cid and cid not in collected_ids:
                    collected_ids.add(cid)
                    comments.append({
                        "id": cid,
                        "username": c.get("user", {}).get("username", ""),
                        "text": c.get("text", ""),
                        "timestamp": c.get("created_at", 0),
                    })

            if on_progress:
                on_progress(f"댓글 {len(comments)}개 수집 중...")

            # next_min_id 가 있으면 has_more_comments 값과 무관하게 계속 가져옴
            # (Instagram 이 has_more_comments 를 가끔 잘못 내려보내는 경우 대비)
            next_cursor = data.get("next_min_id")
            new_count = len(collected_ids) - before
            if next_cursor and new_count > 0:
                cursor = next_cursor
            else:
                break

    finally:
        page.close()

    if on_progress:
        on_progress(f"수집 완료: {len(comments)}개")

    return comments


def delete_comments(context: BrowserContext, post_url: str, comment_ids: list[str], on_progress=None) -> int:
    """
    Deletes comments via Instagram's private API.
    Uses Playwright's network-level request event to capture the exact headers
    Instagram's own JS sends (including x-ig-www-claim), then reuses them for DELETE.
    """
    page = context.new_page()
    deleted = 0
    captured: dict = {}

    def _on_request(request):
        if "/api/v1/" in request.url:
            captured.update(request.headers)

    page.on("request", _on_request)

    try:
        page.bring_to_front()
        page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3000)  # let Instagram's JS fire its initial API calls

        csrf = _get_csrf(context)
        media_id = _get_media_id(page)
        if not media_id:
            m = re.search(r"/p/([A-Za-z0-9_-]+)", page.url)
            if m:
                media_id = _shortcode_to_media_id(m.group(1))
        if not media_id:
            raise RuntimeError(f"게시물 ID를 가져올 수 없어요. 현재 URL: {page.url}")

        if on_progress:
            on_progress(f"{len(comment_ids)}개 댓글 삭제 중...")

        results = _bulk_delete(page, media_id, comment_ids, csrf, captured)
        for r in results:
            if r["ok"]:
                deleted += 1

    finally:
        page.close()

    return deleted


def _bulk_delete(page, media_id: str, comment_ids: list[str], csrf: str, captured: dict) -> list[dict]:
    """Promise.all로 모든 댓글을 동시에 삭제한다."""
    headers = {
        "x-ig-app-id": "936619743392459",
        "x-csrftoken": csrf,
        "x-requested-with": "XMLHttpRequest",
        "content-type": "application/x-www-form-urlencoded",
    }
    headers.update({k: v for k, v in captured.items() if k and v})

    return page.evaluate(
        """async ([media_id, comment_ids, headers]) => {
            const del = async (cid) => {
                try {
                    const res = await fetch(
                        `https://www.instagram.com/api/v1/web/comments/${media_id}/delete/${cid}/`,
                        {method: 'POST', headers, body: '', credentials: 'include'}
                    );
                    const text = await res.text();
                    return {cid, ok: res.status === 200 && !text.trimStart().startsWith('<')};
                } catch(e) {
                    return {cid, ok: false};
                }
            };
            return await Promise.all(comment_ids.map(del));
        }""",
        [media_id, comment_ids, headers]
    )
    return result["status"] == 200 and not result["html"]


def _get_media_id(page) -> str | None:
    """
    Extracts the post's numeric media ID from the page.
    Media IDs are 15+ digit numbers. User IDs are shorter, so we filter by length.
    """
    try:
        return page.evaluate("""() => {
            const sources = [
                ...document.querySelectorAll('script[type="application/json"]'),
                document.getElementById('__NEXT_DATA__'),
            ].filter(Boolean);

            for (const s of sources) {
                const text = s.textContent || '';

                // "media_id" key specifically refers to the post pk in comment/caption objects
                const m1 = text.match(/"media_id":"(\\d{15,})"/);
                if (m1) return m1[1];

                // "items":[{"pk":"..." — first item in feed response is the post
                const m2 = text.match(/"items":\\s*\\[\\s*\\{[^}]*"pk"\\s*:\\s*"(\\d{15,})"/);
                if (m2) return m2[1];

                // Any pk with 15+ digits (media IDs), skipping short user IDs
                const all = [...text.matchAll(/"pk"\\s*:\\s*"(\\d{15,})"/g)];
                if (all.length > 0) return all[0][1];
            }
            return null;
        }""")
    except Exception:
        return None
