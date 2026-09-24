# zhuangtaiji — Multi-Paradigm Decision Engine & Visual Workbench

An orchestration engine that wires several computation / decision paradigms — state machine
(FSM/HSM), behavior tree, decision tree, difference engine, Petri net, Markov chain, rule
engine, decision table, LLM agent — into one configurable system driven by a single
`config.json`, with a **Tkinter desktop workbench** and a **React + react-flow web editor**.

> `README.md` (Chinese) is the authoritative document for this repository.
> This file is a short English entry point and intentionally does not duplicate it.

## Features

- **Pure standard library** engine — no third-party runtime dependencies.
- `core/kernel/` — a Cordis-style kernel: Context, effects, inject, reversible disposal,
  event dispatch and layered assembly.
- **Orchestration layer** — event bus (`*` wildcard subscriptions) plus declarative
  bindings (`when event → then action`).
- **Two front ends** — `main.py` (Tkinter tabs) and `web/server.py` + `web/webui`
  (React flow editor with drag-to-create nodes, bind, step and run traces).

## Requirements

- Python 3.8+ (`tkinter` ships with Windows Python; install `python3-tk` on Linux).
- Node.js only if you want to build the optional web editor.

## Quick start

```bash
python main.py                     # Tkinter workbench

cd web/webui && npm install && npm run build
python web/server.py 8011          # then open http://localhost:8011/
```

`8011` is this project's registered port (`8000` is taken by the radio panel); pass any
other port explicitly instead: `python web/server.py <port>`.

> **Secure default (since 2026-09-24)**: the server binds **`127.0.0.1` only** (localhost).
> It has **no authentication** and replies with `Access-Control-Allow-Origin: *`, so never expose it to
> a LAN/public network — anyone on the same network could read/write/delete your orchestrations
> (`PUT/DELETE/POST /api/orchestration/*`). If you really need LAN access, opt in explicitly and take
> the risk: `python web/server.py 8011 --host 0.0.0.0` (or `ZHUANGTAIJI_HOST=0.0.0.0`), and add a
> firewall rule or an authenticating reverse proxy.

## Tests

```bash
python tools/run_tests.py          # unified entry: runs every test, exit code is the gate
python tools/run_tests.py --list   # list the tests that would run
```

Exit code `0` means pass. `ENV-SKIP` means a prerequisite (tkinter, front-end `dist/`)
is missing; it is reported prominently but not counted as a failure.

## Layout

`core/` engine kernel · `ui/` Tkinter workbench · `web/` REST server + React editor ·
`test/` test suite · `tools/` test gate, kernel demo and doc builder.

## License

MIT — see `LICENSE`. Copyright 2026 siwpan.
