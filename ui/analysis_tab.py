# -*- coding: utf-8 -*-
"""
形式化分析 Tab（P2-1）
======================

对所选范式引擎做形式化分析：Petri 可达性/有界性/死锁/活性、状态机可达/不可达/环、
马尔可夫吸收概率与期望步数、决策树路径覆盖与特征重要性。从「能跑」升级到「能证明」。
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from core import load_config, analysis

_KINDS = [
    ("petri_net", "petri_nets", "Petri 网"),
    ("state_machine", "state_machines", "状态机/HSM"),
    ("markov_chain", "markov_chains", "马尔可夫链"),
    ("decision_tree", "decision_trees", "决策树"),
]

_KIND_MAP = {k[2]: k[0] for k in _KINDS}
_SECTION = {k[0]: k[1] for k in _KINDS}


def _log(text_widget, msg):
    text_widget.config(state="normal")
    text_widget.insert("end", msg + "\n")
    text_widget.see("end")
    text_widget.config(state="disabled")


class AnalysisTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.kind = _KINDS[0][0]
        self._build_ui()
        self._on_kind()

    def _build_ui(self):
        tk.Label(self, text="形式化分析（P2-1）",
                 font=("Arial", 14, "bold"), fg="#37474F").pack(
            anchor="w", pady=(0, 4))
        ctrl = tk.Frame(self)
        ctrl.pack(fill="x", pady=4)
        tk.Label(ctrl, text="范式:").pack(side="left")
        self.kind_var = tk.StringVar(value=_KINDS[0][2])
        cb = ttk.Combobox(ctrl, textvariable=self.kind_var, width=14,
                          state="readonly")
        cb["values"] = [k[2] for k in _KINDS]
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_kind())

        tk.Label(ctrl, text="实例:").pack(side="left")
        self.name_var = tk.StringVar()
        self.name_cb = ttk.Combobox(ctrl, textvariable=self.name_var,
                                    width=18, state="readonly")
        self.name_cb.pack(side="left", padx=4)
        ttk.Button(ctrl, text="🔍 分析", command=self._on_analyze).pack(
            side="left", padx=4)

        self.text = tk.Text(self, font=("Consolas", 10), wrap="word",
                            bg="#ECEFF1", relief="flat", borderwidth=0,
                            padx=8, pady=8)
        self.text.pack(fill="both", expand=True, pady=4)

    def _on_kind(self):
        self.kind = _KIND_MAP.get(self.kind_var.get(), self.kind)
        names = list(self.full_config.get(_SECTION[self.kind], {}).keys())
        self.name_cb["values"] = names
        if names:
            self.name_var.set(names[0])
            self._on_analyze()

    def _on_analyze(self):
        name = self.name_var.get()
        spec = self.full_config[_SECTION[self.kind]][name]
        out = analysis.format_analysis(self.kind, spec)
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", f"=== {name} ===\n\n{out}\n")
        self.text.config(state="disabled")
