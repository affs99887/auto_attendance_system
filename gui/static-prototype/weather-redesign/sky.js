/* 天空背景。
   做法：云、雨、雪、星空、月亮各是一张图，页面上只让这几张图慢慢平移或闪动，移动交给显卡，不占用页面的计算。
   云和月亮的图是提前画好的文件（在 sky/ 目录，由 sky-build.js 生成）；雨丝、雪花、星空很简单，页面打开时现画。
   用法：Sky.mount(容器元素, 天气种类, { orb, cloudScale, calm })，返回新建的背景元素。 */
(function () {
'use strict';

const mix = (a, b, t) => a + (b - a) * t;
const smooth = (a, b, v) => { const t = Math.min(1, Math.max(0, (v - a) / (b - a))); return t * t * (3 - 2 * t); };

/* 固定种子的随机数：同一个种子每次生成的图都一样，刷新页面星星不会换位置 */
function prng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const cache = new Map();
const cached = (key, make) => { if (!cache.has(key)) cache.set(key, make()); return cache.get(key); };
function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }

/* ---------- 提前画好的图片：名字 → 图片的 [宽, 高] ---------- */
const HERE = document.currentScript.src.replace(/[^/]*$/, '');
const IMAGES = {
  wisp: [2304, 768], cumulus: [2304, 1152], cumulusFar: [2048, 640],
  stratus: [2304, 1152], stratusFar: [1536, 768], storm: [2304, 1152], stormFar: [1536, 768],
  nightStorm: [2304, 1152], snowCloud: [2304, 1152], nightCumulus: [2304, 1152], fog: [1536, 768],
};
/* 调画法时用：往这里放某个名字的图片地址，就用它代替 sky/ 目录里的文件 */
const textures = {};
const imageUrl = name => textures[name] || `${HERE}sky/${name}.webp`;

/* ---------- 雨：一张能上下左右无缝拼接的雨丝图 ---------- */
function rainTex(o) {
  const c = canvas(o.w, o.h), g = c.getContext('2d'), r = prng(o.seed);
  g.lineCap = 'round';
  for (let i = 0; i < o.n; i++) {
    const x = r() * o.w, y = r() * o.h, len = mix(o.len[0], o.len[1], r()), a = mix(o.a[0], o.a[1], r());
    g.lineWidth = mix(o.lw[0], o.lw[1], r());
    /* 雨丝上头淡、下头亮；超出图片底边的部分在顶上补画一段，拼接处才不会断 */
    for (const oy of y + len > o.h ? [0, -o.h] : [0]) {
      const grad = g.createLinearGradient(0, y + oy, 0, y + oy + len);
      grad.addColorStop(0, `rgba(${o.color},0)`); grad.addColorStop(1, `rgba(${o.color},${a})`);
      g.strokeStyle = grad; g.beginPath(); g.moveTo(x, y + oy); g.lineTo(x, y + oy + len); g.stroke();
    }
  }
  return c.toDataURL();
}
const RAINS = {
  far: { seed: 11, w: 520, h: 700, n: 430, len: [12, 28], lw: [.6, .9], a: [.14, .32], color: '214,226,250' },
  mid: { seed: 12, w: 640, h: 820, n: 160, len: [30, 62], lw: [.8, 1.2], a: [.16, .4], color: '222,232,252' },
  near: { seed: 13, w: 760, h: 940, n: 36, len: [80, 140], lw: [1.1, 1.7], a: [.2, .46], color: '232,240,255' },
};

/* ---------- 雪：一张能无缝拼接的雪花图 ---------- */
function snowTex(o) {
  const c = canvas(o.w, o.h), g = c.getContext('2d'), r = prng(o.seed);
  for (let i = 0; i < o.n; i++) {
    const x = r() * o.w, y = r() * o.h, rad = mix(o.r[0], o.r[1], r()), a = mix(o.a[0], o.a[1], r());
    for (const ox of [0, o.w, -o.w]) for (const oy of [0, o.h, -o.h]) {
      if (x + ox < -rad * 2 || x + ox > o.w + rad * 2 || y + oy < -rad * 2 || y + oy > o.h + rad * 2) continue;
      const grad = g.createRadialGradient(x + ox, y + oy, 0, x + ox, y + oy, rad);
      grad.addColorStop(0, `rgba(255,255,255,${a})`); grad.addColorStop(o.hard, `rgba(255,255,255,${a * .8})`); grad.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = grad; g.beginPath(); g.arc(x + ox, y + oy, rad, 0, 7); g.fill();
    }
  }
  return c.toDataURL();
}
const SNOWS = {
  far: { seed: 21, w: 500, h: 600, n: 150, r: [.9, 1.7], a: [.35, .7], hard: .6 },
  mid: { seed: 22, w: 620, h: 760, n: 70, r: [1.8, 3], a: [.5, .9], hard: .5 },
  near: { seed: 23, w: 800, h: 900, n: 20, r: [5, 9], a: [.22, .42], hard: .15 },
};

/* ---------- 星空 ----------
   一张不动的星空图：绝大多数星星又小又暗，只有少数几颗亮星带一点光晕，最亮的几颗带很细的十字光芒。
   星星不是均匀撒的：有的地方密、有的地方疏，越靠近地平线（下方）越少越暗。
   图按两倍大小画，显示时缩回去，星点才是清楚的小点而不是糊的圆斑 */
function starField(w, h) {
  const c = canvas(w * 2, h * 2), g = c.getContext('2d'), r = prng(31);
  g.scale(2, 2);
  /* 几处"星星特别密"的区域 */
  const dense = Array.from({ length: 7 }, () => [r() * w, r() * h * .7, 120 + r() * 260]);
  const density = (x, y) => { let d = .28; for (const [cx, cy, cr] of dense) d += .5 * Math.exp(-((x - cx) * (x - cx) + (y - cy) * (y - cy)) / (cr * cr)); return Math.min(1, d); };
  const count = Math.round(w * h / 900);
  for (let i = 0; i < count; i++) {
    const x = r() * w, y = Math.pow(r(), 1.25) * h, keep = r(), b = Math.pow(r(), 5), tint = r();
    if (keep > density(x, y)) continue;
    const low = 1 - .8 * smooth(.45, 1, y / h);
    const col = tint < .14 ? '255,226,196' : tint < .42 ? '200,220,255' : '255,255,255';
    const rad = .32 + b * .95, a = Math.min(1, (.2 + r() * .35 + b * .7) * low);
    if (b > .62) {
      const glow = g.createRadialGradient(x, y, 0, x, y, rad * 5);
      glow.addColorStop(0, `rgba(${col},${.3 * low})`); glow.addColorStop(1, `rgba(${col},0)`);
      g.fillStyle = glow; g.fillRect(x - rad * 5, y - rad * 5, rad * 10, rad * 10);
    }
    if (b > .93) {
      const len = 4 + b * 5;
      for (const [dx, dy] of [[1, 0], [0, 1]]) {
        const ray = g.createLinearGradient(x - dx * len, y - dy * len, x + dx * len, y + dy * len);
        ray.addColorStop(0, `rgba(${col},0)`); ray.addColorStop(.5, `rgba(${col},${.42 * low})`); ray.addColorStop(1, `rgba(${col},0)`);
        g.strokeStyle = ray; g.lineWidth = .6; g.beginPath(); g.moveTo(x - dx * len, y - dy * len); g.lineTo(x + dx * len, y + dy * len); g.stroke();
      }
    }
    g.fillStyle = `rgba(${col},${a})`; g.beginPath(); g.arc(x, y, rad, 0, 7); g.fill();
  }
  return c;
}
/* 单独闪烁的亮星：每颗有自己的快慢和先后，不会一起亮一起暗 */
function twinklers(n) {
  const r = prng(47), out = [];
  for (let i = 0; i < n; i++) {
    const tint = r(), col = tint < .2 ? '255 232 204' : tint < .5 ? '206 224 255' : '255 255 255';
    out.push(`<i class="sky-star" style="left:${(r() * 100).toFixed(2)}%;top:${(Math.pow(r(), 1.5) * 78).toFixed(2)}%;--s:${(2.6 + r() * 2.6).toFixed(1)}px;--c:${col};--dur:${(1.6 + r() * 3.4).toFixed(2)}s;--delay:${(-r() * 6).toFixed(2)}s"></i>`);
  }
  return out.join('');
}

/* ---------- 每种天气由哪些图层组成 ----------
   tone 给页面用：页面按它决定面板底色。
   clouds 里 top 是占容器高度的百分比，tile 是一张云图铺多宽（按容器高 920 像素时的像素数写，实际按容器高度等比换算；
   高度按图片本身的宽高比算，云不会被拉扁），dur 是飘过一张图要多少秒。
   fade 表示这种天气的云又白又亮，要把压着大号文字的那一块调淡。
   shade 用在云铺满天空的天气：云调淡会露出一个洞，所以改成在大号文字那一块盖一层很淡的暗色，数值是这层暗色有多重。
   rain 里的 level 是雨的大小（1 中雨，2 大雨），页面按它决定面板上溅起多少水花 */
const RAIN_MID = { tilt: 11, level: 1, layers: [['far', 1.35, .9], ['mid', .88, .85], ['near', .6, .7]] };
const RAIN_HEAVY = { tilt: 17, level: 2, layers: [['far', 1.05, 1], ['mid', .7, 1], ['near', .46, 1]] };
const KINDS = {
  sun: {
    label: '晴', tone: 'blue',
    base: 'linear-gradient(203deg, oklch(.68 .105 238) 0%, oklch(.56 .125 249) 36%, oklch(.43 .135 259) 100%)',
    sun: { glow: 1, rays: 1 },
    clouds: [{ tex: 'wisp', top: 2, tile: 2700, dur: 480, opacity: .9 }],
  },
  partly: {
    label: '多云', tone: 'blue',
    base: 'linear-gradient(203deg, oklch(.66 .09 238) 0%, oklch(.55 .11 249) 38%, oklch(.44 .12 258) 100%)',
    sun: { glow: .75, rays: .5, through: .5 },
    clouds: [{ tex: 'cumulusFar', top: 48, tile: 1700, dur: 560, opacity: .85 }, { tex: 'cumulus', top: 0, tile: 2300, dur: 340, opacity: 1 }],
    fade: 1,
  },
  overcast: {
    label: '阴', tone: 'grey',
    base: 'linear-gradient(180deg, oklch(.4 .034 256) 0%, oklch(.47 .032 251) 55%, oklch(.54 .028 246) 100%)',
    light: 'radial-gradient(760px 420px at 70% 4%, rgb(255 255 255 / .2), transparent 70%)',
    clouds: [{ tex: 'stratusFar', top: -20, tile: 3000, dur: 560, opacity: .9 }, { tex: 'stratus', top: -6, tile: 2400, dur: 340, opacity: 1 }],
    shade: .3,
  },
  rain: {
    label: '雨', tone: 'storm',
    base: 'linear-gradient(180deg, oklch(.31 .04 262) 0%, oklch(.4 .046 257) 55%, oklch(.5 .042 250) 100%)',
    clouds: [{ tex: 'stormFar', top: -20, tile: 3000, dur: 380, opacity: .9 }, { tex: 'storm', top: -6, tile: 2400, dur: 230, opacity: 1 }],
    rain: RAIN_MID, mist: 'rgb(196 208 230 / .2)',
  },
  thunder: {
    label: '雷雨', tone: 'storm',
    base: 'linear-gradient(180deg, oklch(.2 .035 268) 0%, oklch(.29 .045 262) 55%, oklch(.4 .045 254) 100%)',
    clouds: [{ tex: 'stormFar', top: -20, tile: 3000, dur: 280, opacity: .7 }, { tex: 'nightStorm', top: -6, tile: 2400, dur: 170, opacity: 1 }],
    rain: RAIN_HEAVY, mist: 'rgb(170 184 214 / .18)', flash: 1,
  },
  snow: {
    label: '雪', tone: 'grey',
    base: 'linear-gradient(180deg, oklch(.43 .036 252) 0%, oklch(.5 .036 246) 55%, oklch(.58 .032 240) 100%)',
    clouds: [{ tex: 'stratusFar', top: -20, tile: 3000, dur: 520, opacity: .85 }, { tex: 'snowCloud', top: -6, tile: 2400, dur: 380, opacity: 1 }],
    snow: 1, mist: 'rgb(236 240 248 / .22)', shade: .32,
  },
  haze: {
    label: '雾霾', tone: 'warm',
    base: 'linear-gradient(180deg, oklch(.5 .04 74) 0%, oklch(.57 .045 76) 55%, oklch(.63 .05 78) 100%)',
    sun: { glow: .35, pale: 1 },
    clouds: [{ tex: 'fog', top: -24, tile: 3200, dur: 520, opacity: .7 }, { tex: 'fog', top: 14, tile: 2600, dur: 380, opacity: .8 }],
  },
  night: {
    label: '晴夜', tone: 'night',
    base: 'linear-gradient(180deg, oklch(.115 .04 276) 0%, oklch(.165 .06 270) 42%, oklch(.25 .08 262) 82%, oklch(.3 .085 256) 100%)',
    stars: 1, moon: { glow: 1 }, meteor: 1,
  },
  partlyNight: {
    label: '多云夜', tone: 'night',
    base: 'linear-gradient(180deg, oklch(.125 .038 274) 0%, oklch(.175 .055 268) 42%, oklch(.25 .07 261) 82%, oklch(.29 .075 256) 100%)',
    stars: .85, moon: { glow: .9, through: .32 },
    clouds: [{ tex: 'nightCumulus', top: 0, tile: 2300, dur: 380, opacity: 1 }],
  },
  rainNight: {
    label: '雨夜', tone: 'night',
    base: 'linear-gradient(180deg, oklch(.13 .025 270) 0%, oklch(.19 .035 264) 55%, oklch(.27 .04 256) 100%)',
    clouds: [{ tex: 'nightStorm', top: -6, tile: 2400, dur: 240, opacity: 1 }],
    rain: { tilt: 11, level: 1, layers: [['far', 1.35, .6], ['mid', .88, .6], ['near', .6, .5]] },
    /* 夜里下雨时，底部留一点城市灯光映在雨雾里的暖色 */
    mist: 'rgb(214 176 138 / .13)',
  },
};

const STYLE = `
.sky { position: absolute; inset: 0; overflow: hidden; pointer-events: none; contain: strict; }
.sky > *, .sky-wrap > *, .sky-fall-wrap > *, .sky-sway > *, .sky-night > * { position: absolute; pointer-events: none; }
.sky-fill, .sky-night { inset: 0; }
.sky-stars { display: block; inset: 0; width: 100%; height: 100%; }
.sky-star { width: var(--s); height: var(--s); margin: calc(var(--s) / -2) 0 0 calc(var(--s) / -2); border-radius: 50%;
  background: radial-gradient(circle, #fff 0 26%, rgb(var(--c) / .5) 44%, rgb(var(--c) / 0) 72%);
  animation: sky-twinkle var(--dur) ease-in-out var(--delay) infinite alternate; }
.sky-meteor { width: 150px; height: 1.5px; border-radius: 1px; opacity: 0; background: linear-gradient(90deg, #fff, rgb(190 214 255 / .5) 30%, transparent); animation: sky-meteor var(--dur) linear var(--delay) infinite; }
.sky-orb { transform-origin: 0 0; }
.sky-rays { width: 1900px; height: 1900px; margin: -950px 0 0 -950px; border-radius: 50%;
  background: repeating-conic-gradient(from 8deg, rgb(255 248 228 / 0) 0deg, rgb(255 248 228 / .1) 5deg, rgb(255 248 228 / 0) 13deg, rgb(255 248 228 / 0) 23deg),
              repeating-conic-gradient(from 0deg, rgb(255 255 255 / 0) 0deg, rgb(255 255 255 / .07) 3deg, rgb(255 255 255 / 0) 7deg, rgb(255 255 255 / 0) 37deg);
  -webkit-mask-image: radial-gradient(circle, #000 0, rgb(0 0 0 / .55) 14%, transparent 52%); mask-image: radial-gradient(circle, #000 0, rgb(0 0 0 / .55) 14%, transparent 52%);
  animation: sky-spin 320s linear infinite; }
.sky-sun { width: 48px; height: 48px; margin: -24px 0 0 -24px; border-radius: 50%;
  background: radial-gradient(circle, #fff 0 46%, rgb(255 251 236 / .92) 62%, rgb(255 246 218 / 0) 100%);
  box-shadow: 0 0 26px 10px rgb(255 248 226 / .7), 0 0 90px 40px rgb(255 240 200 / .32), 0 0 220px 110px rgb(255 236 190 / .14); }
.sky-sun.pale { background: radial-gradient(circle, rgb(255 244 222 / .92) 0 58%, rgb(255 240 214 / 0) 66%); box-shadow: 0 0 60px 22px rgb(255 236 204 / .2); }
.sky-moon { width: 76px; height: 76px; margin: -38px 0 0 -38px; border-radius: 50%; background-size: 100% 100%;
  box-shadow: 0 0 14px 1px rgb(226 234 255 / .55), 0 0 46px 10px rgb(176 198 255 / .3), 0 0 130px 46px rgb(150 176 255 / .13); }
.sky-wrap { inset: 0; }
.sky-wrap.fade { -webkit-mask-image: var(--calm); mask-image: var(--calm); }
.sky-cloud { left: 0; width: calc(100% + var(--tile)); background-repeat: repeat-x; background-size: var(--tile) 100%; will-change: transform; animation: sky-drift var(--dur) linear var(--delay) infinite; }
.sky-fall-wrap { inset: -30% -12%; transform: rotate(var(--tilt)); }
.sky-fall { left: 0; right: 0; bottom: 0; top: calc(var(--th) * -1); background-repeat: repeat; will-change: transform; animation: sky-fall var(--dur) linear var(--delay) infinite; }
.sky-sway { inset: -6%; animation: sky-sway var(--dur) ease-in-out infinite alternate; }
.sky-flash { inset: 0; opacity: 0; }
.sky-flash.f1 { background: radial-gradient(560px 300px at 64% 10%, rgb(226 232 255 / .95), rgb(190 204 255 / .35) 45%, transparent 75%), rgb(150 170 230 / .14); animation: sky-flash 7.3s linear infinite; }
.sky-flash.f2 { background: radial-gradient(460px 260px at 24% 6%, rgb(226 232 255 / .9), rgb(190 204 255 / .3) 45%, transparent 75%), rgb(150 170 230 / .1); animation: sky-flash 11.9s linear -4s infinite; }
@keyframes sky-drift { to { transform: translate3d(calc(var(--tile) * -1), 0, 0); } }
@keyframes sky-fall { to { transform: translate3d(0, var(--th), 0); } }
@keyframes sky-sway { from { transform: translateX(-22px); } to { transform: translateX(22px); } }
@keyframes sky-spin { to { transform: rotate(360deg); } }
@keyframes sky-twinkle { from { opacity: .12; transform: scale(.7); } to { opacity: 1; transform: scale(1); } }
/* 流星：绝大部分时间看不见，每隔一阵从右上往左下划过一次 */
@keyframes sky-meteor { 0%, 94% { opacity: 0; transform: rotate(-28deg) translateX(0); } 94.6% { opacity: 1; } 98% { opacity: 0; transform: rotate(-28deg) translateX(-460px); } 100% { opacity: 0; transform: rotate(-28deg) translateX(-460px); } }
@keyframes sky-flash { 0%, 91.5%, 100% { opacity: 0; } 92% { opacity: 1; } 93% { opacity: .15; } 94.2% { opacity: .8; } 97% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .sky * { animation: none !important; } }
`;
let styled = false;

function mount(host, kind, opts) {
  opts = opts || {};
  if (!styled) { document.head.insertAdjacentHTML('beforeend', `<style>${STYLE}</style>`); styled = true; }
  const K = KINDS[kind] || KINDS.sun, w = host.clientWidth || 1480, h = host.clientHeight || 920;
  /* orb：太阳、月亮的位置（占容器的百分比）和大小倍数。默认放在右上方地点切换和头盔提醒之间的空位里 */
  const orb = Object.assign({ x: 75.5, y: 14, scale: 1 }, opts.orb), at = `left:${orb.x}%;top:${orb.y}%`;
  /* cloudScale：小卡片里把云层放大几倍，只露出云层靠上的一段，云朵才不会小得像碎屑 */
  const cs = opts.cloudScale || 1;
  const glowAt = (px, stops) => `<div class="sky-fill" style="background:radial-gradient(${px * orb.scale}px circle at ${orb.x}% ${orb.y}%, ${stops})"></div>`;
  const out = [`<div class="sky-fill" style="background:${K.base}"></div>`];
  if (K.light) out.push(`<div class="sky-fill" style="background:${K.light}"></div>`);
  if (K.stars) {
    out.push(`<div class="sky-night" style="opacity:${K.stars}"><i data-stars></i>${twinklers(Math.round(w * h / 36000))}</div>`);
    if (K.meteor) out.push('<i class="sky-meteor" style="left:58%;top:13%;--dur:17s;--delay:-11s"></i><i class="sky-meteor" style="left:36%;top:6%;--dur:29s;--delay:-9s"></i>');
  }
  if (K.sun) {
    const s = K.sun.glow;
    out.push(glowAt(640, `rgb(255 248 228 / ${.5 * s}), rgb(255 244 214 / ${.2 * s}) 22%, rgb(255 240 204 / ${.07 * s}) 55%, transparent`));
    if (K.sun.rays) out.push(`<div class="sky-orb" style="${at};opacity:${K.sun.rays};transform:scale(${orb.scale})"><div class="sky-rays"></div></div>`);
    out.push(`<div class="sky-orb" style="${at};transform:scale(${orb.scale})"><div class="sky-sun${K.sun.pale ? ' pale' : ''}"></div></div>`);
  }
  if (K.moon) {
    /* 月亮四周一大片很淡的月光，把附近的夜空映亮一点 */
    out.push(glowAt(520, `rgb(170 192 255 / ${.22 * K.moon.glow}), rgb(150 176 250 / ${.08 * K.moon.glow}) 45%, transparent`));
    out.push(`<div class="sky-orb" style="${at};transform:scale(${orb.scale})"><div class="sky-moon" style="background-image:url(${imageUrl('moon')})"></div></div>`);
  }
  if (K.clouds) {
    /* calm：页面上直接写大号文字的那一块（椭圆，中心和两个半径都是占容器的百分比），这一块里的云调淡，文字才看得清 */
    const calm = Object.assign({ x: 37, y: 29, rx: 34, ry: 20 }, opts.calm);
    out.push(`<div class="sky-wrap${K.fade ? ' fade' : ''}" style="--calm:radial-gradient(ellipse ${calm.rx}% ${calm.ry}% at ${calm.x}% ${calm.y}%, rgb(0 0 0 / .3) 0, rgb(0 0 0 / .42) 55%, #000 100%)">`);
    K.clouds.forEach((c, i) => {
      const tile = Math.round(c.tile / 920 * h * cs), size = IMAGES[c.tex];
      out.push(`<div class="sky-cloud" style="top:${c.top * cs}%;height:${Math.round(tile * size[1] / size[0])}px;opacity:${c.opacity};background-image:url(${imageUrl(c.tex)});--tile:${tile}px;--dur:${c.dur}s;--delay:${-(c.dur * (.17 + i * .31)).toFixed(0)}s"></div>`);
    });
    out.push('</div>');
  }
  if (K.shade) { const c = Object.assign({ x: 37, y: 29, rx: 34, ry: 20 }, opts.calm); out.push(`<div class="sky-fill" style="background:radial-gradient(ellipse ${c.rx * 1.25}% ${c.ry * 1.35}% at ${c.x}% ${c.y}%, rgb(8 14 34 / ${K.shade}), rgb(8 14 34 / ${K.shade * .7}) 50%, transparent 100%)"></div>`); }
  /* 太阳、月亮被云挡住时，云上还留一团透出来的光 */
  if (K.sun && K.sun.through) out.push(glowAt(400, `rgb(255 251 236 / ${K.sun.through}), rgb(255 246 220 / ${K.sun.through * .32}) 42%, transparent`));
  if (K.moon && K.moon.through) out.push(glowAt(300, `rgb(206 220 255 / ${K.moon.through}), rgb(176 196 255 / ${K.moon.through * .3}) 42%, transparent`));
  if (K.rain) {
    out.push(`<div class="sky-fall-wrap" style="--tilt:${K.rain.tilt}deg">`);
    K.rain.layers.forEach(([name, dur, op], i) => { const o = RAINS[name]; out.push(`<div class="sky-fall" style="opacity:${op};background-image:url(${cached('rain:' + name, () => rainTex(o))});background-size:${o.w}px ${o.h}px;--th:${o.h}px;--dur:${dur}s;--delay:${-(dur * i * .37).toFixed(2)}s"></div>`); });
    out.push('</div>');
  }
  if (K.snow) {
    [['far', 15, 9], ['mid', 10, 7], ['near', 6.5, 5]].forEach(([name, dur, sway], i) => {
      const o = SNOWS[name];
      out.push(`<div class="sky-sway" style="--dur:${sway}s"><div class="sky-fall" style="background-image:url(${cached('snow:' + name, () => snowTex(o))});background-size:${o.w}px ${o.h}px;--th:${o.h}px;--dur:${dur}s;--delay:${-(dur * i * .41).toFixed(1)}s"></div></div>`);
    });
  }
  if (K.mist) out.push(`<div class="sky-fill" style="background:linear-gradient(0deg, ${K.mist}, transparent 46%)"></div>`);
  if (K.flash) out.push('<div class="sky-flash f1"></div><div class="sky-flash f2"></div>');
  /* 顶上和底下各压暗一点：标题栏的字、底部面板里的字压在亮云上也看得清 */
  out.push('<div class="sky-fill" style="background:linear-gradient(180deg, rgb(6 12 32 / .2) 0, transparent 20%), linear-gradient(0deg, rgb(6 12 32 / .22), transparent 52%)"></div>');

  const el = document.createElement('div');
  el.className = 'sky'; el.dataset.kind = kind; el.dataset.tone = K.tone;
  /* 落在面板上的效果（雨滴溅起、积雪）由页面来画，这里只告诉页面现在是下雨还是下雪、雨有多大 */
  el.dataset.fall = K.rain ? 'rain' : K.snow ? 'snow' : '';
  el.dataset.level = K.rain ? K.rain.level : 1;
  el.innerHTML = out.join('');
  const slot = el.querySelector('[data-stars]');
  if (slot) { const stars = starField(w, h); stars.className = 'sky-stars'; slot.replaceWith(stars); }
  host.appendChild(el);
  return el;
}

window.Sky = { mount, KINDS, textures };
})();
