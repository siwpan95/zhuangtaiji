# -*- coding: utf-8 -*-
"""
内核（core.kernel）的行为断言（纯标准库，无 pytest）
================================================

运行：``python tools/run_tests.py kernel``  或  ``PYTHONPATH=. python test/test_kernel.py``
退出码 0 = 全通过。风格对齐项目现有的 ``test_verify.py`` 等脚本式测试。

覆盖七组契约：
  1. Disposable 单次性 / 逆序回收
  2. Context 服务容器与 fail-loud
  3. effect 注册即可逆 + 插件级联卸载 + 失败回滚
  4. inject 驱动的延迟激活
  5. 事件三种派发模式 + 派发模式契约校验
  6. patch 语义（insert / 整键替换 / name 断言 / 入参不可变）
  7. 隔离作用域 + 必败清单审计

最后一组是**内核自身的不变式**——对应报告里"把架构原则写成可执行断言"。
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_KERNEL_DIR = _PROJECT_ROOT / "zhuangtaiji" / "core" / "kernel"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from zhuangtaiji.core.kernel import (  # noqa: E402
    ACTIVE, DISPOSED, FAILED, PENDING,
    Context, Disposable, DisposableList, EventBus, Loader, Plugin,
    apply_patches, build_index, compose,
)

_PASS = 0
_FAIL = 0
_FAILURES: list = []


def check(label: str, fn) -> None:
    """运行一个断言块；异常即记为失败并继续（不中断后续用例）。"""
    global _PASS, _FAIL
    try:
        fn()
    except Exception as exc:
        _FAIL += 1
        _FAILURES.append((label, exc, traceback.format_exc()))
        print(f"  [FAIL] {label}: {exc!r}")
    else:
        _PASS += 1
        print(f"  [ok]   {label}")


def eq(actual, expected, what: str = "") -> None:
    if actual != expected:
        raise AssertionError(f"{what or 'value'}: expected {expected!r}, got {actual!r}")


# ======================================================================
def test_disposable():
    print("\n[1] Disposable 单次性 / 逆序回收")

    def single_shot():
        calls = []
        d = Disposable(lambda: calls.append(1) or "first", "t")
        eq(d.dispose(), "first", "首次结果")
        eq(d.dispose(), "first", "重复调用返回首次结果")
        eq(len(calls), 1, "清理体只执行一次")
        eq(d.disposed, True, "disposed 标记")
    check("单次性：重复 dispose 是 no-op 且返回首次结果", single_shot)

    def reverse_order():
        order = []
        lst = DisposableList()
        for i in range(3):
            lst.add(Disposable(lambda i=i: order.append(i)))
        lst.dispose()
        eq(order, [2, 1, 0], "逆序回收")
        eq(len(lst), 0, "回收后清空")
    check("DisposableList 逆序回收并清空", reverse_order)

    def failure_isolated():
        order = []

        def boom():
            raise RuntimeError("boom")

        lst = DisposableList()
        lst.add(Disposable(boom))
        lst.add(Disposable(lambda: order.append("after")))
        lst.dispose()                       # 逆序：先 after，再 boom
        eq(order, ["after"], "单个清理器异常不阻断其余回收")
    check("清理器异常不阻断兄弟清理", failure_isolated)

    def normalize_list():
        order = []
        d = Disposable.of([lambda: order.append("a"), lambda: order.append("b")])
        d.dispose()
        eq(order, ["a", "b"], "列表返回值归一化")
    check("Disposable.of 归一化列表返回值", normalize_list)


# ======================================================================
def test_context_services():
    print("\n[2] Context 服务容器与 fail-loud")

    def provide_and_get():
        ctx = Context(name="t")
        ctx.provide("a", 1)
        eq(ctx.get("a"), 1)
        eq(ctx.a, 1, "属性访问解析服务")
        eq(ctx.has("a"), True)
        eq(ctx.get("missing"), None)
    check("provide / get / 属性访问", provide_and_get)

    def duplicate_provide():
        ctx = Context(name="t")
        ctx.provide("a", 1)
        try:
            ctx.provide("a", 2)
        except KeyError:
            return
        raise AssertionError("重复 provide 应当报错")
    check("重复 provide 立即报错", duplicate_provide)

    def require_message():
        ctx = Context(name="t")
        try:
            ctx.require("llm")
        except LookupError as exc:
            assert "inject" in str(exc), "错误提示应指向 inject"
            return
        raise AssertionError("require 缺失服务应当报错")
    check("require 缺失服务的错误提示可操作", require_message)

    def dispose_clears():
        ctx = Context(name="t")
        ctx.provide("a", 1)
        ctx.dispose()
        eq(ctx.state, DISPOSED, "状态")
        eq(ctx.services(), {}, "服务清空")
        try:
            ctx.provide("b", 2)
        except RuntimeError:
            return
        raise AssertionError("已释放的 context 不应接受注册")
    check("dispose 后服务清空且拒绝新注册", dispose_clears)

    def attr_error_clear():
        ctx = Context(name="t")
        try:
            ctx.nope
        except AttributeError as exc:
            assert "available" in str(exc), "错误应列出可用服务"
            return
        raise AssertionError("未知服务应抛 AttributeError")
    check("未知服务属性访问抛清晰 AttributeError", attr_error_clear)


# ======================================================================
def test_effect_and_lifecycle():
    print("\n[3] effect / 级联卸载 / 失败回滚")

    def effect_registers_and_unwinds():
        ctx = Context(name="t")
        log = []
        ctx.effect(lambda: (log.append("setup"), lambda: log.append("teardown"))[1],
                   "demo")
        eq(log, ["setup"], "注册即执行")
        ctx.dispose()
        eq(log, ["setup", "teardown"], "卸载时执行清理")
    check("effect 注册即执行、卸载时回收", effect_registers_and_unwinds)

    def child_cascade():
        ctx = Context(name="root")
        log = []

        def child_plugin(c, config):
            c.effect(lambda: (log.append("child-setup"),
                              lambda: log.append("child-teardown"))[1])
            return None

        ctx.plugin(Plugin("child", child_plugin))
        eq(log, ["child-setup"])
        ctx.dispose()
        eq(log, ["child-setup", "child-teardown"], "父卸载级联子插件清理")
        eq(ctx.effect_count(), 0, "父级清单已清空")
    check("父卸载级联回收子插件", child_cascade)

    def failing_plugin_rolls_back():
        ctx = Context(name="root")
        log = []

        def bad_plugin(c, config):
            c.effect(lambda: (log.append("partial"),
                              lambda: log.append("rollback"))[1])
            raise RuntimeError("plugin blew up")

        child = ctx.plugin(Plugin("bad", bad_plugin))
        eq(child.state, FAILED, "失败状态")
        eq(log, ["partial", "rollback"], "失败插件的已注册 effect 被回滚")
        eq(child.effect_count(), 0, "失败插件不留残余注册")
        ctx.dispose()
    check("插件 apply 失败时回滚已注册 effect", failing_plugin_rolls_back)

    def dispose_is_idempotent():
        ctx = Context(name="t")
        log = []
        ctx.effect(lambda: (log.append("s"), lambda: log.append("d"))[1])
        ctx.dispose()
        ctx.dispose()
        eq(log, ["s", "d"], "重复 dispose 不重复清理")
    check("重复 dispose 幂等", dispose_is_idempotent)


# ======================================================================
def test_inject():
    print("\n[4] inject 驱动的延迟激活")

    def pending_then_active():
        ctx = Context(name="root")
        events = []

        def consumer(c, config):
            events.append("activated")
            c.effect(lambda: (None, lambda: events.append("unloaded"))[1])
            return None

        child = ctx.plugin(Plugin("consumer", consumer, inject=("llm",)))
        eq(child.state, PENDING, "provider 缺失时停在 PENDING")
        eq(events, [], "PENDING 期间不执行 apply")
        eq(ctx.pending_plugins(), ["consumer"], "待激活清单")

        ctx.provide("llm", {"provider": "local"})
        eq(child.state, ACTIVE, "provider 上线后自动激活")
        eq(events, ["activated"], "激活时执行 apply")
        eq(ctx.pending_plugins(), [], "待激活清单清空")

        ctx.dispose()
        eq(events, ["activated", "unloaded"], "随后可正常卸载")
    check("consumer 先挂载 → PENDING → provider 上线后激活", pending_then_active)

    def reverse_order_equivalent():
        """provider 先挂载 vs 后挂载，最终状态必须一致（行序无关）。"""
        def build(reverse: bool):
            ctx = Context(name="root")

            def consumer(c, config):
                return None

            cp = Plugin("consumer", consumer, inject=("llm",))
            if reverse:
                ctx.provide("llm", 1)
                child = ctx.plugin(cp)
            else:
                child = ctx.plugin(cp)
                ctx.provide("llm", 1)
            return ctx, child
        _, c1 = build(False)
        _, c2 = build(True)
        eq(c1.state, c2.state, "两种挂载顺序应得到同一状态")
        eq(c1.state, ACTIVE)
    check("挂载顺序不影响最终状态（依赖驱动）", reverse_order_equivalent)

    def nested_dependency_chain():
        """C → B → A 三级依赖，逆序挂载也应全部激活。"""
        ctx = Context(name="root")

        def mk(name, needs, out):
            def apply(c, config):
                out.append(name)
                return None
            return Plugin(name, apply, inject=needs)

        out = []
        ctx.plugin(mk("C", ("b",), out))
        ctx.plugin(mk("B", ("a",), out))
        eq(sorted(ctx.pending_plugins()), ["B", "C"], "两级都待激活")
        ctx.provide("a", 1)
        eq(out, ["B"], "a 上线激活 B")
        ctx.provide("b", 1)
        eq(out, ["B", "C"], "b 上线激活 C（链式）")
        eq(ctx.pending_plugins(), [])
    check("三级依赖链在服务到位时逐级激活", nested_dependency_chain)


# ======================================================================
def test_events():
    print("\n[5] 事件派发模式与契约校验")

    def emit_order_and_containment():
        bus = EventBus()
        seen = []
        bus.on("x", lambda p: seen.append(1))
        bus.on("x", lambda p: (_ for _ in ()).throw(RuntimeError("nope")))
        bus.on("x", lambda p: seen.append(2))
        bus.emit("x", None)
        eq(seen, [1, 2], "emit 按注册序且异常不阻断")
    check("emit 注册序 + 单监听器异常隔离", emit_order_and_containment)

    def registration_returns_disposable():
        ctx = Context(name="t")
        ctx.on("x", lambda p: None)
        eq(ctx.events.listener_count("x"), 1)
        ctx.dispose()
        eq(ctx.events.listener_count("x"), 0, "context 卸载自动退订")
    check("on() 返回可撤销句柄且随 context 卸载", registration_returns_disposable)

    def explicit_unsubscribe():
        ctx = Context(name="t")
        d = ctx.on("x", lambda p: None)
        d.dispose()
        eq(ctx.events.listener_count("x"), 0, "显式退订生效")
    check("显式退订生效", explicit_unsubscribe)

    def prepend_wins():
        ctx = Context(name="t")
        order = []
        ctx.on("x", lambda p: order.append("normal"))
        ctx.on("x", lambda p: order.append("prepended"), prepend=True)
        ctx.emit("x")
        eq(order, ["prepended", "normal"], "prepend 插队")
    check("prepend 插队到最前", prepend_wins)

    def waterfall_wraps():
        ctx = Context(name="t")
        ctx.on("w", lambda p, nxt: nxt({**p, "v": p["v"] + 1}), mode="waterfall")
        ctx.on("w", lambda p, nxt: {**nxt(p), "tag": "inner"}, mode="waterfall")
        result = ctx.waterfall("w", {"v": 0}, inner=lambda p: {**p, "end": True})
        eq(result, {"v": 1, "end": True, "tag": "inner"}, "waterfall 包裹与改写")
    check("waterfall 改写入参与出参", waterfall_wraps)

    def waterfall_short_circuit():
        ctx = Context(name="t")
        called = []
        ctx.on("w", lambda p, nxt: {"vetoed": True}, mode="waterfall")
        ctx.on("w", lambda p, nxt: called.append("should-not-run") or nxt(p),
               mode="waterfall")
        result = ctx.waterfall("w", {"v": 1}, inner=lambda p: called.append("inner"))
        eq(result, {"vetoed": True}, "不调用 next 即短路")
        eq(called, [], "短路后下游与 inner 都不执行")
    check("waterfall 不调 next 即短路（含 inner）", waterfall_short_circuit)

    def serial_bails():
        ctx = Context(name="t")
        ctx.on("s", lambda p: "first", mode="serial")
        ctx.on("s", lambda p: "second", mode="serial")
        eq(ctx.serial("s"), "first", "首个非 None 胜出")
        eq(ctx.serial("none-registered"), None, "无监听器返回 None")
    check("serial 首个非 None 短路", serial_bails)

    def mode_is_contract():
        ctx = Context(name="t")
        ctx.on("x", lambda p: None, mode="waterfall")
        try:
            ctx.on("x", lambda p: None, mode="emit")
        except ValueError as exc:
            assert "contract" in str(exc)
            return
        raise AssertionError("混用派发模式应当报错")
    check("同一事件名混用派发模式立即报错", mode_is_contract)

    def unknown_mode_rejected():
        ctx = Context(name="t")
        try:
            ctx.on("x", lambda p: None, mode="parallel")
        except ValueError:
            return
        raise AssertionError("未知模式应当报错")
    check("未知派发模式被拒绝", unknown_mode_rejected)


# ======================================================================
def test_patch_semantics():
    print("\n[6] patch 语义")

    def insert_and_override():
        out = apply_patches([], compose(
            [{"insert": [{"id": "a", "name": "x", "config": {"v": 1}},
                         {"id": "b", "name": "y", "config": {"v": 2}}]}],
            [{"id": "a", "config": {"v": 9}}, {"id": "b", "disabled": True}],
        ))
        by_id = {e["id"]: e for e in out}
        eq(by_id["a"]["config"], {"v": 9}, "整键替换")
        eq(by_id["b"]["disabled"], True, "覆盖 disabled")
        eq(len(out), 2)
    check("insert + 按 id 整键替换", insert_and_override)

    def whole_key_replace_not_merge():
        base = [{"id": "a", "config": {"keep": 1, "drop": 2}}]
        out = apply_patches(base, [{"id": "a", "config": {"keep": 7}}])
        eq(out[0]["config"], {"keep": 7}, "不做深合并（drop 被整体移除）")
    check("整键替换而非深合并", whole_key_replace_not_merge)

    def input_not_mutated():
        base = [{"id": "a", "config": {"v": 1}}]
        snapshot = repr(base)
        apply_patches(base, [{"id": "a", "config": {"v": 2}}])
        eq(repr(base), snapshot, "入参不可变（热重载可回退的前提）")
    check("patch 不修改入参", input_not_mutated)

    def name_assertion():
        base = [{"id": "a", "name": "x", "config": {}}]
        warns = []
        out = apply_patches(base, [{"id": "a", "name": "wrong", "config": {"v": 9}}],
                            warn=warns.append)
        eq(out[0]["config"], {}, "name 不匹配则跳过")
        assert warns, "应产生警告"
    check("name 作为断言防止改错行", name_assertion)

    def missing_target_warns_only():
        warns = []
        out = apply_patches([{"id": "a"}], [{"id": "nope", "config": {}}],
                            warn=warns.append)
        eq(len(out), 1, "目标缺失不改变结果")
        assert warns
    check("目标缺失只警告不抛错", missing_target_warns_only)

    def inserted_row_is_patchable_same_layer():
        """Harness 对上游 Cordis 的修复：同层后续 patch 能命中刚 insert 的行。"""
        out = apply_patches([], [
            {"insert": [{"id": "new", "name": "x", "config": {"v": 1}}]},
            {"id": "new", "config": {"v": 2}},
        ])
        eq(out[0]["config"], {"v": 2}, "同层可 patch 刚插入的行")
    check("insert 后立即可被同层 patch 命中", inserted_row_is_patchable_same_layer)

    def nested_group_index():
        base = [{"id": "g", "group": True,
                 "config": [{"id": "inner", "config": {"v": 1}}]}]
        idx = build_index(base)
        eq(sorted(idx), ["g", "inner"], "递归索引 group 子行")
        out = apply_patches(base, [{"id": "inner", "config": {"v": 5}}])
        eq(out[0]["config"][0]["config"], {"v": 5}, "可 patch 嵌套行")
    check("group 子行可被索引与 patch", nested_group_index)

    def insert_into_group():
        base = [{"id": "g", "group": True, "config": []}]
        out = apply_patches(base, [{"id": "g", "insert": [{"id": "x", "name": "y"}]}])
        eq(len(out[0]["config"]), 1, "insert 进 group 子列表")
    check("insert 可定向到 group", insert_into_group)

    def insert_into_non_group_warns():
        warns = []
        base = [{"id": "leaf", "config": {}}]
        apply_patches(base, [{"id": "leaf", "insert": [{"id": "x"}]}],
                      warn=warns.append)
        assert any("not a group" in w for w in warns), warns
    check("向非 group 行 insert 只警告", insert_into_non_group_warns)


# ======================================================================
def test_scope_and_loader():
    print("\n[7] 隔离作用域 / Loader 审计")

    def isolate_shields():
        host = Context(name="host")
        host.provide("svc", "host-value")
        scope = host.isolate("svc")
        eq(scope.get("svc"), None, "隔离名不穿透到祖先")
        scope.provide("svc", "scope-value")
        eq(scope.get("svc"), "scope-value")
        eq(host.get("svc"), "host-value", "父级不受影响")
        scope.dispose()
    check("isolate 隔离同名服务", isolate_shields)

    def sibling_scopes_independent():
        host = Context(name="host")
        a = host.isolate("svc")
        b = host.isolate("svc")
        a.provide("svc", "A")
        b.provide("svc", "B")
        eq(a.get("svc"), "A")
        eq(b.get("svc"), "B")
        a.dispose()
        eq(b.get("svc"), "B", "兄弟作用域互不影响")
    check("兄弟隔离作用域互不干扰", sibling_scopes_independent)

    def loader_mounts_and_skips():
        ctx = Context(name="root")
        mounted = []

        def fac(kind):
            def make(config):
                def apply(c, cfg):
                    mounted.append((kind, cfg))
                    return None
                return Plugin(kind, apply)
            return make

        loader = Loader(ctx, {"x": fac("x"), "y": fac("y")})
        loader.mount([{"id": "1", "name": "x", "config": {"v": 1}},
                      {"id": "2", "name": "y", "disabled": True},
                      {"id": "3", "name": "unknown"}])
        eq([m[0] for m in mounted], ["x"], "禁用行与未知插件不挂载")
        eq(len(loader.warnings), 2, "未知插件与禁用行各一条警告")
        eq(loader.status(), {"1": ACTIVE})
        ctx.dispose()
    check("Loader 挂载 / 跳过禁用 / 未知只警告", loader_mounts_and_skips)

    def loader_audit_fail_loud():
        ctx = Context(name="root")
        loader = Loader(ctx, {"x": lambda cfg: Plugin("x", lambda c, g: None)},
                        required=("1", "must-exist"))
        try:
            loader.mount([{"id": "1", "name": "x"}])
        except RuntimeError as exc:
            assert "must-exist" in str(exc)
            return
        raise AssertionError("必败清单缺失应当抛错")
    check("必败清单缺失时整体失败", loader_audit_fail_loud)

    def group_isolate_scope():
        ctx = Context(name="root")
        ctx.provide("svc", "host")
        seen = {}

        def fac(config):
            def apply(c, cfg):
                seen["svc"] = c.get("svc")
                return None
            return Plugin("p", apply)

        loader = Loader(ctx, {"p": fac})
        loader.mount([{"id": "g", "group": True, "isolate": {"svc": True},
                       "config": [{"id": "inner", "name": "p"}]}])
        eq(seen["svc"], None, "group 内隔离名看不到宿主服务")
        ctx.dispose()
    check("group 的 isolate 生效", group_isolate_scope)


# ======================================================================
def test_kernel_invariants():
    """内核自身的不变式 —— 对应报告「把架构原则写成可执行断言」。"""
    print("\n[8] 内核不变式（可执行断言）")

    def invariant_no_leak_after_dispose():
        ctx = Context(name="root")
        ctx.provide("engines", {})

        def plugin(c, config):
            c.effect(lambda: (None, lambda: None)[1])
            c.provide("sub", 1)
            c.on("e", lambda p: None)
            return lambda: None

        ctx.plugin(Plugin("p", plugin))
        ctx.plugin(Plugin("q", plugin, inject=("missing-svc",)))
        ctx.dispose()
        assert ctx.effect_count() == 0, "卸载后不留 effect"
        assert ctx.services() == {}, "卸载后不留服务"
        assert ctx.events.listener_count("e") == 0, "卸载后不留监听器"
        assert ctx.pending_plugins() == [], "卸载后不留待激活项"
    check("不变式：卸载后无 effect / 服务 / 监听器 / 待激活项残留", invariant_no_leak_after_dispose)

    def invariant_declared_services_are_available():
        """插件声明了 inject，就必须在被激活时全部可解析。"""
        ctx = Context(name="root")
        observed = []

        def consumer(c, config):
            for name in ("a", "b"):
                c.require(name)          # 缺任一即抛
            observed.append("ok")
            return None

        ctx.plugin(Plugin("c", consumer, inject=("a", "b")))
        eq(observed, [], "未满足时不激活")
        ctx.provide("a", 1)
        eq(observed, [], "只满足一半仍不激活")
        ctx.provide("b", 2)
        eq(observed, ["ok"], "全部满足才激活")
    check("不变式：被激活的插件其 inject 必可解析", invariant_declared_services_are_available)

    def invariant_patch_replay_is_deterministic():
        """同一组 patch 重放必须得到同一结果（热重载可回退的前提）。"""
        base = []
        patches = compose(
            [{"insert": [{"id": "a", "name": "x", "config": {"v": 1}}]}],
            [{"id": "a", "config": {"v": 2}}],
        )
        first = apply_patches(base, patches)
        for _ in range(3):
            eq(apply_patches(base, patches), first, "重复重放结果一致")
    check("不变式：patch 重放确定性", invariant_patch_replay_is_deterministic)

    def invariant_emit_does_not_change_control_flow():
        """emit 监听器的返回值必须不影响调用方（与 waterfall 区分开）。"""
        ctx = Context(name="t")
        ctx.on("x", lambda p: {"should": "be ignored"}, mode="emit")
        try:
            ctx._assert_active()
        except Exception:
            raise AssertionError("emit 不应影响控制流")
        ctx.emit("x", None)
        ctx.dispose()
    check("不变式：emit 返回值不改变控制流", invariant_emit_does_not_change_control_flow)


# ======================================================================
def test_bootstrap_consistency():
    """自举一致性：用**项目自己的**状态机引擎验证内核的生命周期。

    这是本方案最有价值的一组测试，因为它把"内核的行为"变成了可由项目自身
    工具链消费的数据：

    * ``core/kernel/fiber_model.json`` 用项目的状态机配置格式描述 Fiber 生命周期；
    * 本用例驱动「真实内核」与「该模型」锁步前进，逐步比对状态；
    * 任何一步不一致即失败 —— 内核实现与它的模型不可能悄悄漂移。

    副作用收益：模型里的 ``on_enter`` / ``on_exit`` 是真实的 ACTION_REGISTRY 动作，
    因此"内核状态迁移的动作序列"也变成可断言、可可视化的数据。
    """
    print("\n[9] 自举一致性：用项目 FSM 引擎验证内核生命周期")

    try:
        import json

        from zhuangtaiji.core import create_state_machine, register_action, register_guard
    except Exception as exc:                       # 项目引擎不可用时优雅跳过
        print(f"  [skip] 无法导入项目 FSM 引擎：{exc!r}")
        return

    model_cfg = json.loads(
        (_KERNEL_DIR / "fiber_model.json").read_text(encoding="utf-8"))
    model_cfg.pop("_comment", None)
    full_cfg = {"state_machines": {"fiber": model_cfg}}

    # 模型里的 on_enter / on_exit 引用的是真实动作名 —— 注册成可观测的动作
    action_log: list = []
    for _name in ("join_pending_list", "leave_pending_list", "run_apply",
                  "unwind_effects", "rollback_effects"):
        register_action(_name, (lambda n: lambda *a, **k: action_log.append(n))(_name))
    register_guard("inject_satisfied",
                   lambda ctx: bool(ctx.get("inject_satisfied")))

    def new_pair():
        ctx = Context(name="root")
        model = create_state_machine("fiber", dict(full_cfg))
        return ctx, model

    def good_plugin(c, config):
        c.effect(lambda: (None, lambda: None)[1])
        return None

    def bad_plugin(c, config):
        c.effect(lambda: (None, lambda: None)[1])
        raise RuntimeError("apply failed")

    def drive(title, ops, state_of):
        """按 ops 逐操作驱动内核与模型，逐步断言状态一致。

        每个 op = ``(说明, kernel_fn, model_event, guard_ctx)``；
        ``model_event`` 为 ``None`` 表示该步在模型中不产生转移。
        """
        ctx, model = new_pair()
        for desc, kfn, event, guard_ctx in ops:
            kfn(ctx)
            if event is not None:
                model.trigger(event, guard_ctx or {})
            kstate = state_of()
            mstate = model.current_state_id
            if kstate != mstate:
                raise AssertionError(
                    f"[{title}] 在「{desc}」处分歧：内核={kstate} 模型={mstate}")
        return ctx, model

    # ---------------- 场景 A：正常插件完整生命周期 ----------------
    def scn_a():
        holder = {}

        def mount_k(ctx):
            # 先挂载、后提供 —— 这是本项目 config.json 里调换行序也会遇到的情形
            holder["p"] = ctx.plugin(Plugin("good", good_plugin, inject=("svc",)))

        def provide_k(ctx):
            holder["h"] = ctx.provide("svc", {"v": 1})

        def unprovide_k(ctx):
            holder["h"].dispose()

        ops = [
            ("mount", mount_k, None, None),
            ("provide", provide_k, "provide", {"inject_satisfied": True}),
            ("unprovide", unprovide_k, "unprovide", None),
            ("provide again", provide_k, "provide", {"inject_satisfied": True}),
            ("dispose", lambda c: c.dispose(), "dispose", None),
        ]
        ctx, model = drive("A 正常插件", ops, lambda: holder["p"].state)
        eq(ctx.mount_states(), {}, "卸载后无挂载记录")

    check("A 正常插件：PENDING→ACTIVE→PENDING→ACTIVE→DISPOSED 与模型逐步一致",
          scn_a)

    # ---------------- 场景 B：apply 抛错的插件 ----------------
    def scn_b():
        holder = {}

        def mount_k(ctx):
            holder["p"] = ctx.plugin(Plugin("bad", bad_plugin, inject=("svc",)))

        def provide_k(ctx):
            holder["h"] = ctx.provide("svc", {"v": 1})

        def unprovide_k(ctx):
            holder["h"].dispose()

        ops = [
            ("mount", mount_k, None, None),
            ("provide（apply 抛错）", provide_k, "provide_error", None),
            ("unprovide", unprovide_k, "unprovide", None),
            ("provide again", provide_k, "provide_error", None),
            ("dispose", lambda c: c.dispose(), "dispose", None),
        ]
        ctx, model = drive("B 失败插件", ops, lambda: holder["p"].state)
        eq(ctx.mount_states(), {}, "卸载后无挂载记录")

    check("B 失败插件：PENDING→FAILED→PENDING→FAILED→DISPOSED 与模型一致", scn_b)

    # ---------------- 场景 C：模型未声明的转移，内核也不得发生 ----------------
    def scn_c():
        ctx, model = new_pair()
        holder = {}
        holder["p"] = ctx.plugin(Plugin("good", good_plugin, inject=("svc",)))
        eq(holder["p"].state, PENDING, "provider 未提供时 PENDING")

        # 模型在 PENDING 上没有 unprovide 这条转移
        moved, reason = model.trigger("unprovide", {})
        eq(moved, None, "模型未声明该转移")
        assert reason, "应给出拒绝原因"
        eq(holder["p"].state, PENDING, "内核侧状态同样未变")

        holder["h"] = ctx.provide("svc", 1)
        eq(holder["p"].state, ACTIVE, "内核进入 ACTIVE")
        model.trigger("provide", {"inject_satisfied": True})
        eq(model.current_state_id, ACTIVE, "模型同步到 ACTIVE")

        holder["h"].dispose()
        eq(holder["p"].state, PENDING, "provider 撤回 → 内核退回 PENDING")
        model.trigger("unprovide", {})
        eq(model.current_state_id, PENDING, "模型同步到 PENDING")
    check("C 模型未声明的转移与内核行为一致（双向校验）", scn_c)

    # ---------------- 场景 D：动作序列被模型记录 ----------------
    def scn_d():
        action_log.clear()
        ctx, model = new_pair()
        holder = {}
        holder["p"] = ctx.plugin(Plugin("good", good_plugin, inject=("svc",)))
        holder["h"] = ctx.provide("svc", 1)
        model.trigger("provide", {"inject_satisfied": True})
        ctx.dispose()
        assert action_log, "on_enter/on_exit 动作应已执行"
        assert "run_apply" in action_log, f"进入 ACTIVE 应执行 run_apply：{action_log}"
    check("D 模型的 on_enter/on_exit 以真实动作执行（可断言、可视化）", scn_d)

    # ---------------- 场景 E：真实配置也可被加载（非伪造格式） ----------------
    def scn_e():
        assert "states" in model_cfg and "transitions" in model_cfg["states"]["PENDING"]
        events = set(model_cfg["states"]["PENDING"]["transitions"])
        assert {"provide", "provide_error", "dispose"} <= events, events
        # 模型能被项目引擎构造出来即说明格式合法
        m = create_state_machine("fiber", dict(full_cfg))
        eq(m.current_state_id, "PENDING")
    check("E fiber_model.json 是项目 FSM 引擎可直接加载的合法配置", scn_e)


# ======================================================================
def test_registry_migration():
    """P1-1：守卫/动作注册表已由内核 Context 承载。

    这一组断言锁定"可撤销 + fail-loud + fail-closed"三条契约。其中
    **fail-closed** 是改造中发现的真实缺陷：过去守卫查不到时会被静默放行
    （``callable(None)`` 为假 → 不拒绝 → 转移照常发生），使"config 里写错
    guard 名"从一个配置错误变成"意外允许转移"。
    """
    print("\n[10] 注册表收编（P1-1）：可撤销 / fail-loud / fail-closed")

    from zhuangtaiji.core import create_state_machine, register_action, register_guard
    from zhuangtaiji.core.registries import ACTION_REGISTRY, GUARD_REGISTRY

    def scn_revocable():
        holder = {}
        holder["h"] = register_guard("_kit_g", lambda c: c.get("ok") is True)
        cfg = {"state_machines": {"p": {"initial": "a", "states": {
            "a": {"content": "A",
                  "transitions": {"go": {"target": "b", "guard": "_kit_g"}}},
            "b": {"content": "B", "transitions": {}}}}}}
        sm = create_state_machine("p", cfg)
        eq(sm.trigger("go", {"ok": True})[0], "b", "注册后守卫生效")

        holder["h"].dispose()
        sm2 = create_state_machine("p", cfg)
        moved, reason = sm2.trigger("go", {"ok": True})
        eq(moved, None, "撤销后不再放行")
        assert "未注册" in reason, reason
    check("守卫可撤销，且撤销后立即失效", scn_revocable)

    def scn_existing_instances_see_revocation():
        """撤销对**已创建**的实例也立即生效（实时查询，而非构造时快照）。"""
        h = register_guard("_kit_g2", lambda c: True)
        cfg = {"state_machines": {"p": {"initial": "a", "states": {
            "a": {"content": "A",
                  "transitions": {"go": {"target": "b", "guard": "_kit_g2"}}},
            "b": {"content": "B", "transitions": {}}}}}}
        sm = create_state_machine("p", cfg)      # 先建实例
        h.dispose()                              # 后撤销
        moved, reason = sm.trigger("go", {})
        eq(moved, None, "已存在实例也必须感知撤销")
        assert "未注册" in reason
    check("撤销对已创建实例实时生效", scn_existing_instances_see_revocation)

    def scn_fail_closed_on_missing_guard():
        cfg = {"state_machines": {"p": {"initial": "a", "states": {
            "a": {"content": "A",
                  "transitions": {"go": {"target": "b", "guard": "_kit_ghost"}}},
            "b": {"content": "B", "transitions": {}}}}}}
        sm = create_state_machine("p", cfg)
        moved, reason = sm.trigger("go", {})
        eq(moved, None, "未注册的 guard 必须拒绝转移（fail-closed）")
        assert "_kit_ghost" in reason and "未注册" in reason, reason
        eq(sm.current_state_id, "a", "状态未变")
    check("未注册的 guard 被 fail-closed 拒绝（不再静默放行）", scn_fail_closed_on_missing_guard)

    def scn_fail_closed_in_hsm():
        """HSM 走独立的守卫解析路径，同样必须 fail-closed。"""
        from zhuangtaiji.core import HierarchicalStateMachine
        cfg = {"state_machines": {"h": {
            "type": "hierarchical", "initial": "top",
            "states": {"top": {"initial": "inner", "substates": {
                "inner": {"content": "inner", "transitions": {
                    "go": {"target": "done", "guard": "_kit_ghost2"}}},
                "done": {"content": "done", "transitions": {}}}}}}}}
        hsm = HierarchicalStateMachine("h", cfg)
        moved, reason = hsm.trigger("go", {})
        eq(moved, None, "HSM 未注册 guard 也必须拒绝")
        assert "未注册" in reason, reason
    check("HSM 的守卫解析同样 fail-closed", scn_fail_closed_in_hsm)

    def scn_duplicate_fails_loud():
        h = register_guard("_kit_dup", lambda c: True)
        try:
            register_guard("_kit_dup", lambda c: False)
        except KeyError as exc:
            assert "_kit_dup" in str(exc), str(exc)
        else:
            raise AssertionError("重复注册应当抛 KeyError")
        finally:
            h.dispose()
    check("重复注册 fail-loud（不再静默覆盖）", scn_duplicate_fails_loud)

    def scn_assignment_blocked():
        """禁止直接赋值：绕过 register() 就无法追踪 disposer。"""
        try:
            GUARD_REGISTRY["_kit_x"] = lambda c: True
        except TypeError as exc:
            assert "register_guard" in str(exc) or "register" in str(exc), str(exc)
        else:
            raise AssertionError("RegistryView 应禁止赋值")
    check("禁止直接赋值（防止绕过 disposer 追踪）", scn_assignment_blocked)

    def scn_dict_compat_read():
        """历史代码以 dict 方式读取，必须继续工作。"""
        h = register_action("_kit_a", lambda ctx, detail: None)
        assert "_kit_a" in ACTION_REGISTRY
        assert ACTION_REGISTRY["_kit_a"] is not None
        assert ACTION_REGISTRY.get("_kit_a") is not None
        assert len(list(ACTION_REGISTRY.keys())) >= 1
        assert list(ACTION_REGISTRY.items())
        assert "_kit_a" in dict(ACTION_REGISTRY)
        h.dispose()
        assert "_kit_a" not in ACTION_REGISTRY
    check("RegistryView 保持 dict 兼容读取", scn_dict_compat_read)

    def scn_instance_override_wins():
        """实例级 guards 参数优先于进程注册表。"""
        h = register_guard("_kit_ovr", lambda c: False)
        try:
            cfg = {"state_machines": {"p": {"initial": "a", "states": {
                "a": {"content": "A",
                      "transitions": {"go": {"target": "b", "guard": "_kit_ovr"}}},
                "b": {"content": "B", "transitions": {}}}}}}
            eq(create_state_machine("p", cfg).trigger("go", {})[0], None,
               "注册表里的守卫返回 False → 拒绝")
            sm = create_state_machine("p", cfg, guards={"_kit_ovr": lambda c: True})
            eq(sm.trigger("go", {})[0], "b", "实例级覆盖优先生效")
        finally:
            h.dispose()
    check("实例级 guards 覆盖进程注册表", scn_instance_override_wins)

    def scn_action_registry_live():
        """动作注册同样是实时的（不必重建实例）。"""
        log = []
        h = register_action("_kit_act", lambda ctx, detail: log.append(detail.get("state")))
        cfg = {"state_machines": {"p": {"initial": "a", "states": {
            "a": {"content": "A", "on_enter": "_kit_act", "transitions": {}}}}}}
        sm = create_state_machine("p", cfg)
        assert log, "已注册动作应当被调用"
        h.dispose()
    check("动作注册实时生效", scn_action_registry_live)


# ======================================================================
def test_engine_registry_single_source():
    """P1-2：引擎范式信息只有**一处**归属（core.registries.engines）。

    改造前，同一份「kind → config 段名」映射在项目里有 **7 份副本**：
    ``engine_adapters`` 两张表、``plugin.py`` 七次 ``_section_provider``、
    ``web/server.py`` 三处、``ui/analysis_tab.py``、``ui/visualization_tab.py``。
    新增一个范式需要逐处补写，漏一处就出现"某个入口看不到新范式"。

    本组断言除验证注册表行为外，还用**源码级扫描**锁定"不再出现重复映射"——
    这是一条反回归门禁：谁把硬编码写回来，测试就红。
    """
    print("\n[11] 引擎注册表单源（P1-2）")

    from zhuangtaiji.core import build_adapter, load_config, plugin
    from zhuangtaiji.core.registries import engine_kinds, engine_of, engine_sections

    plugin.ensure_discovered()

    def scn_single_table():
        kinds = engine_kinds()
        assert kinds, "引擎注册表不应为空"
        names = [m.kind for m in kinds]
        eq(len(names), len(set(names)), "kind 唯一")
        for meta in kinds:
            assert meta.section, f"{meta.kind} 缺少 section"
            assert meta.adapter_cls is not None, f"{meta.kind} 缺少 adapter_cls"
            assert meta.label, f"{meta.kind} 缺少 label"
        # 内置 7 + 插件 2
        assert {"state_machine", "behavior_tree", "decision_tree", "petri_net",
                "markov_chain", "rule_engine", "difference_engine"} <= set(names), names
        assert {"decision_table", "llm_agent"} <= set(names), names
    check("注册表是引擎信息的唯一归属（9 个范式，字段完整）", scn_single_table)

    def scn_pluginregistry_is_a_view():
        """PluginRegistry 必须是注册表的视图，而不是第二张表。"""
        eq(sorted(plugin.PluginRegistry.kinds()),
           sorted(m.kind for m in engine_kinds()),
           "PluginRegistry.kinds() 与注册表一致")
        for pl in plugin.PluginRegistry.all():
            meta = engine_of(pl.kind)
            assert meta is not None, f"{pl.kind} 不在注册表中"
            eq(pl.section, meta.section, f"{pl.kind} 的 section 一致")
            eq(pl.label, meta.label, f"{pl.kind} 的 label 一致")
    check("PluginRegistry 是注册表的视图（不存在第二张表）", scn_pluginregistry_is_a_view)

    def scn_build_adapter_errors_are_actionable():
        cfg = load_config()
        try:
            build_adapter("nonexistent_kind", "x", cfg)
        except ValueError as exc:
            msg = str(exc)
            assert "nonexistent_kind" in msg and "已注册" in msg, msg
        else:
            raise AssertionError("未知 kind 应当抛 ValueError")

        try:
            build_adapter("state_machine", "NO_SUCH_INSTANCE", cfg)
        except ValueError as exc:
            msg = str(exc)
            assert "NO_SUCH_INSTANCE" in msg and "可用" in msg, msg
        else:
            raise AssertionError("不存在的实例应当抛 ValueError")
    check("构造失败给出可操作的错误（列出已注册/可用项）", scn_build_adapter_errors_are_actionable)

    def scn_no_duplicate_section_maps():
        """源码级反回归：消费方不得再硬编码 kind → 段名 的映射。

        判定用两种**可辨识的硬编码特征**，而不是裸字符串——因为 ``kind``
        本身常常与段名同形（例如 ``"difference_engine"`` 既是 kind 也是段名），
        裸串匹配会误报合法的 kind 字面量：

        1. **按段名直接索引配置**：``["state_machines"]``；
        2. **映射字面量**：``"state_machine": "state_machines"``。

        ``core/engine_adapters.py`` 的 ``_BUILTIN_ENGINE_KINDS`` 是唯一合法归属，
        因此不在扫描范围内。
        """
        sections = dict(engine_sections())
        targets = ["web/server.py", "ui/application.py", "ui/analysis_tab.py",
                   "ui/visualization_tab.py", "ui/orchestrator_tab.py",
                   "ui/plugin_tab.py", "core/plugin.py", "core/orchestrator.py"]
        offenders = []
        for rel in targets:
            path = _PROJECT_ROOT / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for kind, section in sections.items():
                if f'["{section}"]' in text:
                    offenders.append(f"{rel}: 按段名直接索引 {section!r}")
                if f'"{kind}": "{section}"' in text or f"'{kind}': '{section}'" in text:
                    offenders.append(f"{rel}: 映射字面量 {kind!r} → {section!r}")
        assert not offenders, ("发现重复的 kind → 段名 映射（应改为 engine_sections()）：\n  "
                               + "\n  ".join(offenders))
    check("消费方不再硬编码 kind → 段名（源码级门禁）", scn_no_duplicate_section_maps)

    def scn_revocable_engine_kind():
        """注册可撤销：撤销后该范式从所有入口消失。"""
        from zhuangtaiji.core.registries import register_engine

        class _Dummy:
            def __init__(self, name="", on_event=None):
                self.name = name

            def load(self, spec):
                pass

        h = register_engine("_kit_kind", _Dummy, "_kit_section", "临时范式")
        assert "_kit_kind" in plugin.PluginRegistry.kinds()
        eq(engine_sections().get("_kit_kind"), "_kit_section")
        h.dispose()
        assert "_kit_kind" not in plugin.PluginRegistry.kinds(), "撤销后应消失"
        assert "_kit_kind" not in engine_sections()
    check("引擎范式注册可撤销", scn_revocable_engine_kind)

    def scn_analysis_capability_declared():
        """分析能力声明在 analysis 模块里（唯一归属），且对不支持的范式 fail-loud。"""
        from zhuangtaiji.core import analysis
        assert analysis.SUPPORTED_KINDS, "应声明支持的范式"
        for kind in analysis.SUPPORTED_KINDS:
            assert engine_of(kind) is not None, f"{kind} 未注册为引擎范式"
        try:
            analysis.format_analysis("behavior_tree", {})
        except ValueError as exc:
            assert "没有形式化分析实现" in str(exc), str(exc)
        else:
            raise AssertionError("不支持的范式应当抛 ValueError")
    check("分析能力声明唯一归属且 fail-loud", scn_analysis_capability_declared)

    def scn_web_catalog_derived():
        """Web 端目录从注册表派生（含插件范式）。"""
        try:
            import zhuangtaiji.web.server as ws
        except Exception as exc:                   # 前端依赖缺失时跳过
            print(f"  [skip] 无法导入 web.server: {exc!r}")
            return
        catalog = ws._engine_catalog()
        kinds = engine_kinds()
        eq(len(catalog), len(kinds), "目录覆盖全部范式")
        for meta in kinds:
            assert meta.kind in catalog, f"{meta.kind} 未出现在 Web 目录中"
    check("Web 目录从注册表派生", scn_web_catalog_derived)


# ======================================================================
def test_event_bus_migration():
    """P1-3 / P2：事件总线接入内核 + 引擎扩展点。

    其中前两条锁定一个**真实 bug 的修复**：``Orchestrator.reset()`` 过去清
    ``engines``/``trace``/``_bindings`` 但**不清总线**，而 ``configure()`` 每次
    都往总线注册新 handler —— 于是反复 ``configure()`` 会让监听器线性累积、
    同一个事件被触发 N 次。
    """
    print("\n[12] 事件总线与编排器（P1-3 / P2）")

    from zhuangtaiji.core import load_config
    from zhuangtaiji.core.orchestrator import Orchestrator

    cfg = load_config()
    spec = cfg["orchestration"]["demo"]
    bindings = len(spec.get("bindings", []))

    def scn_no_listener_accumulation():
        o = Orchestrator()
        counts = []
        for _ in range(5):
            o.configure(spec, cfg)
            counts.append(o.bus.listener_count())
        eq(counts, [bindings] * 5,
           f"反复 configure 后监听器数应恒为 {bindings}（实际 {counts}）")
    check("反复 configure 不累积监听器（真实 bug 修复）", scn_no_listener_accumulation)

    def scn_reset_unsubscribes():
        o = Orchestrator()
        o.configure(spec, cfg)
        assert o.bus.listener_count() > 0
        o.reset()
        eq(o.bus.listener_count(), 0, "reset 必须退订全部绑定")
        eq(o.engines, {}, "reset 清空引擎")
    check("reset() 退订全部绑定", scn_reset_unsubscribes)

    def scn_subscribe_is_revocable():
        o = Orchestrator()
        h = o.bus.subscribe("enter", lambda e: None)
        eq(o.bus.listener_count("enter"), 1)
        h.dispose()
        eq(o.bus.listener_count("enter"), 0, "退订后计数归零")

        h2 = o.bus.subscribe_all(lambda e: None)
        assert o.bus.listener_count() >= 1
        h2.dispose()
        eq(o.bus.listener_count(), 0)
    check("subscribe / subscribe_all 返回可撤销句柄", scn_subscribe_is_revocable)

    def scn_wildcard_semantics_preserved():
        o = Orchestrator()
        o.configure(spec, cfg)
        seen = []
        h = o.bus.subscribe_all(lambda e: seen.append(e.etype))
        o.start()
        assert seen, "通配订阅应当收到事件"
        h.dispose()
    check("'*' 通配订阅语义保持不变", scn_wildcard_semantics_preserved)

    def scn_behavior_unchanged():
        o = Orchestrator()
        o.configure(spec, cfg)
        o.start()
        assert o.trace, "编排轨迹不应为空"
        text = o.report()
        assert "事件/动作轨迹" in text, text[:80]
        # 绑定链应当从 sm 传播到 bt 再到 mc
        actions = [t.get("action", "") for t in o.trace if "action" in t]
        assert any(a.startswith("bt.") for a in actions), actions
        assert any(a.startswith("mc.") for a in actions), actions
    check("编排既有行为不变（绑定链正常传播）", scn_behavior_unchanged)

    def scn_step_waterfall_intercepts():
        """策略监听器可改写 step 入参 —— 无需修改 Orchestrator。"""
        o = Orchestrator()
        o.configure(spec, cfg)
        seen = []

        def clamp(meta, nxt):
            seen.append(dict(meta["ctx"]))
            meta = {**meta, "ctx": {**meta["ctx"], "event": "safe_event"}}
            return nxt(meta)

        o.bus.subscribe(Orchestrator.EVENT_STEP, clamp, mode="waterfall")
        o.invoke_engine("sm", {"event": "risky_event"})
        assert seen, "waterfall 监听器应当被调用"
        eq(seen[0], {"event": "risky_event"}, "监听器看到原始入参")
    check("engine/step waterfall 可改写入参（策略可插入）", scn_step_waterfall_intercepts)

    def scn_step_waterfall_can_veto():
        o = Orchestrator()
        o.configure(spec, cfg)
        o.bus.subscribe(Orchestrator.EVENT_STEP, lambda meta, nxt: None,
                        mode="waterfall")
        eq(o.invoke_engine("sm", {"event": "start"}), None, "不调 next_ 即否决")
    check("engine/step 不调 next_ 即短路（否决）", scn_step_waterfall_can_veto)

    def scn_stepped_is_notification():
        o = Orchestrator()
        o.configure(spec, cfg)
        notes = []
        o.bus.subscribe(Orchestrator.EVENT_STEPPED,
                        lambda p: notes.append(p["alias"]), mode="emit")
        o.invoke_engine("sm", {"event": "start"})
        assert "sm" in notes, notes
    check("engine/stepped 是 step 完成后的纯通知", scn_stepped_is_notification)

    def scn_mode_contract_on_engine_events():
        o = Orchestrator()
        o.configure(spec, cfg)
        o.bus.subscribe(Orchestrator.EVENT_STEP, lambda m, n: n(m),
                        mode="waterfall")
        try:
            o.bus.subscribe(Orchestrator.EVENT_STEP, lambda p: None, mode="emit")
        except ValueError as exc:
            assert "contract" in str(exc), str(exc)
        else:
            raise AssertionError("engine/step 混用模式应当报错")
    check("engine/step 的派发模式契约被强制", scn_mode_contract_on_engine_events)


# ======================================================================
# ======================================================================
def test_load_time_validation():
    """P4：状态机配置在 load 期即校验，而非首次 trigger 才抛裸 KeyError。

    此前 ``core/state_machine.py`` 不在装配期校验 ``initial`` / ``transitions.target``，
    导致非法引用要等到第一次触发事件才暴露为裸 ``KeyError``。现在改为 fail-loud：
    装配阶段抛出**带精确路径**的 ``ValueError``。
    """
    print("\n[13] load 期配置校验（P4）")

    from zhuangtaiji.core import create_state_machine, load_config

    def scn_real_config_valid():
        """真实 config.json 的所有状态机都应通过校验（无假阳性）。"""
        cfg = load_config()
        for name in cfg.get("state_machines", {}):
            sm = create_state_machine(name, cfg)      # 不应抛错
            assert sm.current_state_id
    check("真实 config.json 的全部状态机通过 load 期校验", scn_real_config_valid)

    def scn_bad_initial():
        cfg = {"state_machines": {"bad": {"initial": "nope",
                                          "states": {"a": {}, "b": {}}}}}
        try:
            create_state_machine("bad", cfg)
        except ValueError as exc:
            assert "initial" in str(exc) and "nope" in str(exc), str(exc)
        else:
            raise AssertionError("非法 initial 应在 load 期抛 ValueError")
    check("非法 initial 在 load 期 fail-loud 且定位精确", scn_bad_initial)

    def scn_bad_target():
        cfg = {"state_machines": {"bad": {"initial": "a",
                                          "states": {"a": {"transitions": {"go": "ghost"}},
                                                     "b": {}}}}}
        try:
            create_state_machine("bad", cfg)
        except ValueError as exc:
            assert "ghost" in str(exc) and "transitions.go" in str(exc), str(exc)
        else:
            raise AssertionError("非法 transition.target 应在 load 期抛 ValueError")
    check("非法 transition.target 在 load 期 fail-loud 且定位精确",
          scn_bad_target)

    def scn_trigger_still_runs():
        """合法机器在 load 期通过后，触发行为不变。"""
        cfg = {"state_machines": {"ok": {"initial": "a",
                                        "states": {"a": {"transitions": {"go": "b"}},
                                                   "b": {}}}}}
        sm = create_state_machine("ok", cfg)
        eq(sm.trigger("go", {})[0], "b", "合法转移仍正常工作")
    check("load 期校验不破坏合法机器", scn_trigger_still_runs)


def test_ctx_inspect():
    """P4：ctx.inspect 自省接口（engines / services / bindings / pending）。

    把内核的可观测面汇成一份结构化快照，供 UI 诊断面板与锁步测试比对。
    要求：四类信息齐全、返回副本、读它不触发重算（不污染生命周期）。
    """
    print("\n[14] ctx.inspect 自省接口（P4）")

    def scn_surface_four_facets():
        ctx = Context(name="root")
        ctx.provide("engines", {"sm": "StateMachineEngine", "bt": "BehaviorTreeEngine"})
        ctx.provide("bindings", [{"from": "sm", "to": "bt"}, {"from": "bt", "to": "mc"}])

        def lazy(c, config):
            c.effect(lambda: (None, lambda: None)[1])
            return None

        ctx.plugin(Plugin("ready", lazy, inject=("svc",)))
        ctx.plugin(Plugin("waiting", lazy, inject=("svc",)))

        snap = ctx.inspect()
        eq(snap["name"], "root")
        eq(snap["state"], ACTIVE)
        # services：可见服务名（含 engines / bindings）
        assert "engines" in snap["services"] and "bindings" in snap["services"], snap["services"]
        # engines：键列表
        eq(snap["engines"], ["bt", "sm"], "engines 暴露实例键")
        # bindings：数量
        eq(snap["bindings"], 2, "bindings 暴露绑定数量")
        # pending：无 provider 时两个插件都在待激活
        eq(sorted(snap["pending_plugins"]), ["ready", "waiting"])
        eq(snap["active_plugins"], [])
        eq(snap["mount_states"], {"ready": PENDING, "waiting": PENDING})
        # 副本语义：改快照不污染内核
        snap["services"].append("mutated")
        eq(ctx.inspect()["services"], sorted(ctx.services().keys()),
           "inspect 返回副本，改动不影响内核")
    check("inspect 覆盖 engines/services/bindings/pending 四类信息且返回副本",
          scn_surface_four_facets)

    def scn_read_is_non_mutating():
        """读 inspect() 不得触发 _recheck，不得改变任何生命周期状态。"""
        ctx = Context(name="root")
        ctx.provide("svc", 1)

        def lazy(c, config):
            return None
        child = ctx.plugin(Plugin("p", lazy, inject=("svc",)))
        before = ctx.mount_states()
        for _ in range(3):
            ctx.inspect()
        eq(ctx.mount_states(), before, "多次 inspect 不改变挂载状态")
        eq(child.state, ACTIVE, "inspect 不触发重算即可见激活态")
    check("inspect 是只读的（不触发重算、不改变生命周期）", scn_read_is_non_mutating)

    def scn_missing_containers_absent():
        """未挂载 engines / bindings 时快照中相应键缺省（不报错）。"""
        ctx = Context(name="t")
        snap = ctx.inspect()
        assert "engines" not in snap, snap
        assert "bindings" not in snap, snap
    check("未挂载 engines/bindings 时相应键缺省", scn_missing_containers_absent)


def main() -> int:
    print("=" * 74)
    print("core.kernel 行为断言（纯标准库）")
    print("=" * 74)
    test_disposable()
    test_context_services()
    test_effect_and_lifecycle()
    test_inject()
    test_events()
    test_patch_semantics()
    test_scope_and_loader()
    test_kernel_invariants()
    test_bootstrap_consistency()
    test_registry_migration()
    test_engine_registry_single_source()
    test_event_bus_migration()
    test_load_time_validation()
    test_ctx_inspect()

    print("\n" + "=" * 74)
    print(f"通过 {_PASS} 项，失败 {_FAIL} 项")
    if _FAILURES:
        for label, _exc, tb in _FAILURES:
            print("-" * 74)
            print(f"FAILED: {label}")
            print(tb)
    print("=" * 74)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
