import threading

import customtkinter as ctk

from browser import clear_profile, open_instagram_login
from playwright_worker import pw_run


class LoginView(ctk.CTkFrame):
    def __init__(self, parent, on_login_success):
        super().__init__(parent, fg_color="transparent")
        self._on_login_success = on_login_success
        self._build_ui()

    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self, text="Instagram 악성 댓글 탐지기",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(pady=(50, 8))

        ctk.CTkLabel(
            self,
            text="본인 인스타그램 계정으로 로그인하면\n탐지 및 삭제를 시작할 수 있어요.",
            justify="center", text_color="gray",
        ).pack(pady=(0, 32))

        self._login_btn = ctk.CTkButton(
            self, text="Instagram으로 로그인",
            width=260, height=48, font=ctk.CTkFont(size=15),
            command=self._start_login,
        )
        self._login_btn.pack(pady=8)

        # 다른 계정으로 전환 — 저장된 세션을 지우고 새로 로그인
        ctk.CTkButton(
            self, text="다른 계정으로 로그인",
            width=260, height=36,
            fg_color="transparent", hover_color="#2a2a2a",
            border_width=1, border_color="#555",
            font=ctk.CTkFont(size=13),
            command=self._clear_and_login,
        ).pack(pady=(4, 0))

        self._status = ctk.CTkLabel(
            self, text="", text_color="gray", font=ctk.CTkFont(size=13)
        )
        self._status.pack(pady=10)

        ctk.CTkLabel(
            self,
            text="브라우저가 열리면 직접 로그인해주세요.\n비밀번호는 이 앱에 저장되지 않습니다.",
            justify="center", text_color="#555555", font=ctk.CTkFont(size=12),
        ).pack(pady=(12, 0))

        # ── 하단 정보 영역 ──────────────────────────────────────────────────

        # 주의사항 버튼
        ctk.CTkButton(
            self,
            text="⚠️  주의사항 — 반드시 공식 사이트에서만 받아주세요",
            width=340, height=34,
            fg_color="#7d3c00", hover_color="#a04d00",
            font=ctk.CTkFont(size=12),
            command=self._show_warning,
        ).pack(pady=(20, 0))

        # 개발자 연락처
        ctk.CTkLabel(
            self,
            text="개발자 연락처 : dlwlgns7540@naver.com",
            text_color="#555555", font=ctk.CTkFont(size=11),
            justify="center",
        ).pack(pady=(8, 0))

    # ── 로그인 ────────────────────────────────────────────────────────────────

    def _start_login(self) -> None:
        self._set_buttons_enabled(False)
        self._status.configure(text="")
        threading.Thread(target=self._login_thread, daemon=True).start()

    def _clear_and_login(self) -> None:
        """저장된 세션을 완전히 지우고 새 로그인 창을 연다."""
        self._set_buttons_enabled(False)
        self._status.configure(text="기존 세션 삭제 중...", text_color="gray")
        threading.Thread(target=self._clear_then_login_thread, daemon=True).start()

    def _clear_then_login_thread(self) -> None:
        try:
            pw_run(clear_profile)  # Playwright 전용 스레드에서 실행
            self._login_thread()
        except Exception as e:
            self.after(0, lambda e=e: self._on_error(str(e)))

    def _login_thread(self) -> None:
        try:
            session, page = pw_run(lambda: open_instagram_login(on_waiting=self._set_status))
            if session:
                self.after(0, lambda: self._on_login_success(session, page))
            else:
                self.after(0, lambda: self._on_error("로그인이 취소되었거나 실패했어요."))
        except Exception as e:
            self.after(0, lambda e=e: self._on_error(str(e)))

    # ── 주의사항 팝업 ────────────────────────────────────────────────────────

    def _show_warning(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("주의사항")
        dialog.geometry("420x300")
        dialog.resizable(False, False)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="⚠️  중요 안내",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="#e67e22",
        ).pack(pady=(24, 12))

        ctk.CTkLabel(
            dialog,
            text=(
                "이 앱은 반드시 공식 경로에서만 받아주세요.\n\n"
                "출처 불명의 파일을 실행하면 계정 정보가\n"
                "탈취될 수 있습니다.\n\n"
                "공식 배포 주소 :\n"
                "hoonzeee.github.io"
            ),
            justify="center", text_color="white",
            font=ctk.CTkFont(size=13),
        ).pack(padx=24)

        ctk.CTkButton(
            dialog, text="확인", width=140, height=36,
            command=dialog.destroy,
        ).pack(pady=(20, 0))

    # ── 헬퍼 ──────────────────────────────────────────────────────────────────

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for w in self.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(state=state)

    def _set_status(self, msg: str) -> None:
        self.after(0, lambda: self._status.configure(text=msg, text_color="gray"))

    def _on_error(self, msg: str) -> None:
        self._set_buttons_enabled(True)
        self._status.configure(text=f"오류: {msg}", text_color="red")
