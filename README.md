# 多范式决策引擎 · 可视化工作台

一个把多种计算/决策范式连成「可编排系统」的 Python 引擎，提供 **Tkinter 桌面工作台**
与 **React + react-flow Web 编排编辑器** 两种前端界面。所有范式由同一份 `config.json`
驱动，并通过编排层（事件总线 + 声明式绑定）协同工作。

## 特性

- **多范式引擎**（纯标准库实现，零第三方依赖）：
  - 状态机 `FSM` / 层次状态机 `HSM`（嵌套子状态 · 历史 · 内部转移 · 声明式 Guard）
  - 行为树 `Behavior Tree`（Selector / Sequence / Parallel / 装饰器 / 服务节点）
  - 决策树 `Decision Tree`
  - 差分机 `Difference Engine`（巴贝奇有限差分 + 状态差量 / 响应式脏检查）
  - Petri 网 `Petri Net`（含抑制弧、优先级）
  - 马尔可夫链 `Markov Chain`
  - 规则引擎 `Rule Engine`（Rete 风格前向链 + 生产规则）
  - 决策表 `Decision Table`
  - LLM 智能体 `LLM Agent`（local / 可接后端）
- **编排层**：事件总线（`*` 通配订阅）+ 声明式绑定（`when 事件 → then 动作`），
  把独立引擎连成系统，也是后续接入 LLM 的底座。
- **两种界面**：
  - `main.py` —— Tkinter 可视化工作台（每个范式一个 Tab）。
  - `web/server.py` + `web/webui` —— React + @xyflow/react 编排可视化编辑器，
    支持拖拽建节点、连线建绑定、单步驱动、运行轨迹，并持久化到 `web/orchestrations.json`。

## 目录结构

```
zhuangtaiji/
├── config.json              # 所有引擎与 demo 编排的配置（单一数据源）
├── main.py                  # Tkinter 工作台入口
├── core/                    # 引擎内核（纯标准库）
│   ├── state_machine.py / hierarchical_state_machine.py
│   ├── behavior_tree.py / decision_tree.py / difference_engine.py
│   ├── petri_net.py / markov_chain.py / rule_engine.py / decision_tables.py
│   ├── engine_base.py       # Engine / EngineEvent / Graph 等契约
│   ├── engine_adapters.py   # 各引擎 -> 统一 Engine 接口
│   ├── orchestrator.py      # 事件总线 + Orchestrator（编排层）
│   ├── analysis.py / renderers.py / plugin.py / adapters_io.py
│   └── __init__.py          # 统一导出
├── ui/
│   └── application.py       # Tkinter 工作台
├── engine/
│   └── progress_bar.py      # Canvas 进度条组件
├── web/
│   ├── server.py            # 标准库 http.server 的 REST 后端 + 静态托管
│   ├── static/              # 兜底静态页（dist 缺失时使用）
│   ├── orchestrations.json  # 用户持久化的编排（自动生成，可删）
│   └── webui/               # 真正的 Vite + React + @xyflow/react 前端
│       ├── index.html / package.json / vite.config.js
│       ├── src/{main.jsx, App.jsx, EngineNode.jsx, api.js, index.css}
│       └── dist/            # npm run build 产物（由 server.py 托管）
├── test_verify.py           # 原始回归测试
├── test_enhancements.py     # P0~P3 增强测试
└── test_web_e2e.py          # Web 端到端测试
```

## 安装

### Python 端
仅需 Python 3.8+ 标准库（`tkinter` 在 Windows 自带；Linux 需额外安装 `python3-tk`）。
无需 `pip install` 任何第三方包：

```bash
# 可选：确认依赖（项目本身无第三方依赖）
pip install -r requirements.txt
```

### 前端（Web 编辑器）
```bash
cd web/webui
npm install      # 安装 React / @xyflow/react / vite
npm run build    # 产出 dist/（server.py 直接托管）
```

## 运行

### 1. Tkinter 工作台
```bash
python main.py
```

### 2. Web 编排编辑器
```bash
# 确保已执行上述 npm run build
python web/server.py 8000
# 浏览器打开 http://localhost:8000/
```
Web 端点的首页优先服务 `web/webui/dist`，缺失时回退 `web/static`。

### 3. 前端热更新开发模式（可选）
```bash
cd web/webui
npm run dev       # Vite dev server，默认 http://localhost:5173/
```

## 编排 REST API（`web/server.py`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/orchestrations` | 编排列表（内置 demo + 用户持久化） |
| GET | `/api/orchestration/<name>` | 取图谱（`nodes`/`edges`）供 react-flow 渲染 |
| PUT | `/api/orchestration/<name>` | 保存（图谱 → spec，写入 `orchestrations.json`） |
| DELETE | `/api/orchestration/<name>` | 删除（仅用户持久化编排；内置只读） |
| POST | `/api/orchestration/<name>/run` | 运行（执行 `start` 触发器） |
| POST | `/api/orchestration/<name>/step` | 单步驱动某引擎（触发绑定链），body：`{"engine": "别名", "ctx": {...}}` |
| POST | `/api/orchestration/<name>/reset` | 重置所有引擎状态 |
| GET | `/api/orchestration/<name>/status` | 各引擎实时摘要 |

## 测试

```bash
python test_verify.py        # 原始功能回归
python test_enhancements.py  # P0~P3 增强覆盖
python test_web_e2e.py       # Web 端到端（需先 npm run build）
```

## 配置

所有引擎与 demo 编排定义在 `config.json`，结构见文件内注释；编排层读取
`orchestration` 段（`engines` / `bindings` / `start`）。可视化编辑后保存为
`web/orchestrations.json`。
