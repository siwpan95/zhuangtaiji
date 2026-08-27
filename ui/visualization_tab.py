# -*- coding: utf-8 -*-
"""
可视化工作台 Tab（P0-2）
======================

任选一个范式引擎 + 实例，渲染其结构图（ASCII 离线可见；可导出 Mermaid / DOT），
并支持「单步执行 + 执行轨迹高亮」——把差分引擎的响应式事件源接到渲染层，
运行时实时高亮当前激活状态/变迁。
"""
import json
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from core import load_config, build_adapter, renderers
from core.adapters_io import graph_to_mermaid, graph_to_dot

_KINDS = [
    ("state_machine", "state_machines", "状态机/HSM"),
    ("behavior_tree", "behavior_trees", "行为树"),
    ("decision_tree", "decision_trees", "决策树"),
    ("petri_net", "petri_nets", "Petri 网"),
    ("markov_chain", "markov_chains", "马尔可夫链"),
    ("rule_engine", "rule_engines", "规则引擎"),
    ("difference_engine", "difference_engine", "差分引擎"),
]


def _log(text_widget, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    text_widget.config(state="normal")
    text_widget.insert("end", f"[{ts}] {msg}\n")
    text_widget.see("end")
    text_widget.config(state="disabled")


class VisualizationTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.engine = None
        self.kind = _KINDS[0][0]
        self.name = ""
        self._build_ui()
        self._on_kind()

    def _build_ui(self):
        tk.Label(self, text="图形化渲染（P0-2）",
                 font=("Arial", 14, "bold"), fg="#00838F").pack(
            anchor="w", pady=(0, 4))

        ctrl = tk.Frame(self)
        ctrl.pack(fill="x", pady=4)
        tk.Label(ctrl, text="范式:").pack(side="left")
        self.kind_var = tk.StringVar(value=_KINDS[0][2])
        self.kind_cb = ttk.Combobox(ctrl, textvariable=self.kind_var,
                                    width=14, state="readonly")
        self.kind_cb["values"] = [k[2] for k in _KINDS]
        self.kind_cb.pack(side="left", padx=4)
        self.kind_cb.bind("<<ComboboxSelected>>", lambda e: self._on_kind())

        tk.Label(ctrl, text="实例:").pack(side="left")
        self.name_var = tk.StringVar()
        self.name_cb = ttk.Combobox(ctrl, textvariable=self.name_var,
                                    width=18, state="readonly")
        self.name_cb.pack(side="left", padx=4)
        self.name_cb.bind("<<ComboboxSelected>>", lambda e: self._on_instance())

        ttk.Button(ctrl, text="▶ step", command=self._on_step).pack(
            side="left", padx=4)
        ttk.Button(ctrl, text="🔄 reset", command=self._on_reset).pack(
            side="left", padx=2)
        ttk.Button(ctrl, text="📈 渲染", command=self._on_render).pack(
            side="left", padx=2)

        mid = tk.Frame(self)
        mid.pack(fill="both", expand=True)
        left = tk.LabelFrame(mid, text=" 结构图 (ASCII · 轨迹高亮) ",
                             font=("Arial", 10, "bold"), padx=6, pady=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.graph_text = tk.Text(left, font=("Consolas", 9), wrap="none",
                                  bg="#E0F7FA", relief="flat", borderwidth=0)
        self.graph_text.pack(fill="both", expand=True)

        right = tk.LabelFrame(mid, text=" 导出 (Mermaid / DOT) ",
                              font=("Arial", 10, "bold"), padx=6, pady=6)
        right.pack(side="right", fill="both", expand=True)
        fmt = tk.Frame(right)
        fmt.pack(fill="x")
        self.fmt_var = tk.StringVar(value="mermaid")
        ttk.Radiobutton(fmt, text="Mermaid", variable=self.fmt_var,
                        value="mermaid", command=self._on_render).pack(side="left")
        ttk.Radiobutton(fmt, text="DOT", variable=self.fmt_var,
                        value="dot", command=self._on_render).pack(side="left")
        self.export_text = tk.Text(right, font=("Consolas", 9), wrap="word",
                                   bg="#263238", fg="#80DEEA", relief="flat",
                                   borderwidth=0)
        self.export_text.pack(fill="both", expand=True)
        ttk.Button(right, text="导出到文件", command=self._on_export).pack(
            fill="x", pady=(4, 0))

        self.name_map = {k[2]: k[0] for k in _KINDS}

    # ---- 事件 ----
    def _on_kind(self):
        label = self.kind_var.get()
        self.kind = self.name_map.get(label, self.kind)
        section = dict((k[0], k[1]) for k in _KINDS)[self.kind]
        names = list(self.full_config.get(section, {}).keys())
        self.name_cb["values"] = names
        if names:
            self.name_var.set(names[0])
            self._on_instance()

    def _on_instance(self):
        self.name = self.name_var.get()
        self.engine = build_adapter(self.kind, self.name, self.full_config)
        self._on_render()

    def _on_step(self):
        if not self.engine:
            return
        self.engine.step()
        self._on_render()
        _log(self.export_text, f"step -> {self.name}")

    def _on_reset(self):
        if not self.engine:
            return
        self.engine.reset()
        self._on_render()

    def _on_render(self):
        if not self.engine:
            return
        g = self.engine.visualize()
        self.graph_text.config(state="normal")
        self.graph_text.delete("1.0", "end")
        self.graph_text.insert("1.0", renderers.to_ascii(g))
        self.graph_text.config(state="disabled")
        self._render_export(g)

    def _render_export(self, g):
        fmt = self.fmt_var.get()
        text = graph_to_mermaid(g) if fmt == "mermaid" else graph_to_dot(g)
        self.export_text.config(state="normal")
        self.export_text.delete("1.0", "end")
        self.export_text.insert("1.0", text)
        self.export_text.config(state="disabled")

    def _on_export(self):
        from tkinter import filedialog
        fmt = self.fmt_var.get()
        ext = "mmd" if fmt == "mermaid" else "dot"
        path = filedialog.asksaveasfilename(
            defaultextension=f".{ext}",
            filetypes=[(fmt.upper(), f"*.{ext}")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.export_text.get("1.0", "end"))
            _log(self.export_text, f"已导出: {path}")
