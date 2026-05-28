import re
import threading
from pathlib import Path

import customtkinter as ctk

from instagram import fetch_comments
from playwright_worker import pw_run

_POST_RE = re.compile(r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)")
_USERNAME_FILE = Path.home() / ".instagram_detector" / "last_username.txt"


def _load_saved_username() -> str:
    try:
        return _USERNAME_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _save_username(username: str) -> None:
    try:
        _USERNAME_FILE.parent.mkdir(parents=True, exist_ok=True)
        _USERNAME_FILE.write_text(username, encoding="utf-8")
    except Exception:
        pass


class PostView(ctk.CTkFrame):
    def __init__(self, parent, session, page, on_post_selected):
        super().__init__(parent, fg_color="transparent")
        self._session = session
        self._page = page
        self._on_post_selected = on_post_selected
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self, text="게시물 선택",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(40, 8))

        ctk.CTkLabel(
            self, text="내 Instagram 아이디",
            text_color="gray", font=ctk.CTkFont(size=13),
        ).pack(pady=(16, 2))

        self._username_entry = ctk.CTkEntry(
            self, width=260, height=40,
            placeholder_text="예) ji__bboo",
        )
        self._username_entry.pack(pady=(0, 12))

        # 저장된 아이디 자동 채우기
        saved = _load_saved_username()
        if saved:
            self._username_entry.insert(0, saved)

        ctk.CTkButton(
            self, text="내 게시물 페이지로 이동",
            width=260, height=40, font=ctk.CTkFont(size=13),
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            border_width=1, border_color="#555",
            command=self._goto_profile,
        ).pack(pady=(0, 24))

        ctk.CTkFrame(self, height=1, fg_color="#333").pack(fill="x", padx=40, pady=(0, 20))

        self._guide = ctk.CTkLabel(
            self,
            text="위 버튼을 눌러 게시물 페이지로 이동해주세요.",
            justify="center", text_color="gray", font=ctk.CTkFont(size=13),
        )
        self._guide.pack(pady=(0, 12))

        # 선택 버튼은 이동 후에만 표시
        self._select_btn = ctk.CTkButton(
            self, text="이 게시물 선택",
            width=260, height=44, font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_select,
        )
        # pack 하지 않음 — 이동 성공 후 pack

        self._status = ctk.CTkLabel(
            self, text="", text_color="gray", font=ctk.CTkFont(size=13)
        )
        self._status.pack(pady=8)

    # ── 프로필 이동 ───────────────────────────────────────────────────────────

    def _goto_profile(self) -> None:
        username = self._username_entry.get().strip().lstrip("@")
        if not username:
            self._set_status("Instagram 아이디를 입력해주세요.", "orange")
            return
        _save_username(username)
        self._set_status("브라우저로 이동 중...")
        threading.Thread(target=self._goto_thread, args=(username,), daemon=True).start()

    def _goto_thread(self, username: str) -> None:
        try:
            url = f"https://www.instagram.com/{username}/"
            pw_run(lambda: self._page.goto(url, wait_until="domcontentloaded", timeout=30_000))
            self.after(0, lambda u=username: self._on_profile_opened(u))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"이동 오류: {e}", "red"))

    def _on_profile_opened(self, username: str) -> None:
        if not self.winfo_exists():
            return
        self._guide.configure(
            text=f"@{username} 페이지가 열렸어요.\n게시물에 들어간 후 아래 버튼을 눌러주세요.",
        )
        self._set_status("")
        self._select_btn.pack(pady=4)

    # ── 게시물 선택 버튼 ──────────────────────────────────────────────────────

    def _on_select(self) -> None:
        self._select_btn.configure(state="disabled", text="확인 중...")
        threading.Thread(target=self._read_url_thread, daemon=True).start()

    def _read_url_thread(self) -> None:
        try:
            url = pw_run(lambda: self._page.evaluate("() => window.location.href"))
            if _POST_RE.search(url):
                clean = url.split("?")[0].rstrip("/") + "/"
                self.after(0, lambda u=clean: self._show_confirm(u))
            else:
                self.after(0, self._wrong_page)
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"오류: {e}", "red"))
            self.after(0, lambda: self._select_btn.configure(state="normal", text="이 게시물 선택"))

    def _wrong_page(self) -> None:
        if not self.winfo_exists():
            return
        self._set_status("게시물 페이지가 아니에요. 게시물로 이동 후 다시 눌러주세요.", "orange")
        self._select_btn.configure(state="normal", text="이 게시물 선택")

    # ── 확인 카드 ─────────────────────────────────────────────────────────────

    def _show_confirm(self, url: str) -> None:
        if not self.winfo_exists():
            return
        self._set_status("")
        self._select_btn.pack_forget()
        # 브라우저도 해당 게시물로 이동 — 유저가 시각적으로 확인 가능
        threading.Thread(
            target=lambda: pw_run(lambda: self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)),
            daemon=True,
        ).start()

        self._confirm_card = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        self._confirm_card.pack(fill="x", padx=24, pady=4)

        ctk.CTkLabel(
            self._confirm_card, text="이 게시물이 맞나요?",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(16, 6))

        ctk.CTkLabel(
            self._confirm_card, text=url,
            text_color="#aaa", font=ctk.CTkFont(size=11),
            wraplength=380,
        ).pack(padx=16, pady=(0, 14))

        btn_row = ctk.CTkFrame(self._confirm_card, fg_color="transparent")
        btn_row.pack(pady=(0, 16))

        ctk.CTkButton(
            btn_row, text="다시 선택", width=130,
            fg_color="transparent", border_width=1, border_color="#555",
            command=self._back_to_select,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_row, text="댓글 탐지 시작 →", width=140,
            fg_color="#1a6b3c", hover_color="#145a31",
            command=lambda u=url: self._confirm(u),
        ).pack(side="left", padx=6)

    def _back_to_select(self) -> None:
        if hasattr(self, "_confirm_card"):
            self._confirm_card.destroy()
        self._select_btn.configure(state="normal", text="이 게시물 선택")
        self._select_btn.pack(pady=4)

    def _confirm(self, url: str) -> None:
        if hasattr(self, "_confirm_card"):
            self._confirm_card.destroy()
        self._set_status("댓글 수집 중...")
        threading.Thread(target=self._fetch_thread, args=(url,), daemon=True).start()

    # ── 댓글 수집 ─────────────────────────────────────────────────────────────

    def _fetch_thread(self, url: str) -> None:
        try:
            comments = pw_run(lambda: fetch_comments(self._session, url, on_progress=self._set_status))
            self.after(0, lambda: self._on_post_selected(url, comments))
        except Exception as e:
            import traceback; traceback.print_exc()
            self.after(0, lambda e=e: self._on_error(str(e)))

    def _on_error(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self._set_status(f"오류: {msg}", "red")

    def _set_status(self, msg: str, color: str = "gray") -> None:
        def _do():
            if self.winfo_exists():
                self._status.configure(text=msg, text_color=color)
        self.after(0, _do)
