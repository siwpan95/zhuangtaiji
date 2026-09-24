# -*- coding: utf-8 -*-
"""
内核演示：core.kernel 解决的七个真实痛点
============================================================

每一节都对应项目里一处**当前存在的具体缺口**，并给出重构后的写法。
运行：``python tools/kernel_demo.py``
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.kernel import (  # noqa: E402
    ACTIVE, PENDING, Context, Loader, Plugin, apply_patches, compose, hot_reload,
)


def header(no: str, title: str, before: str) -> None:
    print("\n" + "=" * 74)
    print(f"痛点 {no} · {title}")
    print(f"  现状：{before}")
    print("=" * 74)


def log_on_dispose(message: str):
    """返回一个可传给 ``ctx.effect`` 的 setup：注册时无动作，卸载时打印。

    注意 ``ctx.effect(fn)`` 的语义是**注册即执行** ``fn``，退出时执行 ``fn`` 的
    **返回值**。所以"登记一条卸载日志"必须写成"返回一个打印函数"，
    而不是"直接把打印函数传给 effect"。
    """
    def setup():
        return lambda: print(message)
    return setup


# ======================================================================
# 假想的最小引擎层：只为演示内核语义，不是真实引擎实现
# ======================================================================
class FakeEngine:
    """模拟 StateMachineEngine / BehaviorTreeEngine 的 adapter 形状。"""

    def __init__(self, kind: str, name: str, config: dict):
        self.kind = kind
        self.name = name
        self.config = config
        self.steps = 0

    def step(self, ctx: dict | None = None) -> dict:
        self.steps += 1
        return {"kind": self.kind, "engine": self.name,
                "value": (ctx or {}).get("event", "idle"), "steps": self.steps}

    def summary(self) -> str:
        return f"[{self.kind}] {self.name} steps={self.steps}"


class EngineRegistry:
    """取代 ``_ADAPTERS`` + ``_SECTION_OF`` 两张硬编码表（core/engine_adapters.py:403,413）。

    新增一个范式只需 ``ctx.engines.register(...)``——不需要改 ``build_adapter``、
    不需要改 ``web/server.py:326`` 的 ``kinds`` 字典、不需要改 UI 的 Tab 列表。
    """

    def __init__(self):
        self._kinds = {}       # kind -> {"cls":..., "section":..., "label":...}

    def register(self, kind, cls, section, label="") -> None:
        if kind in self._kinds:
            raise KeyError(f'engine kind "{kind}" already registered')
        self._kinds[kind] = {"cls": cls, "section": section, "label": label or kind}

    def unregister(self, kind) -> None:
        self._kinds.pop(kind, None)

    def build(self, kind, name, full_config) -> FakeEngine:
        meta = self._kinds.get(kind)
        if meta is None:
            raise ValueError(f"未知引擎类型: {kind}")
        spec = (full_config.get(meta["section"]) or {}).get(name, {})
        return meta["cls"](kind, name, spec)

    def kinds(self) -> list:
        return sorted(self._kinds)

    def labels(self) -> dict:
        """供 UI 动态生成 Tab：``{kind: label}``，不必硬编码 7 个类。"""
        return {k: v["label"] for k, v in self._kinds.items()}


# ======================================================================
def demo_1_service_container():
    header("1", "服务容器取代全局字典",
           "6 处模块级可变状态：GUARD_REGISTRY/ACTION_REGISTRY/_ADAPTERS/"
           "_SECTION_OF/PluginRegistry._plugins/web.server.ORCH")
    ctx = Context(name="host")
    ctx.provide("engines", EngineRegistry())
    ctx.provide("guards", {})
    ctx.provide("actions", {})

    ctx.engines.register("state_machine", FakeEngine, "state_machines", "状态机")
    ctx.engines.register("behavior_tree", FakeEngine, "behavior_trees", "行为树")

    print(f"    · ctx.engines.kinds()  = {ctx.engines.kinds()}")
    print(f"    · ctx.engines.labels() = {ctx.engines.labels()}")
    print(f"    · ctx.services()       = {sorted(ctx.services())}")

    print("  ▸ 重复注册必须立刻失败，而不是静默覆盖")
    try:
        ctx.engines.register("state_machine", FakeEngine, "state_machines")
    except KeyError as exc:
        print(f"    · KeyError: {exc}")

    print("  ▸ 服务缺失要给可操作的错误")
    try:
        ctx.require("llm")
    except LookupError as exc:
        print(f"    · LookupError: {str(exc)[:96]}...")

    print("    · 关键收益：无模块级全局状态 → 同进程可并存多份互不干扰的配置")


# ======================================================================
def demo_2_effect_reversible():
    header("2", "effect 注册即可逆",
           "PluginRegistry.register() 返回 None；EventBus.subscribe() 返回 None —— 无任何退订手段")

    ctx = Context(name="host")
    ctx.provide("engines", EngineRegistry())
    ctx.engines.register("state_machine", FakeEngine, "state_machines")

    def install_reporting(c, config):
        # 注册即执行：这里做"安装"动作，返回的才是"卸载"动作
        c.effect(log_on_dispose("    · [cleanup] 报告服务已卸载"))
        c.effect(lambda: c.provide("reporting", {"enabled": True}))
        c.on("engine/step", lambda p: None, mode="emit")
        return lambda: print("    · [cleanup] reporting 插件 apply 的清理器执行")

    ctx.plugin(Plugin("reporting", install_reporting))
    print(f"    · 挂载后：父 ctx.effect_count={ctx.effect_count()}"
          f"（1 = 插件生命周期本身），services={sorted(ctx.services())}")

    print("  ▸ 卸载")
    ctx.dispose()
    print(f"    · dispose 后：state={ctx.state}, services={sorted(ctx.services())}, "
          f"effect_count={ctx.effect_count()}")
    print("    · 关键收益：测试里可断言 `dispose 后注册表为空`，杜绝状态跨用例泄漏")


# ======================================================================
def demo_3_inject_ordering():
    header("3", "inject 声明依赖 → 加载顺序由服务可得性决定",
           "build_adapter 直接 full_config[section][name]；provider 缺失时抛错或静默半死")

    ctx = Context(name="host")

    def llm_agent_plugin(c, config):
        c.effect(log_on_dispose("    · [cleanup] llm_agent 卸载"))
        print(f"    · llm_agent 激活（llm provider = {c.require('llm')['provider']}）")
        return None

    llm_agent = Plugin("llm_agent", llm_agent_plugin, inject=("llm",))

    print("  ▸ 先挂载 consumer（llm 尚不存在）")
    child = ctx.plugin(llm_agent)
    print(f"    · llm_agent 状态 = {child.state}   （期望 {PENDING}）")
    print(f"    · 待激活清单     = {ctx.pending_plugins()}")

    print("  ▸ 再挂载 provider")
    ctx.provide("llm", {"provider": "local", "model": "demo"})
    print(f"    · llm_agent 状态 = {child.state}   （期望 {ACTIVE}）")
    print(f"    · 待激活清单     = {ctx.pending_plugins()}  （已清空）")
    print("    · 关键收益：加载顺序由依赖决定，配置里调换行序不会出问题")
    print("    · 运维价值：pending_plugins() 是排查「插件静默不生效」的确定入口")


# ======================================================================
def demo_4_dispatch_modes():
    header("4", "三种派发模式：emit / waterfall / serial",
           "EventBus.publish() 只有同步广播；没有拦截、改写、短路能力")

    ctx = Context(name="host")
    ctx.provide("engines", EngineRegistry())
    ctx.engines.register("state_machine", FakeEngine, "state_machines")
    eng = ctx.engines.build("state_machine", "demo", {"state_machines": {"demo": {}}})
    log = []

    # ---- emit：纯通知（观察者，不改变行为） ----
    ctx.on("engine/stepped", lambda p: log.append(
        f"emit 观察到 {p['kind']}.{p['value']}"), mode="emit")

    # ---- waterfall：围绕中间件（可改写输入、可否决、可包裹） ----
    def clamp_input(payload, next_):
        if payload.get("event") == "forbidden":
            print("    · [waterfall] 拦截 forbidden → 改写为 safe")
            payload = {**payload, "event": "safe"}
        return next_(payload)

    def audit(payload, next_):
        print(f"    · [waterfall] 审计入参 {payload}")
        result = next_(payload)
        print(f"    · [waterfall] 审计出参 {result}")
        return result

    ctx.on("engine/step", clamp_input, mode="waterfall", prepend=True)
    ctx.on("engine/step", audit, mode="waterfall")

    # ---- serial：有序检查点，首个非 None 短路 ----
    ctx.on("engine/gate", lambda p: "BLOCKED" if p.get("event") == "nuke" else None,
           mode="serial")
    ctx.on("engine/gate", lambda p: print("    · [serial] 不会到达（已被短路）"),
           mode="serial")

    def run(payload):
        result = eng.step(payload)
        ctx.emit("engine/stepped", result)
        return result

    print("  ▸ 引擎 step 被 waterfall 包裹（外层 prepend 的 clamp 先跑）")
    result = ctx.waterfall("engine/step", {"event": "forbidden"}, inner=run)
    print(f"    · 引擎结果 = {result}")
    print(f"    · emit 日志 = {log}")
    print(f"    · serial 短路 = {ctx.serial('engine/gate', {'event': 'nuke'})}")

    print("  ▸ 同一事件名混用派发模式必须立刻报错（防止监听器静默不生效）")
    try:
        ctx.on("engine/step", lambda p: None, mode="serial")
    except ValueError as exc:
        print(f"    · ValueError: {exc}")

    print("    · 关键收益：编排从「when→then」升级为可插入策略。"
          "限流、审计、输入钳制、缓存都能作为插件挂上，不必改 Orchestrator")


# ======================================================================
def demo_5_layered_patch():
    header("5", "空根 + 分层 patch 取代单文件 config.json",
           "load_config() 只读一个文件；kind→section 映射在 core 与 web 两处重复")

    base = []          # 根永远是空的：内置 demo 全部以 insert 形式进入
    base_patch = [
        {"insert": [
            {"id": "fsm-main", "name": "state_machine",
             "config": {"states": ["idle", "running"], "initial": "idle"}},
            {"id": "bt-main", "name": "behavior_tree",
             "config": {"root": "selector"}},
        ]},
    ]
    user_patch = [
        # 整键替换：想改一个字段，必须重述要保留的字段（代价，但是可推理性）
        {"id": "fsm-main",
         "config": {"states": ["idle", "running", "paused"], "initial": "idle"}},
        {"id": "bt-main", "disabled": True},
        {"insert": [{"id": "petri-extra", "name": "petri_net", "config": {}}]},
    ]

    entries = apply_patches(base, compose(base_patch, user_patch))
    for e in entries:
        print(f"    · {e.get('id'):<12} name={str(e.get('name')):<16} "
              f"disabled={bool(e.get('disabled')):<5} config={e.get('config')}")

    print("  ▸ 目标缺失 / name 不匹配时只警告，绝不静默改错行")
    apply_patches(entries, [{"id": "nope", "config": {}},
                            {"id": "fsm-main", "name": "wrong", "config": {}}])

    print("    · 关键收益：同一算子供「真实装配」与「离线 dump」使用，二者不可能漂移")
    print("    · 本项目对应场景：内置 demo 在 base 层，用户编排在 overlay 层，"
          "无需修改内置文件")


# ======================================================================
def demo_6_isolate_scope():
    header("6", "隔离作用域：一份进程内并存多套配置",
           "web/server.py 的全局 ORCH 字典 → 同一时刻每个编排只能有一份状态")

    host = Context(name="host")
    host.provide("engines", EngineRegistry())
    host.engines.register("state_machine", FakeEngine, "state_machines")
    host_engines = host.engines

    def make_orchestration(alias: str):
        """每个编排进自己的隔离作用域：内部可见同名服务而不互相污染。"""
        scope = host.isolate("engines")
        scope._name = f"orch:{alias}"
        scope.provide("engines", EngineRegistry())
        scope.engines.register("state_machine", FakeEngine, "state_machines")
        scope.provide("engine", scope.engines.build(
            "state_machine", alias, {"state_machines": {alias: {}}}))
        scope.engine.step({"event": f"{alias}-init"})
        return scope

    a = make_orchestration("orch-A")
    b = make_orchestration("orch-B")

    print(f"    · A: engine={a.engine.name!r} steps={a.engine.steps}  state={a.state}")
    print(f"    · B: engine={b.engine.name!r} steps={b.engine.steps}  state={b.state}")
    print(f"    · A.engine is B.engine ? {a.engine is b.engine}")
    print(f"    · 主机 engines 是否被隔离域覆盖 ? "
          f"{host.engines is not host_engines}  （期望 False）")

    a.dispose()
    print(f"  ▸ A.dispose() 之后：A.state={a.state}，B.state={b.state}（B 不受影响）")
    print("    · 关键收益：编排之间真正互不干扰，可并发驱动，可单独卸载")


# ======================================================================
def demo_7_loader_and_audit():
    header("7", "Loader + 必败清单审计（fail-loud 分层）",
           "build_adapter 对未知 kind 抛 ValueError；但 _section_provider 用 "
           "`except Exception: return {}` 吞掉一切（静默降级）")

    factories = {
        "state_machine": lambda cfg: Plugin("state_machine", _mount_stub("state_machine")),
        "behavior_tree": lambda cfg: Plugin("behavior_tree", _mount_stub("behavior_tree")),
    }
    entries = apply_patches([], [
        {"insert": [
            {"id": "gen-fsm", "name": "state_machine", "config": {}},
            {"id": "gen-bt", "name": "behavior_tree", "config": {}},
            {"id": "opt-web", "name": "webserver", "config": {}},       # 未知 → 只警告
            {"id": "opt-off", "name": "behavior_tree", "disabled": True},
        ]},
    ])

    ctx = Context(name="root")
    ctx.provide("engines", EngineRegistry())
    loader = Loader(ctx, factories, required=("gen-fsm",))     # 必败清单
    loader.mount(entries)
    print(f"    · 已挂载 = {loader.status()}")
    print(f"    · 警告 {len(loader.warnings)} 条（未知插件 / 被禁用行 → 只警告，不阻断启动）")

    print("  ▸ 必败清单缺失时必须整体失败，而不是启动半个产品")
    ctx2 = Context(name="root")
    ctx2.provide("engines", EngineRegistry())
    loader2 = Loader(ctx2, factories, required=("gen-fsm", "must-exist"))
    try:
        loader2.mount(entries)
    except RuntimeError as exc:
        print(f"    · RuntimeError: {exc}")

    print("  ▸ config-only 热更新：dispose 旧树 → 重算 patch → 重新挂载")
    ctx3 = Context(name="root")
    ctx3.provide("engines", EngineRegistry())
    patched = [{"id": "gen-bt", "disabled": True}]
    fresh = hot_reload(ctx3, [], compose([{"insert": [
        {"id": "gen-fsm", "name": "state_machine", "config": {}},
        {"id": "gen-bt", "name": "behavior_tree", "config": {}},
    ]}], patched), factories, required=("gen-fsm",))
    print(f"    · 热更新后 = {fresh.status()}  （gen-bt 已被 patch 关掉）")


def _mount_stub(kind):
    def apply(c, config):
        c.provide("engine", FakeEngine(kind, c.name, config or {}))
        print(f"    · mounted {kind} → ctx {c.name}")
        return lambda: print(f"    · [cleanup] {kind} @ {c.name} 卸载")
    return apply


# ======================================================================
def main():
    print("=" * 74)
    print("core.kernel · 七个真实痛点的前后对比")
    print("=" * 74)
    demo_1_service_container()
    demo_2_effect_reversible()
    demo_3_inject_ordering()
    demo_4_dispatch_modes()
    demo_5_layered_patch()
    demo_6_isolate_scope()
    demo_7_loader_and_audit()
    print("\n" + "=" * 74)
    print("全部演示通过。对应的断言见 test/test_kernel.py")
    print("=" * 74)


if __name__ == "__main__":
    main()
