# 多范式决策引擎 · 可视化工作台

## 仓库角色定位（投资组合分级 ②）

> 本仓在 siwpan 投资组合（D:/projects/repos，共 133 仓）中定级为 **② 保留**，领域 **开发者/系统工具**。
> **角色**：AI决策/内部工具。
> **维护策略**：② 旗舰 / 枢纽仓库打磨保留，作为能力展示或收敛点；② 保留类仓库低优先维持、不主动扩张。
> 投资组合统一分级索引：`D:/projects/repos/PORTFOLIO_TIERING.md`。

[![PyPI](https://img.shields.io/pypi/v/zhuangtaiji)](https://pypi.org/project/zhuangtaiji/)
[![Python](https://img.shields.io/pypi/pyversions/zhuangtaiji)](https://pypi.org/project/zhuangtaiji/)
[![License](https://img.shields.io/pypi/l/zhuangtaiji)](https://pypi.org/project/zhuangtaiji/)

**PyPI**：<https://pypi.org/project/zhuangtaiji/> ｜ **发行名与导入名都是 `zhuangtaiji`**
（v1.1.0 起源码统一挂在 `zhuangtaiji` 命名空间下发布 —— 见下方「目录结构」的说明）。

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
  - `zhuangtaiji/web/server.py` + `zhuangtaiji/web/webui` —— React + @xyflow/react 编排可视化编辑器，
    支持拖拽建节点、连线建绑定、单步驱动、运行轨迹，并持久化到 `zhuangtaiji/web/orchestrations.json`。
- **可 pip 安装**（v1.1.0 起）：`pip install zhuangtaiji`，包名 `zhuangtaiji`，纯标准库零运行时依赖。

## 目录结构

> **为什么源码都在 `zhuangtaiji/` 子目录里**：`core`、`engine`、`web` 这三个顶层包名
> 在 PyPI 上**早已被其它项目占用**，直接发版会撞车。因此 v1.1.0 起全部源码统一挂在
> `zhuangtaiji` 命名空间下发布——`pip install zhuangtaiji` 后 `import zhuangtaiji.core`，
> 仓库内从根目录跑也是同一套路径。

```
zhuangtaiji/                     # 仓库根
├── zhuangtaiji/             # ★ 可分发的 Python 包（pip install 后即此包）
│   ├── __init__.py          # 顶层导出：core 的公开 API 全部重导出
│   ├── __main__.py          # python -m zhuangtaiji → Tkinter 工作台
│   ├── config.json          # 所有引擎与 demo 编排的配置（单一数据源，随包分发）
│   ├── core/                # 引擎内核（纯标准库）
│   │   ├── state_machine.py / hierarchical_state_machine.py
│   │   ├── behavior_tree.py / decision_tree.py / difference_engine.py
│   │   ├── petri_net.py / markov_chain.py / rule_engine.py
│   │   ├── engine_base.py       # Engine / EngineEvent / Graph 等契约
│   │   ├── engine_adapters.py   # 各引擎 -> 统一 Engine 接口
│   │   ├── orchestrator.py      # 事件总线 + Orchestrator（编排层）
│   │   ├── config.py            # 配置加载 + 分层 patches 叠加
│   │   ├── registries.py        # 守卫 / 动作 / 引擎 / 插件注册表（由内核 Context 承载）
│   │   ├── analysis.py / renderers.py / plugin.py / adapters_io.py
│   │   ├── plugins/             # 以插件形态接入的范式（decision_table / llm_agent）
│   │   ├── kernel/              # 内核：Context / effect / inject / 事件派发 / 分层装配
│   │   │   ├── context.py / disposable.py / events.py / loader.py / registry.py
│   │   │   └── fiber_model.json # 内核生命周期的自模型（用本项目状态机格式书写）
│   │   └── __init__.py          # 统一导出
│   ├── ui/                  # Tkinter 工作台（入口 + 各功能 Tab）
│   │   ├── application.py / analysis_tab.py / visualization_tab.py
│   │   └── orchestrator_tab.py / plugin_tab.py
│   ├── engine/
│   │   └── progress_bar.py  # Canvas 进度条组件（tkinter 延迟导入，便于无头测试）
│   └── web/                 # REST 后端 + 前端静态托管
│       ├── server.py        # 标准库 http.server 的 REST 后端 + 静态托管
│       ├── static/          # 兜底静态页（dist 缺失时使用）
│       ├── orchestrations.json  # 用户持久化的编排（自动生成，可删；不入库）
│       └── webui/           # 真正的 Vite + React + @xyflow/react 前端
│           ├── index.html / package.json / vite.config.js
│           ├── src/{main.jsx, App.jsx, EngineNode.jsx, api.js, index.css}
│           └── dist/        # npm run build 产物（由 server.py 托管；不入库）
├── main.py                  # Tkinter 工作台入口（仓库内直跑）
├── pyproject.toml           # 打包配置（PEP 621）
├── MANIFEST.in              # sdist 附带文件清单
├── CHANGELOG.md             # 版本更新日志（与注解 tag / Gitee Release 同源）
├── tools/
│   ├── run_tests.py         # 测试与门禁统一入口
│   ├── kernel_demo.py       # 内核能力演示（七个真实痛点）
│   └── build_doc.mjs        # 方案文档构建：md → html（依赖 marked）
├── test/                    # 全部测试（统一入口：python tools/run_tests.py）
│   ├── test_verify.py / test_enhancements.py / test_kernel.py
│   └── test_config_patches.py / test_ui_smoke.py / test_web_e2e.py
└── zhuangtaiji-Cordis内核重构方案.md   # 内核重构方案（同名 .html 由 build_doc.mjs 生成）
```

## 安装

### Python 端

从 PyPI 安装（推荐）：

```bash
pip install zhuangtaiji          # 引擎内核，纯标准库，零运行时依赖
pip install zhuangtaiji[llm]     # 额外装上 LLM 智能体插件的可选后端（openai）
```

引擎本体仅需 Python 3.8+ 标准库，**没有任何第三方运行时依赖**；`tkinter`
在 Windows 自带（Linux 需额外安装 `python3-tk`），且只在真正启动桌面工作台时才导入。

也可以不安装、直接用源码（需 Python 3.8+ 标准库，无需 `pip install` 任何东西）：

```bash
# 可选：确认依赖（项目本身无第三方依赖）
pip install -r requirements.txt
```

### 前端（Web 编辑器）
```bash
cd zhuangtaiji/web/webui
npm install      # 安装 React / @xyflow/react / vite
npm run build    # 产出 dist/（server.py 直接托管）
```

## 运行

### 1. Tkinter 工作台
```bash
python main.py              # 仓库内直跑
python -m zhuangtaiji       # 已 pip 安装时
zhuangtaiji                 # 安装后也可用这个命令
```

### 2. Web 编排编辑器
```bash
# 确保已执行上述 npm run build
python -m zhuangtaiji.web.server 8011
# 浏览器打开 http://localhost:8011/

zhuangtaiji-web 8011        # 已 pip 安装时的等价命令
```
`8011` 是本项目登记的端口（`8000` 已被电台面板占用）；也可显式换端口：
`python -m zhuangtaiji.web.server <port>`。

> **安全默认（2026-09-24 起）**：服务**默认只绑定 `127.0.0.1`**（仅本机可访问）。
> 该服务**没有鉴权**且响应头 `Access-Control-Allow-Origin: *`，因此**不要**把它暴露到局域网/公网——
> 否则同网段任何人都能读写删你的编排（`PUT/DELETE/POST /api/orchestration/*`）。
> 确有需要时显式打开并自担风险：`python -m zhuangtaiji.web.server 8011 --host 0.0.0.0`
> （等价的 `ZHUANGTAIJI_HOST=0.0.0.0`），并自行加防火墙或反向代理鉴权。

Web 端点的首页优先服务 `zhuangtaiji/web/webui/dist`，缺失时回退 `zhuangtaiji/web/static`。

### 3. 前端热更新开发模式（可选）
```bash
cd zhuangtaiji/web/webui
npm run dev       # Vite dev server，默认 http://localhost:5173/
```

## 编排 REST API（`zhuangtaiji/web/server.py`）

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

推荐使用统一入口（自动处理导入路径，并把「环境缺依赖」与「代码失败」区分开）：

```bash
python tools/run_tests.py            # 跑全部测试
python tools/run_tests.py --list     # 只列出会被执行的测试
python tools/run_tests.py --verbose  # 打印每个测试的完整输出
python tools/run_tests.py kernel     # 只跑名字含 "kernel" 的测试
```

退出码 0 表示通过；`ENV-SKIP` 表示前置条件未就绪（缺 `tkinter`、缺前端 `dist/` 等），
**不计为失败**但会在汇总里显著提示。

也可以单独运行（需在项目根目录并设置 `PYTHONPATH=.`）：

```bash
PYTHONPATH=. python test/test_verify.py        # 原始功能回归
PYTHONPATH=. python test/test_enhancements.py  # P0~P3 增强覆盖
PYTHONPATH=. python test/test_kernel.py        # 内核断言 + 自举一致性（80 项）
PYTHONPATH=. python test/test_config_patches.py # 配置 patches 分层叠加
PYTHONPATH=. python test/test_ui_smoke.py      # Tkinter 界面冒烟（需带 tkinter 的解释器）
PYTHONPATH=. python test/test_web_e2e.py       # Web 端到端（需先 cd zhuangtaiji/web/webui && npm run build）
```

## 配置

所有引擎与 demo 编排定义在 `zhuangtaiji/config.json`（随包分发），结构见文件内注释；
编排层读取 `orchestration` 段（`engines` / `bindings` / `start`）。可视化编辑后保存为
`zhuangtaiji/web/orchestrations.json`。

从 Python 侧使用（v1.1.0 起的命名空间路径）：

```python
from zhuangtaiji import load_config, create_state_machine

cfg = load_config()                       # 读随包分发的 config.json
sm = create_state_machine("SM_Init", cfg) # 也可用 zhuangtaiji.core.xxx 的完整路径
sm.trigger("start")
print(sm.current_state_id)
```

## 变更日志

各版本的改动、门禁实测与升级提示见 [`CHANGELOG.md`](CHANGELOG.md)。每个版本对应一个
**注解 tag** 与一个 [Gitee Release](https://gitee.com/siwpan/zhuangtaiji/releases)，三者说明同源。
