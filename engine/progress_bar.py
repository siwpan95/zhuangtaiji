import tkinter as tk
from dataclasses import dataclass
from typing import Optional, Callable


# ==========================================
# 缓动函数
# ==========================================
def ease_out_quad(t: float) -> float:
    """二次缓出：开始快，结束慢"""
    return 1 - (1 - t) ** 2


def ease_in_out_quad(t: float) -> float:
    """二次缓入缓出"""
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def ease_out_cubic(t: float) -> float:
    """三次缓出"""
    return 1 - (1 - t) ** 3


EASING_MAP = {
    "linear": lambda t: t,
    "ease_out": ease_out_quad,
    "ease_in_out": ease_in_out_quad,
    "ease_out_cubic": ease_out_cubic,
}


# ==========================================
# 颜色主题
# ==========================================
@dataclass
class BarTheme:
    bar_color: str = "#2196F3"
    bg_color: str = "#E0E0E0"
    border_color: str = "#555555"
    text_color: str = "#333333"
    bar_high: str = "#4CAF50"   # >80% 时变色


DEFAULT_THEME = BarTheme()
THEME_DARK = BarTheme(
    bar_color="#64B5F6", bg_color="#424242",
    border_color="#757575", text_color="#EEEEEE", bar_high="#81C784"
)
THEME_WARM = BarTheme(
    bar_color="#FF7043", bg_color="#FFE0B2",
    border_color="#BF360C", text_color="#3E2723", bar_high="#FFD54F"
)


# ==========================================
# 可被反复调用的 Canvas 进度条
# ==========================================
class CanvasProgressBar:
    def __init__(self, parent, width=400, height=25,
                 theme: BarTheme = None, show_percentage=True):
        self.theme = theme or DEFAULT_THEME

        self.canvas = tk.Canvas(parent, width=width, height=height,
                                bg=self.theme.bg_color, highlightthickness=0)
        self.canvas.pack(pady=10)

        self.width = width
        self.height = height

        # 背景边框
        self.canvas.create_rectangle(0, 0, width, height,
                                     outline=self.theme.border_color, width=2)
        # 进度填充条
        self.bar_rect = self.canvas.create_rectangle(0, 0, 0, height,
                                                     fill=self.theme.bar_color, outline="")
        # 百分比文字
        self.show_percentage = show_percentage
        self.text_id = self.canvas.create_text(
            width / 2, height / 2, text="0%",
            font=("Arial", max(9, height // 3), "bold"),
            fill=self.theme.text_color
        ) if show_percentage else None

        # 当前绑定的状态机
        self.bound_sm = None
        self._progress = 0

        # 动画控制
        self._animating = False
        self._paused = False
        self._on_complete: Optional[Callable] = None

        # 不确定模式
        self._indeterminate = False
        self._indeterminate_dir = 1  # 1=右, -1=左
        self._indeterminate_pos = 0

    # ---------- 绑定 ----------
    def bind_state_machine(self, sm_instance):
        """将进度条逻辑上绑定到一个状态机"""
        self.bound_sm = sm_instance
        self.reset()

    # ---------- 进度控制 ----------
    def set_progress(self, percent):
        self._progress = max(0, min(percent, 100))
        fill_width = (self._progress / 100) * self.width
        # 高进度变色
        color = self.theme.bar_high if self._progress >= 80 else self.theme.bar_color
        self.canvas.itemconfig(self.bar_rect, fill=color)
        self.canvas.coords(self.bar_rect, 0, 0, fill_width, self.height)
        # 更新文字
        if self.show_percentage and self.text_id:
            self.canvas.itemconfig(self.text_id, text=f"{int(self._progress)}%")
        self.canvas.update_idletasks()

    def reset(self):
        self.set_progress(0)
        self._animating = False
        self._paused = False
        self._indeterminate = False

    @property
    def progress(self):
        return self._progress

    # ---------- 动画 ----------
    def animate(self, step=2, delay=20, on_complete=None, easing="linear"):
        """执行进度条动画"""
        self._animating = True
        self._paused = False
        self._indeterminate = False
        self._on_complete = on_complete
        ease_fn = EASING_MAP.get(easing, EASING_MAP["linear"])

        def _step_forward(raw_step):
            if not self._animating:
                return
            if self._paused:
                self.canvas.after(delay, lambda: _step_forward(raw_step))
                return
            if raw_step <= 100:
                t = raw_step / 100.0
                display = int(ease_fn(t) * 100)
                self.set_progress(display)
                self.canvas.after(delay, lambda: _step_forward(raw_step + step))
            else:
                self.set_progress(100)
                self._animating = False
                if callable(self._on_complete):
                    self._on_complete()

        _step_forward(0)

    def animate_indeterminate(self, delay=15, on_stop=None):
        """不确���模式：来回弹跳的进度条"""
        self._animating = True
        self._paused = False
        self._indeterminate = True
        self._on_complete = on_stop
        bar_w = self.width * 0.3  # 滑块宽度

        def _bounce():
            if not self._animating:
                return
            if self._paused:
                self.canvas.after(delay, _bounce)
                return
            # 位置在 0 ~ (width - bar_w) 之间来回
            max_x = self.width - bar_w
            self._indeterminate_pos += 3 * self._indeterminate_dir
            if self._indeterminate_pos >= max_x:
                self._indeterminate_pos = max_x
                self._indeterminate_dir = -1
            elif self._indeterminate_pos <= 0:
                self._indeterminate_pos = 0
                self._indeterminate_dir = 1
            self.canvas.coords(self.bar_rect,
                               self._indeterminate_pos, 0,
                               self._indeterminate_pos + bar_w, self.height)
            if self.show_percentage and self.text_id:
                self.canvas.itemconfig(self.text_id, text="...")
            self.canvas.update_idletasks()
            self.canvas.after(delay, _bounce)

        _bounce()

    # ---------- 暂停/恢复 ----------
    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    @property
    def is_paused(self):
        return self._paused

    @property
    def is_running(self):
        return self._animating and not self._paused

    def stop(self):
        """强制终止动画"""
        self._animating = False
        self._paused = False
