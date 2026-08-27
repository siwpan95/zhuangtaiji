# -*- coding: utf-8 -*-
"""Web 前端（React+react-flow 构建产物）与编排编辑/持久化 API 的端到端验证。"""
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 项目根目录（原 D:\allin 已失效）
import web.server as ws  # noqa: E402
import http.server as h  # noqa: E402

BASE = "http://127.0.0.1:8151"


def _get(p):
    return urllib.request.urlopen(BASE + p).read()


def jget(p):
    return json.loads(_get(p))


def jpost(p, b=None):
    body = json.dumps(b or {}).encode() if b is not None else None
    req = urllib.request.Request(BASE + p, data=body,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    return json.loads(urllib.request.urlopen(req).read())


def jput(p, b):
    req = urllib.request.Request(BASE + p, data=json.dumps(b).encode(),
                                  headers={"Content-Type": "application/json"},
                                  method="PUT")
    return json.loads(urllib.request.urlopen(req).read())


def jdel(p):
    req = urllib.request.Request(BASE + p, method="DELETE")
    return json.loads(urllib.request.urlopen(req).read())


def main():
    httpd = h.ThreadingHTTPServer(("127.0.0.1", 8151), ws.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    ok = True

    # 1) SPA 首页来自 dist
    html = _get("/").decode("utf-8")
    assert '<div id="root">' in html, "首页未含 #root"
    print("[1] SPA index served from dist: OK")

    # 2) 构建产物资源可访问
    m = re.search(r"/assets/(index-[A-Za-z0-9_-]+\.js)", html)
    assert m, "首页未引用 assets js"
    js = _get("/" + m.group(0))
    assert len(js) > 1000, "js 资源为空"
    print(f"[2] asset {m.group(0)} served ({len(js)} bytes): OK")

    # 3) 编排列表
    lst = jget("/api/orchestrations")["list"]
    names = [x["name"] for x in lst]
    assert "demo" in names, "内置 demo 缺失"
    print(f"[3] orchestrations list: {names}")

    # 4) demo 图谱
    g = jget("/api/orchestration/demo")
    assert len(g["nodes"]) == 3 and len(g["edges"]) == 2, "demo 图谱结构异常"
    print(f"[4] demo graph nodes={len(g['nodes'])} edges={len(g['edges'])}: OK")

    # 5) 编辑式保存：2 节点 + 1 绑定 -> 回读 -> 单步 -> 验证联动
    spec = {
        "description": "e2e",
        "nodes": [
            {"id": "a", "data": {"kind": "state_machine", "name": "SM_Init"},
             "position": {"x": 40, "y": 40}},
            {"id": "b", "data": {"kind": "markov_chain", "name": "MC_Weather"},
             "position": {"x": 300, "y": 40}},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b",
                   "data": {"etype": "enter", "action": "step", "ctx": {}}}],
        "start": [],
    }
    r = jput("/api/orchestration/E2E", spec)
    assert r["ok"], "保存失败"
    g2 = jget("/api/orchestration/E2E")
    assert len(g2["nodes"]) == 2 and len(g2["edges"]) == 1, "回读结构不符"
    print("[5] PUT + reload graph persisted: OK")

    # 6) 单步驱动 a，触发绑定链使 b 演化
    rr = jpost("/api/orchestration/E2E/step", {"engine": "a", "ctx": {"event": "start"}})
    print(f"[6] step a -> {rr['result']}; trace entries={len(rr['trace'])}; "
          f"b-active={[s for s in rr['status'] if s['alias']=='b']}")

    # 7) 运行内置 demo
    rj = jpost("/api/orchestration/demo/run")
    assert len(rj["trace"]) > 0, "运行无轨迹"
    print(f"[7] demo run trace entries={len(rj['trace'])}: OK")

    # 8) 清理 + 内置不可删
    print("[8] delete E2E:", jdel("/api/orchestration/E2E")["deleted"])
    try:
        jdel("/api/orchestration/demo")
        ok = False
    except urllib.error.HTTPError as e:
        assert e.code == 404, "内置删除应被拦截"
        print("[8] builtin delete blocked (404): OK")

    httpd.shutdown()
    print("\nWEB E2E ALL OK" if ok else "\nWEB E2E FAILED")


if __name__ == "__main__":
    main()
