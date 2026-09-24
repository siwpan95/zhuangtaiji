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
from .kernel import DisposableList
from .kernel import EventBus as _KernelEventBus


# ==========================================================
# 事件总线
# ==========================================================
class EventBus:
    """引擎事件总线：精确订阅 + ``*`` 通配订阅。

    自 P2 起由内核 :class:`core.kernel.EventBus` 承载，因此具备：

    * **订阅可撤销**——``subscribe`` / ``subscribe_all`` 返回 ``Disposable``。
      过去它们返回 ``None``，而 ``Orchestrator.reset()`` 又不清总线，
      导致反复 ``configure()`` 会**线性累积监听器**（真实 bug）。
    * **三种派发模式**——``emit``（通知）/ ``waterfall``（可拦截改写的围绕中间件）
      / ``serial``（有序检查点，首个非 None 短路）。

    本类保留历史上的 ``subscribe`` / ``subscribe_all`` / ``publish`` 接口与
    ``*`` 通配语义，因此既有调用方无需改动。
    """

    #: 通配订阅使用的事件名。
    WILDCARD = "*"

    def __init__(self) -> None:
        self._bus = _KernelEventBus()
        self.owns_kernel_bus = True

    # ---- 历史上的注册接口（现在返回可撤销句柄）----
    def subscribe(self, etype: str, cb: Callable[[EngineEvent], None],
                  mode: str = "emit"):
        """订阅指定 ``etype`` 的事件。

        :param etype: 事件类型，或 :data:`WILDCARD` 表示通配。
        :param cb: ``(EngineEvent) -> None``。
        :param mode: 派发模式，``emit`` / ``waterfall`` / ``serial``。
        :returns: ``Disposable``。
        """
        return self._bus.on(etype, cb, mode=mode)

    def subscribe_all(self, cb: Callable[[EngineEvent], None],
                      mode: str = "emit"):
        """订阅所有事件（等价于 ``subscribe(WILDCARD, cb)``）。"""
        return self._bus.on(self.WILDCARD, cb, mode=mode)

    # ---- 分派 ----
    def publish(self, event: EngineEvent) -> None:
        """分派一次引擎事件：先精确匹配 ``etype``，再触发通配订阅。"""
        self._bus.emit(event.etype, event)
        self._bus.emit(self.WILDCARD, event)

    def emit(self, name: str, payload: Any = None) -> None:
        """按事件名通知（返回void）。"""
        self._bus.emit(name, payload)

    def waterfall(self, name: str, payload: Any,
                  inner: Optional[Callable[[Any], Any]] = None) -> Any:
        """围绕中间件派发：监听器收 ``(payload, next_)``，不调``next_``即短路。"""
        return self._bus.waterfall(name, payload, inner=inner)

    def serial(self, name: str, payload: Any = None) -> Any:
        """顺序派发，首个非 ``None`` 返回值短路并作为结果。"""
        return self._bus.serial(name, payload)

    # ---- 诊断 / 清理 ----
    def listener_count(self, name: Optional[str] = None) -> int:
        """监听器数量（``name`` 为 ``None`` 时统计全部）。

        供测试断言"反复 configure 不累积监听器"。
        """
        if name is None:
            return sum(self._bus.listener_count(n) for n in self._bus.names())
        return self._bus.listener_count(name)

    def clear(self) -> None:
        """清空全部监听器（由 :meth:`Orchestrator.reset` 调用）。"""
        self._bus.clear()


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
        # 绑定的订阅句柄：reset() 时统一撤销，杜绝监听器累积
        self._subscriptions = DisposableList()

    # ---- 构建 ----
    def configure(self, spec: Dict[str, Any], full_config: Dict[str, Any]) -> None:
        """按编排 spec 构建引擎并声明绑定。**可重复调用**（幂等，不累积监听器）。"""
        self.spec = spec
        self.reset()
        # 1) 构建各引擎（事件以「别名」标记，供绑定匹配）
        for alias, e in (spec.get("engines") or {}).items():
            eng = build_adapter(e["kind"], e["name"], full_config,
                                on_event=self._make_alias_cb(alias))
            self.engines[alias] = eng
        # 2) 声明绑定（订阅句柄登记到 _subscriptions，reset 时撤销）
        self._bindings = spec.get("bindings", [])
        for b in self._bindings:
            when = b.get("when", {})
            then = b.get("then", {})
            handle = self.bus.subscribe(when.get("etype", "*"),
                                        self._make_handler(when, then))
            self._subscriptions.add(handle)

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
            alias = then.get("engine")
            if alias not in self.engines:
                return
            result = self.invoke_engine(alias, then.get("ctx", {}))
            self.trace.append({
                "trigger": f"{when.get('engine')}.{when.get('etype')}",
                "action": f"{then.get('engine')}.{then.get('action')}",
                "result": getattr(result, "value", None),
            })
        return handler

    # ---- 引擎调用的统一入口（带可拦截扩展点）----
    #: ``engine/step`` 是 **waterfall**：监听器收 ``(meta, next_)``，可改写
    #: ``meta["ctx"]``（钳制输入）、可包裹调用（计时/审计），不调 ``next_`` 即否决。
    EVENT_STEP = "engine/step"
    #: ``engine/stepped`` 是 **emit**：step 完成后纯通知，返回值被忽略。
    EVENT_STEPPED = "engine/stepped"

    def invoke_engine(self, alias: str, ctx: Optional[Dict[str, Any]] = None) -> Any:
        """调用某个引擎的 step，途经 ``engine/step`` waterfall 扩展点。

        这是"编排从 when→then 升级为可插入策略"的落点：限流、审计、输入钳制、
        缓存都能作为监听器挂上，**无需修改 Orchestrator**。

        :param alias: 编排中的引擎别名。
        :param ctx: 传给引擎的上下文（可能被 waterfall 监听器改写）。
        :returns: ``EngineResult``，或 ``None``（别名不存在 / 被监听器否决）。
        """
        meta: Dict[str, Any] = {"alias": alias, "ctx": dict(ctx or {}),
                                "orchestrator": self}

        def _inner(m: Dict[str, Any]) -> Any:
            eng = self.engines.get(m["alias"])
            if eng is None:
                return None
            result = eng.step(m.get("ctx") or {})
            self.bus.emit(self.EVENT_STEPPED,
                          {"alias": m["alias"], "ctx": m.get("ctx"),
                           "result": result})
            return result

        return self.bus.waterfall(self.EVENT_STEP, meta, inner=_inner)

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
        """清空引擎、轨迹与绑定，并**退订全部绑定监听器**。

        过去这里漏掉了总线：``configure()`` 每次都往 ``bus`` 里注册新 handler，
        而 ``reset()`` 只清 ``engines``/``trace``/``_bindings`` ——
        于是反复 ``configure()`` 会线性累积监听器（同一个事件被触发 N 次）。
        """
        self._subscriptions.dispose()       # 退订全部绑定
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
