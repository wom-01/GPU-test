/* 聚算并网 · 接口中心 —— 页面交互
 * 配置由服务端注入 #docs-cfg（JSON）：{mode: "demo"|"dgm", demoUser?, demoPass?}
 */
(function () {
  'use strict';

  const CFG = JSON.parse(document.getElementById('docs-cfg').textContent || '{}');
  const IS_DEMO = CFG.mode === 'demo';
  const API = location.origin + '/api/v1';
  const TOKEN_KEY = 'jusuan_docs_token';
  const $ = (id) => document.getElementById(id);

  let ui = null;           // SwaggerUI 实例
  let token = null;        // {value, expireAt(ms)}
  const TTL_OPTIONS = [
    { label: '长期有效（推荐）', hours: 876000 },   // 服务端配置为无时效
  ];
  let ttlHours = 876000;
  let hosts = [];
  let poolFilter = '全部';

  // ── 工具 ──────────────────────────────────────────────────────────
  function toast(msg) {
    const t = $('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('show'), 1800);
  }

  function copy(text, msg) {
    const done = () => toast(msg || '已复制');
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done);
      return;
    }
    // HTTP 环境下 clipboard API 不可用，退回 execCommand
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { toast('复制失败，请手动选择'); }
    ta.remove();
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function post(path, body, withAuth) {
    const headers = { 'Content-Type': 'application/json;charset=UTF-8' };
    if (withAuth && token) headers.Authorization = 'Bearer ' + token.value;
    const r = await fetch(API + path, { method: 'POST', headers, body: JSON.stringify(body) });
    let d = null;
    try { d = await r.json(); } catch (e) { /* 非 JSON */ }
    if (r.status === 401) { setToken(null); throw new Error('令牌无效或已过期，请重新获取'); }
    if (r.status === 429) {
      const e = new Error('认证失败次数过多，请稍后再试');
      e.retryAfter = +(r.headers.get('Retry-After') || 60);
      throw e;
    }
    if (!d) throw new Error('服务返回异常（HTTP ' + r.status + '）');
    return d;
  }

  // ── 顶栏 ──────────────────────────────────────────────────────────
  $('baseUrl').textContent = API;
  $('baseUrlBtn').onclick = () => copy(API, '接口基址已复制');
  const env = $('envBadge');
  env.style.display = 'none';
  $('menuBtn').onclick = () => $('sidebar').classList.toggle('open');

  // ── 令牌 ──────────────────────────────────────────────────────────
  function parseTime(s) {               // "yyyy-MM-dd HH:mm:ss"（服务器本地时间）
    return s ? new Date(s.replace(' ', 'T')).getTime() : Date.now() + 876000 * 3600e3;
  }

  function setToken(t) {
    token = t;
    if (t) localStorage.setItem(TOKEN_KEY, JSON.stringify(t));
    else localStorage.removeItem(TOKEN_KEY);
    if (ui) {
      if (t) applyAuth(t.value);
      else ui.authActions.logout(['bearerAuth']);
    }
    renderToken();
  }

  // 把令牌写入 Swagger 的 bearerAuth，所有接口自动带 Authorization 头
  function applyAuth(value) {
    ui.authActions.authorize({
      bearerAuth: { name: 'bearerAuth', schema: { type: 'http', scheme: 'bearer' }, value },
    });
  }

  function renderToken() {
    const on = !!token;
    $('tokenBox').hidden = !on;
    $('authForm').hidden = on || IS_DEMO;
    $('authDemo').hidden = on || !IS_DEMO;
    const pill = $('tokenPill');
    pill.classList.toggle('on', on);
    if (on) {
      $('tokenVal').textContent = token.value;
    } else {
      pill.querySelector('span').textContent = '未认证';
      hosts = [];
      renderPool();
    }
    tick();
  }

  function tick() {
    if (!token) return;
    const left = token.expireAt - Date.now();
    if (left <= 0) { setToken(null); toast('令牌已过期，请重新获取'); return; }
    const h = Math.floor(left / 3600e3);
    const m = Math.floor(left % 3600e3 / 60e3);
    const s = Math.floor(left % 60e3 / 1e3);
    if (h > 8760) {
      $('tokenExp').textContent = '剩余：长期有效';
      $('tokenPill').querySelector('span').textContent = '已认证 · 长期';
      return;
    }
    const txt = (h ? h + ' 小时 ' : '') + m + ' 分 ' + String(s).padStart(2, '0') + ' 秒';
    $('tokenExp').textContent = '剩余 ' + txt;
    $('tokenPill').querySelector('span').textContent = '已认证 · ' + (h ? h + 'h' : '') + m + 'm';
  }
  setInterval(tick, 1000);

  async function login(username, password, btn) {
    $('authErr').hidden = true;
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = '获取中…';
    try {
      const d = await post('/authentication/token', { username, password, validHours: ttlHours }, false);
      if (d.code !== '0') throw new Error(d.message || '认证失败');
      setToken({ value: d.data.accessToken, expireAt: parseTime(d.data.expireAt) });
      toast('✅ 长期令牌已获取，并已应用到所有接口');
      loadPool();
    } catch (e) {
      if (e.retryAfter) {
        // 被临时锁定：按钮进入倒计时，避免盲目重复点击
        const until = Date.now() + e.retryAfter * 1000;
        btn.textContent = label;
        btn.disabled = true;
        const h = setInterval(() => {
          const left = Math.ceil((until - Date.now()) / 1000);
          if (left > 0) { btn.textContent = '请等待 ' + left + ' 秒'; return; }
          clearInterval(h);
          btn.disabled = false;
          btn.textContent = label;
          $('authErr').hidden = true;
        }, 1000);
        $('authErr').textContent = '口令错误次数过多，' + e.retryAfter + ' 秒后可重试（演示环境请直接点一键按钮）';
      } else {
        $('authErr').textContent = e.message;
      }
      $('authErr').hidden = false;
      return;
    }
    btn.disabled = false;
    btn.textContent = label;
  }

  function renderTtlChips() {
    ['ttlChips', 'ttlChipsDemo'].forEach((id) => {
      const box = $(id);
      if (!box) return;
      box.innerHTML = TTL_OPTIONS.map((o) =>
        '<button type="button" class="ttl-chip' + (o.hours === ttlHours ? ' on' : '') + '" data-h="' + o.hours + '">' +
        esc(o.label) + '</button>').join('');
      box.querySelectorAll('.ttl-chip').forEach((b) => {
        b.onclick = () => { ttlHours = +b.dataset.h; renderTtlChips(); };
      });
    });
  }
  renderTtlChips();

  $('authBtn').onclick = () => login($('authUser').value.trim(), $('authPass').value, $('authBtn'));
  $('authPass').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('authBtn').click(); });
  $('demoBtn').onclick = () => login(CFG.demoUser, CFG.demoPass, $('demoBtn'));
  $('copyToken').onclick = () => copy(token.value, '令牌已复制');
  $('clearToken').onclick = () => {
    setToken(null);
    toast('已清除令牌，请重新获取');
    $('sec-auth').scrollIntoView({ behavior: 'smooth' });
    if (IS_DEMO) setTimeout(() => $('demoBtn').focus(), 300);
  };

  // 从 JWT 里解出过期时间（authorize 弹窗里粘贴的令牌没有接口返回的 expireAt）
  function jwtExp(value) {
    try {
      const p = JSON.parse(atob(value.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      return p.exp ? p.exp * 1000 : Date.now() + 876000 * 3600e3;
    } catch (e) { return Date.now() + 876000 * 3600e3; }
  }

  // 双向同步：用户在 Swagger Authorize 弹窗里换成新令牌时，页面跟随采用
  function watchSwaggerAuth() {
    setInterval(() => {
      if (!ui) return;
      try {
        const sys = ui.getSystem ? ui.getSystem() : ui;
        const v = sys.authSelectors && sys.authSelectors.authorized &&
                  sys.authSelectors.authorized().getIn(['bearerAuth', 'value']);
        if (v && (!token || token.value !== v)) {
          token = { value: v, expireAt: jwtExp(v) };
          localStorage.setItem(TOKEN_KEY, JSON.stringify(token));
          renderToken();
          loadPool();
          toast('已采用新令牌');
        }
      } catch (e) { /* 结构变化时静默跳过 */ }
    }, 1000);
  }

  // ── 资源池 ────────────────────────────────────────────────────────
  const STATUS = { normal: ['ok', '可售'], maintenance: ['warn', '维护中'], abnormal: ['bad', '异常'] };

  async function loadPool() {
    if (!token) return;
    $('pool').innerHTML = '<div class="empty">正在调用 host/collect 加载资源…</div>';
    try {
      const d = await post('/compute/resource/host/collect', { scaleNum: 100, specification: {} }, true);
      if (d.code !== '0') throw new Error(d.message);
      hosts = d.data.hosts || [];
      renderPool();
    } catch (e) {
      $('pool').innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>';
    }
  }

  // 加速卡信息：GPU 优先，其次 NPU（昇腾等）
  function accel(sp) {
    if (sp.gpuModel) {
      return { label: [sp.gpuBrand === 'NVIDIA' ? '' : sp.gpuBrand, sp.gpuModel].filter(Boolean).join(' '),
               num: +sp.gpuNum || 0, mem: sp.gpuTotalMemory, fp16: sp.gpuFP16Computing };
    }
    if (sp.npuModel) {
      return { label: sp.npuModel.replace(/^Ascend\s*/i, '昇腾 '),
               num: +sp.npuPhysicalCardNum || 0, mem: sp.npuTotalMemory, fp16: null };
    }
    return { label: '通用算力', num: 0, mem: null, fp16: null };
  }
  const gpuLabel = (sp) => accel(sp).label;

  function renderPool() {
    const pool = $('pool');
    const filterBox = $('poolFilter');
    $('statHosts').textContent = token ? hosts.length : '—';
    $('statGpus').textContent = token ? hosts.reduce((n, h) => n + accel(h.specification).num, 0) : '—';

    if (!token) {
      filterBox.hidden = true;
      pool.innerHTML = '<div class="empty">获取令牌后自动加载 <code>host/collect</code> 实时资源</div>';
      return;
    }
    if (!hosts.length) {
      filterBox.hidden = true;
      pool.innerHTML = '<div class="empty">当前没有可售主机</div>';
      return;
    }

    const models = ['全部', ...new Set(hosts.map((h) => gpuLabel(h.specification)))];
    if (!models.includes(poolFilter)) poolFilter = '全部';
    filterBox.hidden = models.length <= 2;
    filterBox.innerHTML = models.map((m) =>
      '<button class="chip' + (m === poolFilter ? ' on' : '') + '" data-m="' + esc(m) + '">' + esc(m) + '</button>').join('');
    filterBox.querySelectorAll('.chip').forEach((b) => {
      b.onclick = () => { poolFilter = b.dataset.m; renderPool(); };
    });

    const list = poolFilter === '全部' ? hosts : hosts.filter((h) => gpuLabel(h.specification) === poolFilter);
    pool.innerHTML = list.map((h) => {
      const sp = h.specification;
      const ac = accel(sp);
      const [cls, txt] = STATUS[h.status] || ['warn', h.status];
      const spec = (k, v) => v ? '<div><span>' + k + '</span><b>' + esc(v) + '</b></div>' : '';
      return '<div class="host">' +
        '<div class="host-top"><div class="host-gpu">' + esc(gpuLabel(sp)) +
          (sp.gpuNum ? '<small>× ' + esc(sp.gpuNum) + '</small>' : '') + '</div>' +
          '<span class="tag ' + cls + '">' + txt + '</span></div>' +
        '<div class="host-name">' + esc(h.hostName) + ' · ' + esc(h.hostIp) + '</div>' +
        '<div class="host-room">📍 ' + esc(h.hostRoomName) + '</div>' +
        '<div class="host-specs">' +
          spec('显存', ac.mem && ac.mem + ' GB') +
          spec(ac.fp16 ? 'FP16' : '架构', ac.fp16 ? ac.fp16 + ' TF' : sp.cpuArch) +
          spec('CPU', sp.cpuNum && sp.cpuNum + ' 核') +
          spec('内存', sp.memorySize && sp.memorySize + ' GB') +
          spec('SSD', sp.ssdDiskSize && (sp.ssdDiskSize >= 1000 ? (sp.ssdDiskSize / 1000).toFixed(1) + ' TB' : sp.ssdDiskSize + ' GB')) +
          spec('带宽', sp.bandwidth && sp.bandwidth + ' Mbps') +
        '</div></div>';
    }).join('');
  }
  $('poolRefresh').onclick = () => token ? loadPool() : toast('请先获取令牌');

  // ── 业务流程 ──────────────────────────────────────────────────────
  const FLOW = [
    ['🔑', '认证', '口令换取长期令牌', '/api/v1/authentication/token'],
    ['📦', '资源上报', '按规格拉取可售主机', '/api/v1/compute/resource/host/collect'],
    ['📌', '预占', '锁定主机，防止超卖', '/api/v1/compute/resource/reserve/notify'],
    ['🚀', '开通', '异步受理，后台交付', '/api/v1/compute/resource/host/open'],
    ['⏱', '轮询结果', 'openCode 4→0，AES 凭证', '/api/v1/compute/resource/host/open/query'],
    ['📈', '监控与运维', '使用率采集 · 暂停/销户', '/api/v1/compute/resource/host/monitor/collect'],
  ];
  $('flow').innerHTML = FLOW.map((f, i) =>
    '<div class="flow-step" data-path="' + f[3] + '"><div class="flow-i">' + f[0] + '</div>' +
    '<div class="flow-t">' + (i + 1) + '. ' + f[1] + '</div><div class="flow-d">' + f[2] + '</div></div>').join('');
  $('flow').querySelectorAll('.flow-step').forEach((el) => { el.onclick = () => openOp(el.dataset.path); });

  // ── 跳转并展开指定接口 ────────────────────────────────────────────
  function openOp(path) {
    const span = document.querySelector('#swagger-ui .opblock-summary-path[data-path="' + path + '"]');
    if (!span) { $('sec-api').scrollIntoView(); return; }
    const block = span.closest('.opblock');
    if (!block.classList.contains('is-open')) {
      (block.querySelector('.opblock-summary-control') || block.querySelector('.opblock-summary')).click();
    }
    $('sidebar').classList.remove('open');
    setTimeout(() => {
      block.scrollIntoView({ behavior: 'smooth', block: 'start' });
      block.classList.add('flash');
      setTimeout(() => block.classList.remove('flash'), 1200);
    }, 60);
  }

  // ── 侧栏接口目录 ──────────────────────────────────────────────────
  function shortName(summary) {
    return (summary || '').split(/[：（(]/)[0];
  }

  function buildSidebar(spec) {
    const groups = {};
    Object.entries(spec.paths || {}).forEach(([path, methods]) => {
      Object.entries(methods).forEach(([method, op]) => {
        const tag = (op.tags || ['其他'])[0];
        (groups[tag] = groups[tag] || []).push({ path, method, op });
      });
    });
    $('statApis').textContent = Object.values(groups).reduce((n, g) => n + g.length, 0);
    $('sideApis').innerHTML = Object.entries(groups).map(([tag, ops]) =>
      '<div class="side-tag">' + esc(tag) + '</div>' + ops.map((o) =>
        '<a class="side-link side-api" data-path="' + esc(o.path) + '" title="' + esc(o.path) + '">' +
        '<span class="method">' + o.method.toUpperCase() + '</span>' + esc(shortName(o.op.summary)) +
        (o.op.security ? '<span class="lock">🔒</span>' : '') + '</a>').join('')).join('');
    document.querySelectorAll('.side-api').forEach((a) => { a.onclick = () => openOp(a.dataset.path); });
  }

  // 侧栏“快速开始”高亮当前所在区块
  const sections = ['sec-auth', 'sec-pool', 'sec-flow', 'sec-api'].map((id) => $(id));
  const quickLinks = document.querySelectorAll('.side-group:first-child .side-link');
  window.addEventListener('scroll', () => {
    let idx = 0;
    sections.forEach((s, i) => { if (s.getBoundingClientRect().top < 140) idx = i; });
    quickLinks.forEach((a, i) => a.classList.toggle('active', i === idx));
  }, { passive: true });
  document.querySelectorAll('.side-link[href^="#"]').forEach((a) => {
    a.addEventListener('click', () => $('sidebar').classList.remove('open'));
  });

  // ── 启动 ──────────────────────────────────────────────────────────
  try {
    const saved = JSON.parse(localStorage.getItem(TOKEN_KEY) || 'null');
    if (saved && saved.expireAt > Date.now()) token = saved;
  } catch (e) { /* 忽略损坏的缓存 */ }
  renderToken();

  // ── Swagger UI 界面文案汉化（授权弹窗等硬编码英文）──────────────
  (function () {
    const zhMap = new Map([
      ['Available authorizations', '可用授权'],
      ['Authorized', '已授权'],
      ['Authorize', '授权'],
      ['Logout', '登出'],
      ['Close', '关闭'],
      ['Value', '值'],
      ['bearerAuth (http, Bearer)', 'Bearer 令牌认证'],
      ['Available values', '可用值'],
    ]);
    const fix = (root) => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = walker.nextNode())) {
        const t = n.nodeValue.trim();
        if (zhMap.has(t)) n.nodeValue = zhMap.get(t);
      }
      // 隐藏静态 Responses 标题（实测结果区 live-responses-table 不受影响）
      document.querySelectorAll('.swagger-ui .opblock h4.opblock-title').forEach((h) => {
        if (h.textContent.trim() === 'Responses') h.style.display = 'none';
      });
    };
    fix(document.body);
    new MutationObserver(() => fix(document.body))
      .observe(document.body, { childList: true, subtree: true });
  })();

  fetch('/openapi.json').then((r) => r.json()).then((spec) => {
    buildSidebar(spec);
    ui = SwaggerUIBundle({
      spec,
      dom_id: '#swagger-ui',
      deepLinking: false,
      docExpansion: 'list',            // 分组展开、接口折叠
      defaultModelsExpandDepth: -1,
      displayRequestDuration: true,
      filter: true,
      tryItOutEnabled: true,           // 展开即可填参调试，少点一次
      presets: [SwaggerUIBundle.presets.apis],
      onComplete: () => { if (token) applyAuth(token.value); watchSwaggerAuth(); },
    });
  }).catch((e) => {
    $('swagger-ui').innerHTML = '<div class="empty">接口文档加载失败：' + esc(e.message) + '</div>';
    $('sideApis').innerHTML = '<div class="side-loading">加载失败</div>';
  });

  if (token) loadPool();
})();
