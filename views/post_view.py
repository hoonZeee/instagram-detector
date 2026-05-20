import customtkinter as ctk
import threading
from instagram import fetch_comments
from playwright_worker import pw_run


class PostView(ctk.CTkFrame):
    def __init__(self, parent, session, on_post_selected):
        super().__init__(parent, fg_color="transparent")
        self._session = session
        self._on_post_selected = on_post_selected
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="게시물 선택", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(50, 8))
        ctk.CTkLabel(self, text="댓글을 탐지할 게시물 URL을 붙여넣어주세요.", text_color="gray").pack(pady=(0, 30))

        self._url_entry = ctk.CTkEntry(self, width=440, height=44, placeholder_text="https://www.instagram.com/p/...")
        self._url_entry.pack(pady=8)

        self._fetch_btn = ctk.CTkButton(self, text="댓글 불러오기", width=260, height=44, font=ctk.CTkFont(size=14), command=self._fetch)
        self._fetch_btn.pack(pady=16)

        self._status = ctk.CTkLabel(self, text="", text_color="gray", font=ctk.CTkFont(size=13))
        self._status.pack(pady=8)

    def _fetch(self):
        url = self._url_entry.get().strip()
        if not url.startswith("https://www.instagram.com/p/"):
            self._status.configure(text="올바른 Instagram 게시물 URL을 입력해주세요.", text_color="orange")
            return
        self._fetch_btn.configure(state="disabled", text="불러오는 중...")
        self._status.configure(text="댓글 수집 중...", text_color="gray")
        threading.Thread(target=self._fetch_thread, args=(url,), daemon=True).start()

    def _fetch_thread(self, url: str):
        try:
            comments = pw_run(lambda: fetch_comments(self._session, url, on_progress=self._set_status))
            self.after(0, lambda: self._on_post_selected(url, comments))
        except Exception as e:
            import traceback; traceback.print_exc()
            self.after(0, lambda e=e: self._on_error(str(e)))

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status.configure(text=msg))

    def _on_error(self, msg: str):
        self._fetch_btn.configure(state="normal", text="댓글 불러오기")
        self._status.configure(text=f"오류: {msg}", text_color="red")
