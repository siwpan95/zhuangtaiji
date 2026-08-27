# -*- coding: utf-8 -*-
"""
统一引擎适配器（P0-1）
=====================

把现有 7 个范式引擎包裹到 ``engine_base.Engine`` 契约之后。
* 不改引擎内核（开闭原则）。
* 提供统一的 ``step() -> EngineResult``、``summary()``、``visualize() -> Graph``。
* 每次 step 通过 on_event 发射 ``EngineEvent``，供编排层串联。

另提供 ``build_adapter(kind, name, full_config)`` 工厂，按 config 段构造适配器。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .engine_base import (
    BaseAdapter, EngineEvent, EngineResult, Graph, GraphEdge, GraphNode,
)
from . import (
    create_state_machine, build_behavior_tree, Blackboard,
    build_decision_tree, build_petri_net, build_markov_chain,
    build_rule_engine, FiniteDifference, StateDiff, ReactiveTracker,
)


# ==========================================================
# 1) 状态机 / 层次状态机
# ==========================================================
class StateMachineEngine(BaseAdapter):
    kind = "state_machine"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        full = {"state_machines": {self.name: spec}}
        self.sm = create_state_machine(self.name, full, on_action=self._on_action)

    def _on_action(self, atype, sid, detail):
        self._emit(atype, state=sid, detail=detail)

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        ctx = ctx or {}
        event = ctx.get("event")
        if event:
            sid, content = self.sm.trigger(event, ctx.get("context", {}))
        else:
            evs = self.sm.available_events
            event = evs[0] if evs else None
            sid, content = (None, "无可用事件") if event is None \
                else self.sm.trigger(event, ctx)
        self._emit("enter", state=self.sm.current_state_id)
        return EngineResult(
            kind="state", value=self.sm.current_state_id,
            detail={"event": event, "content": content,
                    "available": self.sm.available_events},
            trace=self.sm.get_history(limit=30),
        )

    def summary(self) -> str:
        info = self.sm.get_state_info()
        return (f"当前状态: {self.sm.current_state_id}\n"
                f"内容: {info.get('content','')}\n"
                f"可用事件: {info.get('available_events', [])}")

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="stateDiagram", title=f"状态机 {self.name}")
        self._build_fsm_graph(self.spec, g)
        leaf = self.sm.current_state_id
        g.highlight({leaf})
        return g

    # ---- 内部：从 spec 建图 ----
    def _build_fsm_graph(self, spec: Dict[str, Any], g: Graph) -> None:
        states = spec.get("states", {})
        is_hier = spec.get("type") == "hierarchical" or \
            any("substates" in s for s in states.values())
        if is_hier:
            self._walk_hier(states, [], g, None)
        else:
            for sid, s in states.items():
                g.add_node(sid, s.get("content", sid) or sid)
            for sid, s in states.items():
                for ev, tgt in (s.get("transitions") or {}).items():
                    t = tgt.get("target") if isinstance(tgt, dict) else tgt
                    if isinstance(t, str) and t.startswith("#"):
                        g.add_edge(sid, t[1:], label=ev, style="dotted")
                    else:
                        g.add_edge(sid, t, label=ev)

    def _walk_hier(self, states, prefix, g: Graph, sg_id):
        for sid, s in states.items():
            path = "/".join(prefix + [sid])
            g.add_node(path, s.get("content", sid) or sid, sub_of=sg_id)
            if "substates" in s:
                child_sg = f"sg_{path}"
                g.subgraphs[child_sg] = []
                self._walk_hier(s["substates"], prefix + [sid], g, child_sg)
                for c in g.subgraphs[child_sg]:
                    pass
                # 记录子图节点 id 便于渲染
                g.subgraphs[child_sg] = [n.id for n in g.nodes
                                         if n.sub_of == child_sg]
            for ev, tgt in (s.get("transitions") or {}).items():
                t = tgt.get("target") if isinstance(tgt, dict) else tgt
                if isinstance(t, str) and t.startswith("#"):
                    g.add_edge(path, path + t[1:], label=ev, style="dotted")
                else:
                    tp = self._resolve_path(t, self.spec.get("states", {}), [])
                    if tp:
                        g.add_edge(path, "/".join(tp), label=ev)

    def _resolve_path(self, target, states, prefix):
        for name, node in states.items():
            p = prefix + [name]
            if name == target:
                return p
            if "substates" in node:
                r = self._resolve_path(target, node["substates"], p)
                if r:
                    return r
        return None


# ==========================================================
# 2) 行为树
# ==========================================================
class BehaviorTreeEngine(BaseAdapter):
    kind = "behavior_tree"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.bb = Blackboard()
        self.bt = build_behavior_tree(spec, blackboard=self.bb)
        self.last_status: Dict[str, str] = {}

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        ctx = ctx or {}
        if isinstance(ctx.get("blackboard"), dict):
            self.bb.update(ctx["blackboard"])
        status = self.bt.tick()
        self.last_status = self._collect(self.bt.root)
        self._emit("tick", status=status.value, blackboard=self.bb.snapshot())
        return EngineResult(
            kind="trace", value=status.value,
            detail={"blackboard": self.bb.snapshot(), "tick": self.bt.tick_count},
            trace=[{"node": k, "status": v} for k, v in self.last_status.items()],
        )

    def _collect(self, node, out=None):
        out = out if out is not None else {}
        out[node.name] = node.status.value
        for c in getattr(node, "children", []) or []:
            self._collect(c, out)
        if getattr(node, "child", None):
            self._collect(node.child, out)
        return out

    def summary(self) -> str:
        return (f"最近状态: {self.bt.status.value if hasattr(self.bt,'status') else '-'}\n"
                f"黑板: {self.bb.snapshot()}")

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="TB", title=f"行为树 {self.name}")
        self._build(self.bt.root, None, g)
        if highlight:
            g.highlight(highlight)
        return g

    def _build(self, node, parent_id, g: Graph, idx=0):
        nid = f"{parent_id}::{node.name}" if parent_id else node.name
        shape = "diamond" if node.__class__.__name__ == "Condition" else \
            ("round" if node.__class__.__name__ in ("Action", "Service") else "box")
        st = getattr(node, "status", None)
        g.add_node(nid, node.name, shape=shape,
                   style=st.value if st else "")
        if parent_id:
            g.add_edge(parent_id, nid)
        for c in getattr(node, "children", []) or []:
            self._build(c, nid, g)
        if getattr(node, "child", None):
            self._build(node.child, nid, g)


# ==========================================================
# 3) 决策树
# ==========================================================
class DecisionTreeEngine(BaseAdapter):
    kind = "decision_tree"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.dt = build_decision_tree(spec)
        self.last_path: Set[str] = set()

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        feats = ctx or {}
        res = self.dt.decide(feats)
        self.last_path = {tok.split("?")[0] for tok in res.path}
        self._emit("decide", label=res.label, path=res.path)
        return EngineResult(
            kind="decision", value=res.label,
            detail={"payload": res.payload, "path": res.path},
            trace=[{"node": p} for p in res.path],
        )

    def summary(self) -> str:
        return f"最近结论: {list(self.last_path) and '-' or '-'}"

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="TB", title=f"决策树 {self.name}")
        self._build(self.dt.root, None, g)
        if self.last_path:
            g.highlight(self.last_path)
        return g

    def _build(self, node, parent_id, g: Graph):
        nid = f"{parent_id}::{node.name}" if parent_id else node.name
        shape = "diamond" if node.__class__.__name__ == "ConditionNode" else "round"
        g.add_node(nid, node.name, shape=shape)
        if parent_id:
            g.add_edge(parent_id, nid)
        for attr, child in (("true_child", "T"), ("false_child", "F")):
            c = getattr(node, attr, None)
            if c is not None:
                self._build(c, nid, g)


# ==========================================================
# 4) Petri 网
# ==========================================================
class PetriEngine(BaseAdapter):
    kind = "petri_net"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.pn = build_petri_net(spec)

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        ctx = ctx or {}
        strategy = ctx.get("strategy", "priority")
        fired = self.pn.step(strategy=strategy)
        self._emit("fired", transitions=fired)
        return EngineResult(
            kind="marking", value=self.pn.format_marking(),
            detail={"marking": self.pn.marking(), "fired": fired,
                    "enabled": self.pn.enabled_transitions(),
                    "deadlock": self.pn.is_deadlock()},
        )

    def summary(self) -> str:
        return (f"标记: {self.pn.format_marking()}\n"
                f"使能变迁: {self.pn.enabled_transitions() or '（死锁/终止）'}")

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="LR", title=f"Petri 网 {self.name}")
        enabled = set(self.pn.enabled_transitions())
        for p, tok in self.pn.places.items():
            g.add_node(f"P_{p}", f"{p}={tok}", shape="circle")
        for t in self.pn.transitions:
            g.add_node(f"T_{t}", t, shape="rect", active=(t in enabled))
        for tname, t in self.pn.transitions.items():
            for p, w in t.inputs:
                g.add_edge(f"P_{p}", f"T_{tname}", label=str(w) if w != 1 else "")
            for p, w in t.outputs:
                g.add_edge(f"T_{tname}", f"P_{p}", label=str(w) if w != 1 else "")
            for p, w in t.inhibitors:
                g.add_edge(f"P_{p}", f"T_{tname}", label=f"inh{w}", style="dotted")
        return g


# ==========================================================
# 5) 马尔可夫链
# ==========================================================
class MarkovEngine(BaseAdapter):
    kind = "markov_chain"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.mc = build_markov_chain(spec)
        self.seq: List[str] = [self.mc.current]

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        ctx = ctx or {}
        if ctx.get("simulate"):
            n = int(ctx["simulate"])
            self.seq = self.mc.simulate(n)
            self._emit("step", path=self.seq)
            return EngineResult(kind="trace", value=self.seq[-1],
                                detail={"path": self.seq})
        s = self.mc.step()
        self.seq.append(s)
        self._emit("step", state=s)
        return EngineResult(kind="state", value=s,
                            detail={"path": list(self.seq)})

    def summary(self) -> str:
        return (f"当前状态: {self.mc.current}\n"
                f"稳态分布: {self.mc.steady_state()}")

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="LR", title=f"马尔可夫链 {self.name}")
        for s in self.mc.states:
            g.add_node(s, s, shape="circle", active=(s == self.mc.current))
        for i, s in enumerate(self.mc.states):
            for j, t in enumerate(self.mc.states):
                p = self.mc.matrix[i][j]
                if p > 0:
                    g.add_edge(s, t, label=f"{p:.2f}")
        return g


# ==========================================================
# 6) 规则引擎
# ==========================================================
class RuleEngineAdapter(BaseAdapter):
    kind = "rule_engine"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.engine = build_rule_engine(spec)

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        log = self.engine.forward_chain()
        fired = [e["rule"] for e in log if e["type"] == "fire"]
        self._emit("fired", rules=fired)
        return EngineResult(
            kind="facts", value=len(self.engine.working_memory),
            detail={"facts": self.engine.facts_summary(),
                    "fired_rules": fired},
            trace=log,
        )

    def summary(self) -> str:
        return f"事实数: {len(self.engine.working_memory)}\n{self.engine.facts_summary()}"

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="TB", title=f"规则引擎 {self.name}")
        fact_types = set()
        for f in self.engine.working_memory:
            fact_types.add(f.type)
        for ft in fact_types:
            g.add_node(f"F_{ft}", ft, shape="circle")
        for prod in self.engine.productions:
            rid = f"R_{prod.name}"
            g.add_node(rid, prod.name, shape="rect")
            for pat in prod.when:
                t = pat.get("type")
                if t:
                    g.add_edge(f"F_{t}", rid)
        return g


# ==========================================================
# 7) 差分引擎
# ==========================================================
class DifferenceEngineAdapter(BaseAdapter):
    kind = "difference_engine"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.fd = FiniteDifference(spec.get("initial_values", []))
        self.tracker = ReactiveTracker(initial={"status": "idle", "progress": 0},
                                       on_change=self._on_diff)
        self.diff_log: List[str] = []

    def _on_diff(self, entries, state):
        self.diff_log.append(StateDiff.summary(entries))
        self._emit("change", state=state)

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        ctx = ctx or {}
        if ctx.get("patch"):
            self.tracker.update(ctx["patch"])
            value = self.tracker.state
        else:
            value = self.fd.step()
        self._emit("step", value=value)
        return EngineResult(kind="trace", value=value,
                            detail={"history": self.fd.history(),
                                    "tracker": self.tracker.state})

    def summary(self) -> str:
        return (f"多项式阶数: {self.fd.order}\n已有值({self.fd.count}): "
                f"{self.fd.history()}\n差分日志: {self.diff_log[-3:]}")

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="LR", title=f"差分序列 {self.name}")
        hist = self.fd.history()
        prev = None
        for i, v in enumerate(hist):
            nid = f"v{i}"
            g.add_node(nid, f"{i}:{v:.1f}", shape="rect",
                       active=(i == len(hist) - 1))
            if prev:
                g.add_edge(prev, nid)
            prev = nid
        return g


# ==========================================================
# 工厂：按 config 段构造适配器
# ==========================================================
_ADAPTERS = {
    "state_machine": StateMachineEngine,
    "behavior_tree": BehaviorTreeEngine,
    "decision_tree": DecisionTreeEngine,
    "petri_net": PetriEngine,
    "markov_chain": MarkovEngine,
    "rule_engine": RuleEngineAdapter,
    "difference_engine": DifferenceEngineAdapter,
}

_SECTION_OF = {
    "state_machine": "state_machines",
    "behavior_tree": "behavior_trees",
    "decision_tree": "decision_trees",
    "petri_net": "petri_nets",
    "markov_chain": "markov_chains",
    "rule_engine": "rule_engines",
    "difference_engine": "difference_engine",
}


def adapter_class(kind: str):
    return _ADAPTERS.get(kind)


def build_adapter(kind: str, name: str, full_config: Dict[str, Any],
                  on_event=None) -> BaseAdapter:
    """按 kind + config 段构造一个适配器实例。"""
    cls = _ADAPTERS.get(kind)
    if cls is None:
        raise ValueError(f"未知引擎类型: {kind}")
    eng = cls(name=name, on_event=on_event)
    section = _SECTION_OF[kind]
    spec = full_config[section][name]
    eng.load(spec)
    return eng
