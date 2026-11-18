/* 落在面板上的效果。
   下雨：打在面板上沿的雨滴溅起一小团很软的水雾；面板的玻璃面上凝着一颗颗很淡的小水珠，少数几颗会慢慢往下滑一小段。
   下雪：雪花落在面板上沿慢慢积起一层雪，积满后偶尔滑落一块。
   做法：每块面板的上沿放一条画布，下雨时玻璃面上再盖一张；只画这些画布，不重画整个页面。
   用法：PanelFx.set(面板元素的数组, 'rain' | 'snow' | '', 雨的大小)。雨的大小 1 是中雨，2 是大雨 */
(function () {
'use strict';

const RISE = 46;      // 上沿那条画布在面板上沿之上的高度：落下的雨滴、溅起的水雾、积雪画在这一段
const SINK = 64;      // 上沿那条画布在面板上沿之下的高度：滑落的雪块画在这一段
const COL = 3;        // 积雪按 3 像素一列记厚度
const TALL = 90;      // 高度不到这个数的小面板（地点切换那条胶囊等）上，水珠只停着不往下滑
const BEAD_AREA = 1100;   // 每这么多平方像素的玻璃面上大约凝一颗水珠

const items = new Map();   // 面板元素 → 这块面板的画布和当前的水珠、水雾、积雪
let mode = '', level = 1, raf = 0, last = 0;
let clock = 0;        // 效果自己的时间（毫秒），每画一帧往前走一点；积雪多久滑落一次、亮点怎么闪都按它算

const rnd = (a, b) => a + Math.random() * (b - a);
const smooth = (a, b, v) => { const t = Math.min(1, Math.max(0, (v - a) / (b - a))); return t * t * (3 - 2 * t); };

const STYLE = `
.panel-fx { position: absolute; left: 0; width: 100%; z-index: 2; pointer-events: none; }
.panel-fx.top { top: -${RISE}px; height: ${RISE + SINK}px; }
.panel-fx.face { top: 0; height: 100%; }`;
let styled = false;

/* 面板上沿在横向位置 x 处比最高点低多少：中间一段是 0，两头圆角的地方往下弯 */
function edgeDrop(it, x) {
  const d = Math.min(x, it.w - x);
  return d >= it.r ? 0 : it.r - Math.sqrt(Math.max(0, it.r * it.r - (it.r - d) * (it.r - d)));
}
/* 点 (x, y) 在不在面板的玻璃面上（y 从面板上沿算起），pad 是离边缘至少留多少像素；四个圆角以外的地方不算 */
function inFace(it, x, y, pad) {
  if (x < pad || x > it.w - pad || y < pad || y > it.h - pad) return false;
  const dx = Math.max(0, it.r - Math.min(x, it.w - x)), dy = Math.max(0, it.r - Math.min(y, it.h - y));
  return dx === 0 || dy === 0 || dx * dx + dy * dy <= (it.r - pad) * (it.r - pad);
}

function makeCanvas(el, cls) {
  const c = document.createElement('canvas');
  c.className = 'panel-fx ' + cls; c.setAttribute('aria-hidden', 'true');
  el.appendChild(c);
  return { c, g: c.getContext('2d') };
}
/* 盖在玻璃面上的那张画布只有下雨时才按实际大小开，其余时候缩成 1 像素，不白占显存 */
function resize(it) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  it.w = it.el.clientWidth; it.h = it.el.clientHeight;
  it.r = Math.min(parseFloat(getComputedStyle(it.el).borderTopLeftRadius) || 0, it.h / 2);
  it.tall = it.h >= TALL;
  for (const [layer, h] of [[it.top, mode ? RISE + SINK : 0], [it.face, mode === 'rain' ? it.h : 0]]) {
    layer.c.width = h ? Math.max(1, Math.round(it.w * dpr)) : 1; layer.c.height = h ? Math.round(h * dpr) : 1;
    layer.g.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  it.falling = []; it.spray = []; it.beads = []; it.seeded = false; it.wait = 0;
  it.heap = null; it.flakes = []; it.chunks = []; it.puffs = [];
}
const watcher = new ResizeObserver(list => list.forEach(e => { const it = items.get(e.target); if (it && (it.w !== e.target.clientWidth || it.h !== e.target.clientHeight)) resize(it); }));

function attach(el) {
  const it = { el, top: makeCanvas(el, 'top'), face: makeCanvas(el, 'face'), w: 0, h: 0, r: 0 };
  items.set(el, it); resize(it); watcher.observe(el);
}
function detach(el) {
  const it = items.get(el);
  watcher.unobserve(el); it.top.c.remove(); it.face.c.remove(); items.delete(el);
}

/* ====================== 雨 ====================== */
/* 水珠和水雾的样子提前画成几张小图，用的时候按大小缩放贴上去。
   水珠有四种不太圆的形状，外加一种上尖下圆的（正在往下滑的水珠用）。
   画得很淡：左上比面板略深、右下略亮，四周一圈很细的边，像玻璃上一个个小鼓包，不抢文字。
   水雾是一个边缘虚掉的白色圆点 */
let sprites = null;
function makeSprites() {
  const bead = shape => {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    g.save(); g.shadowColor = 'rgba(0,8,30,.2)'; g.shadowBlur = 5; g.shadowOffsetY = 2; g.fillStyle = 'rgba(10,22,52,.07)'; g.fill(shape); g.restore();
    g.save(); g.clip(shape);
    let grad = g.createLinearGradient(14, 10, 50, 56);
    grad.addColorStop(0, 'rgba(6,14,40,.24)'); grad.addColorStop(.5, 'rgba(10,22,52,.06)'); grad.addColorStop(1, 'rgba(255,255,255,.13)');
    g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
    grad = g.createRadialGradient(37, 44, 0, 36, 42, 17);
    grad.addColorStop(0, 'rgba(255,255,255,.2)'); grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
    g.restore();
    grad = g.createLinearGradient(14, 10, 50, 56);
    grad.addColorStop(0, 'rgba(4,10,30,.32)'); grad.addColorStop(.5, 'rgba(120,140,180,.08)'); grad.addColorStop(1, 'rgba(255,255,255,.34)');
    g.strokeStyle = grad; g.lineWidth = 1.6; g.stroke(shape);
    return c;
  };
  /* 一个轮廓有点凹凸的圆：半径随角度略微变大变小，k 不同凹凸的位置就不同 */
  const blob = k => {
    const shape = new Path2D();
    for (let i = 0; i <= 40; i++) {
      const t = i / 40 * Math.PI * 2, r = 22 * (1 + .1 * Math.sin(2 * t + k * 1.7) + .07 * Math.sin(3 * t + k * 2.9 + 1));
      shape.lineTo(32 + Math.cos(t) * r * .93, 33 + Math.sin(t) * r);
    }
    shape.closePath();
    return shape;
  };
  const tear = new Path2D();
  tear.moveTo(32, 6); tear.bezierCurveTo(35, 18, 54, 26, 54, 38); tear.arc(32, 38, 22, 0, Math.PI); tear.bezierCurveTo(10, 26, 29, 18, 32, 6); tear.closePath();
  const dot = document.createElement('canvas'); dot.width = dot.height = 32;
  const g = dot.getContext('2d'), soft = g.createRadialGradient(16, 16, 0, 16, 16, 16);
  soft.addColorStop(0, 'rgba(255,255,255,1)'); soft.addColorStop(.45, 'rgba(255,255,255,.75)'); soft.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = soft; g.fillRect(0, 0, 32, 32);
  sprites = { beads: [bead(blob(0)), bead(blob(1)), bead(blob(2)), bead(blob(3)), bead(tear)], dot };
}

/* 一滴雨打在面板上沿：溅起十来颗细小的水珠，往上、往两边散开一小团，很快落回去 */
function burst(it, x, y, big) {
  for (let i = 7 + (Math.random() * 7 | 0) + (level > 1 ? 2 : 0); i > 0; i--) {
    const a = -Math.PI / 2 + (Math.random() - .5) * 2.3, v = rnd(18, 95) * (.7 + big * .5), small = Math.random();
    it.spray.push({ x: x + rnd(-4, 4), y: y - rnd(0, 2), vx: Math.cos(a) * v - 6, vy: Math.sin(a) * v, t: 0, life: rnd(.45, .95), r: .7 + small * small * 1.2, a: rnd(.2, .55) });
  }
}
/* 在玻璃面上随机找个位置凝一颗水珠。age 给的是它已经存在了多久：刚开始下雨时先铺上一批"已经待了一会儿"的，面板不会是空的 */
function addBead(it, age) {
  for (let tries = 0; tries < 4; tries++) {
    const x = rnd(4, it.w - 4), y = rnd(4, it.h - 4), big = Math.random();
    if (!inFace(it, x, y, 4)) continue;
    /* 高面板上有一小部分水珠是会往下滑的：等一会儿，再走走停停地滑一小段 */
    const creep = it.tall && Math.random() < .12 ? { wait: rnd(1, 4), left: rnd(25, 80), v: rnd(6, 18), phase: rnd(0, 6) } : null;
    it.beads.push({ x, y, r: 1.5 + big * big * 2.3, kind: Math.random() * 4 | 0, wide: rnd(.82, 1.12), t: age || 0, life: rnd(6, 14), creep });
    return;
  }
}
/* 玻璃面上的水珠变化很慢，一秒只需要画十几次 */
function stepBeads(it, dt) {
  const g = it.face.g, want = Math.min(240, it.w * it.h / BEAD_AREA) * (level > 1 ? 1.3 : 1);
  if (!it.seeded) { it.seeded = true; for (let i = want * .7; i > 0; i--) addBead(it, rnd(0, 5)); }
  let n = want / 9 * dt;
  while (n > 0) { if ((n >= 1 || Math.random() < n) && it.beads.length < want * 1.2) addBead(it); n -= 1; }
  g.clearRect(0, 0, it.w, it.h);
  it.beads = it.beads.filter(b => !b.gone && (b.t += dt) < b.life);
  for (const b of it.beads) {
    const c = b.creep;
    if (c && b.t > c.wait && c.left > 0) {
      const d = c.v * (.15 + .85 * Math.pow(Math.abs(Math.sin(b.t * 1.7 + c.phase)), 2)) * dt;
      b.y += d; c.left -= d; b.kind = 4;
      if (b.y > it.h - b.r - 3) c.left = 0;
      /* 往下滑的路上碰到比自己小的水珠，就并进来 */
      for (const o of it.beads) {
        if (o === b || o.gone || o.r > b.r) continue;
        const dx = o.x - b.x, dy = o.y - b.y, reach = (o.r + b.r) * .8;
        if (dx * dx + dy * dy < reach * reach) { b.r = Math.min(4.6, Math.sqrt(b.r * b.r + o.r * o.r * .7)); o.gone = true; }
      }
    }
    if (b.gone) continue;
    /* 慢慢显出来，待几秒，最后一秒多慢慢淡掉 */
    const size = b.r * 2 * 64 / 48;
    g.globalAlpha = smooth(0, .7, b.t) * (1 - smooth(b.life - 1.4, b.life, b.t));
    g.drawImage(sprites.beads[b.kind], b.x - size * b.wide / 2, b.y - size / 2, size * b.wide, size);
  }
  g.globalAlpha = 1;
}

function stepRain(it, dt) {
  if (!sprites) makeSprites();
  const g = it.top.g, heavy = level > 1, lean = heavy ? .31 : .19;   // lean：雨丝每落下 1 像素往左偏多少，跟背景里的雨丝一个方向
  /* 每 100 像素宽的上沿，每秒落下 2.6 滴（大雨 4.2 滴） */
  let n = (heavy ? 4.2 : 2.6) * it.w / 100 * dt;
  while (n > 0) {
    if (n >= 1 || Math.random() < n) { const x = rnd(it.r * .5, it.w - it.r * .5); it.falling.push({ x, y: RISE + edgeDrop(it, x), p: 0, speed: rnd(11, 15), big: Math.random() }); }
    n -= 1;
  }
  g.clearRect(0, 0, it.w, RISE + SINK);
  g.lineCap = 'round';
  /* 正在落下的雨滴：一根上头淡、下头亮的短雨丝，飞到面板上沿就没了 */
  for (const o of it.falling) {
    o.p += o.speed * dt;
    const d = (RISE + 4) * (1 - Math.min(1, o.p)), tail = Math.min(20, RISE + 4 - d);
    const x0 = o.x + (d + tail) * lean, y0 = o.y - d - tail, x1 = o.x + d * lean, y1 = o.y - d, streak = g.createLinearGradient(x0, y0, x1, y1);
    streak.addColorStop(0, 'rgba(235,243,255,0)'); streak.addColorStop(1, 'rgba(235,243,255,.6)');
    g.strokeStyle = streak; g.lineWidth = 1.1 + o.big * .5;
    g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
    if (o.p >= 1) burst(it, o.x, o.y, o.big);
  }
  it.falling = it.falling.filter(o => o.p < 1);
  /* 溅起的水雾：一颗颗边缘虚掉的小圆点，越飞越慢，落回上沿就没了 */
  it.spray = it.spray.filter(o => {
    if ((o.t += dt) >= o.life) return false;
    o.vy += 200 * dt; o.vx *= 1 - .8 * dt; o.x += o.vx * dt; o.y += o.vy * dt;
    if (o.vy > 0 && o.y > RISE + edgeDrop(it, o.x)) return false;
    const size = o.r * 3.2;
    g.globalAlpha = o.a * (1 - smooth(.55, 1, o.t / o.life));
    g.drawImage(sprites.dot, o.x - size / 2, o.y - size / 2, size, size);
    return true;
  });
  g.globalAlpha = 1;

  it.wait += dt;
  if (it.wait >= .066) { stepBeads(it, it.wait); it.wait = 0; }
}

/* ====================== 雪 ====================== */
/* 这块面板最多积多厚：面板越矮积得越薄；也可以在面板上写 data-snow="像素数" 直接指定 */
const snowCap = it => +it.el.dataset.snow || Math.min(14, Math.max(4.5, it.el.clientHeight * .12));
function startSnow(it) {
  const n = Math.ceil(it.w / COL) + 1, cap = snowCap(it), a = rnd(0, 9), b = rnd(0, 9);
  it.cap = cap; it.heap = new Float32Array(n); it.limit = new Float32Array(n);
  /* limit 是每一列最多能积多厚：两头圆角的地方挂不住雪，往两头逐渐减到 0；中间也有高有低，积出来才不是一条直线 */
  for (let i = 0; i < n; i++) {
    const x = i * COL, wave = .72 + .17 * Math.sin(x / 47 + a) + .11 * Math.sin(x / 19 + b);
    it.limit[i] = cap * wave * smooth(0, Math.max(6, it.r * .95), Math.min(x, it.w - x));
    it.heap[i] = it.limit[i] * .3;
  }
  it.lipA = rnd(0, 9); it.lipB = rnd(0, 9);
  /* 雪面上细小的起伏：每一列在雪堆厚度之外再高出或低下去一点点，雪面才不是一条光滑的曲线 */
  const p1 = rnd(0, 9), p2 = rnd(0, 9);
  it.bump = Float32Array.from({ length: n }, (_, i) => .5 * Math.sin(i * COL / 5.3 + p1) + .35 * Math.sin(i * COL / 2.7 + p2) + rnd(-.2, .2));
  /* 雪面上固定的几处小凹坑和几颗会一闪一闪的亮点 */
  it.dents = Array.from({ length: Math.ceil(it.w / 46) }, () => ({ x: rnd(0, it.w), k: rnd(.25, .8), r: rnd(2.5, 5.5) }));
  it.sparks = Array.from({ length: Math.max(2, Math.round(it.w / 64)) }, () => ({ x: rnd(0, it.w), k: rnd(.2, .7), speed: rnd(.7, 1.9), phase: rnd(0, 6) }));
  it.slideAt = clock + rnd(7000, 13000);
}
/* 积得差不多满的地方滑落一块：这一段雪一下子变薄，掉下去的雪变成一把碎雪块和一小团雪雾 */
function slide(it) {
  const h = it.heap, n = h.length;
  for (let tries = 0; tries < 8; tries++) {
    const c = Math.random() * n | 0, half = 5 + (Math.random() * 8 | 0);
    if (h[c] < 4 || h[c] < it.limit[c] * .8) continue;
    for (let i = Math.max(0, c - half); i <= Math.min(n - 1, c + half); i++) {
      const f = smooth(1, .15, Math.abs(i - c) / half), lost = h[i] * .72 * f, x = i * COL, y = RISE + edgeDrop(it, x);
      h[i] -= lost;
      if (lost > .8 && Math.random() < .7) it.chunks.push({ x: x + rnd(0, COL), y: y - rnd(0, lost), vx: rnd(-17, 9), vy: rnd(6, 36), r: rnd(.9, 2.6), t: 0, life: rnd(.7, 1.3) });
    }
    for (let k = 0; k < 3; k++) it.puffs.push({ x: c * COL + rnd(-half, half) * COL, y: RISE + rnd(0, 5), r: rnd(5, 11), t: 0, life: rnd(.6, .95) });
    return;
  }
}
function stepSnow(it, dt, now) {
  if (!it.heap) startSnow(it);
  const g = it.top.g, h = it.heap, n = h.length, cap = it.cap, t = now / 1000;
  /* 每 100 像素宽每秒落下 1 片雪花 */
  let spawn = it.w / 100 * dt;
  while (spawn > 0) { if (spawn >= 1 || Math.random() < spawn) it.flakes.push({ x: rnd(-6, it.w + 14), y: -2, vx: rnd(-13, -4), vy: rnd(22, 46), r: rnd(.9, 2.1), phase: rnd(0, 6), swing: rnd(.8, 2) }); spawn -= 1; }
  /* 雪花碰到雪面就并进雪堆：落点附近几列各长高一点，本来就能积得厚的地方长得多一些 */
  it.flakes = it.flakes.filter(f => {
    f.y += f.vy * dt; f.x += (f.vx + Math.sin(t * f.swing + f.phase) * 9) * dt;
    if (f.x < -8 || f.x > it.w + 16) return false;
    const c = Math.min(n - 1, Math.max(0, Math.round(f.x / COL)));
    if (f.y < RISE + edgeDrop(it, f.x) - h[c] - .5) return true;
    for (let k = -3; k <= 3; k++) { const i = c + k; if (i >= 0 && i < n) h[i] = Math.min(it.limit[i], h[i] + f.r * .7 * Math.exp(-k * k / 4) * it.limit[i] / cap); }
    return false;
  });
  /* 没画出来的细雪也在落：整体再慢慢长一点；相邻几列互相匀一匀，雪堆才是圆滑的 */
  const even = Math.min(.5, dt * 3);
  for (let i = 1; i < n - 1; i++) h[i] = Math.min(it.limit[i], h[i] + ((h[i - 1] + h[i + 1]) / 2 - h[i]) * even + it.limit[i] * .012 * dt);
  if (now > it.slideAt) { slide(it); it.slideAt = now + rnd(5000, 12000); }

  g.clearRect(0, 0, it.w, RISE + SINK);
  const top = i => RISE + edgeDrop(it, i * COL) - h[i] - it.bump[i] * Math.min(1, h[i] / 4) * .8;
  /* 雪堆的下沿：盖过面板上沿再往下垂一点，垂多少有长有短，像雪檐 */
  const lip = i => RISE + edgeDrop(it, i * COL) + Math.min(h[i] * .5, 1 + 2.8 * (.5 + .5 * Math.sin(i * COL / 11 + it.lipA)) * (.5 + .5 * Math.sin(i * COL / 29 + it.lipB)));
  const body = new Path2D(), crest = new Path2D();
  body.moveTo(0, lip(0)); crest.moveTo(0, top(0));
  for (let i = 0; i < n - 1; i++) { const mx = (i + .5) * COL, my = (top(i) + top(i + 1)) / 2; body.quadraticCurveTo(i * COL, top(i), mx, my); crest.quadraticCurveTo(i * COL, top(i), mx, my); }
  for (let i = n - 1; i >= 0; i--) body.lineTo(i * COL, lip(i));
  body.closePath();
  /* 雪堆本体：顶上最白，越往下越带一点蓝灰；下面在玻璃上落一道淡淡的影子 */
  const fill = g.createLinearGradient(0, RISE - cap, 0, RISE + 4);
  fill.addColorStop(0, '#fff'); fill.addColorStop(.55, 'rgb(244,248,253)'); fill.addColorStop(1, 'rgb(208,221,240)');
  g.save();
  g.fillStyle = fill; g.shadowColor = 'rgba(8,22,54,.34)'; g.shadowBlur = 7; g.shadowOffsetY = 3; g.fill(body);
  /* 雪面外面再晕开一圈很淡的白，边缘看起来是松软的 */
  g.shadowColor = 'rgba(255,255,255,.8)'; g.shadowBlur = 3; g.shadowOffsetY = 0; g.strokeStyle = 'rgba(255,255,255,.4)'; g.lineWidth = 2; g.stroke(crest);
  g.restore();
  g.save(); g.clip(body);
  /* 光从左上方来：雪面往右下倾斜的坡是背光的，盖一层蓝灰色的影子，一个个雪包才鼓得起来 */
  for (let i = 4; i < n - 4; i++) {
    /* 两头圆角那一段雪本来就是斜着收薄的，不算背光坡 */
    const shade = Math.min(.3, (h[i - 4] - h[i + 4]) / (8 * COL) * 2.2) * smooth(it.r * .8, it.r * 1.8, Math.min(i * COL, it.w - i * COL));
    if (shade > .02) { g.fillStyle = `rgba(136,162,208,${shade})`; g.fillRect(i * COL - 1, RISE - h[i] - 3, COL, h[i] + 10 + it.r); }
  }
  /* 贴着面板的那一圈压一道蓝灰色的暗边，雪堆才有厚度 */
  const under = g.createLinearGradient(0, RISE - 3, 0, RISE + 4);
  under.addColorStop(0, 'rgba(150,172,210,0)'); under.addColorStop(1, 'rgba(150,172,210,.55)');
  g.fillStyle = under; g.fillRect(0, RISE - 3, it.w, 10 + it.r);
  for (const d of it.dents) {
    const c = Math.min(n - 1, Math.round(d.x / COL)); if (h[c] < 3) continue;
    const y = top(c) + d.k * h[c], dent = g.createRadialGradient(d.x, y, 0, d.x, y, d.r);
    dent.addColorStop(0, 'rgba(168,188,222,.26)'); dent.addColorStop(1, 'rgba(168,188,222,0)');
    g.fillStyle = dent; g.fillRect(d.x - d.r, y - d.r, d.r * 2, d.r * 2);
  }
  g.restore();
  /* 雪面最上面一道亮边 */
  g.strokeStyle = 'rgba(255,255,255,.95)'; g.lineWidth = 1; g.stroke(crest);
  for (const s of it.sparks) {
    const c = Math.min(n - 1, Math.round(s.x / COL)); if (h[c] < 3) continue;
    const a = Math.pow(.5 + .5 * Math.sin(t * s.speed + s.phase), 8); if (a < .05) continue;
    const y = top(c) + s.k * h[c];
    g.strokeStyle = `rgba(255,255,255,${a})`; g.lineWidth = .7;
    g.beginPath(); g.moveTo(s.x - 2.2, y); g.lineTo(s.x + 2.2, y); g.moveTo(s.x, y - 2.2); g.lineTo(s.x, y + 2.2); g.stroke();
  }
  /* 还在半空的雪花：刚进画布的头几像素逐渐显出来 */
  for (const f of it.flakes) { g.fillStyle = `rgba(255,255,255,${.92 * smooth(-2, 9, f.y)})`; g.beginPath(); g.arc(f.x, f.y, f.r, 0, 7); g.fill(); }
  /* 滑落的雪：一小团散开的雪雾，加上往下掉的碎雪块 */
  it.puffs = it.puffs.filter(o => (o.t += dt) < o.life);
  for (const o of it.puffs) {
    const p = o.t / o.life, r = o.r * (1 + p * 1.3), y = o.y + p * 16, puff = g.createRadialGradient(o.x, y, 0, o.x, y, r);
    puff.addColorStop(0, `rgba(255,255,255,${.3 * (1 - p)})`); puff.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = puff; g.fillRect(o.x - r, y - r, r * 2, r * 2);
  }
  it.chunks = it.chunks.filter(o => (o.t += dt) < o.life && o.y < RISE + SINK);
  for (const o of it.chunks) {
    o.vy += 340 * dt; o.x += o.vx * dt; o.y += o.vy * dt;
    g.fillStyle = `rgba(250,252,255,${.95 * (1 - smooth(.55, 1, o.t / o.life))})`; g.beginPath(); g.arc(o.x, o.y, o.r, 0, 7); g.fill();
  }
}

function step(dt) {
  clock += dt * 1000;
  items.forEach(it => { if (!it.w) return; if (mode === 'rain') stepRain(it, dt); else stepSnow(it, dt, clock); });
}
function frame(now) {
  raf = requestAnimationFrame(frame);
  step(Math.min(.05, (now - last) / 1000 || 0));
  last = now;
}
/* 调效果时用：一口气往后算若干秒，直接看到那时候的样子（比如积了一分钟的雪） */
function advance(seconds) { if (mode) for (let t = 0; t < seconds; t += 1 / 60) step(1 / 60); }

function set(elements, nextMode, nextLevel) {
  if (!styled) { document.head.insertAdjacentHTML('beforeend', `<style>${STYLE}</style>`); styled = true; }
  const keep = new Set(nextMode ? elements : []);
  [...items.keys()].forEach(el => { if (!keep.has(el) || !el.isConnected) detach(el); });
  keep.forEach(el => { if (!items.has(el)) attach(el); });
  level = nextLevel || 1;
  if (nextMode === mode) return;
  mode = nextMode;
  cancelAnimationFrame(raf);
  items.forEach(resize);
  if (mode) { last = performance.now(); raf = requestAnimationFrame(frame); }
}

window.PanelFx = { set, advance };
})();
