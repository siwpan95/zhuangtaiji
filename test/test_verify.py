# -*- coding: utf-8 -*-
"""验证脚本：测试所有模块与新增引擎的功能"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from core import (
    GenericStateMachine, create_state_machine, load_config, register_guard,
    register_action,
    HierarchicalStateMachine, BehaviorTree, Blackboard, build_behavior_tree,
    DecisionTree, build_decision_tree, FiniteDifference, StateDiff,
    ReactiveTracker, build_petri_net, build_markov_chain, build_rule_engine,
)
from engine.progress_bar import ease_out_quad, ease_in_out_quad, ease_out_cubic


config = load_config()
print("=" * 50)
print("1. 平面状态机（原有）")
sm = GenericStateMachine("SM_Init", config)
events = ["start", "complete", "complete", "complete"]
for e in events:
    if sm.can_trigger(e):
        sid, content = sm.trigger(e)
        print(f"  [{e}] -> {sid}: {content[:40]}...")
    else:
        print(f"  [{e}] -> unavailable (current: {sm.current_state_id})")
print(f"  History: {len(sm.get_history())} entries")
print(f"  Final: {sm.get_state_info()['id']}")

print("\n" + "=" * 50)
print("2. 状态机工厂 + Guard + 内部转移")
register_guard("ok", lambda ctx: ctx.get("ok", False))
smg = create_state_machine("SM_Process", config)
smg.trigger("start")
sid, c = smg.trigger("validate_ok")
print(f"  SM_Process validate_ok -> {sid}")
print(f"  available_events: {smg.available_events}")

print("\n" + "=" * 50)
print("3. 层次状态机（HSM）")
hsm = create_state_machine("SM_Hier", config)
print(f"  init: {hsm.current_state_id}")
hsm.trigger("turn_on")
print(f"  after turn_on: {hsm.current_state_id}")
hsm.trigger("run")
print(f"  after run: {hsm.current_state_id}")
hsm.trigger("stop")
print(f"  after stop: {hsm.current_state_id}")
hsm.trigger("fault")
print(f"  after fault: {hsm.current_state_id}")
sid, c = hsm.trigger("reset")  # 内部转移 #on
print(f"  after reset (internal): {hsm.current_state_id}")

print("\n" + "=" * 50)
print("4. 行为树（Behavior Tree）")
bb = Blackboard({"fault": False, "load": 90})
bt = build_behavior_tree(config["behavior_trees"]["BT_SelfHeal"], blackboard=bb)
status = bt.run(max_ticks=50)
print(f"  tick 结果: {status.value}, 黑板: {bb.snapshot()}")
# 另一种场景：正常
bb2 = Blackboard({"fault": False, "load": 30})
bt2 = build_behavior_tree(config["behavior_trees"]["BT_SelfHeal"], blackboard=bb2)
bt2.run(max_ticks=50)
print(f"  正常场景黑板: {bb2.snapshot()}")

print("\n" + "=" * 50)
print("5. 决策树（Decision Tree）")
dt = build_decision_tree(config["decision_trees"]["DT_Route"])
r1 = dt.decide({"vip": True, "urgent": True, "load": 95})
print(f"  vip+urgent -> {r1.label}  path={r1.path}")
r2 = dt.decide({"vip": False, "urgent": False, "load": 95})
print(f"  normal+highload -> {r2.label}  path={r2.path}")
r3 = dt.decide({"vip": False, "urgent": False, "load": 40})
print(f"  normal+lowload -> {r3.label}  path={r3.path}")

print("\n" + "=" * 50)
print("6. 差分引擎（Difference Engine）")
fd = FiniteDifference(config["difference_engine"]["progress_predictor"]["initial_values"])
print(f"  初始序列: {fd.history()}")
print(f"  后续3步(差分递推): {fd.generate(3)}")
# 状态差量
old = {"a": 1, "b": 2}
new = {"a": 1, "b": 20, "c": 3}
diffs = StateDiff.diff(old, new)
print(f"  状态差量: {StateDiff.summary(diffs)}")
# 响应式追踪
tracker = ReactiveTracker({"status": "idle"})
logs = []
tracker.subscribe("status", lambda e, s: logs.append(f"status -> {e.new}"))
tracker.update({"status": "running", "progress": 50})
print(f"  响应式回调: {logs}")

print("\n" + "=" * 50)
print("7. 缓动函数预览")
for raw in [0, 25, 50, 75, 100]:
    t = raw / 100.0
    print(f"  raw={raw:3d}% -> ease_out={int(ease_out_quad(t)*100):3d}%  "
          f"ease_in_out={int(ease_in_out_quad(t)*100):3d}%  "
          f"ease_out_cubic={int(ease_out_cubic(t)*100):3d}%")

print("\n" + "=" * 50)
print("8. Petri 网（Petri Net）")
pn = build_petri_net(config["petri_nets"]["PN_Order"])
print(f"  初始标记: {pn.format_marking()}")
print(f"  使能变迁: {pn.enabled_transitions()}")
trace = pn.run(strategy="priority", max_steps=6)
print(f"  运行后标记: {pn.format_marking()}  死锁={pn.is_deadlock()}")

print("\n" + "=" * 50)
print("9. 马尔可夫链（Markov Chain）")
mc = build_markov_chain(config["markov_chains"]["MC_Weather"])
seq = mc.simulate(10)
print(f"  仿真路径: {' -> '.join(seq)}")
sd = mc.steady_state()
print(f"  稳态分布: {sd}")

print("\n" + "=" * 50)
print("10. 规则引擎（Rule Engine / RETE）")
re = build_rule_engine(config["rule_engines"]["RE_Promo"])
log = re.forward_chain()
print(f"  推理触发: {[e['rule'] for e in log if e['type']=='fire']}")
print(f"  最终事实数: {len(re.working_memory)}")
print(f"  事实: {re.facts_summary()}")

print("\n" + "=" * 50)
print("11. 行为树新节点 + HSM 守卫 + 动作注册表")
bb = Blackboard({"hp": 10, "enemy": False})
bt = build_behavior_tree(config["behavior_trees"]["BT_Combat"], blackboard=bb)
status = bt.run(max_ticks=50)
print(f"  BT_Combat 结果: {status.value}  action={bb.get('action')}")

register_guard("allow_go", lambda ctx: ctx.get("go", False))
hsm_g = create_state_machine("SM_Guard", config)
sid, c = hsm_g.trigger("go", context={"go": False})
print(f"  SM_Guard guard 拒绝: {c}")
sid, c = hsm_g.trigger("go", context={"go": True})
print(f"  SM_Guard guard 通过: {sid}")

called = {}
def my_action(ctx, detail):
    called[detail["state"]] = detail["type"]
register_action("demo_enter", my_action)
demo_sm = GenericStateMachine("demo", {
    "state_machines": {"demo": {"initial": "a",
        "states": {"a": {"on_enter": "demo_enter", "content": "x",
                         "transitions": {"next": "b"}},
                   "b": {"content": "y"}}}}
})
print(f"  动作注册表触发: {called}")

print("\nAll tests passed!")
