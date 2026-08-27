# -*- coding: utf-8 -*-
"""
多范式决策引擎 · 可视化工作台
================================
基于联网调研的四种计算/决策范式，对原「状态机工作流引擎」做全面增强：

  * 状态机 (FSM / HSM)  —— 强调「状态 + 事件转移」的时序演化；新增层次状态
    （嵌套子状态 / 历史 / 内部转移）与声明式 Guard。
  * 行为树 (Behavior Tree) —— 「根节点驱动、每帧重新评估」的响应式行为编排。
  * 决策树 (Decision Tree) —— 基于特征空间的一次性路由决策。
  * 差分机 (Difference Engine) —— 巴贝奇有限差分（加法递推多项式）+ 状态差量
    / 响应式脏检查。

界面采用 ttk.Notebook 分页，每个范式一个独立工作台。
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from core import (
    GenericStateMachine, create_state_machine, load_config,
    build_behavior_tree, Blackboard,
    build_decision_tree,
    FiniteDifference, StateDiff, ReactiveTracker,
    build_petri_net, build_markov_chain, build_rule_engine,
)
from engine import CanvasProgressBar, THEME_DARK, ease_out_cubic

# ---- P0~P3 新增 Tab ----
from core.plugin import PluginRegistry, ensure_discovered
from ui.visualization_tab import VisualizationTab
from ui.analysis_tab import AnalysisTab
from ui.orchestrator_tab import OrchestratorTab
from ui.plugin_tab import PluginTab

_BUILTIN_KINDS = {
    "state_machine", "behavior_tree", "decision_tree", "petri_net",
    "markov_chain", "rule_engine", "difference_engine",
}


# ==========================================================
# 通用工具
# ==========================================================
def log_into(text_widget, msg, color=None):
    ts = datetime.now().strftime("%H:%M:%S")
    text_widget.config(state="normal")
    text_widget.insert("end", f"[{ts}] {msg}\n")
    text_widget.see("end")
    text_widget.config(state="disabled")


# ==========================================================
# Tab 1：工作流引擎（原状态机管线 + 层次状态机演示）
# ==========================================================
class WorkflowEngineTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        machine_names = list(self.full_config["state_machines"].keys())
        self.sm_instances = {}
        for name in machine_names:
            self.sm_instances[name] = create_state_machine(
                name, self.full_config, on_action=self._on_sm_action
            )
        self.pipeline = machine_names
        self.stage_index = 0
        self.is_running = False
        self.auto_mode = True
        self.event_log = []
        self._build_ui()
        self._bind_current_sm()

    # ---- UI ----
    def _build_ui(self):
        title = tk.Frame(self)
        title.pack(fill="x", pady=(0, 8))
        tk.Label(title, text="工作流引擎",
                 font=("Arial", 14, "bold"), fg="#1565C0").pack(side="left")
        tk.Label(title, text="平面状态机 → 层次状态机(HSM) → 进度条联动",
                 font=("Arial", 9), fg="#888").pack(side="left", padx=12)

        main = tk.Frame(self)
        main.pack(fill="both", expand=True)

        left = tk.LabelFrame(main, text=" 管线状态 ", font=("Arial", 10, "bold"),
                             padx=8, pady=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.state_canvas = tk.Canvas(left, width=280, height=320,
                                       bg="#FAFAFA", highlightthickness=0)
        self.state_canvas.pack(fill="both", expand=True)

        right = tk.Frame(main, width=340)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        cf = tk.LabelFrame(right, text=" 当前输出 ", font=("Arial", 10, "bold"),
                           padx=8, pady=8)
        cf.pack(fill="x", pady=(0, 8))
        self.content_text = tk.Text(cf, height=4, width=42,
                                    font=("Microsoft YaHei", 10), wrap="word",
                                    bg="#F5F5F5", relief="flat", borderwidth=0,
                                    padx=6, pady=6)
        self.content_text.pack(fill="x")
        self.content_text.insert("1.0", "等待启动工作流...")
        self.content_text.config(state="disabled")

        bf = tk.LabelFrame(right, text=" 进度 ", font=("Arial", 10, "bold"),
                           padx=8, pady=8)
        bf.pack(fill="x", pady=(0, 8))
        self.progress_bar = CanvasProgressBar(bf, width=300, height=30,
                                              show_percentage=True)

        btn = tk.Frame(right)
        btn.pack(fill="x", pady=(0, 8))
        self.start_btn = tk.Button(btn, text="▶ 启动工作流", command=self.on_start,
                                   font=("Arial", 10, "bold"), bg="#4CAF50",
                                   fg="white", activebackground="#388E3C",
                                   relief="flat", padx=15, pady=4)
        self.start_btn.pack(side="left", padx=(0, 5))
        self.pause_btn = tk.Button(btn, text="⏸ 暂停", command=self.on_pause_resume,
                                   font=("Arial", 10), bg="#FF9800", fg="white",
                                   activebackground="#F57C00", relief="flat",
                                   padx=15, pady=4, state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 5))
        self.reset_btn = tk.Button(btn, text="↺ 重置", command=self.on_reset,
                                   font=("Arial", 10), bg="#9E9E9E", fg="white",
                                   relief="flat", padx=15, pady=4)
        self.reset_btn.pack(side="left")

        auto = tk.Frame(right)
        auto.pack(fill="x", pady=(0, 4))
        self.auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(auto, text="🔄 自动循环（条件满足时自动继续）",
                       variable=self.auto_var, command=self._toggle_auto_mode,
                       font=("Arial", 9)).pack(side="left")

        lf = tk.LabelFrame(right, text=" 事件日志 ", font=("Arial", 10, "bold"),
                           padx=8, pady=8)
        lf.pack(fill="both", expand=True)
        self.log_text = tk.Text(lf, height=10, width=42, font=("Consolas", 8),
                                wrap="word", bg="#263238", fg="#B2CCD6",
                                relief="flat", borderwidth=0, padx=6, pady=6)
        self.log_text.pack(fill="both", expand=True)
        log_into(self.log_text, "系统就绪，等待启动工作流...")
        self._draw_pipeline()

    # ---- 绑定 ----
    def _bind_current_sm(self):
        name = self.pipeline[self.stage_index]
        self.progress_bar.bind_state_machine(self.sm_instances[name])

    @property
    def current_sm(self):
        return self.progress_bar.bound_sm

    # ---- 控制 ----
    def _toggle_auto_mode(self):
        self.auto_mode = self.auto_var.get()
        log_into(self.log_text, "🔄 自动模式" if self.auto_mode else "👆 手动模式")

    def on_start(self):
        if self.is_running:
            return
        self.is_running = True
        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.reset_btn.config(state="disabled")
        sm_name = self.pipeline[self.stage_index]
        log_into(self.log_text, f"▶ 启动 [{sm_name}] 工作流")
        if self.current_sm.can_trigger("start"):
            sid, content = self.current_sm.trigger("start")
            self._update_content(content)
            self._draw_pipeline()
        self.progress_bar.animate(step=3, delay=25,
                                  on_complete=self._on_progress_finish,
                                  easing="ease_out")

    def on_pause_resume(self):
        if self.progress_bar.is_paused:
            self.progress_bar.resume()
            self.pause_btn.config(text="⏸ 暂停")
            log_into(self.log_text, "▶ 恢复动画")
        else:
            self.progress_bar.pause()
            self.pause_btn.config(text="▶ 继续")
            log_into(self.log_text, "⏸ 暂停动画")

    def on_reset(self):
        self.progress_bar.stop()
        self.stage_index = 0
        self.is_running = False
        self.event_log.clear()
        for name in self.pipeline:
            self.sm_instances[name] = create_state_machine(
                name, self.full_config, on_action=self._on_sm_action
            )
        self._bind_current_sm()
        self.start_btn.config(state="normal", text="▶ 启动工作流")
        self.pause_btn.config(state="disabled", text="⏸ 暂停")
        self.reset_btn.config(state="normal")
        self._update_content("等待启动工作流...")
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        log_into(self.log_text, "系统已重置，等待启动工作流...")
        self._draw_pipeline()

    def _on_progress_finish(self):
        sm = self.current_sm
        sm_name = self.pipeline[self.stage_index]
        events = sm.available_events
        complete_events = [e for e in events if e in ("complete", "validate_ok")]
        if complete_events:
            event = complete_events[0]
            sid, content = sm.trigger(event)
            self._update_content(content)
            self._draw_pipeline()
            log_into(self.log_text, f"  ✓ [{sm_name}] {event} → {sid}")
        else:
            log_into(self.log_text, f"  ⚠ [{sm_name}] 无完成事件: {events}")
        self.progress_bar.reset()
        if self.auto_mode:
            self._draw_pipeline()
            self.after(500, self._check_and_continue)
        else:
            self._finish_manual_cycle(sm, sm_name)

    def _finish_manual_cycle(self, sm, sm_name):
        self.is_running = False
        self.pause_btn.config(state="disabled", text="⏸ 暂停")
        if not sm.available_events:
            if self.stage_index + 1 < len(self.pipeline):
                self.stage_index += 1
                self._bind_current_sm()
                nxt = self.pipeline[self.stage_index]
                log_into(self.log_text, f"→ 进入下一阶段: [{nxt}]")
                self.start_btn.config(state="normal",
                                      text=f"▶ 启动 [{nxt.split('_')[-1]}]")
            else:
                log_into(self.log_text, "🎉 全部工作流执行完毕！")
                self.start_btn.config(state="normal", text="🔄 重新运行")
        else:
            self.start_btn.config(state="normal",
                                  text=f"▶ 继续 [{sm_name.split('_')[-1]}]")
        self.reset_btn.config(state="normal")
        self._draw_pipeline()

    def _check_and_continue(self):
        sm = self.current_sm
        sm_name = self.pipeline[self.stage_index]
        events = sm.available_events
        has_auto = any(e in ("complete", "validate_ok", "start") for e in events)
        if has_auto:
            log_into(self.log_text, f"  ✔ 条件满足 [{sm_name.split('_')[-1]}]")
            self._draw_pipeline()
            self._auto_continue()
        elif events:
            log_into(self.log_text, f"  [X] 需手动处理: {events}")
            self._finish_auto_cycle()
        elif self.stage_index + 1 < len(self.pipeline):
            log_into(self.log_text, f"  ✔ [{sm_name}] 到达终点，进入下一阶段")
            self.stage_index += 1
            self._bind_current_sm()
            nxt = self.pipeline[self.stage_index]
            log_into(self.log_text, f"  → 自动进入: [{nxt}]")
            self._draw_pipeline()
            if self.current_sm.can_trigger("start"):
                sid, content = self.current_sm.trigger("start")
                self._update_content(content)
                self._draw_pipeline()
            self.after(400, self._auto_continue)
        else:
            log_into(self.log_text, "🎉 全部工作流执行完毕！")
            self._finish_auto_cycle()

    def _auto_continue(self):
        self.progress_bar.animate(step=3, delay=25,
                                  on_complete=self._on_progress_finish,
                                  easing="ease_out")

    def _finish_auto_cycle(self):
        self.is_running = False
        self.pause_btn.config(state="disabled", text="⏸ 暂停")
        self.start_btn.config(state="normal", text="🔄 重新运行")
        self.reset_btn.config(state="normal")
        self._draw_pipeline()

    # ---- 辅助 ----
    def _update_content(self, text):
        self.content_text.config(state="normal")
        self.content_text.delete("1.0", "end")
        self.content_text.insert("1.0", text)
        self.content_text.config(state="disabled")

    def _on_sm_action(self, action_type, state_id, detail):
        desc = detail.get("description", "")
        if action_type == "enter":
            label, extra = "进入", (f" ({desc})" if desc else "")
        elif action_type == "exit":
            label, extra = "离开", (f" ({desc})" if desc else "")
        elif action_type == "transition":
            label = "转移"
            extra = f": {detail.get('from','?')} --[{detail.get('event','?')}]--> {state_id}"
        elif action_type == "internal":
            label, extra = "内部", f" (原地 #{detail.get('to','')})"
        else:
            return
        for name, sm in self.sm_instances.items():
            if sm.current_state_id.split("/")[-1] == state_id or \
               state_id in sm.current_state_id:
                log_into(self.log_text, f"  [{name}] {label} → {state_id}{extra}")
                break

    def _draw_pipeline(self):
        canvas = self.state_canvas
        canvas.delete("all")
        w = int(canvas.winfo_width()) if canvas.winfo_width() > 1 else 280
        h = int(canvas.winfo_height()) if canvas.winfo_height() > 1 else 320
        y_start = 20
        box_h, gap = 50, 20
        total_h = len(self.pipeline) * (box_h + gap)
        y_start = max(10, (h - total_h) // 2)
        for i, name in enumerate(self.pipeline):
            sm = self.sm_instances[name]
            y = y_start + i * (box_h + gap)
            desc = self.full_config["state_machines"][name].get("description", "")
            is_current = (i == self.stage_index)
            is_done = (i < self.stage_index)
            if is_current:
                fill, border, text_c, status = "#E3F2FD", "#1565C0", "#0D47A1", "进行中"
            elif is_done:
                fill, border, text_c, status = "#E8F5E9", "#4CAF50", "#1B5E20", "✓ 完成"
            else:
                fill, border, text_c, status = "#F5F5F5", "#BDBDBD", "#9E9E9E", "待执行"
            canvas.create_rectangle(15, y, w - 15, y + box_h, fill=fill,
                                    outline=border, width=2)
            canvas.create_text(25, y + 12, text=name.replace("SM_", ""), anchor="w",
                               font=("Arial", 11, "bold"), fill=text_c)
            canvas.create_text(25, y + 30, text=desc, anchor="w",
                               font=("Arial", 8), fill="#757575")
            info = sm.get_state_info()
            canvas.create_text(w - 20, y + 12, text=f"[{info['id']}]", anchor="e",
                               font=("Arial", 9, "bold"), fill=text_c)
            canvas.create_text(w - 20, y + 30, text=status, anchor="e",
                               font=("Arial", 8), fill=text_c)
            if is_current or is_done:
                ev = info.get("available_events", [])
                canvas.create_text(25, y + box_h - 6, text=f"可用事件: {ev}",
                                   anchor="w", font=("Consolas", 7), fill="#9E9E9E")
            if i < len(self.pipeline) - 1:
                canvas.create_line(w // 2, y + box_h + 2, w // 2, y + box_h + gap - 4,
                                   fill="#BDBDBD", width=2, arrow="last")
        legend_y = y_start + len(self.pipeline) * (box_h + gap) + 10
        if legend_y < h - 20:
            canvas.create_text(w // 2, legend_y + 5,
                               text=f"阶段 {self.stage_index + 1}/{len(self.pipeline)}",
                               font=("Arial", 9), fill="#1565C0")
            if self.progress_bar.progress > 0:
                canvas.create_text(w // 2, legend_y + 22,
                                   text=f"当前进度: {int(self.progress_bar.progress)}%",
                                   font=("Arial", 9), fill="#FF9800")


# ==========================================================
# Tab 2：行为树（Behavior Tree）
# ==========================================================
class BehaviorTreeTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.spec = self.full_config["behavior_trees"]["BT_SelfHeal"]
        self.bb = Blackboard()
        self.bt = build_behavior_tree(self.spec, blackboard=self.bb)
        self._build_ui()

    def _build_ui(self):
        title = tk.Frame(self)
        title.pack(fill="x", pady=(0, 8))
        tk.Label(title, text="行为树 (Behavior Tree)",
                 font=("Arial", 14, "bold"), fg="#6A1B9A").pack(side="left")
        tk.Label(title, text="根节点驱动 · 每帧重新评估 · 黑板共享",
                 font=("Arial", 9), fg="#888").pack(side="left", padx=12)

        main = tk.Frame(self)
        main.pack(fill="both", expand=True)

        left = tk.LabelFrame(main, text=" 黑板 (Blackboard) ",
                             font=("Arial", 10, "bold"), padx=8, pady=8)
        left.pack(side="left", fill="y", padx=(0, 8))
        self.fault_var = tk.BooleanVar()
        self.load_var = tk.IntVar(value=30)
        ttk.Checkbutton(left, text="fault (故障)", variable=self.fault_var,
                        command=self._sync_bb).pack(anchor="w", pady=2)
        tk.Label(left, text="load (负载):", font=("Arial", 9)).pack(anchor="w")
        tk.Scale(left, from_=0, to=100, orient="horizontal",
                 variable=self.load_var, command=lambda e: self._sync_bb()
                 ).pack(fill="x")
        ttk.Button(left, text="▶ tick 一次", command=self._on_tick).pack(
            fill="x", pady=6)
        ttk.Button(left, text="⏩ 连续运行 run()", command=self._on_run).pack(
            fill="x", pady=2)
        self.status_var = tk.StringVar(value="—")
        tk.Label(left, text="最近状态:", font=("Arial", 9)).pack(anchor="w", pady=(8, 0))
        tk.Label(left, textvariable=self.status_var, font=("Arial", 11, "bold"),
                 fg="#6A1B9A").pack(anchor="w")

        right = tk.Frame(main)
        right.pack(side="right", fill="both", expand=True)
        bf = tk.LabelFrame(right, text=" 黑板内容 ", font=("Arial", 10, "bold"),
                           padx=8, pady=8)
        bf.pack(fill="x", pady=(0, 8))
        self.bb_text = tk.Text(bf, height=5, width=40, font=("Consolas", 9),
                               wrap="word", bg="#F3E5F5", relief="flat",
                               borderwidth=0, padx=6, pady=6)
        self.bb_text.pack(fill="x")
        self.bb_text.insert("1.0", "{}")
        self.bb_text.config(state="disabled")

        tf = tk.LabelFrame(right, text=" 行为树结构 / 日志 ",
                           font=("Arial", 10, "bold"), padx=8, pady=8)
        tf.pack(fill="both", expand=True)
        self.bt_log = tk.Text(tf, height=12, width=40, font=("Consolas", 8),
                              wrap="word", bg="#263238", fg="#CE93D8",
                              relief="flat", borderwidth=0, padx=6, pady=6)
        self.bt_log.pack(fill="both", expand=True)
        log_into(self.bt_log, "行为树已加载: " + self.spec.get("name", ""))
        # 打印树结构
        log_into(self.bt_log, self._tree_preview(self.bt.root, 0))

    def _sync_bb(self):
        self.bb.set("fault", self.fault_var.get())
        self.bb.set("load", self.load_var.get())
        self._refresh_bb()

    def _refresh_bb(self):
        self.bb_text.config(state="normal")
        self.bb_text.delete("1.0", "end")
        self.bb_text.insert("1.0", str(self.bb.snapshot()))
        self.bb_text.config(state="disabled")

    def _on_tick(self):
        self._sync_bb()
        status = self.bt.tick()
        self.status_var.set(status.value)
        log_into(self.bt_log, f"tick#{self.bt.tick_count} → {status.value}  "
                               f"黑板={self.bb.snapshot()}")
        self._refresh_bb()

    def _on_run(self):
        self._sync_bb()
        status = self.bt.run(max_ticks=50)
        self.status_var.set(status.value)
        log_into(self.bt_log, f"run() → {status.value}  "
                               f"黑板={self.bb.snapshot()}")
        self._refresh_bb()

    def _tree_preview(self, node, depth):
        pad = "  " * depth
        tag = node.name
        if getattr(node, "children", None):
            lines = [f"{pad}- {tag}"]
            for c in node.children:
                lines.append(self._tree_preview(c, depth + 1))
            return "\n".join(lines)
        if getattr(node, "child", None):
            return f"{pad}- {tag}\n" + self._tree_preview(node.child, depth + 1)
        return f"{pad}- {tag}"


# ==========================================================
# Tab 3：决策树（Decision Tree）
# ==========================================================
class DecisionTreeTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.spec = self.full_config["decision_trees"]["DT_Route"]
        self.dt = build_decision_tree(self.spec)
        self._build_ui()

    def _build_ui(self):
        title = tk.Frame(self)
        title.pack(fill="x", pady=(0, 8))
        tk.Label(title, text="决策树 (Decision Tree)",
                 font=("Arial", 14, "bold"), fg="#00695C").pack(side="left")
        tk.Label(title, text="基于特征空间的一次性路由决策",
                 font=("Arial", 9), fg="#888").pack(side="left", padx=12)

        main = tk.Frame(self)
        main.pack(fill="both", expand=True)
        left = tk.LabelFrame(main, text=" 特征输入 ",
                             font=("Arial", 10, "bold"), padx=8, pady=8)
        left.pack(side="left", fill="y", padx=(0, 8))
        self.vip_var = tk.BooleanVar()
        self.urgent_var = tk.BooleanVar()
        self.load_var = tk.IntVar(value=40)
        ttk.Checkbutton(left, text="vip (VIP用户)", variable=self.vip_var
                        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(left, text="urgent (紧急)", variable=self.urgent_var
                        ).pack(anchor="w", pady=2)
        tk.Label(left, text="load (负载):", font=("Arial", 9)).pack(anchor="w")
        tk.Scale(left, from_=0, to=100, orient="horizontal",
                 variable=self.load_var).pack(fill="x")
        ttk.Button(left, text="⚖ 决策", command=self._on_decide).pack(
            fill="x", pady=8)

        right = tk.Frame(main)
        right.pack(side="right", fill="both", expand=True)
        rf = tk.LabelFrame(right, text=" 决策结论 ", font=("Arial", 10, "bold"),
                           padx=8, pady=8)
        rf.pack(fill="x", pady=(0, 8))
        self.result_var = tk.StringVar(value="—")
        tk.Label(rf, text="结论标签:", font=("Arial", 9)).pack(anchor="w")
        tk.Label(rf, textvariable=self.result_var, font=("Arial", 13, "bold"),
                 fg="#00695C").pack(anchor="w", pady=(0, 6))
        self.payload_var = tk.StringVar(value="")
        tk.Label(rf, textvariable=self.payload_var, font=("Arial", 9),
                 fg="#555").pack(anchor="w")

        pf = tk.LabelFrame(right, text=" 命中路径 / 日志 ",
                           font=("Arial", 10, "bold"), padx=8, pady=8)
        pf.pack(fill="both", expand=True)
        self.dt_log = tk.Text(pf, height=12, width=40, font=("Consolas", 8),
                              wrap="word", bg="#263238", fg="#80CBC4",
                              relief="flat", borderwidth=0, padx=6, pady=6)
        self.dt_log.pack(fill="both", expand=True)
        log_into(self.dt_log, "决策树已加载: " + self.spec.get("name", ""))

    def _on_decide(self):
        feats = {
            "vip": self.vip_var.get(),
            "urgent": self.urgent_var.get(),
            "load": self.load_var.get(),
        }
        res = self.dt.decide(feats)
        self.result_var.set(str(res.label))
        self.payload_var.set(f"payload={res.payload}")
        log_into(self.dt_log, f"特征={feats}")
        log_into(self.dt_log, f"  → 结论: {res.label}")
        log_into(self.dt_log, f"  → 路径: {' > '.join(res.path)}")


# ==========================================================
# Tab 4：差分引擎（Difference Engine）
# ==========================================================
class DifferenceEngineTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.fd = FiniteDifference(
            self.full_config["difference_engine"]["progress_predictor"]["initial_values"]
        )
        self.tracker_state = {"status": "idle", "progress": 0}
        self.tracker = ReactiveTracker(
            dict(self.tracker_state),
            on_change=self._on_diff
        )
        self._build_ui()

    def _build_ui(self):
        title = tk.Frame(self)
        title.pack(fill="x", pady=(0, 8))
        tk.Label(title, text="差分机 (Difference Engine)",
                 font=("Arial", 14, "bold"), fg="#EF6C00").pack(side="left")
        tk.Label(title, text="巴贝奇有限差分(加法递推) + 状态差量/响应式",
                 font=("Arial", 9), fg="#888").pack(side="left", padx=12)

        main = tk.Frame(self)
        main.pack(fill="both", expand=True)
        left = tk.LabelFrame(main, text=" 有限差分 · 进度预测 ",
                             font=("Arial", 10, "bold"), padx=8, pady=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.fd_text = tk.Text(left, height=8, width=42, font=("Consolas", 9),
                               wrap="word", bg="#FFF3E0", relief="flat",
                               borderwidth=0, padx=6, pady=6)
        self.fd_text.pack(fill="x")
        ttk.Button(left, text="➕ 推进一步 (差分加法)", command=self._on_step
                   ).pack(fill="x", pady=6)
        ttk.Button(left, text="⏭ 生成后续 5 步", command=self._on_gen5
                   ).pack(fill="x", pady=2)
        self._refresh_fd()

        right = tk.LabelFrame(main, text=" 状态差量 · 响应式脏检查 ",
                              font=("Arial", 10, "bold"), padx=8, pady=8)
        right.pack(side="right", fill="both", expand=True, padx=(0, 8))
        ctl = tk.Frame(right)
        ctl.pack(fill="x")
        tk.Label(ctl, text="status:").pack(side="left")
        self.ns_var = tk.StringVar(value="running")
        ttk.Combobox(ctl, textvariable=self.ns_var, width=10,
                     values=["idle", "running", "done", "error"]
                     ).pack(side="left", padx=4)
        tk.Label(ctl, text="progress:").pack(side="left")
        self.np_var = tk.IntVar(value=50)
        tk.Scale(ctl, from_=0, to=100, orient="horizontal",
                 variable=self.np_var, length=120).pack(side="left")
        ttk.Button(right, text="🔄 应用补丁 (仅变更触发回调)",
                   command=self._on_patch).pack(fill="x", pady=6)
        self.diff_log = tk.Text(right, height=12, width=40, font=("Consolas", 8),
                                wrap="word", bg="#263238", fg="#FFCC80",
                                relief="flat", borderwidth=0, padx=6, pady=6)
        self.diff_log.pack(fill="both", expand=True)
        log_into(self.diff_log, "响应式追踪器已初始化: " + str(self.tracker.state))

    def _refresh_fd(self):
        self.fd_text.config(state="normal")
        self.fd_text.delete("1.0", "end")
        self.fd_text.insert("1.0",
            f"多项式阶数: {self.fd.order}\n已有值({self.fd.count}): "
            f"{self.fd.history()}")
        self.fd_text.config(state="disabled")

    def _on_step(self):
        v = self.fd.step()
        log_into(self.diff_log, f"[差分] 推进一步 → {v}")
        self._refresh_fd()

    def _on_gen5(self):
        vs = self.fd.generate(5)
        log_into(self.diff_log, f"[差分] 后续5步 → {vs}")
        self._refresh_fd()

    def _on_patch(self):
        patch = {"status": self.ns_var.get(), "progress": self.np_var.get()}
        self.tracker.update(patch)

    def _on_diff(self, entries, state):
        summary = StateDiff.summary(entries) if entries else "无变化"
        log_into(self.diff_log, f"[差量] {summary}  | 新状态={state}")


# ==========================================================
# Tab 5：Petri 网（Petri Net）
# ==========================================================
class PetriNetTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.spec = self.full_config["petri_nets"]["PN_Order"]
        self.pn = build_petri_net(self.spec)
        self._build_ui()

    def _build_ui(self):
        title = tk.Frame(self)
        title.pack(fill="x", pady=(0, 8))
        tk.Label(title, text="Petri 网 (Petri Net)",
                 font=("Arial", 14, "bold"), fg="#C62828").pack(side="left")
        tk.Label(title, text="库所令牌 · 变迁使能 · 并发触发 · 抑制弧",
                 font=("Arial", 9), fg="#888").pack(side="left", padx=12)

        main = tk.Frame(self)
        main.pack(fill="both", expand=True)
        left = tk.LabelFrame(main, text=" 库所 / 令牌 ",
                             font=("Arial", 10, "bold"), padx=8, pady=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.place_text = tk.Text(left, height=12, width=40,
                                  font=("Consolas", 10), wrap="word",
                                  bg="#FFEBEE", relief="flat", borderwidth=0,
                                  padx=6, pady=6)
        self.place_text.pack(fill="both", expand=True)
        bf = tk.Frame(left)
        bf.pack(fill="x", pady=4)
        ttk.Button(bf, text="➡ 推进一步",
                   command=lambda: self._on_step("priority")).pack(
            side="left", fill="x", expand=True, padx=2)
        ttk.Button(bf, text="⚡ 全部触发",
                   command=lambda: self._on_step("all")).pack(
            side="left", fill="x", expand=True, padx=2)
        ttk.Button(bf, text="⏩ 自动运行",
                   command=self._on_run).pack(
            side="left", fill="x", expand=True, padx=2)

        right = tk.LabelFrame(main, text=" 使能变迁 / 日志 ",
                              font=("Arial", 10, "bold"), padx=8, pady=8)
        right.pack(side="right", fill="both", expand=True, padx=(0, 8))
        self.pn_log = tk.Text(right, height=12, width=40,
                              font=("Consolas", 8), wrap="word",
                              bg="#263238", fg="#EF9A9A", relief="flat",
                              borderwidth=0, padx=6, pady=6)
        self.pn_log.pack(fill="both", expand=True)
        log_into(self.pn_log, "Petri 网已加载: " + self.spec.get("name", ""))
        self._refresh()

    def _refresh(self):
        self.place_text.config(state="normal")
        self.place_text.delete("1.0", "end")
        lines = [f"{p} = {self.pn.places[p]} 令牌" for p in self.pn.places]
        enabled = self.pn.enabled_transitions()
        lines.append("")
        lines.append(f"使能变迁: {enabled if enabled else '（无 · 死锁/终止）'}")
        self.place_text.insert("1.0", "\n".join(lines))
        self.place_text.config(state="disabled")

    def _on_step(self, strategy):
        fired = self.pn.step(strategy=strategy)
        if fired:
            log_into(self.pn_log, f"触发 {fired} → {self.pn.format_marking()}")
        else:
            log_into(self.pn_log, "无可使能变迁（死锁/终止）")
        self._refresh()

    def _on_run(self):
        trace = self.pn.run(
            strategy="priority", max_steps=40,
            on_step=lambda f, m: log_into(self.pn_log, f"触发 {f} → {m}"))
        log_into(self.pn_log, f"运行结束，共 {len(trace)} 个标记点")
        self._refresh()


# ==========================================================
# Tab 6：规则引擎（Rule Engine / RETE）
# ==========================================================
class RuleEngineTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.spec = self.full_config["rule_engines"]["RE_Promo"]
        self.engine = build_rule_engine(self.spec)
        self._build_ui()

    def _build_ui(self):
        title = tk.Frame(self)
        title.pack(fill="x", pady=(0, 8))
        tk.Label(title, text="规则引擎 (Rule Engine)",
                 font=("Arial", 14, "bold"), fg="#4527A0").pack(side="left")
        tk.Label(title, text="RETE 正向推理 · α/β 匹配 · 议程冲突消解",
                 font=("Arial", 9), fg="#888").pack(side="left", padx=12)

        main = tk.Frame(self)
        main.pack(fill="both", expand=True)
        left = tk.LabelFrame(main, text=" 工作记忆 (Facts) ",
                             font=("Arial", 10, "bold"), padx=8, pady=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.fact_text = tk.Text(left, height=12, width=40,
                                 font=("Consolas", 9), wrap="word",
                                 bg="#EDE7F6", relief="flat", borderwidth=0,
                                 padx=6, pady=6)
        self.fact_text.pack(fill="both", expand=True)

        right = tk.LabelFrame(main, text=" 推理日志 / 议程 ",
                              font=("Arial", 10, "bold"), padx=8, pady=8)
        right.pack(side="right", fill="both", expand=True, padx=(0, 8))
        self.rule_log = tk.Text(right, height=12, width=40,
                                font=("Consolas", 8), wrap="word",
                                bg="#263238", fg="#B39DDB", relief="flat",
                                borderwidth=0, padx=6, pady=6)
        self.rule_log.pack(fill="both", expand=True)

        ctl = tk.Frame(left)
        ctl.pack(fill="x", pady=4)
        ttk.Button(ctl, text="▶ 正向推理 forward_chain",
                   command=self._on_chain).pack(side="left", fill="x",
                                                 expand=True, padx=2)
        ttk.Button(ctl, text="🔄 重置",
                   command=self._on_reset).pack(side="left", fill="x",
                                                 expand=True, padx=2)

        log_into(self.rule_log, "规则引擎已加载: " + self.spec.get("name", ""))
        self._refresh_facts()

    def _refresh_facts(self):
        self.fact_text.config(state="normal")
        self.fact_text.delete("1.0", "end")
        self.fact_text.insert("1.0", self.engine.facts_summary())
        self.fact_text.config(state="disabled")

    def _on_chain(self):
        log = self.engine.forward_chain()
        for e in log:
            if e["type"] == "fire":
                log_into(self.rule_log,
                         f"⚡ 触发规则 [{e['rule']}] 绑定={e['bindings']}")
            else:
                log_into(self.rule_log, f"  · {e['msg']}")
        log_into(self.rule_log,
                 f"推理完成，事实数={len(self.engine.working_memory)}")
        self._refresh_facts()

    def _on_reset(self):
        self.engine = build_rule_engine(self.spec)
        self.rule_log.config(state="normal")
        self.rule_log.delete("1.0", "end")
        self.rule_log.config(state="disabled")
        log_into(self.rule_log, "已重置工作记忆")
        self._refresh_facts()


# ==========================================================
# Tab 7：马尔可夫链（Markov Chain）
# ==========================================================
class MarkovTab(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.full_config = load_config()
        self.chains = self.full_config["markov_chains"]
        self.current_name = list(self.chains.keys())[0]
        self.mc = build_markov_chain(self.chains[self.current_name])
        self._build_ui()

    def _build_ui(self):
        title = tk.Frame(self)
        title.pack(fill="x", pady=(0, 8))
        tk.Label(title, text="马尔可夫链 (Markov Chain)",
                 font=("Arial", 14, "bold"), fg="#00695C").pack(side="left")
        tk.Label(title, text="概率状态机 · 转移矩阵 · 稳态分布",
                 font=("Arial", 9), fg="#888").pack(side="left", padx=12)

        main = tk.Frame(self)
        main.pack(fill="both", expand=True)
        left = tk.LabelFrame(main, text=" 控制 ",
                             font=("Arial", 10, "bold"), padx=8, pady=8)
        left.pack(side="left", fill="y", padx=(0, 8))
        tk.Label(left, text="选择链:", font=("Arial", 9)).pack(anchor="w")
        self.chain_var = tk.StringVar(value=self.current_name)
        ttk.Combobox(left, textvariable=self.chain_var,
                     values=list(self.chains.keys()),
                     state="readonly").pack(fill="x", pady=2)
        self.chain_var.trace("w", self._on_select)
        ttk.Button(left, text="▶ 单步演化",
                   command=self._on_step).pack(fill="x", pady=4)
        ttk.Button(left, text="⏩ 仿真 20 步",
                   command=self._on_sim).pack(fill="x", pady=2)
        ttk.Button(left, text="📊 稳态分布",
                   command=self._on_steady).pack(fill="x", pady=2)
        self.state_var = tk.StringVar(value="—")
        tk.Label(left, text="当前状态:", font=("Arial", 9)).pack(
            anchor="w", pady=(10, 0))
        tk.Label(left, textvariable=self.state_var,
                 font=("Arial", 13, "bold"), fg="#00695C").pack(anchor="w")

        right = tk.LabelFrame(main, text=" 矩阵 / 路径 / 稳态 ",
                              font=("Arial", 10, "bold"), padx=8, pady=8)
        right.pack(side="right", fill="both", expand=True)
        self.mk_text = tk.Text(right, height=12, width=40,
                               font=("Consolas", 9), wrap="word",
                               bg="#E0F2F1", relief="flat", borderwidth=0,
                               padx=6, pady=6)
        self.mk_text.pack(fill="both", expand=True)
        self._refresh_all()

    def _on_select(self, *a):
        self.current_name = self.chain_var.get()
        self.mc = build_markov_chain(self.chains[self.current_name])
        self._refresh_all()

    def _refresh_all(self):
        self.state_var.set(self.mc.current)
        self.mk_text.config(state="normal")
        self.mk_text.delete("1.0", "end")
        self.mk_text.insert("1.0",
                            "转移概率矩阵:\n" + self.mc.show_matrix())
        self.mk_text.config(state="disabled")

    def _append(self, msg):
        self.mk_text.config(state="normal")
        self.mk_text.insert("end", "\n\n" + msg)
        self.mk_text.see("end")
        self.mk_text.config(state="disabled")

    def _on_step(self):
        s = self.mc.step()
        self.state_var.set(s)
        self._append(f"单步演化 → {s}")

    def _on_sim(self):
        seq = self.mc.simulate(20)
        self.state_var.set(seq[-1])
        self._append("仿真 20 步路径:\n  " + " → ".join(seq))

    def _on_steady(self):
        sd = self.mc.steady_state()
        self._append("稳态分布 π (πP=π):\n  " +
                     ", ".join(f"{k}:{v:.3f}" for k, v in sd.items()))


# ==========================================================
# 主应用：Notebook 容器
# ==========================================================
class Application(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.master.title("多范式决策引擎 · 可视化工作台")
        self.pack(fill="both", expand=True, padx=12, pady=10)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.tab_wf = WorkflowEngineTab(notebook)
        self.tab_bt = BehaviorTreeTab(notebook)
        self.tab_dt = DecisionTreeTab(notebook)
        self.tab_de = DifferenceEngineTab(notebook)
        self.tab_pn = PetriNetTab(notebook)
        self.tab_re = RuleEngineTab(notebook)
        self.tab_mc = MarkovTab(notebook)

        notebook.add(self.tab_wf, text="  工作流引擎 (状态机/HSM)  ")
        notebook.add(self.tab_bt, text="  行为树  ")
        notebook.add(self.tab_dt, text="  决策树  ")
        notebook.add(self.tab_de, text="  差分引擎  ")
        notebook.add(self.tab_pn, text="  Petri 网  ")
        notebook.add(self.tab_re, text="  规则引擎  ")
        notebook.add(self.tab_mc, text="  马尔可夫链  ")

        # ---- P0-2 可视化（图形渲染 + 轨迹高亮）----
        self.tab_viz = VisualizationTab(notebook)
        notebook.add(self.tab_viz, text="  📈 可视化  ")

        # ---- P2-1 形式化分析 ----
        self.tab_analysis = AnalysisTab(notebook)
        notebook.add(self.tab_analysis, text="  🔬 分析  ")

        # ---- P1-1 编排协同 ----
        self.tab_orch = OrchestratorTab(notebook)
        notebook.add(self.tab_orch, text="  🔗 编排  ")

        # ---- P0-1 插件范式（自动发现 core/plugins/ 下的新范式）----
        discovered = ensure_discovered()
        self.plugin_tabs = []
        for plugin in PluginRegistry.all():
            if plugin.kind in _BUILTIN_KINDS:
                continue
            if not plugin.specs_provider():
                continue
            tab = PluginTab(notebook, plugin)
            self.plugin_tabs.append(tab)
            notebook.add(tab, text=f"  🧩 {plugin.label}  ")
