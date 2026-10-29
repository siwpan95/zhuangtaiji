import time

from .hierarchical_state_machine import HierarchicalStateMachine
from .registries import (
    ACTION_REGISTRY, GUARD_REGISTRY, context, register_action, register_guard,
)

__all__ = [
    "GenericStateMachine", "create_state_machine",
    "GUARD_REGISTRY", "ACTION_REGISTRY", "register_guard", "register_action",
    "context",
]


# ==========================================
# 通用状态机（纯逻辑，支持多实例）
# ==========================================
class GenericStateMachine:
    def __init__(self, machine_name, full_config, on_action=None,
                 guards=None):
        """
        根据名称从总配置中提取属于该状态机的配置

        Args:
            machine_name: 状态机名称
            full_config:  完整配置字典
            on_action:    可选回调 (action_type, state_id, detail) -> None
                          用于外部监听 entry/exit/transition 等动作
        """
        if "state_machines" not in full_config:
            raise ValueError('配置缺少 "state_machines" 段')
        config = full_config["state_machines"].get(machine_name)
        if not config:
            raise ValueError(f"找不到状态机配置: {machine_name}")

        # ---- load 期结构校验（fail-loud）：把"首次 trigger 才抛裸 KeyError"
        # 提前到装配阶段，并给出精确定位 ----
        states = config.get("states")
        if not isinstance(states, dict) or not states:
            raise ValueError(
                f"状态机 {machine_name!r} 缺少 states 段或为空")
        initial = config.get("initial")
        if initial not in states:
            raise ValueError(
                f"状态机 {machine_name!r} 的 initial={initial!r} 不是合法状态；"
                f"可用：{sorted(states)}")
        for sid, spec in states.items():
            if not isinstance(spec, dict):
                raise ValueError(
                    f"状态机 {machine_name!r} 的状态 {sid!r} 配置不是映射")
            trans = spec.get("transitions") or {}
            if not isinstance(trans, dict):
                raise ValueError(
                    f"状态机 {machine_name!r}.states.{sid}.transitions 不是映射")
            for ev, tgt in trans.items():
                # 转移值为 dict 时取其中的 target（与 trigger() 解析口径一致）
                if isinstance(tgt, dict):
                    tgt_state = tgt.get("target")
                elif isinstance(tgt, str):
                    tgt_state = tgt
                else:
                    tgt_state = None
                # 内部转移（"#..."）指向动作而非状态，跳过校验
                if isinstance(tgt_state, str) and tgt_state.startswith("#"):
                    continue
                if not isinstance(tgt_state, str) or tgt_state not in states:
                    raise ValueError(
                        f"状态机 {machine_name!r}.states.{sid}.transitions.{ev} 的 "
                        f"target={tgt_state!r} 不存在；可用：{sorted(states)}")

        self.name = machine_name
        self.states = states
        self.current_state_id = initial
        self.on_action = on_action

        # 守卫解析：实例级 guards 显式覆盖优先；其余**实时**查询进程注册表，
        # 因此 register_guard(...).dispose() 对所有实例（含已创建的）立即生效。
        self._guard_overrides = dict(guards) if isinstance(guards, dict) else {}

        # 转移历史：[{"from":str, "event":str, "to":str, "time":float}, ...]
        self.history: list[dict] = []

        # 进入初始状态时触发 on_enter
        self._invoke_action("enter", self.current_state_id, context={})

    # ---------- 守卫解析 ----------
    @property
    def guards(self) -> dict:
        """当前生效的守卫表：实例级覆盖 + 进程注册表的**实时**合并。

        返回新的 dict（不是内部引用），因此修改它不会影响转移判定。
        要增删守卫请用 ``register_guard()``（可撤销）；要为本实例单独指定，
        请用构造参数 ``guards={...}``。实例级覆盖优先于注册表。
        """
        merged = dict(GUARD_REGISTRY)
        merged.update(self._guard_overrides)
        return merged

    # ---------- 事件驱动 ----------
    def trigger(self, event_name, context=None):
        """
        触发事件，执行状态转移。
        支持 guard 条件检查，返回 (new_state_id, content) 或 (None, 拒绝原因)
        """
        context = context or {}
        current = self.states.get(self.current_state_id, {})
        transitions = current.get("transitions", {})

        # 查找匹配的转移
        target = transitions.get(event_name)
        if target is None:
            return None, f"状态 [{self.current_state_id}] 不支持事件 [{event_name}]"

        # 解析转移配置（支持简写 "target_state" 和完整写法 {"target":..., "guard":...}）
        if isinstance(target, str):
            target_state_id = target
            guard_name = None
        elif isinstance(target, dict):
            target_state_id = target.get("target")
            guard_name = target.get("guard")
        else:
            return None, "转移配置格式错误"

        # 内部转移：target 以 "#" 开头表示「原地执行动作但不离开状态」
        if isinstance(target_state_id, str) and target_state_id.startswith("#"):
            real = target_state_id[1:]
            self._invoke_action("internal", self.current_state_id,
                                extra={"event": event_name, "to": real})
            content = self.states[self.current_state_id].get("content", "无内容")
            return self.current_state_id, content

        # 执行 guard 条件检查（fail-closed：查不到即拒绝，绝不静默放行）
        if guard_name:
            guard_fn = self.guards.get(guard_name)
            if guard_fn is None:
                return None, (f"Guard [{guard_name}] 未注册：转移被拒绝。"
                              f"请用 register_guard({guard_name!r}, fn) 注册，"
                              f"或修正 config 中的 guard 名")
            if not callable(guard_fn):
                return None, (f"Guard [{guard_name}] 不是可调用对象"
                              f"（实为 {type(guard_fn).__name__}）：转移被拒绝")
            if not guard_fn(context):
                return None, f"Guard [{guard_name}] 条件不满足"

        # 离开旧状态
        self._invoke_action("exit", self.current_state_id, context=context)
        old_state = self.current_state_id

        # 转移
        self.current_state_id = target_state_id

        # 记录历史
        self.history.append({
            "from": old_state,
            "event": event_name,
            "to": target_state_id,
            "time": time.time()
        })

        # 进入新状态
        self._invoke_action("enter", self.current_state_id, context=context)
        self._invoke_action("transition", self.current_state_id,
                            extra={"from": old_state, "event": event_name})

        content = self.states[self.current_state_id].get("content", "无内容")
        return self.current_state_id, content

    def can_trigger(self, event_name):
        """检查当前状态是否支持某个事件"""
        current = self.states.get(self.current_state_id, {})
        transitions = current.get("transitions", {})
        return event_name in transitions

    # ---------- 属性 ----------
    @property
    def current_content(self):
        return self.states[self.current_state_id].get("content", "")

    @property
    def available_events(self):
        """返回当前状态下可选的事件列表"""
        current = self.states.get(self.current_state_id, {})
        return list(current.get("transitions", {}).keys())

    def get_state_info(self):
        """获取当前状态的完整信息"""
        state = self.states.get(self.current_state_id, {})
        return {
            "id": self.current_state_id,
            "content": state.get("content", ""),
            "on_enter": state.get("on_enter", ""),
            "on_exit": state.get("on_exit", ""),
            "available_events": self.available_events
        }

    def get_history(self, limit=20):
        """获取最近的转移历史"""
        return self.history[-limit:]

    # ---------- 内部 ----------
    def _invoke_action(self, action_type, state_id, extra=None, context=None):
        """调用 on_enter / on_exit / transition / internal 描述，并通知外部回调

        若 state 的 on_<action_type> 取值对应于 ACTION_REGISTRY 中的已注册动作名，
        则额外触发真实回调（带 context 与 detail）。
        """
        context = context or {}
        state = self.states.get(state_id, {})
        description = state.get(f"on_{action_type}", "")

        # 执行已注册动作（当描述为注册名时）
        action_fn = ACTION_REGISTRY.get(description)
        if callable(action_fn):
            try:
                action_fn(context, {"state": state_id, "type": action_type,
                                    "extra": extra or {}})
            except Exception:
                pass

        # 内部回调
        if callable(self.on_action):
            detail = {"description": description}
            if extra:
                detail.update(extra)
            self.on_action(action_type, state_id, detail)


# ==========================================
# 工厂：自动选择 平面 / 层次 状态机
# ==========================================
def create_state_machine(machine_name, full_config, on_action=None, guards=None):
    """根据配置自动构造状态机实例。

    * 若某状态包含 "substates" 或配置 type == "hierarchical"，返回
      HierarchicalStateMachine；
    * 否则返回通用 GenericStateMachine。
    """
    if "state_machines" not in full_config:
        raise ValueError('配置缺少 "state_machines" 段')
    config = full_config["state_machines"].get(machine_name, {})
    is_hier = config.get("type") == "hierarchical" or any(
        "substates" in s for s in config.get("states", {}).values()
    )
    if is_hier:
        return HierarchicalStateMachine(machine_name, full_config, on_action)
    return GenericStateMachine(machine_name, full_config, on_action, guards)
