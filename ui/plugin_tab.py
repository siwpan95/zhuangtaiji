# -*- coding: utf-8 -*-
"""
插件范式 Tab（P0-1 接入）
=======================

由插件注册表驱动：对任意 ``EnginePlugin``（含 ``core/plugins/`` 自动发现的范式，
如决策表、LLM Agent）生成一个通用 Tab——无需为每种新范式写专属 UI。
本文件证明「加一个引擎文件即获得工作台入口」的扩展接缝。
"""
import json
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from core import renderers
from core.plugin import EnginePlugin


def _log(text_widget, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    text_widget.config(state="normal")
    text_widget.insert("end", f"[{ts}] {msg}\n")
    text_widget.see("end")
    text_widget.config(state="disabled")


class PluginTab(tk.Frame):
    def __init__(self, master, plugin: EnginePlugin):
        super().__init__(master)
        self.plugin = plugin
        self.engine = None
        # 各插件的示例输入（ctx）
        self.example_ctx = {
            "decision_table": '{"vip": true, "load": 90}',
            "llm_agent": '{"state": "idle", "legal_events": ["start","complete"]}',
        }.get(plugin.kind, "{}")
        self._build_ui()
        self._on_instance()

    def _build_ui(self):
        tk.Label(self, text=f"插件 · {self.plugin.label}（P0-1）",
                 font=("Arial", 13, "bold"), fg="#00695C").pack(
            anchor="w", pady=(0, 2))
        tk.Label(self, text=self.plugin.description,
                 font=("Arial", 9), fg="#888").pack(anchor="w", pady=(0, 4))

        ctrl = tk.Frame(self)
        ctrl.pack(fill="x", pady=4)
        tk.Label(ctrl, text="实例:").pack(side="left")
        self.name_var = tk.StringVar()
        self.name_cb = ttk.Combobox(ctrl, textvariable=self.name_var,
                                    width=20, state="readonly")
        specs = self.plugin.specs_provider()
        self.name_cb["values"] = list(specs.keys())
        if specs:
            self.name_var.set(list(specs.keys())[0])
        self.name_cb.pack(side="left", padx=4)
        self.name_cb.bind("<<ComboboxSelected>>", lambda e: self._on_instance())
        ttk.Button(ctrl, text="▶ step", command=self._on_step).pack(
            side="left", padx=4)
        ttk.Button(ctrl, text="🔄 reset", command=self._on_instance).pack(
            side="left", padx=2)

        mid = tk.Frame(self)
        mid.pack(fill="both", expand=True)
        left = tk.LabelFrame(mid, text=" 输入 / 结论 ",
                             font=("Arial", 10, "bold"), padx=6, pady=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.ctx_var = tk.StringVar(value=self.example_ctx)
        tk.Entry(left, textvariable=self.ctx_var, font=("Consolas", 9)
                 ).pack(fill="x", pady=(0, 4))
        self.summary_text = tk.Text(left, font=("Consolas", 9), wrap="word",
                                    bg="#E0F2F1", relief="flat", borderwidth=0)
        self.summary_text.pack(fill="both", expand=True)

        right = tk.LabelFrame(mid, text=" 结构图 (ASCII) ",
                              font=("Arial", 10, "bold"), padx=6, pady=6)
        right.pack(side="right", fill="both", expand=True)
        self.graph_text = tk.Text(right, font=("Consolas", 9), wrap="none",
                                  bg="#E0F7FA", relief="flat", borderwidth=0)
        self.graph_text.pack(fill="both", expand=True)

    def _on_instance(self):
        name = self.name_var.get()
        if not name:
            return
        self.engine = self.plugin.build(name)
        self._refresh()

    def _on_step(self):
        if not self.engine:
            return
        try:
            ctx = json.loads(self.ctx_var.get() or "{}")
        except Exception as e:
            _log(self.summary_text, f"ctx JSON 错误: {e}")
            return
        res = self.engine.step(ctx)
        _log(self.summary_text, f"step -> {res.value}")
        self._refresh()

    def _refresh(self):
        if not self.engine:
            return
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", self.engine.summary())
        self.summary_text.config(state="disabled")
        g = self.engine.visualize()
        self.graph_text.config(state="normal")
        self.graph_text.delete("1.0", "end")
        self.graph_text.insert("1.0", renderers.to_ascii(g))
        self.graph_text.config(state="disabled")
