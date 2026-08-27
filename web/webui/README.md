# Web 编排编辑器（React + react-flow）

本项目的前端部分：基于 **Vite + React 18 + @xyflow/react v12** 的可视化编排编辑器，
由 `web/server.py`（标准库 `http.server`）托管。

## 功能

- 左侧引擎面板 **拖拽** 到画布生成引擎节点
- 节点 handle **连线** 即建立「绑定」（`when 事件 → then 动作`）
- Inspector 编辑选中节点（单步驱动 `ctx`）/ 边（`etype` / `action` / `ctx`）
- 运行 / 重置 / 实时摘要 / 执行轨迹面板
- 编辑结果持久化到后端 `web/orchestrations.json`

## 开发

```bash
npm install        # 安装依赖
npm run dev        # 热更新开发，默认 http://localhost:5173/
npm run build      # 产出 dist/，供 server.py 托管
npm run preview    # 预览构建产物
```

## 与后端联调

`src/api.js` 通过相对路径 `/api/...` 调用 `web/server.py`。开发时用 Vite 默认端口，
生产由 `python web/server.py <port>` 直接托管 `dist/`。

## 目录

```
webui/
├── index.html
├── package.json
├── vite.config.js
└── src/
    ├── main.jsx        # 入口
    ├── App.jsx         # 主应用（画布 + 工具栏 + Inspector + 轨迹）
    ├── EngineNode.jsx  # 自定义引擎节点
    ├── api.js          # 后端 REST 封装
    └── index.css       # 样式
```
