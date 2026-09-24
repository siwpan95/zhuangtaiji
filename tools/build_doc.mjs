import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

// 仓库根由脚本自身位置推导（tools/ 的上一级），不写死任何一台机器的绝对路径。
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// marked 从本脚本可解析到的 node_modules 解析（逐级向上 + NODE_PATH），
// 缺失时明确报错并给出补救命令，而不是指向某个本机专有目录。
const require = createRequire(import.meta.url);
let marked;
try {
  ({ marked } = require('marked'));
} catch (err) {
  console.error('[build_doc] 缺少依赖 marked，无法把方案 md 渲染为 html。补救方式（任选其一）：');
  console.error('          1) 在仓库根执行：npm install --no-save marked');
  console.error('          2) 设置 NODE_PATH 指向已安装 marked 的 node_modules 后重试。');
  process.exit(2);
}

const mdPath = path.join(root, 'zhuangtaiji-Cordis内核重构方案.md');
const outPath = path.join(root, 'zhuangtaiji-Cordis内核重构方案.html');
const md = fs.readFileSync(mdPath, 'utf8');

const tokens = marked.lexer(md);
const headings = tokens
  .filter(t => t.type === 'heading' && t.depth >= 1 && t.depth <= 2)
  .map(t => ({ depth: t.depth, text: t.text.replace(/[*`]/g, '') }));

function slug(text) {
  return text.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, '').trim().replace(/\s+/g, '-');
}

let html = marked.parse(md, { gfm: true });
html = html.replace(/<h([1-3])>([\s\S]*?)<\/h\1>/g, (m, lvl, inner) => {
  const plain = inner.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&');
  const id = slug(plain);
  return `<h${lvl} id="${id}">${inner}<a class="anchor" href="#${id}">#</a></h${lvl}>`;
});

const D = {};

D.isomorphism = `
<figure class="diagram">
<svg viewBox="0 0 900 400" role="img" aria-label="状态机与 Cordis Fiber 的同构对照">
  <defs>
    <marker id="ia" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#6366f1"/>
    </marker>
    <style>
      .f{font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
      .fl{font-size:12.5px;font-weight:600;fill:#0f172a}
      .fs{font-size:10.5px;fill:#475569}
      .fm{font-family:Consolas,"Cascadia Mono",monospace;font-size:11px;fill:#312e81}
      .hd{font-size:13.5px;font-weight:700}
    </style>
  </defs>

  <text class="f hd" x="40" y="26" fill="#0f766e">zhuangtaiji · core/state_machine.py</text>
  <text class="f hd" x="500" y="26" fill="#4338ca">Cordis · vendor/cordis/src/fiber.ts</text>

  <rect x="40" y="40" width="360" height="52" rx="7" fill="#ecfdf5" stroke="#059669" stroke-width="1.4"/>
  <text class="f fl" x="54" y="62">states</text>
  <text class="f fs" x="54" y="80">idle / running / error …</text>
  <line x1="400" y1="66" x2="500" y2="66" stroke="#6366f1" stroke-width="1.6" marker-end="url(#ia)"/>
  <rect x="500" y="40" width="360" height="52" rx="7" fill="#eef2ff" stroke="#4f46e5" stroke-width="1.4"/>
  <text class="f fl" x="514" y="62">状态集</text>
  <text class="f fs" x="514" y="80">PENDING / ACTIVE / FAILED / DISPOSED / …</text>

  <rect x="40" y="102" width="360" height="52" rx="7" fill="#ecfdf5" stroke="#059669" stroke-width="1.4"/>
  <text class="f fl" x="54" y="124">transitions 的 key</text>
  <text class="f fm" x="54" y="142">start / complete / turn_on</text>
  <line x1="400" y1="128" x2="500" y2="128" stroke="#6366f1" stroke-width="1.6" marker-end="url(#ia)"/>
  <rect x="500" y="102" width="360" height="52" rx="7" fill="#eef2ff" stroke="#4f46e5" stroke-width="1.4"/>
  <text class="f fl" x="514" y="124">转移事件</text>
  <text class="f fm" x="514" y="142">provide / 撤销 / update / dispose</text>

  <rect x="40" y="164" width="360" height="52" rx="7" fill="#fef2f2" stroke="#e11d48" stroke-width="1.6"/>
  <text class="f fl" x="54" y="186">guard: "allow_go"</text>
  <text class="f fs" x="54" y="204">可调用守卫，拒绝则停在原状态</text>
  <line x1="400" y1="190" x2="500" y2="190" stroke="#e11d48" stroke-width="1.8" marker-end="url(#ia)"/>
  <rect x="500" y="164" width="360" height="52" rx="7" fill="#fef2f2" stroke="#e11d48" stroke-width="1.6"/>
  <text class="f fl" x="514" y="186">epoch 依赖指纹</text>
  <text class="f fs" x="514" y="204">inject 的 provider fiber uid 拼接；不符即停在 PENDING</text>

  <rect x="40" y="226" width="360" height="52" rx="7" fill="#ecfdf5" stroke="#059669" stroke-width="1.4"/>
  <text class="f fl" x="54" y="248">on_enter 动作</text>
  <text class="f fs" x="54" y="266">进入状态时执行（ACTION_REGISTRY）</text>
  <line x1="400" y1="252" x2="500" y2="252" stroke="#6366f1" stroke-width="1.6" marker-end="url(#ia)"/>
  <rect x="500" y="226" width="360" height="52" rx="7" fill="#eef2ff" stroke="#4f46e5" stroke-width="1.4"/>
  <text class="f fl" x="514" y="248">_reload()</text>
  <text class="f fs" x="514" y="266">重解析配置 + 执行插件主体</text>

  <rect x="40" y="288" width="360" height="52" rx="7" fill="#ecfdf5" stroke="#059669" stroke-width="1.4"/>
  <text class="f fl" x="54" y="310">on_exit 动作</text>
  <text class="f fs" x="54" y="328">离开状态时执行</text>
  <line x1="400" y1="314" x2="500" y2="314" stroke="#6366f1" stroke-width="1.6" marker-end="url(#ia)"/>
  <rect x="500" y="288" width="360" height="52" rx="7" fill="#eef2ff" stroke="#4f46e5" stroke-width="1.4"/>
  <text class="f fl" x="514" y="310">_unload() + effect 逆序回收</text>
  <text class="f fs" x="514" y="328">fiber.ts:675-696</text>

  <rect x="40" y="350" width="360" height="44" rx="7" fill="#fffbeb" stroke="#d97706" stroke-width="1.4"/>
  <text class="f fl" x="54" y="372">history: "shallow"（HSM）</text>
  <text class="f fs" x="54" y="388">恢复到离开前的子状态</text>
  <line x1="400" y1="372" x2="500" y2="372" stroke="#d97706" stroke-width="1.6" marker-end="url(#ia)"/>
  <rect x="500" y="350" width="360" height="44" rx="7" fill="#fffbeb" stroke="#d97706" stroke-width="1.4"/>
  <text class="f fl" x="514" y="372">HMR 失败回滚</text>
  <text class="f fs" x="514" y="388">回滚缓存并重挂旧插件</text>
</svg>
<figcaption>图 1 · 同构对照：Cordis 的 Fiber 不是"有点像状态机"，它就是一个带守卫、带进入/退出动作、带历史恢复的状态机。</figcaption>
</figure>`;

D.lifecycle = `
<figure class="diagram">
<svg viewBox="0 0 900 420" role="img" aria-label="内核生命周期状态机">
  <defs>
    <marker id="la" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#334155"/>
    </marker>
    <marker id="la2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#e11d48"/>
    </marker>
    <style>
      .g{font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
      .gl{font-size:13px;font-weight:700;fill:#0f172a}
      .gs{font-size:10px;fill:#475569}
      .ge{font-family:Consolas,"Cascadia Mono",monospace;font-size:10.5px;fill:#1e293b}
      .gt{font-family:Consolas,"Cascadia Mono",monospace;font-size:10px;fill:#9f1239}
    </style>
  </defs>

  <circle cx="34" cy="118" r="7" fill="#0f172a"/>
  <line x1="41" y1="118" x2="58" y2="118" stroke="#334155" stroke-width="1.6" marker-end="url(#la)"/>

  <rect x="60" y="86" width="180" height="66" rx="9" fill="#fff7ed" stroke="#d97706" stroke-width="1.8"/>
  <text class="g gl" x="76" y="110">PENDING</text>
  <text class="g gs" x="76" y="129">已挂载；inject 未满足</text>
  <text class="g gs" x="76" y="144">apply 尚未执行</text>

  <rect x="380" y="86" width="180" height="66" rx="9" fill="#ecfdf5" stroke="#059669" stroke-width="1.8"/>
  <text class="g gl" x="396" y="110">ACTIVE</text>
  <text class="g gs" x="396" y="129">apply 已执行</text>
  <text class="g gs" x="396" y="144">持有 N 个 effect</text>

  <rect x="380" y="248" width="180" height="66" rx="9" fill="#fef2f2" stroke="#e11d48" stroke-width="1.8"/>
  <text class="g gl" x="396" y="272">FAILED</text>
  <text class="g gs" x="396" y="291">apply 抛错</text>
  <text class="g gs" x="396" y="306">已回滚本次 effect</text>

  <rect x="690" y="166" width="180" height="66" rx="9" fill="#f1f5f9" stroke="#475569" stroke-width="1.8"/>
  <text class="g gl" x="706" y="190">DISPOSED</text>
  <text class="g gs" x="706" y="209">effect 逆序回收完毕</text>
  <text class="g gs" x="706" y="224">服务清空</text>

  <!-- PENDING -> ACTIVE -->
  <path d="M240 104 L380 104" stroke="#334155" stroke-width="1.8" marker-end="url(#la)" fill="none"/>
  <text class="g ge" x="252" y="90">provide</text>
  <text class="g gt" x="252" y="76">guard: inject_satisfied</text>

  <!-- ACTIVE -> PENDING -->
  <path d="M380 134 L240 134" stroke="#334155" stroke-width="1.8" marker-end="url(#la)" fill="none"/>
  <text class="g ge" x="262" y="152">unprovide（provider 撤回）</text>

  <!-- PENDING -> FAILED -->
  <path d="M150 152 C150 220 300 281 380 281" stroke="#e11d48" stroke-width="1.8" marker-end="url(#la2)" fill="none" stroke-dasharray="6 4"/>
  <text class="g ge" x="176" y="236" fill="#9f1239">provide_error</text>

  <!-- FAILED -> PENDING -->
  <path d="M380 300 C300 300 150 220 150 152" stroke="#334155" stroke-width="1.6" marker-end="url(#la)" fill="none"/>
  <text class="g ge" x="196" y="322">unprovide</text>

  <!-- PENDING/ACTIVE/FAILED -> DISPOSED -->
  <path d="M240 118 L690 184" stroke="#475569" stroke-width="1.5" marker-end="url(#la)" fill="none" stroke-dasharray="5 4"/>
  <path d="M560 118 L690 184" stroke="#475569" stroke-width="1.5" marker-end="url(#la)" fill="none" stroke-dasharray="5 4"/>
  <path d="M560 281 L690 216" stroke="#475569" stroke-width="1.5" marker-end="url(#la)" fill="none" stroke-dasharray="5 4"/>
  <text class="g ge" x="600" y="120" fill="#475569">dispose（任一状态）</text>

  <rect x="60" y="356" width="810" height="48" rx="8" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.2"/>
  <text class="g gs" x="76" y="376" font-size="11">模型文件：<tspan font-family="Consolas" fill="#312e81">prototype/fiber_model.json</tspan> —— 用本项目自己的状态机配置格式描述本项目的内核。</text>
  <text class="g gs" x="76" y="394" font-size="11">校验方式：<tspan font-family="Consolas" fill="#312e81">test_kernel.py</tspan> 驱动真实内核与该模型<tspan font-weight="700">锁步前进</tspan>，逐步比对状态；任何一步不一致即测试失败。</text>
</svg>
<figcaption>图 2 · 内核生命周期状态机（4 状态 / 7 转移）。注意 PENDING→ACTIVE 与 PENDING→FAILED 都是 <code>provide</code> 触发的，前者带守卫 <code>inject_satisfied</code>；<code>ACTIVE/FAILED</code> 在依赖撤回时退回 <code>PENDING</code>——即"只在依赖集合真的变化时才重试"。</figcaption>
</figure>`;

D.lockstep = `
<figure class="diagram">
<svg viewBox="0 0 900 300" role="img" aria-label="自举锁步一致性验证">
  <defs>
    <marker id="ka" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#6366f1"/>
    </marker>
    <style>
      .k{font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
      .kl{font-size:12px;font-weight:600;fill:#0f172a}
      .ks{font-size:10px;fill:#475569}
      .km{font-family:Consolas,"Cascadia Mono",monospace;font-size:10px;fill:#312e81}
      .kc{font-size:10.5px;font-weight:700;fill:#047857}
    </style>
  </defs>

  <rect x="20" y="20" width="860" height="58" rx="8" fill="#ecfdf5" stroke="#059669" stroke-width="1.6"/>
  <text class="k kl" x="36" y="42">真实内核 · prototype/cordis_kernel/context.py</text>
  <text class="k ks" x="36" y="62">执行真实操作：plugin() / provide() / 撤回 / dispose() —— 状态由 _recheck() 按依赖重算</text>

  <rect x="20" y="200" width="860" height="58" rx="8" fill="#eef2ff" stroke="#4f46e5" stroke-width="1.6"/>
  <text class="k kl" x="36" y="222">模型 · prototype/fiber_model.json（由项目自己的 FSM 引擎加载）</text>
  <text class="k ks" x="36" y="242">对每个操作发送对应事件：provide / provide_error / unprovide / dispose</text>

  <g>
    <line x1="140" y1="78" x2="140" y2="200" stroke="#6366f1" stroke-width="1.4" marker-end="url(#ka)"/>
    <line x1="340" y1="78" x2="340" y2="200" stroke="#6366f1" stroke-width="1.4" marker-end="url(#ka)"/>
    <line x1="540" y1="78" x2="540" y2="200" stroke="#6366f1" stroke-width="1.4" marker-end="url(#ka)"/>
    <line x1="740" y1="78" x2="740" y2="200" stroke="#6366f1" stroke-width="1.4" marker-end="url(#ka)"/>
  </g>

  <g>
    <rect x="88" y="104" width="104" height="40" rx="6" fill="#fff" stroke="#94a3b8" stroke-width="1.2"/>
    <text class="k km" x="100" y="129">PENDING</text>
    <rect x="288" y="104" width="104" height="40" rx="6" fill="#fff" stroke="#94a3b8" stroke-width="1.2"/>
    <text class="k km" x="300" y="129">ACTIVE</text>
    <rect x="488" y="104" width="104" height="40" rx="6" fill="#fff" stroke="#94a3b8" stroke-width="1.2"/>
    <text class="k km" x="500" y="129">PENDING</text>
    <rect x="688" y="104" width="104" height="40" rx="6" fill="#fff" stroke="#94a3b8" stroke-width="1.2"/>
    <text class="k km" x="700" y="129">ACTIVE</text>
  </g>

  <g>
    <rect x="88" y="146" width="104" height="38" rx="6" fill="#fff" stroke="#a5b4fc" stroke-width="1.2"/>
    <text class="k km" x="100" y="170">PENDING</text>
    <rect x="288" y="146" width="104" height="38" rx="6" fill="#fff" stroke="#a5b4fc" stroke-width="1.2"/>
    <text class="k km" x="300" y="170">ACTIVE</text>
    <rect x="488" y="146" width="104" height="38" rx="6" fill="#fff" stroke="#a5b4fc" stroke-width="1.2"/>
    <text class="k km" x="500" y="170">PENDING</text>
    <rect x="688" y="146" width="104" height="38" rx="6" fill="#fff" stroke="#a5b4fc" stroke-width="1.2"/>
    <text class="k km" x="700" y="170">ACTIVE</text>
  </g>

  <g>
    <text class="k kc" x="196" y="130">=</text>
    <text class="k kc" x="396" y="130">=</text>
    <text class="k kc" x="596" y="130">=</text>
    <text class="k kc" x="796" y="130">=</text>
  </g>

  <text class="k ks" x="36" y="284" font-size="11">任何一步不等即失败 → 内核实现与它的模型不可能悄悄漂移。开发中该用例当场抓出两处场景设计错误。</text>
</svg>
<figcaption>图 3 · 锁步一致性验证：同一串操作分别驱动「真实内核」与「由项目自己 FSM 引擎加载的模型」，逐步骤断言状态相等。</figcaption>
</figure>`;

D.tiers = `
<figure class="diagram">
<svg viewBox="0 0 900 380" role="img" aria-label="四档复用建议">
  <style>
    .z{font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
    .zl{font-size:12.5px;font-weight:700;fill:#0f172a}
    .zs{font-size:10.5px;fill:#475569}
    .zt{font-family:Consolas,"Cascadia Mono",monospace;font-size:10.5px;fill:#334155}
    .zb{font-size:15px;font-weight:800}
  </style>

  <rect x="16" y="14" width="868" height="80" rx="9" fill="#ecfdf5" stroke="#059669" stroke-width="1.8"/>
  <text class="z zb" x="32" y="42" fill="#047857">A</text>
  <text class="z zl" x="60" y="42">必做 · 高价值低风险（原型已验证）</text>
  <text class="z zs" x="60" y="62">A1 effect / Disposable 注册即可逆　　A2 Context 服务容器　　A3 inject 声明依赖　　A4 事件三模式 + 契约校验</text>
  <text class="z zt" x="60" y="81">直接消除 6 处模块级全局状态，并修掉「reset() 不清 bus」的真实 bug</text>

  <rect x="16" y="102" width="868" height="80" rx="9" fill="#fffbeb" stroke="#d97706" stroke-width="1.8"/>
  <text class="z zb" x="32" y="130" fill="#b45309">B</text>
  <text class="z zl" x="60" y="130">建议做 · 需要一次设计决策</text>
  <text class="z zs" x="60" y="150">B1 空根 + 分层 patch　　B2 fail-loud 分层　　B3 自省接口　　B4 运行时不变式　　B5 isolate 作用域</text>
  <text class="z zt" x="60" y="169">B1 采用最小侵入：保留 config.json，新增顶层 "patches" 段</text>

  <rect x="16" y="190" width="868" height="76" rx="9" fill="#f0f9ff" stroke="#0891b2" stroke-width="1.8"/>
  <text class="z zb" x="32" y="218" fill="#0e7490">C</text>
  <text class="z zl" x="60" y="218">可选 · 视产品方向</text>
  <text class="z zs" x="60" y="238">C1 自省暴露给 LLM Agent（对应 Cordis 的 ui-cordis）　　C2 config-only 热更新　　C3 用 ReactiveTracker 替换 _recheck</text>
  <text class="z zt" x="60" y="257">C1 的前置是 B3；且必须明说「动态插件不是安全边界」</text>

  <rect x="16" y="274" width="868" height="94" rx="9" fill="#fef2f2" stroke="#e11d48" stroke-width="1.8"/>
  <text class="z zb" x="32" y="302" fill="#9f1239">D</text>
  <text class="z zl" x="60" y="302">明确劝退 · 不移植</text>
  <text class="z zs" x="60" y="322">Proxy + trap　·　6 态 fiber + LOADING/UNLOADING　·　epoch 字符串指纹　·　模块级 HMR（依赖 Node internals）</text>
  <text class="z zs" x="60" y="340">Typert / RPC 类型图　·　vendored 框架层 + rescope + 21 条加固　·　双 SDK 投影同步　·　!!js 表达式条件装配</text>
  <text class="z zt" x="60" y="359">这些都是「fork 别人框架」或「TypeScript/多进程」带来的代价，不是收益</text>
</svg>
<figcaption>图 4 · 四档复用建议。核心判断标准：Cordis 的取舍是为「TypeScript + 多进程 + 多端 + fork 上游框架」付出的代价；本项目不承担这些约束，因此只取纪律，不取实现。</figcaption>
</figure>`;

const anchors = [
  ['第一层同构', D.isomorphism, 3],
  ['验证方式：锁步一致性', D.lockstep, 3],
  ['四档复用建议', D.tiers, 2],
  ['做法', D.lifecycle, 3],
];

for (const [needle, svg, depth] of anchors) {
  const re = new RegExp(`<h([1-3]) id="([^"]*)">`, 'g');
  let hit = -1, closeTag = '';
  let m;
  const want = slug(needle).replace(/[^\p{L}\p{N}-]/gu, '');
  while ((m = re.exec(html)) !== null) {
    if (Number(m[1]) === depth && m[2].includes(want)) {
      hit = m.index; closeTag = `</h${m[1]}>`; break;
    }
  }
  if (hit === -1) { console.error('ANCHOR NOT FOUND:', needle, 'depth', depth); continue; }
  const end = html.indexOf(closeTag, hit) + closeTag.length;
  html = html.slice(0, end) + svg + html.slice(end);
  console.log('DIAGRAM INSERTED after:', needle);
}

const toc = headings.map(h =>
  `<a class="toc-l${h.depth}" href="#${slug(h.text)}">${h.text}</a>`).join('\n');

const stats = [
  ['48 / 48', '内核断言通过'],
  ['6 → 0', '模块级全局状态'],
  ['5', '同构对照维度'],
  ['≈49 行', '可删除的重复代码'],
  ['966 行', '原型内核规模'],
];

const css = `
:root{
  --bg:#f8fafc; --panel:#fff; --ink:#0f172a; --muted:#475569; --faint:#94a3b8;
  --line:#e2e8f0; --accent:#4f46e5; --ok:#059669; --warn:#d97706; --bad:#e11d48;
  --code-bg:#f1f5f9;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Segoe UI","Microsoft YaHei",system-ui,-apple-system,"Noto Sans SC",sans-serif;
  font-size:15.5px;line-height:1.78;-webkit-font-smoothing:antialiased}
.layout{display:grid;grid-template-columns:296px minmax(0,1fr);max-width:1580px;margin:0 auto}
.side{position:sticky;top:0;height:100vh;overflow-y:auto;padding:26px 20px 60px;
  background:linear-gradient(180deg,#0b1220,#111c33);color:#cbd5e1}
.side::-webkit-scrollbar{width:8px}
.side::-webkit-scrollbar-thumb{background:#334155;border-radius:4px}
.side .brand{font-size:11px;letter-spacing:.16em;color:#818cf8;font-weight:700;text-transform:uppercase}
.side h1{font-size:16px;line-height:1.5;margin:8px 0 6px;color:#fff;font-weight:700}
.side .meta{font-size:11.5px;color:#64748b;line-height:1.75;margin-bottom:18px}
.side nav{display:flex;flex-direction:column;border-top:1px solid #24304a;padding-top:14px}
.side nav a{color:#94a3b8;text-decoration:none;font-size:12.8px;padding:5px 8px;border-radius:6px;
  border-left:2px solid transparent;transition:.14s}
.side nav a:hover{color:#fff;background:#1e293b;border-left-color:#6366f1}
.side nav a.toc-l1{color:#e2e8f0;font-weight:650;margin-top:8px}
.side nav a.toc-l2{padding-left:16px}
.side nav a.toc-l2::before{content:"·";color:#475569;margin-right:6px}
main{padding:52px 68px 120px;min-width:0;background:var(--panel)}
.hero{border:1px solid var(--line);border-radius:16px;padding:30px 34px;margin-bottom:34px;
  background:linear-gradient(135deg,#ecfdf5 0%,#eef2ff 55%,#fdf4ff 100%)}
.hero .kicker{font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:#047857;font-weight:700}
.hero h1{margin:10px 0 4px;font-size:29px;line-height:1.32;letter-spacing:-.01em}
.hero .sub{margin:0 0 10px;font-size:15px;color:#312e81;font-weight:600}
.hero p{margin:0;color:var(--muted);font-size:14.5px}
.chips{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
.chip{background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 14px;
  display:flex;align-items:baseline;gap:8px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.chip b{font-size:15.5px;color:var(--accent);font-weight:700;font-variant-numeric:tabular-nums}
.chip span{font-size:11.5px;color:var(--muted)}
h1,h2,h3,h4{line-height:1.4;letter-spacing:-.005em}
h2{font-size:23px;margin:60px 0 18px;padding-bottom:12px;border-bottom:2px solid var(--line);position:relative}
h2::before{content:"";position:absolute;left:0;bottom:-2px;width:74px;height:2px;background:var(--accent)}
h3{font-size:18px;margin:36px 0 12px;color:#1e293b}
h4{font-size:15.5px;margin:26px 0 10px;color:#334155}
.anchor{opacity:0;margin-left:8px;color:var(--faint);text-decoration:none;font-weight:400;font-size:.8em}
h2:hover .anchor,h3:hover .anchor{opacity:1}
p{margin:12px 0}
a{color:var(--accent);text-decoration:none;border-bottom:1px solid #c7d2fe}
a:hover{border-bottom-color:var(--accent)}
strong{font-weight:680;color:#0b1220}
hr{border:0;border-top:1px solid var(--line);margin:44px 0}
ul,ol{padding-left:26px;margin:12px 0}
li{margin:5px 0}
code{font-family:Consolas,"Cascadia Mono",monospace;font-size:.875em;background:var(--code-bg);
  padding:2px 6px;border-radius:5px;color:#9d174d;border:1px solid #e2e8f0}
pre{background:#0f172a;color:#e2e8f0;border-radius:12px;padding:18px 20px;overflow-x:auto;
  font-size:12.6px;line-height:1.72;margin:18px 0;border:1px solid #1e293b;box-shadow:0 2px 10px rgba(15,23,42,.10)}
pre code{background:none;border:0;padding:0;color:#e2e8f0;font-size:inherit;white-space:pre}
pre::-webkit-scrollbar{height:9px}
pre::-webkit-scrollbar-thumb{background:#334155;border-radius:5px}
table{border-collapse:collapse;width:100%;margin:20px 0;font-size:13.5px;
  border:1px solid var(--line);border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(15,23,42,.05)}
th{background:#f1f5f9;text-align:left;padding:11px 14px;font-weight:680;color:#0f172a;
  border-bottom:2px solid var(--line)}
td{padding:10px 14px;border-bottom:1px solid #eef2f6;vertical-align:top;color:#1e293b}
tr:last-child td{border-bottom:0}
tbody tr:nth-child(2n){background:#fcfdfe}
tbody tr:hover{background:#f8fafc}
blockquote{margin:20px 0;padding:14px 20px;background:#f8fafc;border-left:4px solid var(--accent);
  border-radius:0 10px 10px 0;color:#334155}
blockquote p{margin:6px 0}
.diagram{margin:26px 0;padding:18px 16px 6px;background:#fcfdff;border:1px solid var(--line);
  border-radius:14px;box-shadow:0 1px 4px rgba(15,23,42,.05)}
.diagram svg{width:100%;height:auto;display:block}
.diagram figcaption{font-size:12.4px;color:var(--muted);margin-top:12px;padding-top:12px;
  border-top:1px dashed var(--line);line-height:1.65;text-align:center}
.diagram code{font-size:.9em}
.foot{margin-top:70px;padding-top:22px;border-top:1px solid var(--line);font-size:12.4px;color:var(--faint);line-height:1.8}
@media (max-width:1200px){
  .layout{grid-template-columns:1fr}
  .side{position:static;height:auto;padding:20px 22px}
  .side nav{max-height:280px;overflow-y:auto}
  main{padding:32px 22px 80px}
  .hero{padding:22px}.hero h1{font-size:23px}
  table{font-size:12.6px}
}
@media print{
  .side{display:none}.layout{grid-template-columns:1fr;max-width:none}main{padding:0}
  pre{background:#f8fafc;color:#0f172a;border-color:#cbd5e1}pre code{color:#0f172a}
  h2{page-break-after:avoid}.diagram{page-break-inside:avoid}
}
`;

const doc = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>zhuangtaiji × Cordis 内核重构方案</title>
<style>${css}</style>
</head>
<body>
<div class="layout">
  <aside class="side">
    <div class="brand">Kernel Refactor Proposal</div>
    <h1>zhuangtaiji × Cordis<br>内核重构方案</h1>
    <div class="meta">
      论状态机项目与 Cordis 内核的同构性<br>
      目标 commit fccb8e6 · 6,660 行 Python<br>
      附可运行原型（48 项断言全通过）
    </div>
    <nav>${toc}</nav>
  </aside>
  <main>
    <div class="hero">
      <div class="kicker">Isomorphism · Not Analogy</div>
      <h1>zhuangtaiji × Cordis 内核重构方案</h1>
      <p class="sub">Cordis 的 Fiber 本身就是一台状态机；而本项目的差分引擎与 Cordis 的 epoch 是同一种技术。</p>
      <p>因此重构不是"给 Python 项目套一个 TypeScript 框架"，而是<b>给一个已具备 Cordis 四分之三要素的系统补上 Context，并把所有接线从"单向"改成"可逆"</b>。并且——内核自身的生命周期可以用项目自己的状态机引擎来验证。</p>
      <div class="chips">
        ${stats.map(([b, s]) => `<div class="chip"><b>${b}</b><span>${s}</span></div>`).join('\n        ')}
      </div>
    </div>
    ${html}
    <div class="foot">
      基于对 Cordis 参考实现 <code>deepseek-harness</code>（DSH）源码的研究与对 <code>zhuangtaiji</code>（commit <code>fccb8e6</code>）的实测。<br>
      交付物：本方案 + 可运行原型 <code>prototype/</code>（<code>python prototype/test_kernel.py</code> 48/48 通过）。原型为设计验证，非生产代码，局限见 §10.4。
    </div>
  </main>
</div>
</body>
</html>`;

fs.writeFileSync(outPath, doc, 'utf8');
console.log('WROTE', outPath, (doc.length / 1024).toFixed(1) + ' KB');
