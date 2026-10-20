# -*- coding: utf-8 -*-
"""``python -m zhuangtaiji`` —— 启动 Tkinter 可视化工作台。

tkinter 在**函数内**导入：这样 ``import zhuangtaiji`` 在无头环境（CI / 容器 /
没有显示会话的场景）里不会因为顶层依赖 GUI 而直接失败。
"""


def main() -> None:
    import tkinter as tk

    from .ui import Application

    root = tk.Tk()
    root.resizable(False, False)
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    main()
