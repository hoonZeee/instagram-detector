from playwright.sync_api import sync_playwright, BrowserContext, Page

# 보안상 로그인 세션을 디스크에 저장하지 않는다.
# 브라우저 컨텍스트는 메모리에만 유지되며, 앱을 종료하면 세션은 사라진다.

_playwright = None
_browser = None
_context: BrowserContext | None = None
_page = None


def _has_valid_session(context) -> bool:
    """Returns True if the context has a live Instagram session (sessionid cookie present)."""
    cookies = context.cookies(["https://www.instagram.com"])
    return any(c["name"] == "sessionid" and c["value"] for c in cookies)


PENDING_PATTERNS = (
    "accounts/login",
    "accounts/onetap",
    "challenge",
    "emails/confirm",
    "two_factor",
    "checkpoint",
    "auth_platform",
)


def open_instagram_login(on_waiting=None) -> tuple[BrowserContext, Page] | tuple[None, None]:
    """
    Opens Instagram in a fresh in-memory browser context.
    Keeps the browser page open after login and returns (context, page).
    Nothing is written to disk — credentials and session cookies live in memory only.
    """
    global _playwright, _browser, _context, _page

    _playwright = sync_playwright().start()

    _browser = _playwright.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    _context = _browser.new_context(viewport={"width": 430, "height": 820})

    page = _context.new_page()

    # 디스크 세션이 없으므로 항상 로그인부터 시작한다.
    page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=30_000)
    if on_waiting:
        on_waiting("브라우저에서 로그인해주세요...")

    try:
        prev_url = ""
        for _ in range(300):  # wait up to 5 minutes
            url = page.url
            if url != prev_url:
                prev_url = url
                if any(p in url for p in ("challenge", "emails/confirm", "two_factor", "checkpoint", "auth_platform")):
                    if on_waiting:
                        on_waiting("인증 절차를 완료해주세요 (이메일/SMS 확인)...")
                else:
                    if on_waiting:
                        on_waiting("브라우저에서 로그인해주세요...")

            if not any(p in url for p in PENDING_PATTERNS) and _has_valid_session(_context):
                break
            page.wait_for_timeout(1000)
        else:
            return None, None

        if on_waiting:
            on_waiting("로그인 완료! 브라우저가 열린 상태로 유지됩니다.")
        _page = page
        return _context, page

    except Exception:
        return None, None


def close_session() -> None:
    global _playwright, _browser, _context, _page
    try:
        if _page:
            _page.close()
        if _context:
            _context.close()
        if _browser:
            _browser.close()
        if _playwright:
            _playwright.stop()
    finally:
        _page = None
        _context = None
        _browser = None
        _playwright = None
