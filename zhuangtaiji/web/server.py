# -*- coding: utf-8 -*-
"""
Web UI 服务端（P3 升级 · React + react-flow + 编排可视化编辑/持久化）
====================================================================

用标准库 ``http.server`` 暴露同一套 ``core`` 引擎，作为前端（Vite 构建的
React + @xyflow/react 节点编辑器）的 REST 后端。

新增能力（相对上一版）：
* 编排编排的「可视化编辑 + 持久化」：
  - GET    /api/orchestrations            列表（内置 demo + 用户持久化）
  - GET    /api/orchestration/<name>       取图谱(nodes/edges) 供 react-flow 渲染
  - PUT    /api/orchestration/<name>       保存（图谱 -> spec，写入 orchestrations.json）
  - DELETE /api/orchestration/<name>       删除（仅用户持久化部分）
  - POST   /api/orchestration/<name>/run   运行（执行 start 触发器）
  - POST   /api/orchestration/<name>/step  单步驱动某引擎（触发绑定链）
  - POST   /api/orchestration/<name>/reset 重置所有引擎状态
  - GET    /api/orchestration/<name>/status 各引擎实时摘要
* 托管构建产物：优先 ``zhuangtaiji/web/webui/dist``，缺失时回退 ``zhuangtaiji/web/static``。

运行：  python -m zhuangtaiji.web.server [port] [--host <addr>]
        默认只绑定 **127.0.0.1**（仅本机可访问）——本服务无鉴权且 CORS 放开，
        对局域网/公网开放等于把编排的读写删接口交给任何人。
        确需局域网访问时显式打开：--host 0.0.0.0（或用环境变量 ZHUANGTAIJI_HOST），
        并自行加防火墙/反向代理鉴权。
访问：  http://localhost:8011/
"""
import os
import sys
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

#: ``zhuangtaiji/`` 包目录——config.json、前端产物与用户编排都挂在它下面。
#: 用 ``__file__`` 推导而非 cwd，因此无论从仓库根目录还是从 site-packages 里
#: 以 ``python -m zhuangtaiji.web.server`` 启动，都能定位到随包分发的资源。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from ..core import load_config, build_adapter, analysis, renderers
from ..core import plugin as _plugin
from ..core.registries import engine_of, engine_sections
from ..core.orchestrator import Orchestrator

DIST = os.path.join(ROOT, "web", "webui", "dist")
STATIC = os.path.join(ROOT, "web", "static")
USER_FILE = os.path.join(ROOT, "web", "orchestrations.json")

# 进程内编排实例缓存（跨请求保持引擎状态，供「单步」连续驱动）
ORCH: dict = {}
_USER_LOCK = threading.Lock()


# ==========================================================
# 持久化：用户编排编排（orchestrations.json）
# ==========================================================
def _load_user() -> dict:
    if not os.path.exists(USER_FILE):
        return {}
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_user(data: dict) -> None:
    with _USER_LOCK:
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _spec_for(name: str):
    user = _load_user()
    if name in user:
        return user[name], "user"
    cfg = load_config()
    if name in cfg.get("orchestration", {}):
        return cfg["orchestration"][name], "builtin"
    return None, None


# ==========================================================
# 图谱 <-> 编排 spec 互转
# ==========================================================
def _auto_layout(nodes, edges):
    """为缺少位置的节点做分层布局（Kahn），避免全部叠在 (40,40)。"""
    ids = [n["id"] for n in nodes]
    if not ids:
        return
    indeg = {i: 0 for i in ids}
    adj = {i: [] for i in ids}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in indeg and t in indeg and s != t:
            indeg[t] += 1
            adj[s].append(t)
    layer = {}
    q = [i for i in ids if indeg[i] == 0]
    for i in q:
        layer[i] = 0
    while q:
        nxt = []
        for a in q:
            for b in adj[a]:
                layer[b] = max(layer.get(b, 0), layer[a] + 1)
                indeg[b] -= 1
                if indeg[b] == 0:
                    nxt.append(b)
        q = nxt
    for i in ids:
        layer.setdefault(i, 0)
    by_layer = {}
    for n in nodes:
        if n["position"].get("x", 40) == 40 and n["position"].get("y", 40) == 40:
            L = layer[n["id"]]
            by_layer.setdefault(L, []).append(n)
    for L, arr in by_layer.items():
        for idx, n in enumerate(arr):
            n["position"] = {"x": 60 + L * 240, "y": 60 + idx * 130}


def _spec_to_graph(spec: dict) -> dict:
    nodes, edges = [], []
    for alias, e in (spec.get("engines") or {}).items():
        nodes.append({
            "id": alias,
            "data": {"kind": e.get("kind"), "name": e.get("name"), "summary": ""},
            "position": {"x": e.get("x", 40), "y": e.get("y", 40)},
        })
    for i, b in enumerate(spec.get("bindings", [])):
        when, then = b.get("when", {}), b.get("then", {})
        etype = when.get("etype", "*")
        action = then.get("action", "step")
        edges.append({
            "id": f"b{i}",
            "source": when.get("engine", ""),
            "target": then.get("engine", ""),
            "label": f"{etype} → {action}",
            "data": {"etype": etype, "action": action, "ctx": then.get("ctx", {})},
        })
    _auto_layout(nodes, edges)
    return {
        "nodes": nodes,
        "edges": edges,
        "start": spec.get("start", []),
        "description": spec.get("description", ""),
    }


def _graph_to_spec(payload: dict) -> dict:
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    engines = {}
    for n in nodes:
        d = n.get("data", {})
        pos = n.get("position", {})
        engines[n["id"]] = {
            "kind": d.get("kind"),
            "name": d.get("name"),
            "x": int(pos.get("x", 40)),
            "y": int(pos.get("y", 40)),
        }
    bindings = []
    for e in edges:
        d = e.get("data", {}) or {}
        bindings.append({
            "when": {"engine": e.get("source"), "etype": d.get("etype", "*")},
            "then": {"engine": e.get("target"), "action": d.get("action", "step"),
                     "ctx": d.get("ctx", {})},
        })
    return {
        "description": payload.get("description", ""),
        "engines": engines,
        "bindings": bindings,
        "start": payload.get("start", []),
    }


def _engine_catalog() -> dict:
    """``{kind: [实例名, ...]}``——从引擎注册表派生。

    取代过去 ``web/server.py`` 内**三处**各自硬编码的 kind → 段名 映射表
    （``_validate_spec``、``api/engines``、``_catalog``）：新增一个范式只需
    ``register_engine()`` 一次，所有端点自动可见。
    """
    _plugin.ensure_discovered()
    cfg = load_config()
    return {kind: list((cfg.get(section) or {}).keys())
            for kind, section in engine_sections().items()}


def _validate_spec(spec: dict) -> str:
    """返回错误描述，空串表示通过。"""
    kinds = set(_plugin.PluginRegistry.kinds())
    catalog = _engine_catalog()
    engines = spec.get("engines", {})
    for alias, e in engines.items():
        kind, name = e.get("kind"), e.get("name")
        if kind not in kinds:
            return f"引擎 {alias} 的范式 {kind} 未注册"
        if name not in catalog.get(kind, []):
            return f"范式 {kind} 不存在实例 {name}"
    for b in spec.get("bindings", []):
        w, t = b.get("when", {}), b.get("then", {})
        if w.get("engine") not in engines:
            return f"绑定来源引擎 {w.get('engine')} 不存在"
        if t.get("engine") not in engines:
            return f"绑定目标引擎 {t.get('engine')} 不存在"
    return ""


# ==========================================================
# 编排实例（进程内缓存）
# ==========================================================
def _get_orch(name: str):
    spec, source = _spec_for(name)
    if spec is None:
        return None, None
    if name in ORCH:
        return ORCH[name], source
    cfg = load_config()
    o = Orchestrator()
    o.configure(spec, cfg)
    ORCH[name] = o
    return o, source


def _drop_orch(name: str):
    ORCH.pop(name, None)


# ==========================================================
# 引擎视图辅助
# ==========================================================
def _graph_json(g):
    return {
        "kind": g.kind, "direction": g.direction, "title": g.title,
        "nodes": [{"id": n.id, "label": n.label, "shape": n.shape,
                   "active": n.active} for n in g.nodes],
        "edges": [{"src": e.src, "dst": e.dst, "label": e.label,
                   "active": e.active} for e in g.edges],
    }


def _engine_view(kind, name):
    cfg = load_config()
    eng = build_adapter(kind, name, cfg)
    g = eng.visualize()
    return {
        "kind": kind, "name": name,
        "summary": eng.summary(),
        "graph": _graph_json(g),
        "mermaid": renderers.to_mermaid(g),
        "dot": renderers.to_dot(g),
    }


def _engine_step(kind, name, ctx):
    cfg = load_config()
    eng = build_adapter(kind, name, cfg)
    eng.step(ctx or {})
    return _engine_view(kind, name)


def _orch_status_payload(o: Orchestrator):
    status = o.engine_status()
    # 把实时摘要回填到图谱节点，便于前端高亮/显示
    graph = o.to_graph()
    by_alias = {s["alias"]: s["summary"] for s in status}
    for n in graph["nodes"]:
        n["data"]["summary"] = by_alias.get(n["id"], "")
    return {"status": status, "graph": graph, "trace": o.trace[-50:]}


# ==========================================================
# 静态文件托管（dist 优先，static 回退）
# ==========================================================
def _serve_static(handler, rel_path: str):
    # 优先 dist，其次 static
    cand = os.path.join(DIST, rel_path)
    if not (rel_path and os.path.isfile(cand)):
        cand = os.path.join(STATIC, rel_path)
    if os.path.isfile(cand):
        ctype = "text/html; charset=utf-8"
        if cand.endswith(".js"):
            ctype = "text/javascript; charset=utf-8"
        elif cand.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif cand.endswith(".json"):
            ctype = "application/json"
        elif cand.endswith(".svg"):
            ctype = "image/svg+xml"
        with open(cand, "rb") as f:
            handler._send(200, f.read(), ctype)
        return True
    return False


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, (bytes, bytearray)) else \
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path.strip("/")
        parts = [x for x in p.split("/") if x]
        try:
            # SPA 首页
            if p in ("", "index.html"):
                if not _serve_static(self, "index.html"):
                    self._send(404, {"error": "未构建前端，请先 npm run build"})
                return
            if p.startswith("assets/"):
                if not _serve_static(self, p):
                    self._send(404, {"error": "not found"})
                return

            if p == "api/engines":
                return self._send(200, _engine_catalog())
            if p == "api/plugins":
                _plugin.ensure_discovered()
                return self._send(200, [{"kind": pl.kind, "label": pl.label,
                                          "description": pl.description}
                                         for pl in _plugin.PluginRegistry.all()])
            if p == "api/orchestrations":
                _plugin.ensure_discovered()
                cfg = load_config()
                user = _load_user()
                items = [{"name": n, "description": s.get("description", ""),
                          "source": "builtin"}
                         for n, s in cfg.get("orchestration", {}).items()]
                for n, s in user.items():
                    items.append({"name": n, "description": s.get("description", ""),
                                  "source": "user"})
                return self._send(200, {"list": items, "catalog": self._catalog()})
            if p.startswith("api/orchestration/"):
                rest = p[len("api/orchestration/"):]
                if rest.endswith("/status"):
                    name = rest[:-len("/status")]
                    o, _ = _get_orch(name)
                    if o is None:
                        return self._send(404, {"error": "编排不存在"})
                    return self._send(200, _orch_status_payload(o))
                name = rest
                spec, source = _spec_for(name)
                if spec is None:
                    return self._send(404, {"error": "编排不存在"})
                return self._send(200, {"name": name, "source": source,
                                        **_spec_to_graph(spec)})
            if p.startswith("api/analysis/"):
                _, _, kind, name = p.split("/")
                meta = engine_of(kind)
                if meta is None:
                    return self._send(404, {"error": f"未知范式: {kind}"})
                spec = (load_config().get(meta.section) or {}).get(name)
                if spec is None:
                    return self._send(404,
                                      {"error": f"{meta.section} 中不存在实例: {name}"})
                return self._send(200, {"report": analysis.format_analysis(kind, spec)})
            if p.startswith("api/engine/"):
                _, _, kind, name = p.split("/")
                return self._send(200, _engine_view(kind, name))
        except Exception as e:
            return self._send(500, {"error": str(e)})
        if not _serve_static(self, p):
            self._send(404, {"error": "not found"})

    def _catalog(self):
        return _engine_catalog()

    # ---- POST / PUT / DELETE ----
    def do_POST(self):
        u = urlparse(self.path)
        p = u.path.strip("/")
        try:
            if p.startswith("api/engine/") and p.endswith("/step"):
                _, _, kind, name, _ = p.split("/")
                return self._send(200, _engine_step(kind, name, self._body().get("ctx")))

            if p.startswith("api/orchestration/") and p.endswith("/run"):
                name = p[len("api/orchestration/"):-len("/run")]
                o, _ = _get_orch(name)
                if o is None:
                    return self._send(404, {"error": "编排不存在"})
                o.start()
                return self._send(200, _orch_status_payload(o))

            if p.startswith("api/orchestration/") and p.endswith("/step"):
                name = p[len("api/orchestration/"):-len("/step")]
                o, _ = _get_orch(name)
                if o is None:
                    return self._send(404, {"error": "编排不存在"})
                body = self._body()
                r = o.step_engine(body.get("engine", ""), body.get("ctx") or {})
                return self._send(200, {"result": r,
                                        **_orch_status_payload(o)})

            if p.startswith("api/orchestration/") and p.endswith("/reset"):
                name = p[len("api/orchestration/"):-len("/reset")]
                spec, _ = _spec_for(name)
                if spec is None:
                    return self._send(404, {"error": "编排不存在"})
                o = Orchestrator()
                o.configure(spec, load_config())
                ORCH[name] = o
                return self._send(200, _orch_status_payload(o))
        except Exception as e:
            return self._send(500, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        u = urlparse(self.path)
        p = u.path.strip("/")
        try:
            if p.startswith("api/orchestration/"):
                name = p[len("api/orchestration/"):]
                payload = self._body()
                spec = _graph_to_spec(payload)
                err = _validate_spec(spec)
                if err:
                    return self._send(400, {"error": err})
                user = _load_user()
                user[name] = spec
                _save_user(user)
                _drop_orch(name)  # 下次访问按新 spec 重建
                return self._send(200, {"ok": True, "name": name,
                                        "source": "user",
                                        **_spec_to_graph(spec)})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        u = urlparse(self.path)
        p = u.path.strip("/")
        try:
            if p.startswith("api/orchestration/"):
                name = p[len("api/orchestration/"):]
                user = _load_user()
                if name in user:
                    del user[name]
                    _save_user(user)
                    _drop_orch(name)
                    return self._send(200, {"ok": True, "deleted": name})
                return self._send(404, {"error": "内置编排不可删除（仅用户编排可删）"})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def _parse_argv(argv):
    """解析 `[port] [--host <addr>]`。

    默认 host = 127.0.0.1（仅本机）：本服务无鉴权、CORS 放开，
    绑定 0.0.0.0 等于把编排读写删接口暴露给整个局域网，必须显式要求。
    优先级：命令行 --host > 环境变量 ZHUANGTAIJI_HOST > 127.0.0.1。
    """
    port, host = 8011, os.environ.get("ZHUANGTAIJI_HOST", "127.0.0.1")
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--host":
            if not rest:
                raise SystemExit("--host 需要一个地址参数，例如 --host 0.0.0.0")
            host = rest.pop(0)
        elif a.startswith("--host="):
            host = a.split("=", 1)[1]
        elif a.isdigit():
            port = int(a)
        else:
            raise SystemExit(f"无法识别的参数: {a}（用法: python web/server.py [port] [--host <addr>]）")
    return port, host


def main():
    port, host = _parse_argv(sys.argv[1:])
    _plugin.ensure_discovered()
    httpd = ThreadingHTTPServer((host, port), Handler)
    shown = "localhost" if host in ("127.0.0.1", "::1") else host
    print(f"决策引擎 Web UI 已启动: http://{shown}:{port}/  (监听 {host}；Ctrl+C 退出)")
    if host not in ("127.0.0.1", "::1"):
        print(f"[警告] 正在监听 {host}，本服务无鉴权且 CORS 放开 —— 同网段任何人都能读写/删除编排。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
