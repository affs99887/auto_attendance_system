// 天空背景。
// 做法：云、雨、雪、星空、月亮各是一张图，页面上只让这几张图慢慢平移或闪动，移动交给显卡，不占用页面的计算。
// 云和月亮的图是提前画好的文件（src/assets/sky）；雨丝、雪花、星空很简单，用到时现画。
// 用法：mountSky(容器元素, 天气种类, 选项)，往容器里加一层背景并返回它。对应的样式在 weather.css 的 .wx-sky 一段。
import { skyInfo } from './weather';

export type SkyKind =
  | 'sun' | 'partly' | 'overcast' | 'rain' | 'thunder' | 'snow' | 'haze'
  | 'night' | 'partlyNight' | 'overcastNight' | 'rainNight';
/** 天空的色调，页面按它决定面板底色 */
export type SkyTone = 'blue' | 'grey' | 'storm' | 'warm' | 'night';
/** 这种天气有没有东西落到面板上：下雨、下雪，或者都没有 */
export type SkyFall = 'rain' | 'snow' | '';

export interface SkyOptions {
  /** 太阳、月亮的位置和大小倍数。位置写数字是占容器的百分比，写字符串是样式里的长度（比如 '40px'、'calc(100% - 380px)'） */
  orb?: { x: number | string; y: number | string; scale: number };
  /** 小卡片里把云层放大几倍，只露出云层靠上的一段，云朵才不会小得像碎屑 */
  cloudScale?: number;
  /** 页面上直接写大号文字的那一块（椭圆，中心和两个半径都是占容器的百分比）：这一块里的云调淡，文字才看得清 */
  calm?: { x: number; y: number; rx: number; ry: number };
}

interface CloudLayer {
  tex: string;
  /** 占容器高度的百分比 */
  top: number;
  /** 一张云图铺多宽：按容器高 920 像素时的像素数写，实际按容器高度等比换算；高度按图片本身的宽高比算，云不会被拉扁 */
  tile: number;
  /** 飘过一张图要多少秒 */
  dur: number;
  opacity: number;
}
interface RainDef {
  tilt: number;
  /** 雨的大小：1 中雨，2 大雨。面板上溅起多少水雾按它定 */
  level: number;
  /** 每层雨丝：用哪张雨丝图、落一张图要多少秒、不透明度 */
  layers: Array<[keyof typeof RAINS, number, number]>;
}
interface SkyDef {
  tone: SkyTone;
  base: string;
  light?: string;
  sun?: { glow: number; rays?: number; through?: number };
  moon?: { glow: number; through?: number };
  stars?: number;
  meteor?: boolean;
  clouds?: CloudLayer[];
  /** 这种天气的云又白又亮，要把压着大号文字的那一块调淡 */
  fade?: boolean;
  /** 云铺满天空的天气：云调淡会露出一个洞，所以改成在大号文字那一块盖一层很淡的暗色，数值是这层暗色有多重 */
  shade?: number;
  rain?: RainDef;
  snow?: boolean;
  mist?: string;
  flash?: boolean;
}

const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const smooth = (a: number, b: number, v: number) => { const t = Math.min(1, Math.max(0, (v - a) / (b - a))); return t * t * (3 - 2 * t); };

/** 固定种子的随机数：同一个种子每次生成的图都一样，星星不会换位置 */
function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const cache = new Map<string, string>();
function cached(key: string, make: () => string): string {
  let value = cache.get(key);
  if (value === undefined) { value = make(); cache.set(key, value); }
  return value;
}
function canvas(w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  return c;
}

// ---------- 提前画好的图片 ----------
const IMAGE_URLS = import.meta.glob<string>('../assets/sky/*.webp', { eager: true, query: '?url', import: 'default' });
const imageUrl = (name: string) => IMAGE_URLS[`../assets/sky/${name}.webp`];
/** 每张云图的 [宽, 高] */
const IMAGE_SIZE: Record<string, [number, number]> = {
  wisp: [2304, 768], cumulus: [2304, 1152], cumulusFar: [2048, 640],
  stratus: [2304, 1152], stratusFar: [1536, 768], storm: [2304, 1152], stormFar: [1536, 768],
  nightStorm: [2304, 1152], snowCloud: [2304, 1152], nightCumulus: [2304, 1152], fog: [1536, 768],
};

// ---------- 雨：一张能上下左右无缝拼接的雨丝图 ----------
interface RainTex { seed: number; w: number; h: number; n: number; len: [number, number]; lw: [number, number]; a: [number, number]; color: string }
const RAINS = {
  far: { seed: 11, w: 520, h: 700, n: 430, len: [12, 28], lw: [.6, .9], a: [.14, .32], color: '214,226,250' },
  mid: { seed: 12, w: 640, h: 820, n: 160, len: [30, 62], lw: [.8, 1.2], a: [.16, .4], color: '222,232,252' },
  near: { seed: 13, w: 760, h: 940, n: 36, len: [80, 140], lw: [1.1, 1.7], a: [.2, .46], color: '232,240,255' },
} satisfies Record<string, RainTex>;
function rainTex(o: RainTex): string {
  const c = canvas(o.w, o.h), g = c.getContext('2d')!, r = prng(o.seed);
  g.lineCap = 'round';
  for (let i = 0; i < o.n; i++) {
    const x = r() * o.w, y = r() * o.h, len = mix(o.len[0], o.len[1], r()), a = mix(o.a[0], o.a[1], r());
    g.lineWidth = mix(o.lw[0], o.lw[1], r());
    // 雨丝上头淡、下头亮；超出图片底边的部分在顶上补画一段，拼接处才不会断
    for (const oy of y + len > o.h ? [0, -o.h] : [0]) {
      const grad = g.createLinearGradient(0, y + oy, 0, y + oy + len);
      grad.addColorStop(0, `rgba(${o.color},0)`); grad.addColorStop(1, `rgba(${o.color},${a})`);
      g.strokeStyle = grad; g.beginPath(); g.moveTo(x, y + oy); g.lineTo(x, y + oy + len); g.stroke();
    }
  }
  return c.toDataURL();
}

// ---------- 雪：一张能无缝拼接的雪花图 ----------
interface SnowTex { seed: number; w: number; h: number; n: number; r: [number, number]; a: [number, number]; hard: number }
const SNOWS = {
  far: { seed: 21, w: 500, h: 600, n: 150, r: [.9, 1.7], a: [.35, .7], hard: .6 },
  mid: { seed: 22, w: 620, h: 760, n: 70, r: [1.8, 3], a: [.5, .9], hard: .5 },
  near: { seed: 23, w: 800, h: 900, n: 20, r: [5, 9], a: [.22, .42], hard: .15 },
} satisfies Record<string, SnowTex>;
function snowTex(o: SnowTex): string {
  const c = canvas(o.w, o.h), g = c.getContext('2d')!, r = prng(o.seed);
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

// ---------- 星空 ----------
// 一张不动的星空图：绝大多数星星又小又暗，只有少数几颗亮星带一点光晕，最亮的几颗带很细的十字光芒。
// 星星不是均匀撒的：有的地方密、有的地方疏，越靠近地平线（下方）越少越暗。
// 图按两倍大小画，显示时缩回去，星点才是清楚的小点而不是糊的圆斑
function starField(w: number, h: number): HTMLCanvasElement {
  const c = canvas(w * 2, h * 2), g = c.getContext('2d')!, r = prng(31);
  g.scale(2, 2);
  // 几处"星星特别密"的区域
  const dense = Array.from({ length: 7 }, () => [r() * w, r() * h * .7, 120 + r() * 260]);
  const density = (x: number, y: number) => {
    let d = .28;
    for (const [cx, cy, cr] of dense) d += .5 * Math.exp(-((x - cx) * (x - cx) + (y - cy) * (y - cy)) / (cr * cr));
    return Math.min(1, d);
  };
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
// 同样大小的星空图是一样的：画过一次就留着，下次照着复制一张（复制比重画快得多，"全部地点"里十几张卡片同时出现时不会卡）
const STAR_CACHE_MAX = 8;
const starCache = new Map<string, HTMLCanvasElement>();
function starFieldCopy(w: number, h: number): HTMLCanvasElement {
  const key = `${w}x${h}`;
  let source = starCache.get(key);
  if (!source) {
    source = starField(w, h);
    if (starCache.size >= STAR_CACHE_MAX) starCache.delete(starCache.keys().next().value as string);
    starCache.set(key, source);
  }
  const copy = canvas(source.width, source.height);
  copy.getContext('2d')!.drawImage(source, 0, 0);
  return copy;
}

/** 单独闪烁的亮星：每颗有自己的快慢和先后，不会一起亮一起暗 */
function twinklers(n: number): string {
  const r = prng(47), out: string[] = [];
  for (let i = 0; i < n; i++) {
    const tint = r(), col = tint < .2 ? '255 232 204' : tint < .5 ? '206 224 255' : '255 255 255';
    out.push(`<i class="wx-sky-star" style="left:${(r() * 100).toFixed(2)}%;top:${(Math.pow(r(), 1.5) * 78).toFixed(2)}%;--s:${(2.6 + r() * 2.6).toFixed(1)}px;--c:${col};--dur:${(1.6 + r() * 3.4).toFixed(2)}s;--delay:${(-r() * 6).toFixed(2)}s"></i>`);
  }
  return out.join('');
}

// ---------- 每种天气由哪些图层组成 ----------
const RAIN_MID: RainDef = { tilt: 11, level: 1, layers: [['far', 1.35, .9], ['mid', .88, .85], ['near', .6, .7]] };
const RAIN_HEAVY: RainDef = { tilt: 17, level: 2, layers: [['far', 1.05, 1], ['mid', .7, 1], ['near', .46, 1]] };
const NIGHT_DECK_BASE = 'linear-gradient(180deg, oklch(.13 .025 270) 0%, oklch(.19 .035 264) 55%, oklch(.27 .04 256) 100%)';
const SKIES: Record<SkyKind, SkyDef> = {
  sun: {
    tone: 'blue',
    base: 'linear-gradient(203deg, oklch(.68 .105 238) 0%, oklch(.56 .125 249) 36%, oklch(.43 .135 259) 100%)',
    sun: { glow: 1, rays: 1 },
    clouds: [{ tex: 'wisp', top: 2, tile: 2700, dur: 480, opacity: .9 }],
  },
  partly: {
    tone: 'blue',
    base: 'linear-gradient(203deg, oklch(.66 .09 238) 0%, oklch(.55 .11 249) 38%, oklch(.44 .12 258) 100%)',
    sun: { glow: .75, rays: .5, through: .5 },
    clouds: [{ tex: 'cumulusFar', top: 48, tile: 1700, dur: 560, opacity: .85 }, { tex: 'cumulus', top: 0, tile: 2300, dur: 340, opacity: 1 }],
    fade: true,
  },
  overcast: {
    tone: 'grey',
    base: 'linear-gradient(180deg, oklch(.4 .034 256) 0%, oklch(.47 .032 251) 55%, oklch(.54 .028 246) 100%)',
    light: 'radial-gradient(760px 420px at 70% 4%, rgb(255 255 255 / .2), transparent 70%)',
    clouds: [{ tex: 'stratusFar', top: -20, tile: 3000, dur: 560, opacity: .9 }, { tex: 'stratus', top: -6, tile: 2400, dur: 340, opacity: 1 }],
    shade: .3,
  },
  rain: {
    tone: 'storm',
    base: 'linear-gradient(180deg, oklch(.31 .04 262) 0%, oklch(.4 .046 257) 55%, oklch(.5 .042 250) 100%)',
    clouds: [{ tex: 'stormFar', top: -20, tile: 3000, dur: 380, opacity: .9 }, { tex: 'storm', top: -6, tile: 2400, dur: 230, opacity: 1 }],
    rain: RAIN_MID, mist: 'rgb(196 208 230 / .2)',
  },
  thunder: {
    tone: 'storm',
    base: 'linear-gradient(180deg, oklch(.2 .035 268) 0%, oklch(.29 .045 262) 55%, oklch(.4 .045 254) 100%)',
    clouds: [{ tex: 'stormFar', top: -20, tile: 3000, dur: 280, opacity: .7 }, { tex: 'nightStorm', top: -6, tile: 2400, dur: 170, opacity: 1 }],
    rain: RAIN_HEAVY, mist: 'rgb(170 184 214 / .18)', flash: true,
  },
  snow: {
    tone: 'grey',
    base: 'linear-gradient(180deg, oklch(.43 .036 252) 0%, oklch(.5 .036 246) 55%, oklch(.58 .032 240) 100%)',
    clouds: [{ tex: 'stratusFar', top: -20, tile: 3000, dur: 520, opacity: .85 }, { tex: 'snowCloud', top: -6, tile: 2400, dur: 380, opacity: 1 }],
    snow: true, mist: 'rgb(236 240 248 / .22)', shade: .32,
  },
  haze: {
    tone: 'warm',
    base: 'linear-gradient(180deg, oklch(.5 .04 74) 0%, oklch(.57 .045 76) 55%, oklch(.63 .05 78) 100%)',
    clouds: [{ tex: 'fog', top: -24, tile: 3200, dur: 520, opacity: .7 }, { tex: 'fog', top: 14, tile: 2600, dur: 380, opacity: .8 }],
  },
  night: {
    tone: 'night',
    base: 'linear-gradient(180deg, oklch(.115 .04 276) 0%, oklch(.165 .06 270) 42%, oklch(.25 .08 262) 82%, oklch(.3 .085 256) 100%)',
    stars: 1, moon: { glow: 1 }, meteor: true,
  },
  partlyNight: {
    tone: 'night',
    base: 'linear-gradient(180deg, oklch(.125 .038 274) 0%, oklch(.175 .055 268) 42%, oklch(.25 .07 261) 82%, oklch(.29 .075 256) 100%)',
    stars: .85, moon: { glow: .9, through: .32 },
    clouds: [{ tex: 'nightCumulus', top: 0, tile: 2300, dur: 380, opacity: 1 }],
  },
  overcastNight: {
    tone: 'night',
    base: NIGHT_DECK_BASE,
    clouds: [{ tex: 'nightStorm', top: -6, tile: 2400, dur: 360, opacity: 1 }],
  },
  rainNight: {
    tone: 'night',
    base: NIGHT_DECK_BASE,
    clouds: [{ tex: 'nightStorm', top: -6, tile: 2400, dur: 240, opacity: 1 }],
    rain: { tilt: 11, level: 1, layers: [['far', 1.35, .6], ['mid', .88, .6], ['near', .6, .5]] },
    // 夜里下雨时，底部留一点城市灯光映在雨雾里的暖色
    mist: 'rgb(214 176 138 / .13)',
  },
};

export const skyTone = (kind: SkyKind): SkyTone => SKIES[kind].tone;
/** 这种天气的底色：天空最底下那一层渐变，不带云、雨、雪、星星 */
export const skyBase = (kind: SkyKind): string => SKIES[kind].base;

/** 趁浏览器空闲把雨丝、雪花图都先画好。每张图第一次画要几十毫秒，
 *  留到"全部地点"里一批雨雪卡片同时出现时再画，会正好卡在收放动画中间 */
export function warmSkyTextures(): () => void {
  const jobs: Array<() => void> = [
    ...(Object.keys(RAINS) as Array<keyof typeof RAINS>).map(name => () => { cached('rain:' + name, () => rainTex(RAINS[name])); }),
    ...(Object.keys(SNOWS) as Array<keyof typeof SNOWS>).map(name => () => { cached('snow:' + name, () => snowTex(SNOWS[name])); }),
  ];
  let handle = 0;
  const next = () => {
    const job = jobs.shift();
    if (!job) return;
    job();
    handle = window.requestIdleCallback(next, { timeout: 2000 });
  };
  handle = window.requestIdleCallback(next, { timeout: 2000 });
  return () => window.cancelIdleCallback(handle);
}
/** 这种天气落到面板上的是雨还是雪，雨有多大 */
export function skyFall(kind: SkyKind): { mode: SkyFall; level: number } {
  const def = SKIES[kind];
  return { mode: def.rain ? 'rain' : def.snow ? 'snow' : '', level: def.rain ? def.rain.level : 1 };
}

/** 按彩云的天气代码和当前钟点，决定背景用哪一种天空。
 *  彩云只给晴和多云分了白天、夜晚两种代码，阴、雨、雾霾、大风在夜里（19 点到次日 6 点）要自己换成夜晚的天空 */
export function resolveSkyKind(skycon: string | null | undefined, now: Date): SkyKind {
  // 钟点按北京时间算，跟天气数据用的时区一致，不受电脑时区设置影响
  const hour = (now.getUTCHours() + 8) % 24, dark = hour >= 19 || hour < 6;
  if (!skycon) return dark ? 'night' : 'sun';
  const info = skyInfo(skycon);
  if (info.icon === 'thunder') return 'thunder';
  if (info.tone === 'rain') return dark ? 'rainNight' : 'rain';
  if (info.tone === 'snow') return 'snow';
  if (info.icon === 'moon') return 'night';
  if (info.icon === 'partly-night') return 'partlyNight';
  if (info.icon === 'partly' || info.tone === 'wind') return dark ? 'partlyNight' : 'partly';
  if (info.tone === 'haze') return dark ? 'overcastNight' : 'haze';
  if (info.tone === 'cloud') return dark ? 'overcastNight' : 'overcast';
  return 'sun';
}

export function mountSky(host: HTMLElement, kind: SkyKind, opts: SkyOptions = {}): HTMLElement {
  const K = SKIES[kind], w = host.clientWidth || 1480, h = host.clientHeight || 920;
  // 太阳、月亮默认放在窗口最上面一条里、右上角那排状态标签左边的空位：这一带没有文字，页面内容怎么排都压不到它
  const orb = { x: 'calc(100% - 380px)', y: '40px', scale: 1, ...opts.orb };
  const length = (value: number | string) => typeof value === 'number' ? `${value}%` : value;
  const orbX = length(orb.x), orbY = length(orb.y), at = `left:${orbX};top:${orbY}`;
  const calm = { x: 37, y: 29, rx: 34, ry: 20, ...opts.calm };
  const cs = opts.cloudScale || 1;
  const fill = (style: string) => `<div class="wx-sky-fill" style="${style}"></div>`;
  const glowAt = (px: number, stops: string) => fill(`background:radial-gradient(${px * orb.scale}px circle at ${orbX} ${orbY}, ${stops})`);
  const out = [fill(`background:${K.base}`)];
  if (K.light) out.push(fill(`background:${K.light}`));
  if (K.stars) {
    out.push(`<div class="wx-sky-night" style="opacity:${K.stars}"><i data-stars></i>${twinklers(Math.round(w * h / 36000))}</div>`);
    if (K.meteor) out.push('<i class="wx-sky-meteor" style="left:58%;top:13%;--dur:17s;--delay:-11s"></i><i class="wx-sky-meteor" style="left:36%;top:6%;--dur:29s;--delay:-9s"></i>');
  }
  if (K.sun) {
    const s = K.sun.glow;
    out.push(glowAt(640, `rgb(255 248 228 / ${.5 * s}), rgb(255 244 214 / ${.2 * s}) 22%, rgb(255 240 204 / ${.07 * s}) 55%, transparent`));
    if (K.sun.rays) out.push(`<div class="wx-sky-orb" style="${at};opacity:${K.sun.rays};transform:scale(${orb.scale})"><div class="wx-sky-rays"></div></div>`);
    out.push(`<div class="wx-sky-orb" style="${at};transform:scale(${orb.scale})"><div class="wx-sky-sun"></div></div>`);
  }
  if (K.moon) {
    // 月亮四周一大片很淡的月光，把附近的夜空映亮一点
    out.push(glowAt(520, `rgb(170 192 255 / ${.22 * K.moon.glow}), rgb(150 176 250 / ${.08 * K.moon.glow}) 45%, transparent`));
    out.push(`<div class="wx-sky-orb" style="${at};transform:scale(${orb.scale})"><div class="wx-sky-moon" style="background-image:url(${imageUrl('moon')})"></div></div>`);
  }
  if (K.clouds) {
    out.push(`<div class="wx-sky-wrap${K.fade ? ' fade' : ''}" style="--calm:radial-gradient(ellipse ${calm.rx}% ${calm.ry}% at ${calm.x}% ${calm.y}%, rgb(0 0 0 / .3) 0, rgb(0 0 0 / .42) 55%, #000 100%)">`);
    K.clouds.forEach((c, i) => {
      const tile = Math.round(c.tile / 920 * h * cs), size = IMAGE_SIZE[c.tex];
      out.push(`<div class="wx-sky-cloud" style="top:${c.top * cs}%;height:${Math.round(tile * size[1] / size[0])}px;opacity:${c.opacity};background-image:url(${imageUrl(c.tex)});--tile:${tile}px;--dur:${c.dur}s;--delay:${-(c.dur * (.17 + i * .31)).toFixed(0)}s"></div>`);
    });
    out.push('</div>');
  }
  if (K.shade) out.push(fill(`background:radial-gradient(ellipse ${calm.rx * 1.25}% ${calm.ry * 1.35}% at ${calm.x}% ${calm.y}%, rgb(8 14 34 / ${K.shade}), rgb(8 14 34 / ${K.shade * .7}) 50%, transparent 100%)`));
  // 太阳、月亮被云挡住时，云上还留一团透出来的光
  if (K.sun?.through) out.push(glowAt(400, `rgb(255 251 236 / ${K.sun.through}), rgb(255 246 220 / ${K.sun.through * .32}) 42%, transparent`));
  if (K.moon?.through) out.push(glowAt(300, `rgb(206 220 255 / ${K.moon.through}), rgb(176 196 255 / ${K.moon.through * .3}) 42%, transparent`));
  if (K.rain) {
    out.push(`<div class="wx-sky-fall-wrap" style="--tilt:${K.rain.tilt}deg">`);
    K.rain.layers.forEach(([name, dur, op], i) => {
      const o = RAINS[name];
      out.push(`<div class="wx-sky-fall" style="opacity:${op};background-image:url(${cached('rain:' + name, () => rainTex(o))});background-size:${o.w}px ${o.h}px;--th:${o.h}px;--dur:${dur}s;--delay:${-(dur * i * .37).toFixed(2)}s"></div>`);
    });
    out.push('</div>');
  }
  if (K.snow) {
    ([['far', 15, 9], ['mid', 10, 7], ['near', 6.5, 5]] as Array<[keyof typeof SNOWS, number, number]>).forEach(([name, dur, sway], i) => {
      const o = SNOWS[name];
      out.push(`<div class="wx-sky-sway" style="--dur:${sway}s"><div class="wx-sky-fall" style="background-image:url(${cached('snow:' + name, () => snowTex(o))});background-size:${o.w}px ${o.h}px;--th:${o.h}px;--dur:${dur}s;--delay:${-(dur * i * .41).toFixed(1)}s"></div></div>`);
    });
  }
  if (K.mist) out.push(fill(`background:linear-gradient(0deg, ${K.mist}, transparent 46%)`));
  if (K.flash) out.push('<div class="wx-sky-flash f1"></div><div class="wx-sky-flash f2"></div>');
  // 顶上和底下各压暗一点：标题栏的字、底部面板里的字压在亮云上也看得清
  out.push(fill('background:linear-gradient(180deg, rgb(6 12 32 / .2) 0, transparent 20%), linear-gradient(0deg, rgb(6 12 32 / .22), transparent 52%)'));

  const el = document.createElement('div');
  el.className = 'wx-sky';
  el.dataset.kind = kind;
  el.innerHTML = out.join('');
  const slot = el.querySelector('[data-stars]');
  if (slot) { const stars = starFieldCopy(w, h); stars.className = 'wx-sky-stars'; slot.replaceWith(stars); }
  host.appendChild(el);
  return el;
}
