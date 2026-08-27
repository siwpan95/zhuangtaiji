# -*- coding: utf-8 -*-
"""
编排工作台 Tab（P1-1）
====================

加载 config 的 ``orchestration`` 段，把多个引擎按声明式绑定串联：一个引擎的事件
触发另一个引擎的动作。点击「运行」即驱动跨引擎协同，并展示事件/动作轨迹。
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from core import load_config
from core.orchestrator import Orchestrator, build_orchestrator_from_config


def _log(text_widget, msg):
    text_widget.config(state="normal")
    text_widget.insert("end", msg + "\n")
    text_widget.see("end")
    text_widget.config(state="disabled")


class OrchestratorTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.orch_specs = self.full_config.get("orchestration", {})
        self.orch: Orchestrator = None
        self.name = ""
        self._build_ui()
        if self.orch_specs:
            self.name_var.set(list(self.orch_specs.keys())[0])
            self._on_select()

    def _build_ui(self):
        tk.Label(self, text="范式协同 / 编排（P1-1）",
                 font=("Arial", 14, "bold"), fg="#5E35B1").pack(
            anchor="w", pady=(0, 4))
        ctrl = tk.Frame(self)
        ctrl.pack(fill="x", pady=4)
        tk.Label(ctrl, text="编排方案:").pack(side="left")
        self.name_var = tk.StringVar()
        cb = ttk.Combobox(ctrl, textvariable=self.name_var, width=22,
                          state="readonly")
        cb["values"] = list(self.orch_specs.keys())
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_select())
        ttk.Button(ctrl, text="▶ 运行", command=self._on_run).pack(
            side="left", padx=4)
        ttk.Button(ctrl, text="🔄 重置", command=self._on_select).pack(
            side="left", padx=2)

        self.text = tk.Text(self, font=("Consolas", 9), wrap="word",
                            bg="#EDE7F6", relief="flat", borderwidth=0,
                            padx=8, pady=8)
        self.text.pack(fill="both", expand=True, pady=4)

    def _on_select(self):
        self.name = self.name_var.get()
        self.orch = build_orchestrator_from_config(self.full_config, self.name)
        self._show()

    def _on_run(self):
        if not self.orch:
            return
        self.orch.start()
        self._show()

    def _show(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        if self.orch:
            self.text.insert("1.0", self.orch.report())
        else:
            self.text.insert("1.0", "（config.json 中无 orchestration 段）")
        self.text.config(state="disabled")
