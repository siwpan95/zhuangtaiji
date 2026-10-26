"""Headless self-check for zhuangtaiji（多范式决策引擎）.

Only the stdlib-only core package is imported: ``zhuangtaiji`` re-exports
``zhuangtaiji.core`` and the Tkinter workbench (``zhuangtaiji.ui``) / Web
server are never touched, so no window or socket is created and ``tkinter``
is not even imported.

Verified: config loading + layered patches, flat FSM walking + guards,
hierarchical FSM (nesting / bubbling / internal transition / history),
Babbage-style finite differences & reactive state diff, Markov steady state,
and the orchestrator's declarative engine binding chain.

Run from the project root:  .venv\\Scripts\\python.exe selfcheck.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from zhuangtaiji import (
    FiniteDifference,
    GenericStateMachine,
    HierarchicalStateMachine,
    MarkovChain,
    ReactiveTracker,
    StateDiff,
    create_state_machine,
    load_config,
    register_guard,
)
from zhuangtaiji.core.config import apply_config_patches
from zhuangtaiji.core.orchestrator import build_orchestrator_from_config


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def check_headless_import():
    """Importing the engine must not pull in tkinter (no GUI initialisation)."""
    import zhuangtaiji

    _check(zhuangtaiji.__version__ == "1.1.0",
           f"unexpected version {zhuangtaiji.__version__}")
    _check("tkinter" not in sys.modules,
           "importing zhuangtaiji imported tkinter")
    for name in ("ui", "web"):
        _check(f"zhuangtaiji.{name}" not in sys.modules,
               f"importing zhuangtaiji imported the {name} frontend")


def check_config_and_patches():
    """load_config() and the fail-soft layered patches."""
    cfg = load_config()
    for section in ("state_machines", "behavior_trees", "decision_trees",
                    "difference_engine", "petri_nets", "markov_chains",
                    "rule_engines", "orchestration"):
        _check(section in cfg, f"config section {section!r} missing")
    _check({"SM_Init", "SM_Guard", "SM_Hier"} <= set(cfg["state_machines"]),
           "built-in state machines missing")
    _check("demo" in cfg["orchestration"], "demo orchestration missing")
    _check("patches" not in cfg, "config.json unexpectedly carries patches")

    base = {
        "state_machines": {
            "SM_X": {"initial": "a", "states": {"a": {}, "b": {}}},
        },
        "patches": [
            {"section": "state_machines", "name": "SM_X",
             "override": {"initial": "b"}},
            {"insert": {"section": "state_machines", "name": "SM_Y",
                        "spec": {"initial": "a", "states": {"a": {}}}}},
            {"section": "no_such_section", "name": "SM_X",
             "override": {"initial": "a"}},
            {"insert": {"section": "state_machines", "name": "SM_X",
                        "spec": {"initial": "a"}}},
        ],
    }
    warnings = []
    applied = apply_config_patches(base, base["patches"], warn=warnings.append)
    _check(applied["state_machines"]["SM_X"]["initial"] == "b",
           "override patch was not applied")
    _check(applied["state_machines"]["SM_Y"]["initial"] == "a",
           "insert patch was not applied")
    _check("patches" not in applied, "patches metadata leaked into the result")
    _check(base["state_machines"]["SM_X"]["initial"] == "a",
           "input config was mutated by apply_config_patches")
    _check(len(warnings) == 2,
           f"expected 2 skipped-patch warnings, got {len(warnings)}")
    applied["state_machines"]["SM_Y"]["states"]["a"]["x"] = 1
    _check("x" not in base["patches"][1]["insert"]["spec"]["states"]["a"],
           "patched result aliases the input (no deep copy)")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config_patched.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "state_machines": {"SM_Z": {"initial": "a",
                                            "states": {"a": {}, "b": {}}}},
                "patches": [{"section": "state_machines", "name": "SM_Z",
                             "override": {"initial": "b"}}],
            }, fh)
        loaded = load_config(path)
    _check(loaded["state_machines"]["SM_Z"]["initial"] == "b",
           "load_config() did not apply the patches section")
    _check("patches" not in loaded, "load_config() kept the patches metadata")


def check_fsm():
    """Flat FSM: transition walk, history, invalid events and guards."""
    cfg = load_config()
    actions = []
    sm = create_state_machine(
        "SM_Init", cfg, on_action=lambda atype, sid, detail:
        actions.append((atype, sid)))
    _check(isinstance(sm, GenericStateMachine), "SM_Init is not a flat FSM")
    _check(sm.current_state_id == "idle", "wrong initial state")
    _check(sm.current_content, "initial state has no content")

    state, content = sm.trigger("start")
    _check(state == "booting" and content, "start transition failed")
    for expected in ("loading_modules", "ready", "finished"):
        state, _ = sm.trigger("complete")
        _check(state == expected, f"expected {expected}, got {state}")
    _check(sm.current_state_id == "finished", "final state not reached")

    _check(len(sm.history) == 4, f"history has {len(sm.history)} entries")
    _check([h["from"] for h in sm.history]
           == ["idle", "booting", "loading_modules", "ready"],
           "history 'from' chain wrong")
    _check([h["to"] for h in sm.history]
           == ["booting", "loading_modules", "ready", "finished"],
           "history 'to' chain wrong")
    _check(all(isinstance(h["time"], float) for h in sm.history),
           "history entries missing timestamps")

    kinds = [a[0] for a in actions]
    _check(kinds.count("enter") == 5, f"enter actions: {kinds.count('enter')}")
    _check(kinds.count("exit") == 4, f"exit actions: {kinds.count('exit')}")
    _check(kinds.count("transition") == 4, "transition actions missing")

    rejected = sm.trigger("complete")
    _check(rejected[0] is None and "不支持" in rejected[1],
           f"invalid event was not rejected: {rejected}")
    _check(sm.current_state_id == "finished", "rejected event moved the state")
    _check(sm.can_trigger("complete") is False, "can_trigger lied")
    _check(sm.available_events == [], "finished state still offers events")
    _check(sm.get_state_info()["id"] == "finished", "get_state_info mismatch")

    # Guarded transition: fail-closed while the guard is unknown.
    GUARD = "allow_go"  # name referenced by the SM_Guard config
    guarded = create_state_machine("SM_Guard", cfg)
    rejected = guarded.trigger("go", {"allowed": True})
    _check(rejected[0] is None and "未注册" in rejected[1],
           "unregistered guard was not rejected")
    _check(guarded.current_state_id == "wait", "rejected guard moved the state")

    handle = register_guard(GUARD, lambda ctx: ctx.get("allowed") is True)
    try:
        guarded = create_state_machine("SM_Guard", cfg)
        blocked = guarded.trigger("go", {})
        _check(blocked[0] is None and "不满足" in blocked[1],
               "guard=pass, expected a rejection")
        allowed = guarded.trigger("go", {"allowed": True})
        _check(allowed[0] == "run", f"guard=pass did not transition: {allowed}")
        duplicate = False
        try:
            register_guard(GUARD, lambda ctx: True)
        except KeyError:
            duplicate = True
        _check(duplicate, "duplicate guard registration was accepted")
    finally:
        handle.dispose()

    after = create_state_machine("SM_Guard", cfg).trigger("go", {"allowed": True})
    _check(after[0] is None, "disposed guard still allows the transition")


def check_hsm():
    """Hierarchical FSM: nesting, bubbling, internal transition, history."""
    cfg = load_config()
    hsm = create_state_machine("SM_Hier", cfg)
    _check(isinstance(hsm, HierarchicalStateMachine), "SM_Hier is not an HSM")
    _check(hsm.current_state_id == "power/off",
           f"wrong initial path {hsm.current_state_id}")

    _check(hsm.trigger("turn_on")[0] == "power/on/idle",
           "turn_on did not enter the default child state")
    _check(hsm.trigger("run")[0] == "power/on/working", "run failed")
    _check(hsm.trigger("fault")[0] == "power/on/error", "fault failed")
    _check(hsm.current_leaf == "error", "leaf state is not error")
    _check({"reset", "power_off", "kill"} <= set(hsm.available_events),
           f"events do not bubble from ancestors: {hsm.available_events}")

    before = len(hsm.history)
    _check(hsm.trigger("reset")[0] == "power/on/error",
           "internal transition left the state")
    _check(len(hsm.history) == before + 1,
           "internal transition should record exactly one entry")
    _check(hsm.history[-1]["action"] == "internal",
           "internal transition not recorded as internal")
    _check(not any(h["action"] in ("exit", "enter")
                   for h in hsm.history[before:]),
           "internal transition triggered exit/enter")

    # kill lives on the root state: reachable only by bubbling.
    _check(hsm.trigger("kill")[0] == "power/off", "bubbled kill failed")

    hsm.trigger("turn_on")
    hsm.trigger("run")
    hsm.trigger("fault")
    hsm.go_history("power")
    _check(hsm.current_state_id == "power/on/idle",
           f"shallow history restored {hsm.current_state_id}")

    info = hsm.get_state_info()
    _check(info["path"] == hsm.current_state_id, "get_state_info path mismatch")
    _check(info["content"], "current leaf has no content")
    _check(hsm.can_trigger("no_such_event") is False, "can_trigger lied")
    _check(hsm.trigger("no_such_event")[0] is None,
           "unknown event was accepted")


def check_difference_engine():
    """Finite differences (Babbage) and reactive state diffing."""
    quad = FiniteDifference([0, 1, 4, 9])
    _check(quad.order == 3, f"order is {quad.order}")
    _check(quad.count == 4, f"initial count is {quad.count}")
    quad_next = quad.generate(3)
    _check(quad_next == [16, 25, 36],
           f"x^2 continuation wrong: {quad_next}")
    _check(quad.count == 7, "count not advanced")
    _check(quad.history() == [0, 1, 4, 9, 16, 25, 36],
           f"history wrong: {quad.history()}")

    cubic = FiniteDifference([0, 1, 8, 27])
    cubic_next = cubic.generate(2)
    _check(cubic_next == [64, 125],
           f"x^3 continuation wrong: {cubic_next}")

    raised = False
    try:
        FiniteDifference([1])
    except ValueError:
        raised = True
    _check(raised, "single seed value was accepted")

    entries = StateDiff.diff({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
    kinds = {e.key: e.kind for e in entries}
    _check(kinds == {"b": "changed", "c": "added"},
           f"StateDiff entries wrong: {kinds}")
    removed = StateDiff.diff({"old": 1}, {})
    _check(len(removed) == 1 and removed[0].kind == "removed"
           and removed[0].old == 1, "removed keys not reported")

    fired = []
    tracker = ReactiveTracker({"hp": 100, "mp": 50})
    tracker.subscribe("hp", lambda entry, state: fired.append(entry.kind))
    batch = tracker.set("hp", 90)
    _check(len(batch) == 1 and batch[0].kind == "changed",
           "hp change not diffed")
    _check(fired == ["changed"], f"hp subscriber calls: {fired}")
    tracker.set("mp", 40)
    _check(fired == ["changed"], "unrelated key fired the hp subscriber")
    _check(tracker.state == {"hp": 90, "mp": 40}, "state did not update")
    snapshot = tracker.state
    snapshot["hp"] = 1
    _check(tracker.state["hp"] == 90, "state property leaks the internal dict")


def check_markov():
    """Markov chain: normalisation, seeded sampling, stationary distribution."""
    spec = {
        "晴": {"晴": 0.6, "阴": 0.3, "雨": 0.1},
        "阴": {"晴": 0.3, "阴": 0.4, "雨": 0.3},
        "雨": {"晴": 0.2, "阴": 0.3, "雨": 0.5},
    }
    chain = MarkovChain(["晴", "阴", "雨"], spec, seed=7)
    steady = chain.steady_state()
    _check(abs(sum(steady.values()) - 1.0) < 1e-6,
           f"steady state does not sum to 1: {sum(steady.values())}")
    for state, expected in (("晴", 7 / 18), ("阴", 1 / 3), ("雨", 5 / 18)):
        _check(abs(steady[state] - expected) < 1e-6,
               f"steady[{state}]={steady[state]} != {expected}")

    walk = chain.simulate(10)
    _check(len(walk) == 11 and walk[0] == "晴",
           "simulate() did not start at the initial state")
    _check(all(s in chain.states for s in walk), "simulate() left the state space")
    twin = MarkovChain(["晴", "阴", "雨"], spec, seed=7).simulate(10)
    _check(twin == walk, "same seed produced a different walk")
    _check(not chain.is_absorbing("晴"), "晴 wrongly reported as absorbing")

    degenerate = MarkovChain(["a", "b"], {"a": {"b": 3}, "b": {"a": 1}})
    for row in degenerate.matrix:
        _check(abs(sum(row) - 1.0) < 1e-9, f"row not normalised: {row}")
    _check(abs(degenerate.steady_state()["a"] - 0.5) < 1e-9,
           "two-state stationary distribution wrong")

    absorbing = MarkovChain(["x", "y"], {"x": {"x": 1.0}, "y": {"x": 0.5, "y": 0.5}})
    _check(absorbing.is_absorbing("x"), "absorbing state not detected")
    _check(not absorbing.is_absorbing("y"), "transient state flagged absorbing")


def check_orchestrator():
    """Declarative engine bindings: sm.enter → bt.tick → mc.step."""
    cfg = load_config()
    orch = build_orchestrator_from_config(cfg)
    _check(orch is not None, "build_orchestrator_from_config returned None")
    _check(sorted(orch.engines) == ["bt", "mc", "sm"],
           f"unexpected engine aliases {sorted(orch.engines)}")
    _check(orch.engines["sm"].kind == "state_machine", "sm adapter kind wrong")
    _check(orch.bus.listener_count() == 2,
           f"bindings registered {orch.bus.listener_count()} listeners, expected 2")

    spec = cfg["orchestration"]["demo"]
    orch.configure(spec, cfg)
    _check(orch.bus.listener_count() == 2,
           "repeated configure() leaked bus listeners")

    graph = orch.to_graph()
    _check(len(graph["nodes"]) == 3, f"graph has {len(graph['nodes'])} nodes")
    _check(len(graph["edges"]) == 2, f"graph has {len(graph['edges'])} edges")
    _check(len(graph["start"]) == 1, "graph lost the start trigger")
    _check({n["id"] for n in graph["nodes"]} == {"sm", "bt", "mc"},
           "graph nodes do not match the aliases")

    orch.start()
    events = [t["event"] for t in orch.trace if "event" in t]
    for expected in ("sm.enter", "bt.tick", "mc.step"):
        _check(expected in events, f"{expected} never fired; trace={events}")
    actions = [t["action"] for t in orch.trace if "action" in t]
    _check("bt.step" in actions and "mc.step" in actions,
           f"binding chain incomplete: {actions}")

    _check(orch.engines["sm"].sm.current_state_id == "booting",
           "orchestrated FSM did not reach booting")
    _check(orch.engines["bt"].bb.get("healthy") is True,
           "behaviour tree did not set the healthy fallback")
    _check(orch.engines["mc"].mc.current in orch.engines["mc"].mc.states,
           "Markov engine left its state space")

    status = orch.engine_status()
    _check(len(status) == 3 and all(s["summary"] for s in status),
           "engine_status() is incomplete")
    _check(orch.step_engine("no_such_alias") is None,
           "step_engine() accepted an unknown alias")
    _check(orch.report().startswith("编排:"), "report() lost its header")


CHECKS = (
    ("headless import", check_headless_import),
    ("config patches", check_config_and_patches),
    ("flat fsm", check_fsm),
    ("hierarchical fsm", check_hsm),
    ("difference engine", check_difference_engine),
    ("markov chain", check_markov),
    ("orchestrator", check_orchestrator),
)


def main():
    passed = []
    for name, func in CHECKS:
        try:
            func()
        except AssertionError as exc:
            print(f"FAIL: {name}: {exc}")
            return 1
        except Exception as exc:  # noqa: BLE001 - report any unexpected error
            print(f"FAIL: {name}: {type(exc).__name__}: {exc}")
            return 1
        passed.append(name)
    print("selfcheck ok: " + ", ".join(passed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
