import threading
from dataclasses import dataclass, field

import customtkinter as ctk

from detector import CommentGroup, Confidence, SpamReason, detect, search_comments
from instagram import delete_comments
from playwright_worker import pw_run

# ── 탭 정의 ──────────────────────────────────────────────────────────────────

_DETECT_TABS: list[tuple[Confidence, str, str, bool]] = [
    (Confidence.HIGH,   "🔴 높음", "#c0392b", True),
    (Confidence.MEDIUM, "🟠 중간", "#e67e22", True),
    (Confidence.LOW,    "🟡 검토", "#d4ac0d", False),
]
_SEARCH_KEY = "search"
_SEARCH_NAME = "🔍 검색"
_SEARCH_COLOR = "#2980b9"

_ALL_KEY = "all"
_ALL_NAME = "💬 전체 댓글"
_ALL_COLOR = "#555"

_REASON_LABEL: dict[SpamReason, str] = {
    SpamReason.BLACKLIST:      "키워드",
    SpamReason.EXACT_REPEAT:   "반복",
    SpamReason.SIMILAR_REPEAT: "유사반복",
    SpamReason.CAMPAIGN:       "패턴일치",
    SpamReason.OBFUSCATED:     "우회표기",
}
_REASON_COLOR: dict[SpamReason, str] = {
    SpamReason.BLACKLIST:      "#c0392b",
    SpamReason.EXACT_REPEAT:   "#e67e22",
    SpamReason.SIMILAR_REPEAT: "#d4ac0d",
    SpamReason.CAMPAIGN:       "#8e44ad",
    SpamReason.OBFUSCATED:     "#6c3483",
}


@dataclass
class _GroupRow:
    var: ctk.BooleanVar
    ids: list[str]


@dataclass
class _TabUI:
    scroll: ctk.CTkScrollableFrame
    delete_btn: ctk.CTkButton
    header: ctk.CTkLabel | None = None
    rows: list[_GroupRow] = field(default_factory=list)


class ResultView(ctk.CTkFrame):
    def __init__(self, parent, session, post_url: str, comments: list[dict], on_back=None):
        super().__init__(parent, fg_color="transparent")
        self._session = session
        self._post_url = post_url
        self._comments = comments
        self._on_back = on_back
        self._id_to_comment: dict[str, dict] = {c["id"]: c for c in comments}
        self._tabs: dict[object, _TabUI] = {}
        self._last_keyword: str = ""
        self._all_filter: str = ""
        self._build_ui()
        self._run_detection()
        # 전체 댓글 탭은 즉시 렌더 (API 재호출 없음)
        self.after(50, self._render_all_tab)

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(20, 0))
        ctk.CTkLabel(
            top, text="탐지 결과", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        if self._on_back:
            ctk.CTkButton(
                top, text="← 다른 게시물", width=110, height=30,
                fg_color="transparent", border_width=1, border_color="#555",
                hover_color="#2a2a2a", command=self._on_back,
            ).pack(side="right")

        self._status = ctk.CTkLabel(
            self, text="탐지 중...", text_color="gray", font=ctk.CTkFont(size=13)
        )
        self._status.pack(pady=4)

        tabview = ctk.CTkTabview(self, height=490)
        tabview.pack(fill="both", expand=True, padx=16, pady=4)

        # 탐지 탭 3개
        for conf, name, color, _ in _DETECT_TABS:
            tabview.add(name)
            self._tabs[conf] = self._build_detection_tab(tabview.tab(name), conf, color)

        # 검색 탭
        tabview.add(_SEARCH_NAME)
        self._tabs[_SEARCH_KEY] = self._build_search_tab(tabview.tab(_SEARCH_NAME))

        # 전체 댓글 탭
        tabview.add(_ALL_NAME)
        self._tabs[_ALL_KEY] = self._build_all_tab(tabview.tab(_ALL_NAME))

    def _build_detection_tab(self, tab, conf: Confidence, color: str) -> _TabUI:
        header = ctk.CTkLabel(
            tab, text="", text_color=color, font=ctk.CTkFont(size=13, weight="bold")
        )
        header.pack(pady=(2, 4))
        scroll = ctk.CTkScrollableFrame(tab, height=320)
        scroll.pack(fill="both", expand=True, padx=2, pady=2)
        delete_btn = self._build_action_row(tab, conf, color)
        return _TabUI(scroll=scroll, delete_btn=delete_btn, header=header)

    def _build_search_tab(self, tab) -> _TabUI:
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=2, pady=(4, 2))
        self._search_entry = ctk.CTkEntry(
            row, height=34,
            placeholder_text="필터가 놓친 단어를 입력하세요 (예: 성세라, 구글)",
        )
        self._search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._search_entry.bind("<Return>", lambda _e: self._run_search())
        ctk.CTkButton(row, text="검색", width=70, height=34, command=self._run_search).pack(side="left")

        header = ctk.CTkLabel(
            tab, text="단어를 입력하면 포함된 댓글과 유사한 댓글을 모아줘요.",
            text_color="gray", font=ctk.CTkFont(size=12),
        )
        header.pack(pady=(4, 2))
        scroll = ctk.CTkScrollableFrame(tab, height=290)
        scroll.pack(fill="both", expand=True, padx=2, pady=2)
        delete_btn = self._build_action_row(tab, _SEARCH_KEY, _SEARCH_COLOR)
        delete_btn.configure(state="disabled")
        return _TabUI(scroll=scroll, delete_btn=delete_btn, header=header)

    def _build_all_tab(self, tab) -> _TabUI:
        # 상단: 필터 + 카운터
        top_row = ctk.CTkFrame(tab, fg_color="transparent")
        top_row.pack(fill="x", padx=2, pady=(4, 2))
        self._all_filter_entry = ctk.CTkEntry(
            top_row, height=34, placeholder_text="댓글 내 검색 (실시간 필터)"
        )
        self._all_filter_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._all_filter_entry.bind("<KeyRelease>", lambda _e: self._on_all_filter_change())
        ctk.CTkButton(
            top_row, text="초기화", width=60, height=34,
            fg_color="transparent", border_width=1, border_color="#555",
            command=self._clear_all_filter,
        ).pack(side="left")

        header = ctk.CTkLabel(
            tab, text="", text_color="gray", font=ctk.CTkFont(size=12)
        )
        header.pack(pady=(2, 2))

        scroll = ctk.CTkScrollableFrame(tab, height=295)
        scroll.pack(fill="both", expand=True, padx=2, pady=2)
        delete_btn = self._build_action_row(tab, _ALL_KEY, "#c0392b")
        return _TabUI(scroll=scroll, delete_btn=delete_btn, header=header)

    def _build_action_row(self, tab, key, color: str) -> ctk.CTkButton:
        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(pady=8)
        ctk.CTkButton(
            btn_row, text="전체 선택", width=92, height=30,
            command=lambda: self._select_all(key, True),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row, text="선택 해제", width=92, height=30,
            command=lambda: self._select_all(key, False),
        ).pack(side="left", padx=4)
        delete_btn = ctk.CTkButton(
            btn_row, text="선택 삭제", width=110, height=30,
            fg_color=color, hover_color="#962d22",
            command=lambda: self._confirm_delete(key),
        )
        delete_btn.pack(side="left", padx=4)
        return delete_btn

    # ── 자동 탐지 ────────────────────────────────────────────────────────────

    def _run_detection(self) -> None:
        threading.Thread(target=self._detect_thread, daemon=True).start()

    def _detect_thread(self) -> None:
        result = detect(self._comments)
        self.after(0, lambda: self._render_results(result))

    def _render_results(self, result) -> None:
        by_conf: dict[Confidence, list[CommentGroup]] = {conf: [] for conf, _, _, _ in _DETECT_TABS}
        for g in result.groups:
            if g.confidence in by_conf:
                by_conf[g.confidence].append(g)

        total = sum(len(g.ids) for g in result.groups)
        self._status.configure(
            text=f"총 {len(self._comments)}개 댓글 중 {total}개 의심 댓글 탐지",
            text_color="#e67e22" if total else "#2ecc71",
        )

        for conf, _name, _color, default in _DETECT_TABS:
            tab = self._tabs[conf]
            self._clear_tab(tab)
            groups = sorted(by_conf[conf], key=lambda g: len(g.ids), reverse=True)
            count = sum(len(g.ids) for g in groups)
            if tab.header:
                tab.header.configure(text=f"{count}개 댓글 · {len(groups)}개 그룹")
            if not groups:
                ctk.CTkLabel(tab.scroll, text="해당 항목 없음", text_color="gray").pack(pady=20)
                tab.delete_btn.configure(state="disabled")
                continue
            tab.delete_btn.configure(state="normal")
            for group in groups:
                self._add_group_row(tab, group, default_checked=default)

    # ── 전체 댓글 탭 ─────────────────────────────────────────────────────────

    def _render_all_tab(self) -> None:
        tab = self._tabs[_ALL_KEY]
        self._clear_tab(tab)
        kw = self._all_filter.strip().lower()
        shown = [
            c for c in self._comments
            if not kw or kw in c.get("text", "").lower() or kw in c.get("username", "").lower()
        ]
        total = len(self._comments)
        filtered = len(shown)
        if tab.header:
            if kw:
                tab.header.configure(
                    text=f"전체 {total}개 댓글 중 '{kw}' 포함 {filtered}개 표시",
                    text_color=_SEARCH_COLOR,
                )
            else:
                tab.header.configure(
                    text=f"전체 {total}개 댓글", text_color="gray"
                )
        if not shown:
            ctk.CTkLabel(tab.scroll, text="표시할 댓글이 없어요.", text_color="gray").pack(pady=20)
            tab.delete_btn.configure(state="disabled")
            return
        tab.delete_btn.configure(state="normal")
        for c in shown:
            self._add_comment_row(tab, c)

    def _add_comment_row(self, tab: _TabUI, comment: dict) -> None:
        username = comment.get("username", "")
        text = comment.get("text", "")
        cid = comment["id"]

        row = ctk.CTkFrame(tab.scroll, fg_color="#1e1e1e", corner_radius=6)
        row.pack(fill="x", pady=2, padx=4)

        var = ctk.BooleanVar(value=False)
        tab.rows.append(_GroupRow(var=var, ids=[cid]))

        ctk.CTkCheckBox(row, text="", variable=var, width=28).pack(
            side="left", padx=(10, 6), pady=8
        )
        ctk.CTkLabel(
            row, text=f"@{username}",
            text_color="#7eb8f7", font=ctk.CTkFont(size=12),
            width=90, anchor="w",
        ).pack(side="left", padx=(0, 6), pady=8)
        ctk.CTkLabel(
            row, text=text,
            anchor="w", wraplength=340, justify="left",
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=4, pady=8, fill="x", expand=True)

    def _on_all_filter_change(self) -> None:
        self._all_filter = self._all_filter_entry.get()
        self._render_all_tab()

    def _clear_all_filter(self) -> None:
        self._all_filter = ""
        self._all_filter_entry.delete(0, "end")
        self._render_all_tab()

    # ── 키워드 검색 탭 ───────────────────────────────────────────────────────

    def _run_search(self) -> None:
        keyword = self._search_entry.get().strip()
        if not keyword:
            return
        self._last_keyword = keyword
        threading.Thread(target=self._search_thread, args=(keyword,), daemon=True).start()

    def _search_thread(self, keyword: str) -> None:
        exact, similar = search_comments(self._comments, keyword)
        self.after(0, lambda: self._render_search(keyword, exact, similar))

    def _render_search(self, keyword: str, exact: list, similar: list) -> None:
        tab = self._tabs[_SEARCH_KEY]
        self._clear_tab(tab)
        exact_n = sum(len(g.ids) for g in exact)
        similar_n = sum(len(g.ids) for g in similar)
        if tab.header:
            tab.header.configure(
                text=f"'{keyword}' — 정확히 포함 {exact_n}개 · 유사 추천 {similar_n}개"
            )
        if not exact and not similar:
            ctk.CTkLabel(
                tab.scroll, text=f"'{keyword}'(을)를 포함한 댓글이 없어요.", text_color="gray"
            ).pack(pady=20)
            tab.delete_btn.configure(state="disabled")
            return
        tab.delete_btn.configure(state="normal")
        if exact:
            self._add_section_label(tab, "정확히 포함", _SEARCH_COLOR)
            for g in sorted(exact, key=lambda g: len(g.ids), reverse=True):
                self._add_group_row(tab, g, default_checked=True, badge=("포함", "#1a6b3c"))
        if similar:
            self._add_section_label(tab, "유사한 댓글 · 추천 (기본 미선택)", "#8e44ad")
            for g in sorted(similar, key=lambda g: len(g.ids), reverse=True):
                self._add_group_row(tab, g, default_checked=False, badge=("유사", "#8e44ad"))

    def _add_section_label(self, tab: _TabUI, text: str, color: str) -> None:
        ctk.CTkLabel(
            tab.scroll, text=f"■ {text}", text_color=color,
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).pack(fill="x", padx=6, pady=(10, 2))

    # ── 공용 행 빌더 (그룹용) ────────────────────────────────────────────────

    def _clear_tab(self, tab: _TabUI) -> None:
        for w in tab.scroll.winfo_children():
            w.destroy()
        tab.rows.clear()

    def _add_group_row(self, tab: _TabUI, group: CommentGroup, default_checked: bool,
                       badge: tuple[str, str] | None = None) -> None:
        rep = self._id_to_comment.get(group.ids[0], {})
        username = rep.get("username", "")
        text = rep.get("text", group.sample_text)
        count = len(group.ids)

        row = ctk.CTkFrame(tab.scroll, fg_color="#2b2b2b", corner_radius=8)
        row.pack(fill="x", pady=3, padx=4)

        var = ctk.BooleanVar(value=default_checked)
        tab.rows.append(_GroupRow(var=var, ids=list(group.ids)))

        ctk.CTkCheckBox(row, text="", variable=var, width=28).pack(
            side="left", padx=(10, 4), pady=10
        )
        label, color = badge if badge else (
            _REASON_LABEL.get(group.reason, ""), _REASON_COLOR.get(group.reason, "#555")
        )
        ctk.CTkLabel(
            row, text=label, width=64, height=22, fg_color=color, corner_radius=4,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 4), pady=10)
        if count >= 2:
            ctk.CTkLabel(
                row, text=f"{count}회", width=36, height=22,
                fg_color="#1a6b3c", corner_radius=4, font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(0, 4), pady=10)
        if group.obfuscated:
            ctk.CTkLabel(
                row, text="깨짐", width=36, height=22,
                fg_color="#6c3483", corner_radius=4, font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(0, 6), pady=10)
        ctk.CTkLabel(
            row, text=f"@{username}  {text}",
            anchor="w", wraplength=360, justify="left",
        ).pack(side="left", padx=4, pady=10, fill="x", expand=True)

    # ── 선택 ─────────────────────────────────────────────────────────────────

    def _select_all(self, key, value: bool) -> None:
        for row in self._tabs[key].rows:
            row.var.set(value)

    # ── 삭제 ─────────────────────────────────────────────────────────────────

    def _confirm_delete(self, key) -> None:
        selected_ids = list({
            cid for row in self._tabs[key].rows if row.var.get() for cid in row.ids
        })
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
            command=lambda: self._do_delete(key, selected_ids, dialog),
        ).pack(side="left", padx=8)

    def _do_delete(self, key, comment_ids: list[str], dialog: ctk.CTkToplevel) -> None:
        dialog.destroy()
        self._set_all_delete_btns(state="disabled")
        self._status.configure(text=f"삭제 중입니다... ({len(comment_ids)}개)", text_color="gray")
        threading.Thread(
            target=self._delete_thread, args=(key, comment_ids), daemon=True
        ).start()

    def _delete_thread(self, key, comment_ids: list[str]) -> None:
        try:
            deleted = pw_run(
                lambda: delete_comments(
                    self._session, self._post_url, comment_ids, on_progress=self._set_status,
                )
            )
            self.after(0, lambda: self._on_delete_done(key, deleted, comment_ids))
        except Exception as e:
            self.after(0, lambda e=e: self._on_delete_error(key, str(e)))

    def _set_status(self, msg: str) -> None:
        self.after(0, lambda: self._status.configure(text=msg, text_color="gray"))

    def _set_all_delete_btns(self, state: str) -> None:
        for tab in self._tabs.values():
            tab.delete_btn.configure(state=state, text="선택 삭제")

    def _on_delete_error(self, key, msg: str) -> None:
        self._set_all_delete_btns(state="normal")
        self._status.configure(text=f"오류: {msg}", text_color="red")

    def _on_delete_done(self, key, count: int, deleted_ids: list[str]) -> None:
        self._set_all_delete_btns(state="normal")
        self._status.configure(text=f"삭제 완료! {count}개 댓글이 삭제되었습니다.", text_color="#2ecc71")
        deleted_set = set(deleted_ids)
        self._comments = [c for c in self._comments if c["id"] not in deleted_set]
        self._id_to_comment = {c["id"]: c for c in self._comments}
        self._run_detection()
        self._render_all_tab()
        if self._last_keyword:
            threading.Thread(
                target=self._search_thread, args=(self._last_keyword,), daemon=True
            ).start()
