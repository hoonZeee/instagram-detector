import customtkinter as ctk
import threading
from browser import open_instagram_login
from playwright_worker import pw_run


class LoginView(ctk.CTkFrame):
    def __init__(self, parent, on_login_success):
        super().__init__(parent, fg_color="transparent")
        self._on_login_success = on_login_success
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="Instagram 악성 댓글 탐지기", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(60, 8))
        ctk.CTkLabel(self, text="본인 인스타그램 계정으로 로그인하면\n탐지 및 삭제를 시작할 수 있어요.", justify="center", text_color="gray").pack(pady=(0, 40))

        self._login_btn = ctk.CTkButton(self, text="Instagram으로 로그인", width=260, height=48, font=ctk.CTkFont(size=15), command=self._start_login)
        self._login_btn.pack(pady=8)

        self._status = ctk.CTkLabel(self, text="", text_color="gray", font=ctk.CTkFont(size=13))
        self._status.pack(pady=12)

        ctk.CTkLabel(self, text="브라우저가 열리면 직접 로그인해주세요.\n비밀번호는 이 앱에 저장되지 않습니다.", justify="center", text_color="#555555", font=ctk.CTkFont(size=12)).pack(pady=(20, 0))

    def _start_login(self):
        self._login_btn.configure(state="disabled", text="브라우저 열리는 중...")
        self._status.configure(text="")
        threading.Thread(target=self._login_thread, daemon=True).start()

    def _login_thread(self):
        try:
            session = pw_run(lambda: open_instagram_login(on_waiting=self._set_status))
            if session:
                self.after(0, lambda: self._on_login_success(session))
            else:
                self.after(0, lambda: self._on_error("로그인이 취소되었거나 실패했어요."))
        except Exception as e:
            self.after(0, lambda e=e: self._on_error(str(e)))

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status.configure(text=msg))

    def _on_error(self, msg: str):
        self._login_btn.configure(state="normal", text="Instagram으로 로그인")
        self._status.configure(text=f"오류: {msg}", text_color="red")
