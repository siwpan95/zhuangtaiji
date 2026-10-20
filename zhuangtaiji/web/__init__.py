# -*- coding: utf-8 -*-
"""Web 编排服务（REST 后端 + 前端静态托管）。

本包**不在** :mod:`zhuangtaiji` 顶层自动导入——它需要前端构建产物
（``zhuangtaiji/web/webui/dist``）才有完整功能，按需导入可让无头环境保持轻量。

启动::

    python -m zhuangtaiji.web.server [port] [--host <addr>]

默认只绑定 ``127.0.0.1``：该服务**没有鉴权**且 CORS 头是 ``*``，
绑定到 ``0.0.0.0`` 等于把编排的读、写、删接口交给同网段任何人。
"""
