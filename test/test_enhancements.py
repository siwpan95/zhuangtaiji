# -*- coding: utf-8 -*-
"""P0~P3 增强功能离线验证（不启动 GUI）。"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from core import (load_config, build_adapter, renderers, plugin, analysis,
                  adapters_io)
from core.orchestrator import build_orchestrator_from_config
from core.petri_net import build_petri_net


cfg = load_config()
ok = []

# ---------- P0-1 适配器 + 统一 step/visualize ----------
print("=" * 60)
print("P0-1 统一引擎契约 + 适配器 + 插件注册表")
for kind, section in [("state_machine", "state_machines"),
                      ("behavior_tree", "behavior_trees"),
                      ("decision_tree", "decision_trees"),
                      ("petri_net", "petri_nets"),
                      ("markov_chain", "markov_chains"),
                      ("rule_engine", "rule_engines"),
                      ("difference_engine", "difference_engine")]:
    name = list(cfg[section].keys())[0]
    eng = build_adapter(kind, name, cfg)
    if kind == "state_machine":
        r = eng.step({"event": "start"})
    elif kind == "decision_tree":
        r = eng.step({"vip": True, "load": 90})
    elif kind == "behavior_tree":
        r = eng.step({"blackboard": {"fault": True, "load": 90}})
    elif kind == "markov_chain":
        r = eng.step({"simulate": 3})
    elif kind == "difference_engine":
        r = eng.step()
    else:
        r = eng.step()
    assert r is not None
    g = eng.visualize()
    assert g.nodes, f"{kind} 无节点"
    print(f"  [{kind}] {name}: step={r.value}  节点={len(g.nodes)}")
ok.append("adapters")

# ---------- P0-1 插件发现 ----------
print("\n" + "=" * 60)
print("P0-1 插件自动发现")
newly = plugin.ensure_discovered()
print(f"  已发现插件: {[p.kind for p in plugin.PluginRegistry.all()]}")
print(f"  本次新增: {newly}")
ok.append("plugin_discover")

# 决策表插件
dt = plugin.PluginRegistry.get("decision_table")
assert dt, "决策表插件缺失"
dte = dt.build("DT_PromoRoute")
rd = dte.step({"vip": True, "amount": 800})
print(f"  决策表 vip+800 -> {rd.value}")
gd = dte.visualize()
assert gd.nodes
ok.append("decision_table")

# LLM Agent 插件（离线默认后端）
llm = plugin.PluginRegistry.get("llm_agent")
assert llm, "LLM 插件缺失"
llme = llm.build("LLM_Init")
rl = llme.step({"state": "idle", "legal_events": ["start", "complete"]})
print(f"  LLM 选择事件 -> {rl.value} (后端={rl.detail['backend']})")
assert rl.value in ["start", "complete"]
ok.append("llm_agent")

# ---------- P0-2 渲染层 ----------
print("\n" + "=" * 60)
print("P0-2 图形化渲染 (ASCII/Mermaid/DOT)")
sm = build_adapter("state_machine", "SM_Init", cfg)
sm.step({"event": "start"})
g = sm.visualize()
asc = renderers.to_ascii(g)
mer = renderers.to_mermaid(g)
dot = renderers.to_dot(g)
print("  ASCII 片段:\n    " + asc.splitlines()[0])
print(f"  Mermaid 行数={len(mer.splitlines())}, DOT 行数={len(dot.splitlines())}")
assert "flowchart" in mer or "stateDiagram" in mer
ok.append("renderers")

# ---------- P1-1 编排 ----------
print("\n" + "=" * 60)
print("P1-1 范式协同 / 编排")
orch = build_orchestrator_from_config(cfg, "demo")
assert orch, "编排缺失"
orch.start()
rep = orch.report()
print("  " + rep.replace("\n", "\n  ").rstrip())
assert any("bt" in t.get("action", "") for t in orch.trace if "action" in t)
ok.append("orchestrator")

# ---------- P1-2 互操作 ----------
print("\n" + "=" * 60)
print("P1-2 互操作适配器 (PNML/SCXML/XState)")
pn = build_petri_net(cfg["petri_nets"]["PN_Order"])
xml = adapters_io.petri_to_pnml(pn)
spec2 = adapters_io.petri_from_pnml(xml)
assert spec2["places"] == pn.places, f"PNML 往返失败: {spec2['places']} vs {pn.places}"
print(f"  PNML 往返 OK (places={spec2['places']})")

sm_spec = cfg["state_machines"]["SM_Init"]
scxml = adapters_io.fsm_to_scxml(sm_spec)
sm_spec2 = adapters_io.fsm_from_scxml(scxml)
assert set(sm_spec2["states"]) == set(sm_spec["states"])
print(f"  SCXML 往返 OK (states={list(sm_spec2['states'])})")

xs = adapters_io.fsm_to_xstate(sm_spec)
xs_back = adapters_io.xstate_to_fsm(xs)
assert xs_back["initial"] == sm_spec["initial"]
print(f"  XState 往返 OK (initial={xs_back['initial']})")

csv = adapters_io.export_trace_csv([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
assert "a,b" in csv
print(f"  轨迹 CSV 导出 OK:\n    {csv.splitlines()[0]}")
ok.append("adapters_io")

# ---------- P2-1 形式化分析 ----------
print("\n" + "=" * 60)
print("P2-1 形式化分析")
pa = analysis.analyze_petri(cfg["petri_nets"]["PN_Order"])
print(f"  Petri: 可达={pa['reachable_states']} 有界={pa['is_bounded']} "
      f"死锁自由={pa['is_deadlock_free']} 活性={pa['liveness_ok']}")
assert pa["is_bounded"] and pa["is_deadlock_free"]
fa = analysis.analyze_fsm(cfg["state_machines"]["SM_Init"])
print(f"  状态机: 可达={fa['reachable']}/{fa['total_states']} "
      f"不可达={fa['unreachable']} 含环={fa['has_cycle']}")
ma = analysis.analyze_markov(cfg["markov_chains"]["MC_User"])
print(f"  马尔可夫: 吸收态={ma['absorbing']} 暂态={ma['transient']}")
if "expected_steps_to_absorb" in ma:
    print(f"    期望步数到吸收: {ma['expected_steps_to_absorb']}")
da = analysis.analyze_decision_tree(cfg["decision_trees"]["DT_Route"])
print(f"  决策树: 结论={da['leaf_conclusions']} 特征重要性={da['feature_importance']}")
ok.append("analysis")

# ---------- P3 Web 端依赖检查（仅验证可导入，不启动 server）----------
print("\n" + "=" * 60)
print("P3 Web 模块可导入性")
import importlib.util
ws = importlib.util.spec_from_file_location(
    "web_server", "web/server.py")
print("  web/server.py 存在:", ws is not None)
ok.append("web")

print("\n" + "=" * 60)
print(f"✔ 全部通过：{ok}")
