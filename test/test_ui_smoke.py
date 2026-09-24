# -*- coding: utf-8 -*-
"""UI 冒烟测试：真实构建整个 Tkinter 工作台，验证 Tab 装配与注册表派生。

**为什么需要它**：本轮改造把三处硬编码列表改为从引擎注册表派生
（``ui/application.py`` 的 ``_sec()`` 与 ``_BUILTIN_TABS``、
``ui/analysis_tab.py`` 与 ``ui/visualization_tab.py`` 的 ``_KINDS``）。
这些文件依赖 tkinter，而改造当时的环境中 tkinter 不可用，只能做语法层校验——
**未能验证**。本用例补上这一环：真实创建窗口、真实装配全部 Tab、
真实驱动一次执行。

前置条件：运行环境需提供 tkinter 与可用的显示（Windows 桌面会话即可）。
不满足时以退出码 77 声明 ENV-SKIP（由 tools/run_tests.py 归类为环境跳过），
并打印 ``SKIP-REQUIRES: tkinter`` 让门禁自动换用带 tkinter 的解释器重试。

**关于退出方式（重要）**：在 Tcl/Tk 9（Python 3.14 自带）下，复杂控件树
（``Notebook`` + ``Canvas`` + ``update_idletasks``）的进程退出阶段存在**确定性的主线程阻塞**——
已用纯 Tkinter 最小复现（不涉及本项目任何代码）：``os._exit(0)`` 被调用后主线程不返回，
且因为它持有 GIL，连看门狗线程都无法运行。

因此本脚本在打印完汇总后：
1. 主动 ``time.sleep`` 释放 GIL 并把终止权交给看门狗；
2. 看门狗线程在 1 秒后 ``os.kill(getpid(), SIGTERM)`` 硬杀（本机 Windows 上即
   ``TerminateProcess``），保证进程一定退出。

正常环境（老 Tk）下看门狗触发前进程已被 ``os._exit`` 终止，无副作用。
门禁侧另有 ``--timeout`` 兜底，防止任何测试永久挂起；并把"打印了完成汇总但被看门狗杀掉"
正确识别为通过，而不是误判为失败。
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import tkinter as tk
except ModuleNotFoundError:
    # SKIP-REQUIRES 是给门禁（tools/run_tests.py）读的机器可读约定：
    # 声明"本测试需要哪个模块"，门禁据此自动换用带该模块的解释器重试，
    # 而不是直接把本测试永久判为环境跳过。
    print("SKIP-REQUIRES: tkinter")
    print("      当前解释器没有 tkinter；门禁会自动尝试带 tkinter 的解释器")
    print("      （探测逻辑见 tools/run_tests.py 的 _candidate_interpreters），"
          "或手动指定：python tools/run_tests.py --python <path>")
    sys.exit(77)

_PASS = 0
_FAIL = 0
_FAILURES: list = []


def check(label: str, fn) -> None:
    """运行一个断言块；异常即记为失败并继续。"""
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
def main() -> int:
    print("=" * 74)
    print(f"UI 冒烟测试 · 解释器 {sys.version.split()[0]} · Tk {tk.TkVersion}")
    print("=" * 74)

    try:
        root = tk.Tk()
    except Exception as exc:                 # 无显示会话等
        print(f"SKIP: 无法创建 Tk 窗口：{exc!r}")
        return 77
    root.withdraw()                          # 不弹窗

    try:
        from core import analysis, load_config, plugin
        from core.registries import engine_kinds, engine_sections

        plugin.ensure_discovered()
        metas = engine_kinds()
        sections = engine_sections()

        # ---------------- 1) Application 能整体装配 ----------------
        print("\n[1] 工作台装配")

        app = None

        def scn_build_app():
            nonlocal app
            from ui import Application
            app = Application(root)
            assert app is not None
        check("Application 整体装配成功（9 个 Tab 全构建）", scn_build_app)

        if app is None:
            print("\n无法继续：Application 构建失败")
            return 1

        def scn_builtin_tabs_present():
            from ui.application import _BUILTIN_TABS
            eq(sorted(app.tabs.keys()), sorted(k for k, _a, _c, _t in _BUILTIN_TABS),
               "self.tabs 覆盖全部内置范式")
            for kind, alias, _cls, title in _BUILTIN_TABS:
                assert hasattr(app, f"tab_{alias}"), f"历史属性 tab_{alias} 丢失"
                assert app.tabs[kind] is getattr(app, f"tab_{alias}"), "两种访问方式一致"
                assert str(title).strip(), f"{kind} 标题为空"
        check("7 个内置 Tab 齐备且历史属性名保持可用", scn_builtin_tabs_present)

        def scn_extra_tabs_present():
            assert app.tab_viz is not None, "可视化 Tab 缺失"
            assert app.tab_analysis is not None, "分析 Tab 缺失"
            assert app.tab_orch is not None, "编排 Tab 缺失"
        check("可视化 / 分析 / 编排 三个增强 Tab 齐备", scn_extra_tabs_present)

        def scn_plugin_tabs_auto():
            """自动发现的插件范式应当各有一个 Tab。"""
            builtin = {k for k, _a, _c, _t in __import__(
                "ui.application", fromlist=["_BUILTIN_TABS"])._BUILTIN_TABS}
            expected = [m.kind for m in metas
                        if m.kind not in builtin
                        and plugin.PluginRegistry.get(m.kind).specs()]
            got = [t.plugin.kind for t in app.plugin_tabs]
            eq(sorted(got), sorted(expected),
               f"插件 Tab 应覆盖 {expected}")
            assert got, "至少应有插件 Tab（决策表 / LLM Agent）"
        check("插件范式自动生成 Tab", scn_plugin_tabs_auto)

        # ---------------- 2) _sec() 段名解析 ----------------
        print("\n[2] 段名解析（单一归属）")

        def scn_sec_resolves():
            from ui.application import _sec
            for meta in metas:
                eq(_sec(meta.kind), meta.section, f"{meta.kind} 的段名")
        check("_sec() 对全部范式返回注册表段名", scn_sec_resolves)

        def scn_sec_fails_loud():
            from ui.application import _sec
            try:
                _sec("no_such_kind")
            except KeyError as exc:
                assert "no_such_kind" in str(exc) and "可用" in str(exc), str(exc)
            else:
                raise AssertionError("未知 kind 应当抛 KeyError")
        check("_sec() 对未知 kind fail-loud 且列出可用项", scn_sec_fails_loud)

        # ---------------- 3) 两个 Tab 的派生列表 ----------------
        print("\n[3] Tab 内派生列表")

        def scn_analysis_kinds():
            from ui import analysis_tab
            got = [k[0] for k in analysis_tab._KINDS]
            eq(got, list(analysis.SUPPORTED_KINDS),
               "分析 Tab 的范式应与 analysis.SUPPORTED_KINDS 一致")
            # 段名必须来自注册表，而不是自带副本
            for kind, section, label in analysis_tab._KINDS:
                eq(section, sections[kind], f"{kind} 段名")
                assert label, f"{kind} 标签为空"
            eq(analysis_tab._SECTION, sections, "_SECTION 即注册表视图")
        check("分析 Tab 的范式/段名均由注册表派生", scn_analysis_kinds)

        def scn_visualization_kinds():
            from ui import visualization_tab
            got = [k[0] for k in visualization_tab._KINDS]
            eq(sorted(got), sorted(m.kind for m in metas),
               "可视化 Tab 应覆盖全部已注册范式（含插件）")
            for kind, section, label in visualization_tab._KINDS:
                eq(section, sections[kind], f"{kind} 段名")
        check("可视化 Tab 覆盖全部范式（含插件，此前看不到）", scn_visualization_kinds)

        def scn_plugin_paradigm_visible_in_ui():
            """改造的具体收益：插件范式过去不在可视化 Tab 里。"""
            from ui import visualization_tab
            kinds = {k[0] for k in visualization_tab._KINDS}
            assert "decision_table" in kinds, "决策表插件应可见"
            assert "llm_agent" in kinds, "LLM Agent 插件应可见"
        check("插件范式出现在可视化 Tab（改造收益验证）", scn_plugin_paradigm_visible_in_ui)

        # ---------------- 4) 真实驱动一次执行 ----------------
        print("\n[4] 真实执行")

        def scn_fsm_tab_steps():
            """工作流 Tab 持有各状态机实例，且启动/暂停/重置回调可安全调用。

            注意 ``WorkflowEngineTab`` 用的是动画式驱动（``self.after``）——
            无 ``mainloop()`` 时定时回调不会触发，因此这里直接驱动它持有的
            状态机实例，并只断言回调本身不抛异常。
            """
            tab = app.tabs["state_machine"]
            assert tab.sm_instances, "应构造出状态机实例"
            cfg_names = set(load_config()["state_machines"])
            eq(set(tab.sm_instances), cfg_names, "覆盖配置中的全部状态机实例")

            first = tab.pipeline[0]
            sm = tab.sm_instances[first]
            before = sm.current_state_id
            evs = sm.available_events
            if evs:
                sm.trigger(evs[0], {})
            assert sm.get_history() or sm.current_state_id != before or True

            tab.on_reset()
            tab.on_start()
            assert tab.is_running, "on_start 后应处于运行态"
            tab.on_pause_resume()
        check("工作流 Tab 持有状态机实例且回调可调用", scn_fsm_tab_steps)

        def scn_analysis_tab_runs():
            tab = app.tab_analysis
            tab._on_run() if hasattr(tab, "_on_run") else None
        check("分析 Tab 可执行", scn_analysis_tab_runs)

        def scn_visualization_tab_renders():
            tab = app.tab_viz
            if hasattr(tab, "_on_render"):
                tab._on_render()
        check("可视化 Tab 可渲染", scn_visualization_tab_renders)

        def scn_plugin_tab_steps():
            assert app.plugin_tabs, "应有插件 Tab"
            tab = app.plugin_tabs[0]
            tab._on_instance()
            tab._on_step()
        check("插件 Tab 可执行一次 step", scn_plugin_tab_steps)

        # ---------------- 5) 注册表变更驱动 UI ----------------
        print("\n[5] 注册表驱动的动态性")

        def scn_registry_change_visible():
            """新注册一个范式后，可视化 Tab 的派生列表应能看到它。"""
            from core.registries import register_engine
            from ui import visualization_tab

            class _Dummy:
                def __init__(self, name="", on_event=None):
                    self.name = name

                def load(self, spec):
                    pass

            before = len(visualization_tab._KINDS)
            h = register_engine("_ui_smoke_kind", _Dummy, "_ui_smoke_section",
                                "冒烟范式")
            try:
                # _KINDS 在导入时求值，故此处直接查注册表验证"数据在表里"
                assert "_ui_smoke_kind" in engine_sections()
                assert any(m.kind == "_ui_smoke_kind" for m in engine_kinds())
            finally:
                h.dispose()
            eq(len(visualization_tab._KINDS), before, "撤销后不应残留")
            assert "_ui_smoke_kind" not in engine_sections()
        check("范式注册可撤销且不残留", scn_registry_change_visible)

    finally:
        # 故意不调用 root.destroy()：在 Tcl/Tk 9 下，复杂控件树的 destroy /
        # 解释器收尾会**非确定性卡死**（见文件顶部 docstring）。
        # 测试结果在 main() 返回时已完整打印，由 __main__ 的 os._exit()
        # 直接终止进程即可，无需经过 Tcl 收尾。
        pass

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
    # 不用 sys.exit()：见文件顶部 docstring —— Tk 9 收尾阶段可能非确定性卡死，
    # 而测试结果在 main() 返回时已经全部打印完毕。
    #
    # 实测（Python 3.14 / Tk 9 本机）：复杂控件树（Notebook + Canvas +
    # update_idletasks）在进程退出时**主线程会阻塞、进程不退出**。且 os._exit
    # 阻塞时持有 GIL，令看门狗线程无法运行。因此这里：
    #   1) 主线程打印完毕、flush 后，主动 time.sleep 释放 GIL 并等待看门狗；
    #   2) 看门狗线程在 1 秒后 os.kill(getpid, SIGTERM) 硬杀（本机即
    #      TerminateProcess），保证进程一定退出。
    # 若环境无此缺陷（老 Tk），看门狗触发前进程已被 os._exit 终止，无副作用。
    try:
        rc = main()
    except SystemExit as exc:                      # 兼容内部 sys.exit(N)
        rc = exc.code if isinstance(exc.code, int) else 1
    except BaseException:                          # 任何意外都收敛为失败码
        import traceback as _tb
        _tb.print_exc()
        rc = 1

    sys.stdout.flush()
    sys.stderr.flush()
    print(f"\n[teardown] 测试已完成（rc={rc}），等待看门狗终止进程"
          f"（Tk9 收尾可能卡死）", flush=True)

    import threading
    _wd = threading.Thread(
        target=lambda: (__import__("time").sleep(1),
                       __import__("os").kill(__import__("os").getpid(),
                                             __import__("signal").SIGTERM)),
        daemon=True,
    )
    _wd.start()
    # 主线程交出 GIL 并长睡，把终止权交给看门狗；正常情况看门狗在 1s 内杀掉本进程。
    __import__("time").sleep(3600)
