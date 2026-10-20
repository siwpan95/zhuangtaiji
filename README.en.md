# zhuangtaiji — Multi-Paradigm Decision Engine & Visual Workbench

An orchestration engine that wires several computation / decision paradigms — state machine
(FSM/HSM), behavior tree, decision tree, difference engine, Petri net, Markov chain, rule
engine, decision table, LLM agent — into one configurable system driven by a single
`config.json`, with a **Tkinter desktop workbench** and a **React + react-flow web editor**.

> `README.md` (Chinese) is the authoritative document for this repository.
> This file is a short English entry point and intentionally does not duplicate it.

[![PyPI](https://img.shields.io/pypi/v/zhuangtaiji)](https://pypi.org/project/zhuangtaiji/)
[![Python](https://img.shields.io/pypi/pyversions/zhuangtaiji)](https://pypi.org/project/zhuangtaiji/)
[![License](https://img.shields.io/pypi/l/zhuangtaiji)](https://pypi.org/project/zhuangtaiji/)

**PyPI**: <https://pypi.org/project/zhuangtaiji/> | distribution name and import name are both
`zhuangtaiji`:

```bash
pip install zhuangtaiji
python -c "import zhuangtaiji; print(zhuangtaiji.__version__)"
python -m zhuangtaiji            # Tkinter workbench
```

## Features

- **Pure standard library** engine — no third-party runtime dependencies.
- `core/kernel/` — a Cordis-style kernel: Context, effects, inject, reversible disposal,
  event dispatch and layered assembly.
- **Orchestration layer** — event bus (`*` wildcard subscriptions) plus declarative
  bindings (`when event → then action`).
- **Two front ends** — `main.py` (Tkinter tabs) and `zhuangtaiji/web/server.py` +
  `zhuangtaiji/web/webui` (React flow editor with drag-to-create nodes, bind, step and run traces).
- **Installable** (since v1.1.0) — `pip install zhuangtaiji`, pure standard library, no runtime deps.

## Requirements

- Python 3.8+ (`tkinter` ships with Windows Python; install `python3-tk` on Linux).
- Node.js only if you want to build the optional web editor.

## Install

```bash
pip install zhuangtaiji            # engine core: pure stdlib, zero runtime dependencies
pip install zhuangtaiji[llm]       # + optional backend for the LLM agent plugin
```

## Quick start

```bash
python main.py                     # Tkinter workbench (from a source checkout)
python -m zhuangtaiji              # …or, once installed

cd zhuangtaiji/web/webui && npm install && npm run build
python -m zhuangtaiji.web.server 8011   # then open http://localhost:8011/
```

`8011` is this project's registered port (`8000` is taken by the radio panel); pass any
other port explicitly instead: `python -m zhuangtaiji.web.server <port>`.
After `pip install`, the `zhuangtaiji` and `zhuangtaiji-web` console scripts do the same.

> **Secure default (since 2026-09-24)**: the server binds **`127.0.0.1` only** (localhost).
> It has **no authentication** and replies with `Access-Control-Allow-Origin: *`, so never expose it to
> a LAN/public network — anyone on the same network could read/write/delete your orchestrations
> (`PUT/DELETE/POST /api/orchestration/*`). If you really need LAN access, opt in explicitly and take
> the risk: `python -m zhuangtaiji.web.server 8011 --host 0.0.0.0` (or `ZHUANGTAIJI_HOST=0.0.0.0`),
> and add a firewall rule or an authenticating reverse proxy.

## Tests

```bash
python tools/run_tests.py          # unified entry: runs every test, exit code is the gate
python tools/run_tests.py --list   # list the tests that would run
```

Exit code `0` means pass. `ENV-SKIP` means a prerequisite (tkinter, front-end `dist/`)
is missing; it is reported prominently but not counted as a failure.

## Layout

All Python sources live under the `zhuangtaiji/` namespace package — the plain top-level
names `core`, `engine` and `web` are **already taken on PyPI**, so publishing them as-is
would collide. Import path is therefore `zhuangtaiji.core`, `zhuangtaiji.ui`, …:

```python
from zhuangtaiji import load_config, create_state_machine
```

`zhuangtaiji/core/` engine kernel · `zhuangtaiji/ui/` Tkinter workbench ·
`zhuangtaiji/web/` REST server + React editor · `test/` test suite ·
`tools/` test gate, kernel demo and doc builder.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) (Chinese). Every release is an annotated tag plus a
[Gitee Release](https://gitee.com/siwpan/zhuangtaiji/releases); both mirror that file.

## License

MIT — see `LICENSE`. Copyright 2026 siwpan.
