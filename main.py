# ==========================================
# 程序入口
# ==========================================
import tkinter as tk

from ui import Application

if __name__ == "__main__":
    root = tk.Tk()
    root.resizable(False, False)
    app = Application(root)
    root.mainloop()
