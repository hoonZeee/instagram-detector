import os
import sys

# PyInstaller로 빌드된 경우 Playwright가 번들된 Chromium을 찾도록 경로 설정
if getattr(sys, 'frozen', False):
    _app_dir = os.path.dirname(sys.executable)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(_app_dir, 'pw-browsers')

import customtkinter as ctk
from gui import App

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
