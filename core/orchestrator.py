# -*- coding: utf-8 -*-
"""
范式协同 / 编排层（P1-1）
=======================

把互相独立的范式引擎连成「系统」：一个事件总线 + 声明式绑定。

* ``EventBus`` —— 引擎每次 step 通过 ``on_event`` 发布 ``EngineEvent``。
* ``Orchestrator`` —— 按 config 的 ``orchestration`` 段，把
  「某引擎的某事件」绑定到「另一引擎的某动作」（如：状态机进入某态 → 触发行为树
  tick → 行为树黑板变化 → 驱动马尔可夫链演化）。

这是从「7 个孤岛」升级为「可编排的多范式决策系统」的骨架，也是后续接 LLM 的底座。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .engine_base import EngineEvent
from .engine_adapters import build_adapter


# ==========================================================
# 事件总线
# ==========================================================
class EventBus:
    def __init__(self):
        self._subs: Dict[str, List[Callable[[EngineEvent], None]]] = {}
        self._all: List[Callable[[EngineEvent], None]] = []

    def subscribe(self, etype: str, cb: Callable[[EngineEvent], None]) -> None:
        self._subs.setdefault(etype, []).append(cb)

    def subscribe_all(self, cb: Callable[[EngineEvent], None]) -> None:
        self._all.append(cb)

    def publish(self, event: EngineEvent) -> None:
        # 精确匹配 etype 的订阅者
        for cb in self._subs.get(event.etype, []):
            cb(event)
        # 通配订阅者（etype == "*"）对任意事件都触发
        for cb in self._subs.get("*", []):
            cb(event)
        for cb in self._all:
            cb(event)


# ==========================================================
# 编排器
# ==========================================================
class Orchestrator:
    def __init__(self):
        self.bus = EventBus()
        self.engines: Dict[str, Any] = {}        # alias -> adapter
        self.spec: Dict[str, Any] = {}
        self.trace: List[Dict[str, Any]] = []
        self._bindings: List[Dict[str, Any]] = []

    # ---- 构建 ----
    def configure(self, spec: Dict[str, Any], full_config: Dict[str, Any]) -> None:
        self.spec = spec
        self.reset()
        # 1) 构建各引擎（事件以「别名」标记，供绑定匹配）
        for alias, e in (spec.get("engines") or {}).items():
            eng = build_adapter(e["kind"], e["name"], full_config,
                                on_event=self._make_alias_cb(alias))
            self.engines[alias] = eng
        # 2) 声明绑定
        self._bindings = spec.get("bindings", [])
        for b in self._bindings:
            when = b.get("when", {})
            then = b.get("then", {})
            self.bus.subscribe(when.get("etype", "*"),
                               self._make_handler(when, then))

    def _make_alias_cb(self, alias: str) -> Callable[[EngineEvent], None]:
        def cb(event: EngineEvent):
            event.engine = alias          # 重标为编排别名
            self.bus.publish(event)
            self.trace.append({"event": f"{alias}.{event.etype}",
                               "payload": event.payload})
        return cb

    def _make_handler(self, when, then) -> Callable[[EngineEvent], None]:
        def handler(event: EngineEvent):
            if when.get("engine") and event.engine != when["engine"]:
                return
            target = self.engines.get(then.get("engine"))
            if not target:
                return
            ctx = then.get("ctx", {})
            result = target.step(ctx)
            self.trace.append({
                "trigger": f"{when.get('engine')}.{when.get('etype')}",
                "action": f"{then.get('engine')}.{then.get('action')}",
                "result": getattr(result, "value", None),
            })
        return handler

    # ---- 驱动 ----
    def start(self) -> None:
        for act in self.spec.get("start", []):
            eng = self.engines.get(act.get("engine"))
            if eng:
                eng.step(act.get("ctx", {}))

    def step_engine(self, alias: str, ctx: Optional[Dict[str, Any]] = None) -> Any:
        eng = self.engines.get(alias)
        if not eng:
            return None
        r = eng.step(ctx or {})
        return getattr(r, "value", None)

    def reset(self) -> None:
        self.engines.clear()
        self.trace.clear()
        self._bindings = []

    def report(self) -> str:
        lines = [f"编排: {self.spec.get('description','')}",
                 f"引擎: {list(self.engines.keys())}",
                 f"绑定: {len(self._bindings)} 条",
                 "---- 事件/动作轨迹 ----"]
        for t in self.trace:
            if "event" in t:
                lines.append(f"  • 事件 {t['event']}  {t['payload']}")
            else:
                lines.append(f"  → 由 [{t['trigger']}] 触发 [{t['action']}] -> {t['result']}")
        return "\n".join(lines)

    def engine_status(self) -> List[Dict[str, Any]]:
        """每个引擎的实时摘要，供 Web 节点编辑器展示。"""
        out = []
        for alias, eng in self.engines.items():
            out.append({
                "alias": alias,
                "kind": eng.kind,
                "name": eng.name,
                "summary": eng.summary(),
            })
        return out

    def to_graph(self) -> Dict[str, Any]:
        """把当前编排导出为 react-flow 友好的 {nodes, edges} 结构。"""
        nodes, edges = [], []
        for alias, e in (self.spec.get("engines") or {}).items():
            pos = {"x": e.get("x", 40), "y": e.get("y", 40)}
            nodes.append({"id": alias,
                          "data": {"kind": e.get("kind"), "name": e.get("name"),
                                   "summary": ""},
                          "position": pos})
        for i, b in enumerate(self._bindings):
            when, then = b.get("when", {}), b.get("then", {})
            etype = when.get("etype", "*")
            action = then.get("action", "step")
            edges.append({
                "id": f"b{i}",
                "source": when.get("engine", ""),
                "target": then.get("engine", ""),
                "label": f"{etype} → {action}",
                "data": {"etype": etype, "action": action,
                         "ctx": then.get("ctx", {})},
            })
        return {"nodes": nodes, "edges": edges,
                "start": self.spec.get("start", []),
                "description": self.spec.get("description", "")}


# ==========================================================
# 便捷：从 config 加载首个编排
# ==========================================================
def build_orchestrator_from_config(full_config: Dict[str, Any],
                                   name: str = None) -> Optional[Orchestrator]:
    orch_specs = full_config.get("orchestration", {})
    if not orch_specs:
        return None
    name = name or next(iter(orch_specs))
    spec = orch_specs[name]
    o = Orchestrator()
    o.configure(spec, full_config)
    return o
