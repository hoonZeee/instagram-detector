import sys
import os

# PyInstaller 번들 환경에서 Playwright Chromium 경로 지정
if getattr(sys, 'frozen', False):
    _app_dir = os.path.dirname(sys.executable)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(_app_dir, 'pw-browsers')

# Windows PyInstaller: 멀티프로세스 서브프로세스 안전 초기화
if sys.platform == "win32":
    import multiprocessing
    multiprocessing.freeze_support()

import customtkinter as ctk
from gui import App

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
