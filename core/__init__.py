from .state_machine import (
    GenericStateMachine,
    create_state_machine,
    register_guard,
    register_action,
    GUARD_REGISTRY,
    ACTION_REGISTRY,
)
from .hierarchical_state_machine import HierarchicalStateMachine
from .config import load_config
from .behavior_tree import (
    BehaviorTree,
    Blackboard,
    Status,
    Sequence,
    Selector,
    Parallel,
    Inverter,
    Succeeder,
    Failer,
    Repeater,
    Condition,
    Action,
    build_behavior_tree,
)
from .decision_tree import (
    DecisionTree,
    DecisionResult,
    build_decision_tree,
)
from .difference_engine import (
    FiniteDifference,
    StateDiff,
    DiffEntry,
    ReactiveTracker,
)
from .petri_net import (
    PetriNet,
    Transition,
    build_petri_net,
)
from .markov_chain import (
    MarkovChain,
    build_markov_chain,
)
from .rule_engine import (
    RuleEngine,
    Fact,
    Production,
    build_rule_engine,
    build_production,
)

# ---- P0~P3 增强模块 ----
from .engine_base import (
    EngineResult, Graph, GraphNode, GraphEdge, EngineEvent, Engine, BaseAdapter,
)
from .engine_adapters import (
    StateMachineEngine, BehaviorTreeEngine, DecisionTreeEngine,
    PetriEngine, MarkovEngine, RuleEngineAdapter, DifferenceEngineAdapter,
    build_adapter,
)
from . import renderers
from . import plugin
from . import analysis
from . import adapters_io
from . import orchestrator
