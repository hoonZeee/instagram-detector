import threading
from dataclasses import dataclass

import customtkinter as ctk

from detector import CommentGroup, SpamReason, detect
from instagram import delete_comments
from playwright_worker import pw_run

_REASON_COLOR: dict[SpamReason, str] = {
    SpamReason.BLACKLIST:      "#c0392b",
    SpamReason.EXACT_REPEAT:   "#e67e22",
    SpamReason.SIMILAR_REPEAT: "#d4ac0d",
}
_REASON_LABEL: dict[SpamReason, str] = {
    SpamReason.BLACKLIST:      "키워드",
    SpamReason.EXACT_REPEAT:   "반복",
    SpamReason.SIMILAR_REPEAT: "유사반복",
}


@dataclass
class _GroupRow:
    """UI 한 행에 대응하는 그룹 정보."""
    var: ctk.BooleanVar
    ids: list[str]   # 이 그룹에 속한 모든 comment ID


class ResultView(ctk.CTkFrame):
    def __init__(self, parent, session, post_url: str, comments: list[dict], on_back=None):
        super().__init__(parent, fg_color="transparent")
        self._session = session
        self._post_url = post_url
        self._comments = comments
        self._id_to_comment: dict[str, dict] = {c["id"]: c for c in comments}
        self._rows: list[_GroupRow] = []
        self._on_back = on_back
        self._build_ui()
        self._run_detection()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(30, 0))
        ctk.CTkLabel(
            top, text="탐지 결과", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")

        self._status = ctk.CTkLabel(
            self, text="탐지 중...", text_color="gray", font=ctk.CTkFont(size=13)
        )
        self._status.pack(pady=8)

        self._scroll = ctk.CTkScrollableFrame(self, height=400)
        self._scroll.pack(fill="both", expand=True, padx=24, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(8, 4))
        ctk.CTkButton(btn_row, text="전체 선택",  width=120, command=self._select_all).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="선택 해제",  width=120, command=self._deselect_all).pack(side="left", padx=6)
        self._delete_btn = ctk.CTkButton(
            btn_row, text="선택한 댓글 삭제", width=160,
            fg_color="#c0392b", hover_color="#962d22",
            command=self._confirm_delete,
        )
        self._delete_btn.pack(side="left", padx=6)

        if self._on_back:
            ctk.CTkButton(
                self, text="← 다른 게시물 탐지",
                width=200, height=32,
                fg_color="transparent", hover_color="#2a2a2a",
                border_width=1, border_color="#555",
                font=ctk.CTkFont(size=12),
                command=self._on_back,
            ).pack(pady=(0, 12))

    # ── 탐지 ─────────────────────────────────────────────────────────────────

    def _run_detection(self) -> None:
        threading.Thread(target=self._detect_thread, daemon=True).start()

    def _detect_thread(self) -> None:
        result = detect(self._comments)
        self.after(0, lambda: self._render_results(result))

    def _render_results(self, result) -> None:
        for w in self._scroll.winfo_children():
            w.destroy()
        self._rows.clear()

        # 스팸으로 판정된 그룹만 필터 (is_spam 또는 블랙리스트 단건)
        spam_groups = [g for g in result.groups if g.ids and any(i in result.spam_ids for i in g.ids)]
        total_spam = len(result.spam_ids)

        self._status.configure(
            text=f"총 {len(self._comments)}개 댓글 중 {total_spam}개 악성 댓글 탐지됨 ({len(spam_groups)}개 그룹)",
            text_color="#e67e22",
        )

        if not spam_groups:
            ctk.CTkLabel(self._scroll, text="탐지된 악성 댓글이 없어요.", text_color="gray").pack(pady=20)
            return

        for group in spam_groups:
            self._add_group_row(group)

    def _add_group_row(self, group: CommentGroup) -> None:
        # 그룹 대표 댓글 정보
        rep = self._id_to_comment.get(group.ids[0], {})
        username  = rep.get("username", "")
        text      = rep.get("text", group.sample_text)
        count     = len(group.ids)

        row = ctk.CTkFrame(self._scroll, fg_color="#2b2b2b", corner_radius=8)
        row.pack(fill="x", pady=3, padx=4)

        var = ctk.BooleanVar(value=True)
        self._rows.append(_GroupRow(var=var, ids=list(group.ids)))

        ctk.CTkCheckBox(row, text="", variable=var, width=28).pack(
            side="left", padx=(10, 4), pady=10
        )

        # 탐지 이유 배지
        badge_color = _REASON_COLOR.get(group.reason, "#555")
        badge_label = _REASON_LABEL.get(group.reason, "")
        ctk.CTkLabel(
            row, text=badge_label, width=56, height=22,
            fg_color=badge_color, corner_radius=4,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 4), pady=10)

        # 반복 횟수 배지 (2개 이상일 때만)
        if count >= 2:
            ctk.CTkLabel(
                row, text=f"{count}회", width=36, height=22,
                fg_color="#1a6b3c", corner_radius=4,
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(0, 6), pady=10)

        ctk.CTkLabel(
            row,
            text=f"@{username}  {text}",
            anchor="w", wraplength=380, justify="left",
        ).pack(side="left", padx=4, pady=10, fill="x", expand=True)

    # ── 선택 ─────────────────────────────────────────────────────────────────

    def _select_all(self) -> None:
        for row in self._rows:
            row.var.set(True)

    def _deselect_all(self) -> None:
        for row in self._rows:
            row.var.set(False)

    # ── 삭제 ─────────────────────────────────────────────────────────────────

    def _confirm_delete(self) -> None:
        # 선택된 그룹의 모든 ID 수집
        selected_ids = [cid for row in self._rows if row.var.get() for cid in row.ids]
        if not selected_ids:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("삭제 확인")
        dialog.geometry("360x180")
        dialog.grab_set()
        ctk.CTkLabel(
            dialog,
            text=f"선택한 {len(selected_ids)}개의 댓글을 삭제할까요?\n이 작업은 되돌릴 수 없어요.",
            justify="center",
        ).pack(pady=30)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack()
        ctk.CTkButton(
            btn_row, text="취소", width=120, fg_color="gray", command=dialog.destroy
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            btn_row, text="삭제", width=120,
            fg_color="#c0392b", hover_color="#962d22",
            command=lambda: self._do_delete(selected_ids, dialog),
        ).pack(side="left", padx=8)

    def _do_delete(self, comment_ids: list[str], dialog: ctk.CTkToplevel) -> None:
        dialog.destroy()
        self._delete_btn.configure(state="disabled", text="삭제 중...")
        threading.Thread(target=self._delete_thread, args=(comment_ids,), daemon=True).start()

    def _delete_thread(self, comment_ids: list[str]) -> None:
        try:
            deleted = pw_run(
                lambda: delete_comments(
                    self._session, self._post_url, comment_ids,
                    on_progress=self._set_status,
                )
            )
            self.after(0, lambda: self._on_delete_done(deleted, comment_ids))
        except Exception as e:
            self.after(0, lambda e=e: self._set_status(f"오류: {e}"))

    def _set_status(self, msg: str) -> None:
        self.after(0, lambda: self._status.configure(text=msg))

    def _on_delete_done(self, count: int, deleted_ids: list[str]) -> None:
        self._status.configure(text=f"{count}개 댓글 삭제 완료!", text_color="#2ecc71")
        self._delete_btn.configure(state="normal", text="선택한 댓글 삭제")
        # 삭제된 댓글 로컬 목록에서 제거 후 재탐지
        deleted_set = set(deleted_ids)
        self._comments = [c for c in self._comments if c["id"] not in deleted_set]
        self._id_to_comment = {c["id"]: c for c in self._comments}
        self._run_detection()
