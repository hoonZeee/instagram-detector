import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext

# Session is persisted here — same security model as keeping Instagram logged in Chrome
_PROFILE_DIR = Path.home() / ".instagram_detector" / "browser_profile"

_playwright = None
_browser = None
_context: BrowserContext | None = None

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


def open_instagram_login(on_waiting=None) -> BrowserContext | None:
    """
    Opens Instagram in a persistent browser profile.
    If already logged in, returns the session immediately without showing login UI.
    Credentials are never read by this app — only browser cookies are used.
    """
    global _playwright, _context

    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    _playwright = sync_playwright().start()

    _context = _playwright.chromium.launch_persistent_context(
        str(_PROFILE_DIR),
        headless=False,
        viewport={"width": 430, "height": 820},
        args=["--disable-blink-features=AutomationControlled"],
    )

    page = _context.pages[0] if _context.pages else _context.new_page()

    # Check if already logged in via sessionid cookie (URL-based check is unreliable
    # since Instagram shows the same URL for logged-in and logged-out users)
    if on_waiting:
        on_waiting("기존 세션 확인 중...")

    page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(1500)

    if _has_valid_session(_context):
        if on_waiting:
            on_waiting("세션 복원 완료! 다시 로그인할 필요가 없어요.")
        page.close()
        return _context

    # Need to log in
    page.goto("https://www.instagram.com/accounts/login/")
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

            # Not on auth page AND sessionid cookie is present → truly logged in
            if not any(p in url for p in PENDING_PATTERNS) and _has_valid_session(_context):
                break
            page.wait_for_timeout(1000)
        else:
            return None

        if on_waiting:
            on_waiting("로그인 완료! 세션이 저장됩니다.")
        page.close()
        return _context

    except Exception:
        return None


def close_session() -> None:
    global _playwright, _context
    try:
        if _context:
            _context.close()
        if _playwright:
            _playwright.stop()
    finally:
        _context = None
        _playwright = None


def clear_profile() -> None:
    """
    저장된 브라우저 프로필(세션 쿠키 포함)을 완전히 삭제한다.
    다음 로그인 시 새 계정으로 처음부터 시작할 수 있다.
    """
    close_session()
    if _PROFILE_DIR.exists():
        shutil.rmtree(_PROFILE_DIR)
