import re
import threading

import customtkinter as ctk

from instagram import fetch_comments
from playwright_worker import pw_run

_POST_RE = re.compile(r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)")


class PostView(ctk.CTkFrame):
    def __init__(self, parent, session, page, on_post_selected):
        super().__init__(parent, fg_color="transparent")
        self._session = session
        self._page = page
        self._on_post_selected = on_post_selected
        self._confirmed_url: str | None = None
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self, text="게시물 선택",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(44, 4))

        ctk.CTkLabel(
            self,
            text="인스타 아이디를 입력하고 내 게시물 페이지로 이동한 뒤\n게시물을 클릭하고 아래 버튼을 눌러주세요.",
            text_color="gray", justify="center",
        ).pack(pady=(0, 24))

        # 아이디 입력
        id_row = ctk.CTkFrame(self, fg_color="transparent")
        id_row.pack(pady=4)
        ctk.CTkLabel(id_row, text="인스타 아이디", width=100, anchor="e").pack(side="left", padx=(0, 8))
        self._username_entry = ctk.CTkEntry(id_row, width=260, height=38, placeholder_text="예: ji__bboo")
        self._username_entry.pack(side="left")

        # 프로필 이동 버튼
        self._goto_btn = ctk.CTkButton(
            self, text="내 게시물 페이지로 이동",
            width=300, height=44, font=ctk.CTkFont(size=14),
            command=self._on_goto_profile,
        )
        self._goto_btn.pack(pady=(16, 4))

        self._status = ctk.CTkLabel(self, text="", text_color="gray", font=ctk.CTkFont(size=13))
        self._status.pack(pady=6)

        # 확인 카드 (처음엔 숨김)
        self._confirm_frame = ctk.CTkFrame(self, fg_color="#1e1e2e", corner_radius=12)
        self._url_label = ctk.CTkLabel(
            self._confirm_frame, text="", text_color="#7eb8f7",
            font=ctk.CTkFont(size=12), wraplength=440, justify="center",
        )
        self._url_label.pack(padx=16, pady=(16, 6))
        ctk.CTkLabel(
            self._confirm_frame,
            text="이 게시물이 맞나요?\n브라우저에서도 확인해주세요.",
            text_color="gray", font=ctk.CTkFont(size=12), justify="center",
        ).pack(padx=16, pady=(0, 10))
        confirm_btn_row = ctk.CTkFrame(self._confirm_frame, fg_color="transparent")
        confirm_btn_row.pack(pady=(0, 14))
        ctk.CTkButton(
            confirm_btn_row, text="다시 선택", width=120, height=36,
            fg_color="transparent", border_width=1, border_color="#555",
            hover_color="#2a2a2a", command=self._reset_confirm,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            confirm_btn_row, text="이 게시물로 댓글 불러오기", width=200, height=36,
            command=self._start_fetch,
        ).pack(side="left", padx=6)

        # 게시물 선택 버튼 (프로필 이동 성공 후 표시)
        self._select_btn = ctk.CTkButton(
            self, text="이 게시물 선택",
            width=300, height=44, font=ctk.CTkFont(size=14),
            fg_color="#1a6b3c", hover_color="#145530",
            command=self._on_select_post,
        )
        # 처음엔 숨겨둠 — _on_profile_opened() 에서 pack()

    # ── 프로필 이동 ──────────────────────────────────────────────────────────

    def _on_goto_profile(self) -> None:
        username = self._username_entry.get().strip().lstrip("@")
        if not username:
            self._set_status("인스타 아이디를 입력해주세요.", "orange")
            return
        self._goto_btn.configure(state="disabled", text="이동 중...")
        self._set_status("브라우저에서 프로필 페이지로 이동 중...", "gray")
        url = f"https://www.instagram.com/{username}/"
        threading.Thread(target=self._goto_thread, args=(url,), daemon=True).start()

    def _goto_thread(self, url: str) -> None:
        try:
            pw_run(lambda: self._page.goto(url, wait_until="domcontentloaded", timeout=30_000))
            self.after(0, self._on_profile_opened)
        except Exception as e:
            self.after(0, lambda e=e: self._on_goto_error(str(e)))

    def _on_profile_opened(self) -> None:
        self._goto_btn.configure(state="normal", text="내 게시물 페이지로 이동")
        self._set_status("게시물을 클릭한 뒤 아래 버튼을 눌러주세요.", "#2ecc71")
        self._select_btn.pack(pady=(8, 0))

    def _on_goto_error(self, msg: str) -> None:
        self._goto_btn.configure(state="normal", text="내 게시물 페이지로 이동")
        self._set_status(f"이동 실패: {msg}", "red")

    # ── 게시물 선택 ──────────────────────────────────────────────────────────

    def _on_select_post(self) -> None:
        self._select_btn.configure(state="disabled", text="URL 읽는 중...")
        threading.Thread(target=self._read_url_thread, daemon=True).start()

    def _read_url_thread(self) -> None:
        try:
            url = pw_run(lambda: self._page.evaluate("() => window.location.href"))
            self.after(0, lambda: self._on_url_read(url))
        except Exception as e:
            self.after(0, lambda e=e: self._on_select_error(str(e)))

    def _on_url_read(self, url: str) -> None:
        self._select_btn.configure(state="normal", text="이 게시물 선택")
        if not _POST_RE.search(url):
            self._set_status(
                "게시물 URL이 아니에요.\n게시물을 먼저 클릭한 뒤 버튼을 눌러주세요.", "orange"
            )
            return
        self._show_confirm(url)

    def _on_select_error(self, msg: str) -> None:
        self._select_btn.configure(state="normal", text="이 게시물 선택")
        self._set_status(f"오류: {msg}", "red")

    # ── 확인 카드 ────────────────────────────────────────────────────────────

    def _show_confirm(self, url: str) -> None:
        self._confirmed_url = url
        self._url_label.configure(text=url)
        self._confirm_frame.pack(fill="x", padx=20, pady=8)
        # 브라우저를 해당 URL로 이동한 뒤 댓글 영역까지 스크롤
        threading.Thread(target=self._navigate_to_comments, args=(url,), daemon=True).start()

    def _navigate_to_comments(self, url: str) -> None:
        try:
            def _go():
                self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                self._page.wait_for_timeout(1500)
                # 댓글 입력창(textarea) 또는 댓글 섹션으로 스크롤
                self._page.evaluate("""() => {
                    const el = document.querySelector(
                        'textarea[placeholder], article [role="button"][aria-label*="댓"], ' +
                        'article section:last-of-type'
                    );
                    if (el) {
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    } else {
                        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
                    }
                }""")
            pw_run(_go)
        except Exception:
            pass  # 스크롤 실패해도 URL 이동 자체는 됐으므로 무시

    def _reset_confirm(self) -> None:
        self._confirmed_url = None
        self._confirm_frame.pack_forget()
        self._set_status("게시물을 다시 선택해주세요.", "gray")

    # ── 댓글 불러오기 ────────────────────────────────────────────────────────

    def _start_fetch(self) -> None:
        if not self._confirmed_url:
            return
        self._confirm_frame.pack_forget()
        self._select_btn.pack_forget()
        self._set_status("댓글 수집 중...", "gray")
        url = self._confirmed_url
        threading.Thread(target=self._fetch_thread, args=(url,), daemon=True).start()

    def _fetch_thread(self, url: str) -> None:
        try:
            comments = pw_run(
                lambda: fetch_comments(self._session, url, on_progress=self._set_status)
            )
            self.after(0, lambda: self._on_post_selected(url, comments))
        except Exception as e:
            self.after(0, lambda e=e: self._on_fetch_error(str(e)))

    def _on_fetch_error(self, msg: str) -> None:
        self._set_status(f"오류: {msg}", "red")
        self._select_btn.pack(pady=(8, 0))

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, color: str = "gray") -> None:
        self.after(0, lambda: self._status.configure(text=msg, text_color=color))
