import customtkinter as ctk
from views.login_view import LoginView
from views.post_view import PostView
from views.result_view import ResultView


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Instagram 악성 댓글 탐지기")
        self.geometry("600x700")
        self.resizable(False, False)

        self.session = None
        self.page = None

        self._show_login()

    def _show_login(self):
        self._clear()
        LoginView(self, on_login_success=self._on_login_success).pack(fill="both", expand=True)

    def _on_login_success(self, session, page):
        self.session = session
        self.page = page
        self._clear()
        PostView(
            self, session=session, page=page,
            on_post_selected=self._on_post_selected,
        ).pack(fill="both", expand=True)

    def _on_post_selected(self, post_url, comments):
        self._clear()
        ResultView(
            self, session=self.session, post_url=post_url, comments=comments,
            on_back=self._back_to_post,
        ).pack(fill="both", expand=True)

    def _back_to_post(self):
        self._clear()
        PostView(
            self, session=self.session, page=self.page,
            on_post_selected=self._on_post_selected,
        ).pack(fill="both", expand=True)

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()
