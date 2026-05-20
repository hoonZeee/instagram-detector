import customtkinter as ctk
import threading
from detector import detect_spam
from instagram import delete_comments
from playwright_worker import pw_run


class ResultView(ctk.CTkFrame):
    def __init__(self, parent, session, post_url, comments):
        super().__init__(parent, fg_color="transparent")
        self._session = session
        self._post_url = post_url
        self._comments = comments
        self._spam_vars = {}  # comment_id -> BooleanVar
        self._build_ui()
        self._run_detection()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(30, 0))
        ctk.CTkLabel(top, text="탐지 결과", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        self._status = ctk.CTkLabel(self, text="탐지 중...", text_color="gray", font=ctk.CTkFont(size=13))
        self._status.pack(pady=8)

        self._scroll = ctk.CTkScrollableFrame(self, height=400)
        self._scroll.pack(fill="both", expand=True, padx=24, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=16)
        ctk.CTkButton(btn_row, text="전체 선택", width=120, command=self._select_all).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="선택 해제", width=120, command=self._deselect_all).pack(side="left", padx=6)
        self._delete_btn = ctk.CTkButton(btn_row, text="선택한 댓글 삭제", width=160, fg_color="#c0392b", hover_color="#962d22", command=self._confirm_delete)
        self._delete_btn.pack(side="left", padx=6)

    def _run_detection(self):
        threading.Thread(target=self._detect_thread, daemon=True).start()

    def _detect_thread(self):
        spam_ids = detect_spam(self._comments)
        self.after(0, lambda: self._render_results(spam_ids))

    def _render_results(self, spam_ids: set):
        for w in self._scroll.winfo_children():
            w.destroy()
        self._spam_vars.clear()

        spam_comments = [c for c in self._comments if c["id"] in spam_ids]
        self._status.configure(text=f"총 {len(self._comments)}개 댓글 중 {len(spam_comments)}개 악성 댓글 탐지됨", text_color="#e67e22")

        if not spam_comments:
            ctk.CTkLabel(self._scroll, text="탐지된 악성 댓글이 없어요.", text_color="gray").pack(pady=20)
            return

        for c in spam_comments:
            row = ctk.CTkFrame(self._scroll, fg_color="#2b2b2b", corner_radius=8)
            row.pack(fill="x", pady=3, padx=4)

            var = ctk.BooleanVar(value=True)
            self._spam_vars[c["id"]] = var

            ctk.CTkCheckBox(row, text="", variable=var, width=28).pack(side="left", padx=(10, 4), pady=10)
            text = f"@{c['username']}  {c['text']}"
            ctk.CTkLabel(row, text=text, anchor="w", wraplength=460, justify="left").pack(side="left", padx=4, pady=10, fill="x", expand=True)

    def _select_all(self):
        for var in self._spam_vars.values():
            var.set(True)

    def _deselect_all(self):
        for var in self._spam_vars.values():
            var.set(False)

    def _confirm_delete(self):
        selected = [cid for cid, var in self._spam_vars.items() if var.get()]
        if not selected:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("삭제 확인")
        dialog.geometry("360x180")
        dialog.grab_set()
        ctk.CTkLabel(dialog, text=f"선택한 {len(selected)}개의 댓글을 삭제할까요?\n이 작업은 되돌릴 수 없어요.", justify="center").pack(pady=30)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack()
        ctk.CTkButton(btn_row, text="취소", width=120, fg_color="gray", command=dialog.destroy).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="삭제", width=120, fg_color="#c0392b", hover_color="#962d22",
                      command=lambda: self._do_delete(selected, dialog)).pack(side="left", padx=8)

    def _do_delete(self, comment_ids: list, dialog):
        dialog.destroy()
        self._delete_btn.configure(state="disabled", text="삭제 중...")
        threading.Thread(target=self._delete_thread, args=(comment_ids,), daemon=True).start()

    def _delete_thread(self, comment_ids: list):
        try:
            deleted = pw_run(lambda: delete_comments(self._session, self._post_url, comment_ids, on_progress=self._set_status))
            self.after(0, lambda: self._on_delete_done(deleted))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"오류: {e}"))

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status.configure(text=msg))

    def _on_delete_done(self, count: int):
        self._status.configure(text=f"{count}개 댓글 삭제 완료!", text_color="#2ecc71")
        self._delete_btn.configure(state="normal", text="선택한 댓글 삭제")
        for cid in list(self._spam_vars.keys()):
            if self._spam_vars[cid].get():
                del self._spam_vars[cid]
        self._run_detection()
