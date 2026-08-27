import time

from .hierarchical_state_machine import HierarchicalStateMachine


# ==========================================
# 守卫（Guard）注册表
# ==========================================
# 声明式配置中的 guard 只能写字符串名；真正的可调用守卫在此注册。
# 用法：register_guard("is_ok", lambda ctx: ctx.get("ok"))
GUARD_REGISTRY: dict = {}


def register_guard(name: str, fn) -> None:
    """注册一个命名守卫函数，供 config.json 中的 guard 字段引用。"""
    GUARD_REGISTRY[name] = fn


# ==========================================
# 动作（Action）注册表
# ==========================================
# 与 GUARD_REGISTRY 类似：config 中的 on_enter / on_exit / transition 描述，
# 若其值为已注册动作名，则触发真实回调（否则仅作为可阅读的描述被外部监听）。
# 用法：register_action("挂载空闲监听器", lambda ctx, detail: ...)
ACTION_REGISTRY: dict = {}


def register_action(name: str, fn) -> None:
    """注册一个命名动作函数，供 state 的 on_enter/on_exit 引用。"""
    ACTION_REGISTRY[name] = fn


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
        config = full_config["state_machines"].get(machine_name)
        if not config:
            raise ValueError(f"找不到状态机配置: {machine_name}")

        self.name = machine_name
        self.states = config["states"]
        self.current_state_id = config["initial"]
        self.on_action = on_action

        # 守卫函数表：实例级 guards 优先，其次全局 GUARD_REGISTRY
        self.guards = dict(GUARD_REGISTRY)
        if isinstance(guards, dict):
            self.guards.update(guards)

        # 转移历史：[{"from":str, "event":str, "to":str, "time":float}, ...]
        self.history: list[dict] = []

        # 进入初始状态时触发 on_enter
        self._invoke_action("enter", self.current_state_id, context={})

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

        # 执行 guard 条件检查
        if guard_name:
            guard_fn = self.guards.get(guard_name)
            if callable(guard_fn) and not guard_fn(context):
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
    config = full_config["state_machines"].get(machine_name, {})
    is_hier = config.get("type") == "hierarchical" or any(
        "substates" in s for s in config.get("states", {}).values()
    )
    if is_hier:
        return HierarchicalStateMachine(machine_name, full_config, on_action)
    return GenericStateMachine(machine_name, full_config, on_action, guards)
