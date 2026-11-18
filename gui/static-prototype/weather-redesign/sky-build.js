/* 生成天空背景要用的图片：各种云、月亮。
   这些图算起来慢（一张要一两秒），所以不在页面打开时现算，而是提前算好存成 sky/ 目录下的图片文件，sky.js 直接用文件。
   要重新出图时用浏览器打开 build-sky.html。
   用法：SkyBuild.cloud(名字, 分辨率倍数) / SkyBuild.moon(边长)，都返回一个画好的 canvas。 */
(function () {
'use strict';

const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const mix = (a, b, t) => a + (b - a) * t;
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

/* 固定种子的随机数：同一个种子每次生成的图都一样 */
function prng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ---------- 噪声：云的形状靠它算出来 ---------- */
const NOISE = (() => { const r = prng(20261117), t = new Float32Array(65536); for (let i = 0; i < 65536; i++) t[i] = r(); return t; })();

/* 平滑的随机起伏。px 是横向多少格之后首尾相接，图才能左右无缝拼起来 */
function vnoise(x, y, px) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * xf * (xf * (xf * 6 - 15) + 10), v = yf * yf * yf * (yf * (yf * 6 - 15) + 10);
  const x0 = ((xi % px) + px) % px, x1 = (x0 + 1) % px, y0 = (yi & 255) << 8, y1 = ((yi + 1) & 255) << 8;
  /* & 65535：横向格数超过 256 时下标会超出噪声表，绕回表头接着取 */
  const a = NOISE[(y0 + x0) & 65535], b = NOISE[(y0 + x1) & 65535], c = NOISE[(y1 + x0) & 65535], d = NOISE[(y1 + x1) & 65535];
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
/* 把几层粗细不同的起伏叠在一起：大块轮廓 + 越来越细的碎边 */
function fbm(x, y, px, oct) {
  let s = 0, a = .5, n = 0;
  for (let o = 0, f = 1; o < oct; o++, f *= 2) { s += a * vnoise(x * f + o * 31.7, y * f + o * 17.3, px * f); n += a; a *= .5; }
  return s / n;
}
/* 到最近一个随机点的距离 */
function worley(x, y, px) {
  const xi = Math.floor(x), yi = Math.floor(y);
  let m = 9;
  for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) {
    const cx = xi + i, cy = yi + j, k = (((cy & 255) << 8) + ((cx % px) + px) % px) & 65535;
    const dx = cx + NOISE[k] - x, dy = cy + NOISE[(k + 12345) & 65535] - y, d = dx * dx + dy * dy;
    if (d < m) m = d;
  }
  return Math.sqrt(m);
}
/* 一团团圆鼓鼓的形状（大中小几种叠在一起），积云边缘一个个鼓包靠它 */
function billow(x, y, px) {
  return 1 - .42 * Math.min(1, worley(x * 2, y * 2, px * 2)) - .28 * Math.min(1, worley(x * 4, y * 4, px * 4)) - .18 * Math.min(1, worley(x * 8, y * 8, px * 8)) - .12 * Math.min(1, worley(x * 16, y * 16, px * 16));
}

function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }

/* ---------- 云 ----------
   o.w / o.h 成品图的像素大小
   o.px     横向噪声格数，越小云块越大
   o.flat   纵向压扁的倍数，1 是不压扁
   o.warp   把形状随机扭一扭的幅度，越大轮廓越不规则
   o.puff   圆鼓程度（0 是絮状，越大越像一朵朵积云）
   o.cut    低于这个值的地方没有云，越大云越少
   o.soft   云边从无到有的过渡宽度
   o.reach  算明暗时朝光的方向看多远（像素）：这段路上云越多，这一点越暗，云才有厚度感
   o.absorb 云挡光的强度，越大背光面越暗
   o.relief 细小起伏的明暗强度
   o.rim    云的薄边提亮多少
   o.depth  云越厚越暗的程度；o.depthRange 是从云边往里多深算作最厚
   o.bulk   大块起伏的明暗强度：连成一大片的云靠它在内部分出一团一团的明暗
   o.grain  云面上细碎鼓包的明暗强度
   o.lit / o.dark  受光面和背光面的颜色
   o.profile(v, u) 按位置加减云量，v 是从上到下 0~1，u 是从左到右 0~1
   o.row    有这一项时画成"一排平底积云"：base 是云底在图里的高度（0~1），hmax 是云最高能长多高，gap 越大云与云之间空得越多 */
function cloud(name, q) {
  const o = CLOUDS[name];
  q = q || 1;
  const w = Math.round(o.w * q), h = Math.round(o.h * q), c = canvas(w, h), g = c.getContext('2d');
  const img = g.createImageData(w, h), P = img.data, F = new Float32Array(w * h), B = new Float32Array(w * h), D = new Float32Array(w * h);
  const sx = o.px / w, sy = sx * (o.flat || 1), oct = o.oct || 6, puff = o.puff || 0, warp = o.warp || 0, row = o.row;
  const cut = row ? 0 : o.cut, soft = o.soft;
  for (let y = 0, i = 0; y < h; y++) {
    const v = y / h;
    for (let x = 0; x < w; x++, i++) {
      let X = x * sx, Y = y * sy + o.seed * 13.7;
      if (warp) { const a = fbm(X, Y + 40, o.px, 3) - .5, b = fbm(X, Y + 80, o.px, 3) - .5; X += a * warp; Y += b * warp; }
      const b = puff ? billow(X, Y, o.px) : .5;
      let f;
      if (row) {
        const t = (row.base - v) / row.hmax;
        const m = smooth(row.gap, row.gap + .2, fbm(x * sx, o.seed * 7.1, o.px, 3));
        const top = m * (.4 + .6 * fbm(X * 2, o.seed * 3.3 + 9, o.px * 2, 3));
        f = Math.min(top - t + (b - .5) * puff * m, (t + .03) * 9);
      } else {
        const n = fbm(X, Y, o.px, oct);
        f = mix(n, n * .5 + b * .56, puff) + (o.profile ? o.profile(v, x / w) : 0);
      }
      F[i] = f; B[i] = b; D[i] = smooth(cut, cut + soft, f);
    }
  }
  const L = o.light || [.6, -.8], N = 10, reach = (o.reach || 110) * q, near = Math.max(1, Math.round(10 * q));
  const ox = [], oy = [];
  for (let k = 1; k <= N; k++) { ox.push(Math.round(L[0] * reach * k / N)); oy.push(Math.round(L[1] * reach * k / N)); }
  const nx = Math.round(L[0] * near * 1.4), ny = Math.round(L[1] * near * 1.4);
  const absorb = o.absorb == null ? 2.4 : o.absorb, relief = o.relief == null ? 3 : o.relief, rim = o.rim || 0, depth = o.depth || 0, wd = o.direct == null ? .6 : o.direct, grain = o.grain == null ? .3 : o.grain, bulk = o.bulk || 0, range = o.depthRange || soft * 2.4;
  const fx = Math.round(L[0] * reach * .5), fy = Math.round(L[1] * reach * .5);
  for (let y = 0, i = 0; y < h; y++) {
    const edge = smooth(0, .08, y / h) * smooth(1, .9, y / h);
    for (let x = 0; x < w; x++, i++) {
      const d = D[i];
      if (d <= 0 || edge <= 0) continue;
      let tau = 0;
      for (let k = 0; k < N; k++) tau += D[clamp(y + oy[k], 0, h - 1) * w + (x + ox[k] + w) % w];
      const direct = Math.exp(-tau / N * absorb);
      const emboss = clamp(.5 + (F[i] - F[clamp(y + ny, 0, h - 1) * w + (x + nx + w) % w]) * relief, 0, 1);
      let s = direct * wd + emboss * (1 - wd);
      if (bulk) s = mix(s, clamp(.5 + (F[i] - F[clamp(y + fy, 0, h - 1) * w + (x + fx + w) % w]) * 5, 0, 1), bulk);
      s = mix(s, 1, (1 - d) * rim);
      if (depth) s = mix(s, 1 - smooth(cut, cut + range, F[i]), depth);
      s = clamp(s * (1 - grain * .4 + grain * (B[i] - .5)) + .03, 0, 1);
      const k = i * 4;
      P[k] = mix(o.dark[0], o.lit[0], s); P[k + 1] = mix(o.dark[1], o.lit[1], s); P[k + 2] = mix(o.dark[2], o.lit[2], s);
      P[k + 3] = 255 * d * edge * (o.alpha == null ? 1 : o.alpha);
    }
  }
  g.putImageData(img, 0, 0);
  return c;
}

const CUMULUS = { w: 2304, h: 1152, seed: 2, px: 5, flat: 1.1, warp: .3, oct: 7, puff: .62, cut: .5, soft: .05, reach: 100, absorb: 1.7, relief: 3.4, rim: .5, profile: v => -.3 * smooth(.5, .96, v) - .14 * smooth(.14, 0, v) };
const SMALL = { w: 2048, h: 640, seed: 3, px: 11, flat: 1.25, warp: .25, oct: 6, puff: .62, cut: .53, soft: .05, reach: 46, absorb: 1.2, relief: 3, rim: .5, profile: v => -.3 * smooth(.6, 1, v) - .3 * smooth(.34, 0, v) };
/* 铺满天空的云层（阴天、雨、雪）：跟积云一样是一团团的，只是多到连成一片；光从正上方来，云顶亮、云底暗 */
const DECK = { ...CUMULUS, cut: .485, soft: .07, reach: 120, absorb: 2, rim: .3, grain: .16, bulk: .45, depth: .35, depthRange: .26, light: [.3, -.95], profile: v => -.1 * smooth(.8, 1, v) };
/* 垫在云层后面的一层：铺满、没有清楚的轮廓，把云与云之间的空隙填上 */
const VEIL = { w: 1536, h: 768, px: 4, flat: 1.4, warp: .5, oct: 5, puff: .3, cut: .3, soft: .3, reach: 90, absorb: 1.2, relief: 2.2, depth: .45, direct: .5 };
const CLOUDS = {
  /* 晴天高空的几缕薄云 */
  wisp: { w: 2304, h: 768, seed: 1, px: 5, flat: 3, warp: .9, cut: .5, soft: .3, reach: 40, absorb: .6, relief: 1.2, rim: .9, lit: [255, 255, 255], dark: [212, 226, 250], alpha: .55, profile: v => -.22 * smooth(.25, 1, v) },
  /* 多云：近处大朵的积云，远处一层小朵的 */
  cumulus: { ...CUMULUS, lit: [255, 253, 248], dark: [134, 156, 204], alpha: .97 },
  cumulusFar: { ...SMALL, lit: [246, 249, 254], dark: [160, 180, 220], alpha: .88 },
  /* 阴天 */
  stratus: { ...DECK, seed: 4, lit: [198, 205, 220], dark: [78, 88, 112], alpha: .96 },
  stratusFar: { ...VEIL, seed: 5, lit: [184, 192, 209], dark: [98, 108, 132], alpha: .92 },
  /* 雨云：更厚更暗 */
  storm: { ...DECK, seed: 6, cut: .47, absorb: 2.4, lit: [166, 176, 198], dark: [36, 42, 62], alpha: .97 },
  stormFar: { ...VEIL, seed: 7, lit: [130, 140, 164], dark: [48, 56, 78], alpha: .92 },
  /* 雷雨和夜里下雨时的云：几乎是黑的 */
  nightStorm: { ...DECK, seed: 6, cut: .47, absorb: 2.6, lit: [86, 96, 126], dark: [10, 13, 26], alpha: .97 },
  /* 雪云：比阴天的云更白 */
  snowCloud: { ...DECK, seed: 9, cut: .48, absorb: 1.7, lit: [216, 222, 234], dark: [116, 126, 150], alpha: .95 },
  /* 夜里的积云：被月光照到的一面发亮，其余几乎融进夜色 */
  nightCumulus: { ...CUMULUS, absorb: 2.6, rim: .6, lit: [178, 194, 234], dark: [20, 26, 50], alpha: .96 },
  /* 雾、霾：很宽很淡的雾带 */
  fog: { w: 1536, h: 768, seed: 8, px: 3, flat: 2.2, warp: .4, oct: 4, cut: .36, soft: .5, reach: 40, absorb: .4, relief: .4, rim: .5, lit: [255, 248, 236], dark: [214, 204, 188], alpha: .36 },
};

/* ---------- 月亮：一轮满月 ----------
   月面上深色的几块按真实月亮的大致位置摆（上面和左边多，下面是亮的高地），边缘用噪声弄得不规则 */
const MARIA = [[-.26, -.44, .3, 1], [.2, -.38, .19, 1], [.4, -.1, .22, 1], [.7, -.24, .1, 1], [-.58, -.08, .34, .7], [-.2, .36, .22, .8], [-.5, .34, .11, .9], [.62, .12, .14, .8], [.44, .26, .09, .8], [-.02, -.06, .13, .5]];
function moon(size) {
  const S = size, c = canvas(S, S), g = c.getContext('2d'), img = g.createImageData(S, S), P = img.data, R = S / 2 - 2;
  for (let y = 0, k = 0; y < S; y++) for (let x = 0; x < S; x++, k += 4) {
    const dx = (x + .5 - S / 2) / R, dy = (y + .5 - S / 2) / R, r = Math.hypot(dx, dy);
    if (r > 1 + 1.5 / R) continue;
    const nz = Math.sqrt(Math.max(0, 1 - r * r));
    let sea = 0;
    for (const [mx, my, mr, ms] of MARIA) { const d2 = ((dx - mx) * (dx - mx) + (dy - my) * (dy - my)) / (mr * mr); sea += ms * Math.exp(-d2 * 1.6); }
    const rough = fbm(dx * 3 + 9, dy * 3 + 4, 256, 5), fine = fbm(dx * 14 + 2, dy * 14 + 7, 256, 4);
    const mare = smooth(.3, .95, sea + (rough - .5) * .6);
    /* 靠下有一个亮点，四周带一圈淡淡的亮纹，像月面上最显眼的那个环形山 */
    const tx = dx + .1, ty = dy - .68, td = Math.hypot(tx, ty), ray = Math.exp(-td * 5) * (.5 + .5 * Math.cos(Math.atan2(ty, tx) * 9)) * .1 + Math.exp(-td * td * 500) * .12;
    const light = (1 - mare * .17 + (fine - .5) * .05 + ray) * (.84 + .16 * Math.pow(nz, .55));
    P[k] = clamp(252 * light, 0, 255); P[k + 1] = clamp(249 * light, 0, 255); P[k + 2] = clamp(mix(240, 252, mare) * light, 0, 255);
    P[k + 3] = 255 * clamp((1 - r) * R + .5, 0, 1);
  }
  g.putImageData(img, 0, 0);
  return c;
}

window.SkyBuild = { cloud, moon, CLOUDS };
})();
