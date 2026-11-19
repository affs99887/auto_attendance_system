// 天空背景。
// 做法：云、雨、雪、星空、月亮各是一张图，页面上只让这几张图慢慢平移或闪动，移动交给显卡，不占用页面的计算。
// 云和月亮的图是提前画好的文件（src/assets/sky）；雨丝、雪花、星空很简单，用到时现画。
// 天色跟着当地太阳的高度变（lib/sun.ts）：夜里、黎明、日出、上午、中午、下午、日落、黄昏各有一个样子，
// 太阳高度在两个时段之间时取两边的中间样子，见下面"各时段的样子"一段。
// 用法：mountSky(容器元素, 天气种类, 太阳, 选项) 往容器里加一层背景并返回它；太阳位置变了用 setSkyTime(这层背景, 太阳) 重新上色。
// 对应的样式在 weather.css 的 .wx-sky 一段。
import { skyInfo } from './weather';
import type { SunLight } from './sun';

export type SkyKind =
  | 'sun' | 'partly' | 'overcast' | 'rain' | 'thunder' | 'snow' | 'haze'
  | 'night' | 'partlyNight' | 'overcastNight' | 'rainNight';
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
  /** 太阳：光晕强度、光芒强度、被云挡住时透出来的那团光有多亮 */
  sun?: { glow: number; through?: number };
  /** 太阳的光芒有多亮（不写就没有光芒） */
  rays?: number;
  /** 月亮：月光强度、被云挡住时透出来的那团光有多亮。白天的晴天、多云也写上：天快黑时月亮先出来 */
  moon?: { glow: number; through?: number };
  /** 天黑透时星星有多亮。跟月亮一样，白天的晴天、多云也写上 */
  stars?: number;
  meteor?: boolean;
  /** 阴天云层顶上透出来的一片亮光 */
  light?: string;
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
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));
const smooth = (a: number, b: number, v: number) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

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
// 名字不带 Night 的是白天那一套，带 Night 的是天黑透以后换上的那一套（云图不同）；雷雨、雪、雾霾白天夜里用同一套，只靠上色区分
const RAIN_MID: RainDef = { tilt: 11, level: 1, layers: [['far', 1.35, .9], ['mid', .88, .85], ['near', .6, .7]] };
const RAIN_HEAVY: RainDef = { tilt: 17, level: 2, layers: [['far', 1.05, 1], ['mid', .7, 1], ['near', .46, 1]] };
const SKIES: Record<SkyKind, SkyDef> = {
  sun: {
    sun: { glow: 1 }, rays: 1, moon: { glow: 1 }, stars: 1,
    clouds: [{ tex: 'wisp', top: 2, tile: 2700, dur: 480, opacity: .9 }],
  },
  partly: {
    sun: { glow: .75, through: .5 }, rays: .5, moon: { glow: .9, through: .32 }, stars: .85,
    clouds: [{ tex: 'cumulusFar', top: 48, tile: 1700, dur: 560, opacity: .85 }, { tex: 'cumulus', top: 0, tile: 2300, dur: 340, opacity: 1 }],
    fade: true,
  },
  overcast: {
    light: 'radial-gradient(760px 420px at 70% 4%, rgb(255 255 255 / .2), transparent 70%)',
    clouds: [{ tex: 'stratusFar', top: -20, tile: 3000, dur: 560, opacity: .9 }, { tex: 'stratus', top: -6, tile: 2400, dur: 340, opacity: 1 }],
    shade: .3,
  },
  rain: {
    clouds: [{ tex: 'stormFar', top: -20, tile: 3000, dur: 380, opacity: .9 }, { tex: 'storm', top: -6, tile: 2400, dur: 230, opacity: 1 }],
    rain: RAIN_MID, mist: 'rgb(196 208 230 / .2)',
  },
  thunder: {
    clouds: [{ tex: 'stormFar', top: -20, tile: 3000, dur: 280, opacity: .7 }, { tex: 'nightStorm', top: -6, tile: 2400, dur: 170, opacity: 1 }],
    rain: RAIN_HEAVY, mist: 'rgb(170 184 214 / .18)', flash: true,
  },
  snow: {
    clouds: [{ tex: 'stratusFar', top: -20, tile: 3000, dur: 520, opacity: .85 }, { tex: 'snowCloud', top: -6, tile: 2400, dur: 380, opacity: 1 }],
    snow: true, mist: 'rgb(236 240 248 / .22)', shade: .32,
  },
  haze: {
    clouds: [{ tex: 'fog', top: -24, tile: 3200, dur: 520, opacity: .7 }, { tex: 'fog', top: 14, tile: 2600, dur: 380, opacity: .8 }],
  },
  night: {
    stars: 1, moon: { glow: 1 }, meteor: true,
  },
  partlyNight: {
    stars: .85, moon: { glow: .9, through: .32 },
    clouds: [{ tex: 'nightCumulus', top: 0, tile: 2300, dur: 380, opacity: 1 }],
  },
  overcastNight: {
    clouds: [{ tex: 'nightStorm', top: -6, tile: 2400, dur: 360, opacity: 1 }],
  },
  rainNight: {
    clouds: [{ tex: 'nightStorm', top: -6, tile: 2400, dur: 240, opacity: 1 }],
    rain: { tilt: 11, level: 1, layers: [['far', 1.35, .6], ['mid', .88, .6], ['near', .6, .5]] },
    // 夜里下雨时，底部留一点城市灯光映在雨雾里的暖色
    mist: 'rgb(214 176 138 / .13)',
  },
};
const NIGHT_KINDS = new Set<SkyKind>(['night', 'partlyNight', 'overcastNight', 'rainNight']);

// ---------- 颜色计算 ----------
// 两个时段之间取中间色时按 Oklab 算：在 Oklab 里取的中间色明暗是均匀过渡的，不会在两种颜色中间突然发暗
type Lab = [number, number, number];
/** RGB 三个通道各乘多少（0 ~ 1） */
type Rgb = [number, number, number];
/** 带透明度的颜色 */
type Paint = [Lab, number];
const RAD = Math.PI / 180;
const lch = (L: number, C: number, H: number): Lab => [L, C * Math.cos(H * RAD), C * Math.sin(H * RAD)];
function rgb(r: number, g: number, b: number): Lab {
  const linear = (v: number) => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
  const R = linear(r), G = linear(g), B = linear(b);
  const l = Math.cbrt(.4122214708 * R + .5363325363 * G + .0514459929 * B);
  const m = Math.cbrt(.2119034982 * R + .6806995451 * G + .1073969566 * B);
  const s = Math.cbrt(.0883024619 * R + .2817188376 * G + .6299787005 * B);
  return [
    .2104542553 * l + .793617785 * m - .0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + .4505937099 * s,
    .0259040371 * l + .7827717662 * m - .808675766 * s,
  ];
}
const mixLab = (x: Lab, y: Lab, t: number): Lab => [mix(x[0], y[0], t), mix(x[1], y[1], t), mix(x[2], y[2], t)];
const mixRgb = (x: Rgb, y: Rgb, t: number): Rgb => [mix(x[0], y[0], t), mix(x[1], y[1], t), mix(x[2], y[2], t)];
/** 两种带透明度的颜色取中间：颜色按各自的浓淡加权，一边几乎透明时，中间色就是另一边的颜色 */
function mixPaint([c1, a1]: Paint, [c2, a2]: Paint, t: number): Paint {
  const a = mix(a1, a2, t);
  return a > 1e-4 ? [mixLab(c1, c2, a2 * t / a), a] : [c2, 0];
}
const labCss = (c: Lab, alpha = 1) =>
  `oklab(${c[0].toFixed(4)} ${c[1].toFixed(4)} ${c[2].toFixed(4)}${alpha < 1 ? ` / ${Math.max(0, alpha).toFixed(3)}` : ''})`;
const rgbCss = (c: Rgb, alpha: number) => `rgb(${c.map(v => Math.round(v)).join(' ')} / ${alpha.toFixed(3)})`;

/** 一段渐变：方向（度）和四个色标，色标是 [位置 %, 颜色] */
interface Grad { angle: number; stops: Array<[number, Lab]> }
/** 色标：位置 %，再加 OKLCH 的三个数（明度、彩度、色相） */
type Stop = [number, number, number, number];
const grad = (angle: number, ...stops: Stop[]): Grad => ({ angle, stops: stops.map(([p, L, C, H]) => [p, lch(L, C, H)]) });
/** 三个色标的渐变补成四个（各时段之间才能一个色标对一个色标地过渡）：在后两个色标正中间加一个，颜色取两边的中间色，画出来跟三个色标时一样 */
function grad3(angle: number, a: Stop, b: Stop, c: Stop): Grad {
  const g = grad(angle, a, b, c);
  const [[p1, c1], [p2, c2]] = [g.stops[1], g.stops[2]];
  g.stops.splice(2, 0, [(p1 + p2) / 2, mixLab(c1, c2, .5)]);
  return g;
}
function mixGrad(x: Grad, y: Grad, t: number): Grad {
  return { angle: mix(x.angle, y.angle, t), stops: x.stops.map(([p, c], i) => [mix(p, y.stops[i][0], t), mixLab(c, y.stops[i][1], t)]) };
}
/** 在 base 上加 (to - from) 的 k 倍：晴天从"只按明暗算"到"这个时段真正的样子"差了多少，按比例加到别的天气上 */
function shiftGrad(base: Grad, from: Grad, to: Grad, k: number): Grad {
  return {
    angle: base.angle + (to.angle - from.angle) * k,
    stops: base.stops.map(([p, c], i) => {
      const [tp, tc] = to.stops[i], [fp, fc] = from.stops[i];
      return [p + (tp - fp) * k, [Math.max(0, c[0] + (tc[0] - fc[0]) * k), c[1] + (tc[1] - fc[1]) * k, c[2] + (tc[2] - fc[2]) * k]];
    }),
  };
}
const gradCss = (g: Grad) =>
  `linear-gradient(${g.angle.toFixed(1)}deg, ${g.stops.map(([p, c]) => `${labCss(c)} ${p.toFixed(1)}%`).join(', ')})`;

// ---------- 各时段的样子 ----------
/** 天气本身是哪一类，不分白天夜里 */
type Condition = 'sun' | 'partly' | 'overcast' | 'rain' | 'thunder' | 'snow' | 'haze';
type DayTone = 'blue' | 'grey' | 'storm' | 'warm';
const CONDITION_OF: Record<SkyKind, Condition> = {
  sun: 'sun', night: 'sun', partly: 'partly', partlyNight: 'partly', overcast: 'overcast', overcastNight: 'overcast',
  rain: 'rain', rainNight: 'rain', thunder: 'thunder', snow: 'snow', haze: 'haze',
};
interface ConditionDef {
  /** 白天的色调：面板、侧栏盖什么颜色 */
  tone: DayTone;
  /** 中午和半夜的底色 */
  day: Grad;
  night: Grad;
  /** 日出日落的霞光透出来多少：晴天 1，云越厚越少 */
  glow: number;
  /** 天快黑透时白天的云乘的颜色：压到跟夜晚那张云图差不多暗，换成夜晚的云图时看不出来 */
  dark: Rgb;
}
const DECK_NIGHT = grad3(180, [0, .13, .025, 270], [55, .19, .035, 264], [100, .27, .04, 256]);
const CONDITIONS: Record<Condition, ConditionDef> = {
  sun: {
    tone: 'blue', glow: 1, dark: [.3, .3, .42],
    day: grad3(203, [0, .68, .105, 238], [36, .56, .125, 249], [100, .43, .135, 259]),
    night: grad(180, [0, .115, .04, 276], [42, .165, .06, 270], [82, .25, .08, 262], [100, .3, .085, 256]),
  },
  partly: {
    tone: 'blue', glow: .9, dark: [.39, .42, .5],
    day: grad3(203, [0, .66, .09, 238], [38, .55, .11, 249], [100, .44, .12, 258]),
    night: grad(180, [0, .125, .038, 274], [42, .175, .055, 268], [82, .25, .07, 261], [100, .29, .075, 256]),
  },
  overcast: {
    tone: 'grey', glow: .32, dark: [.33, .35, .44],
    day: grad3(180, [0, .4, .034, 256], [55, .47, .032, 251], [100, .54, .028, 246]),
    night: DECK_NIGHT,
  },
  rain: {
    tone: 'storm', glow: .2, dark: [.46, .49, .58],
    day: grad3(180, [0, .31, .04, 262], [55, .4, .046, 257], [100, .5, .042, 250]),
    night: DECK_NIGHT,
  },
  thunder: {
    tone: 'storm', glow: .1, dark: [.62, .62, .7],
    day: grad3(180, [0, .2, .035, 268], [55, .29, .045, 262], [100, .4, .045, 254]),
    night: grad3(180, [0, .11, .025, 272], [55, .16, .035, 266], [100, .23, .04, 258]),
  },
  // 下雪的夜里，雪和云把地上的灯光映回来，天比别的夜晚亮一点
  snow: {
    tone: 'grey', glow: .35, dark: [.34, .36, .46],
    day: grad3(180, [0, .43, .036, 252], [55, .5, .036, 246], [100, .58, .032, 240]),
    night: grad3(180, [0, .17, .03, 262], [55, .24, .035, 256], [100, .32, .035, 248]),
  },
  // 有霾的夜里，城市灯光把霾映成暗暗的褐色
  haze: {
    tone: 'warm', glow: .6, dark: [.42, .38, .36],
    day: grad3(180, [0, .5, .04, 74], [55, .57, .045, 76], [100, .63, .05, 78]),
    night: grad3(180, [0, .15, .02, 55], [55, .21, .03, 60], [100, .29, .04, 66]),
  },
};

/** 一个时刻（太阳在某个高度时）晴天的样子 */
interface Phase {
  /** 底色。夜里、中午两个时刻不写，用各天气自己的底色 */
  grad?: Grad;
  /** 地平线上那片暖光：OKLCH 三个数和浓度 */
  glow: [number, number, number, number];
  /** 被照亮的云乘的颜色。不写的是天快黑透以后，用各天气自己的 dark */
  cloud?: Rgb;
  /** 太阳：光晕、光芒各显示多少，以及偏暖的程度（0 是白色，1 是橙红）。太阳本身只看高度（见 lookOf） */
  sun: [number, number, number];
  /** 霞光有多重：面板、侧栏和上下压暗的那层颜色往紫红偏多少 */
  dusk: number;
}
interface Moment {
  /** 太阳高度（度） */
  el: number;
  /** 离白天有多近：0 是夜里，1 是白天。不是晴天的天气按它在自己的夜晚底色和白天底色之间取色 */
  day: number;
  /** 太阳在落（下午到半夜）、在升（半夜到中午）各一个样子：黄昏偏橙红，黎明偏粉紫、更淡 */
  set: Phase;
  rise: Phase;
}
const DARK: Phase = { glow: [.42, .1, 300, 0], sun: [0, 0, 1], dusk: 0 };
const NOON: Phase = { glow: [.8, .08, 80, 0], cloud: [1, 1, 1], sun: [1, 1, 0], dusk: 0 };
// 太阳高度从低到高的几个时刻。中午、上午下午这两个时刻的高度按当天正午太阳能升多高再定（见 momentAt）
const MOMENTS: Moment[] = [
  // 夜里
  { el: -14, day: 0, set: DARK, rise: DARK },
  // 天快黑透 / 天刚蒙蒙亮：深蓝，地平线留一点紫
  {
    el: -8, day: .05,
    set: { grad: grad(180, [0, .155, .05, 273], [42, .21, .07, 270], [80, .29, .085, 275], [100, .35, .08, 292]), glow: [.42, .1, 300, .16], sun: [0, 0, 1], dusk: .3 },
    rise: { grad: grad(180, [0, .16, .05, 271], [42, .22, .07, 267], [80, .3, .085, 266], [100, .36, .075, 282]), glow: [.45, .08, 290, .13], sun: [0, 0, 1], dusk: .25 },
  },
  // 黄昏的晚霞 / 黎明的朝霞：上面靛蓝，往下紫、玫红，地平线暗红（黎明偏蓝，地平线是粉色）
  {
    el: -4, day: .15,
    set: { grad: grad(180, [0, .24, .06, 275], [42, .32, .08, 290], [78, .42, .1, 335], [100, .5, .12, 25]), glow: [.58, .14, 22, .32], cloud: [.72, .54, .62], sun: [0, 0, 1], dusk: .8 },
    rise: { grad: grad(180, [0, .27, .06, 265], [42, .36, .07, 278], [78, .48, .08, 310], [100, .58, .09, 345]), glow: [.66, .1, 350, .3], cloud: [.7, .6, .74], sun: [0, 0, 1], dusk: .65 },
  },
  // 日落：上面深紫，往下玫红，地平线一片橙红；日出：上面是清亮的蓝，往下淡紫、粉，地平线金黄。云被照成橙粉色
  {
    el: -.5, day: .35,
    set: { grad: grad(180, [0, .36, .08, 275], [40, .46, .1, 310], [74, .58, .14, 20], [100, .66, .16, 48]), glow: [.74, .16, 45, .5], cloud: [1, .7, .58], sun: [.55, 0, 1], dusk: 1 },
    rise: { grad: grad(180, [0, .5, .09, 255], [40, .6, .07, 290], [72, .7, .1, 20], [100, .78, .12, 62]), glow: [.84, .12, 70, .45], cloud: [1, .82, .74], sun: [.6, 0, 1], dusk: .7 },
  },
  // 太阳刚升起不久 / 快落山：天还是蓝的，越往下越淡、越暖，太阳四周一大片金黄的光，云偏金黄
  {
    el: 4, day: .62,
    set: { grad: grad(196, [0, .64, .085, 244], [38, .58, .085, 250], [72, .55, .07, 262], [100, .56, .05, 300]), glow: [.8, .13, 68, .38], cloud: [1, .86, .7], sun: [1.5, .1, .75], dusk: .35 },
    rise: { grad: grad(200, [0, .68, .08, 236], [38, .62, .07, 242], [72, .6, .06, 255], [100, .62, .05, 290]), glow: [.85, .1, 82, .3], cloud: [1, .9, .8], sun: [1.35, .15, .55], dusk: .25 },
  },
  // 上午：比中午清透、偏青一点；下午：比中午淡一点，阳光微暖。晴天的云这时还是白的，不用上色
  {
    el: 12, day: .86,
    set: { grad: grad(200, [0, .68, .095, 240], [36, .565, .11, 251], [68, .5, .115, 256], [100, .445, .12, 262]), glow: [.8, .08, 80, 0], cloud: [1, 1, 1], sun: [1, .7, .18], dusk: 0 },
    rise: { grad: grad(205, [0, .7, .1, 232], [36, .58, .118, 244], [68, .505, .125, 252], [100, .45, .125, 258]), glow: [.8, .08, 80, 0], cloud: [1, 1, 1], sun: [1, .75, .05], dusk: 0 },
  },
  // 中午
  { el: 24, day: 1, set: NOON, rise: NOON },
];

/** 太阳此刻落在哪两个时刻之间、离前一个有多远（0 ~ 1） */
function momentAt(sun: SunLight): { a: Moment; b: Moment; t: number } {
  // 冬天、北方正午太阳升得低：按当天正午高度把"中午"放低，正午前后照样是中午的样子
  const noon = Math.max(6, Math.min(clamp(sun.peak - 8, 16, 28), sun.peak));
  const soft = clamp(noon - 5, 4.5, 12);
  const els = MOMENTS.map((m, i) => (i === MOMENTS.length - 1 ? Math.max(noon, soft + .5) : i === MOMENTS.length - 2 ? soft : m.el));
  const e = sun.elevation;
  let i = 0;
  while (i < els.length - 2 && e > els[i + 1]) i++;
  return { a: MOMENTS[i], b: MOMENTS[i + 1], t: clamp((e - els[i]) / (els[i + 1] - els[i]), 0, 1) };
}

/** 某种天空在太阳这个位置时的样子 */
interface Look {
  /** 底色渐变 */
  base: Grad;
  /** 地平线暖光 */
  glow: Paint;
  /** 云乘的颜色，[1, 1, 1] 是不染色 */
  cloud: Rgb;
  /** 太阳：圆盘、光晕、光芒、偏暖程度 */
  sun: [number, number, number, number];
  moon: number;
  stars: number;
  meteor: boolean;
  /** 离白天有多近：0 是夜里，1 是白天 */
  day: number;
  /** 霞光有多重（已经按天气打过折） */
  dusk: number;
  /** 夜色有多深：面板、侧栏换成夜里样子的程度 */
  night: number;
}

/** 晴天在某个时刻的底色：夜里、中午两个时刻用晴天自己的底色 */
const clearGrad = (m: Moment, phase: Phase) => phase.grad ?? (m.day >= 1 ? CONDITIONS.sun.day : CONDITIONS.sun.night);

function lookOf(kind: SkyKind, sun: SunLight): Look {
  const cond = CONDITION_OF[kind], C = CONDITIONS[cond], S = CONDITIONS.sun, K = SKIES[kind];
  const { a, b, t } = momentAt(sun);
  const pa = sun.rising ? a.rise : a.set, pb = sun.rising ? b.rise : b.set;
  const day = mix(a.day, b.day, t), el = sun.elevation;
  // 底色：先按"离白天多近"在这种天气自己的夜晚、白天底色之间取色，再把晴天这个时段特有的颜色按霞光的比例加上去
  const clear = mixGrad(clearGrad(a, pa), clearGrad(b, pb), t);
  const base = shiftGrad(mixGrad(C.night, C.day, day), mixGrad(S.night, S.day, day), clear, C.glow);
  const [ga, gb] = [pa.glow, pb.glow].map(([L, Ch, H, alpha]): Paint => [lch(L, Ch, H), alpha]);
  const [glowColor, glowAlpha] = mixPaint(ga, gb, t);
  // 云：晴天的云被照成霞光的颜色；云越厚，越接近只是跟着天色变暗。天黑透以后用的是夜晚的云图，不染色
  const lit = mixRgb(pa.cloud ?? C.dark, pb.cloud ?? C.dark, t);
  const cloud: Rgb = NIGHT_KINDS.has(kind) ? [1, 1, 1] : mixRgb(mixRgb(C.dark, [1, 1, 1], day), lit, C.glow);
  // 太阳本身：升到 2.5 度以上才完整露出来，0.5 度以下看不见。日出日落那一刻太阳贴着地平线，被下面的面板挡着，只看得见那一片暖光
  const [sunGlow, rays, warm] = pa.sun.map((v, i) => mix(v, pb.sun[i], t));
  const sunNow: Look['sun'] = K.sun ? [smooth(.5, 2.5, el), sunGlow, rays, warm] : [0, 0, 0, 0];
  return {
    base,
    glow: [glowColor, glowAlpha * C.glow],
    cloud,
    sun: sunNow,
    moon: K.moon ? smooth(-3, -9, el) : 0,
    stars: K.stars ? K.stars * smooth(-5, -13, el) : 0,
    meteor: Boolean(K.meteor) && el < -12,
    day,
    dusk: mix(pa.dusk, pb.dusk, t) * C.glow,
    night: smooth(-1.5, -8, el),
  };
}

/** 地平线暖光：从窗口底边往上铺开的一大片，最亮的地方在太阳那一侧的正下方（x 是太阳的横向位置） */
const glowCss = ([color, alpha]: Paint, x: string) =>
  `radial-gradient(150% 85% at ${x} 112%, ${labCss(color, alpha)}, ${labCss(color, alpha * .55)} 38%, ${labCss(color, 0)} 72%)`;

// ---------- 面板、侧栏的颜色 ----------
interface ToneDef {
  /** 选中的地点标签上文字的色相 */
  hue: number;
  /** 侧栏那片磨砂玻璃上盖的颜色 */
  side: Paint;
  /** 玻璃面板上盖的颜色 */
  glass: Paint;
  /** 温度条等细条的底色 */
  track: Paint;
}
const WHITE = rgb(255, 255, 255);
const TONES: Record<DayTone | 'dusk' | 'night', ToneDef> = {
  blue: { hue: 250, side: [lch(.34, .09, 256), .34], glass: [lch(.3, .09, 256), .3], track: [rgb(4, 18, 46), .26] },
  grey: { hue: 252, side: [lch(.3, .02, 255), .3], glass: [lch(.27, .02, 255), .26], track: [rgb(10, 16, 28), .28] },
  storm: { hue: 258, side: [lch(.22, .035, 262), .3], glass: [lch(.2, .035, 262), .28], track: [rgb(6, 12, 30), .3] },
  warm: { hue: 70, side: [lch(.32, .035, 70), .3], glass: [lch(.3, .035, 70), .26], track: [rgb(40, 28, 10), .26] },
  // 日出日落前后：跟着霞光偏紫红
  dusk: { hue: 305, side: [lch(.3, .07, 305), .32], glass: [lch(.27, .07, 312), .3], track: [rgb(36, 14, 46), .28] },
  // 夜里：天已经够暗，面板只盖一层很淡的白
  night: { hue: 272, side: [WHITE, .05], glass: [WHITE, .04], track: [WHITE, .1] },
};
function mixTone(x: ToneDef, y: ToneDef, t: number): ToneDef {
  return { hue: t < .5 ? x.hue : y.hue, side: mixPaint(x.side, y.side, t), glass: mixPaint(x.glass, y.glass, t), track: mixPaint(x.track, y.track, t) };
}

/** 跟这片天空配套的面板、侧栏颜色，写成样式变量：--wx-h、--side 给天气页的边框用，--sky-glass-c/-a、--sky-track 给玻璃面板用（见 weather.css） */
export function skyToneStyle(kind: SkyKind, sun: SunLight): Record<string, string> {
  const { a, b, t } = momentAt(sun);
  const cond = CONDITION_OF[kind], C = CONDITIONS[cond];
  const dusk = mix((sun.rising ? a.rise : a.set).dusk, (sun.rising ? b.rise : b.set).dusk, t) * C.glow;
  const tone = mixTone(mixTone(TONES[C.tone], TONES.dusk, dusk), TONES.night, smooth(-1.5, -8, sun.elevation));
  return {
    '--wx-h': String(tone.hue),
    '--side': labCss(...tone.side),
    '--sky-glass-c': labCss(tone.glass[0]),
    '--sky-glass-a': tone.glass[1].toFixed(3),
    '--sky-track': labCss(...tone.track),
  };
}

/** 这种天气此刻的底色：天空最底下那一层渐变加上地平线暖光，不带云、雨、雪、星星 */
export function skyBase(kind: SkyKind, sun: SunLight): string {
  const look = lookOf(kind, sun);
  return look.glow[1] > .004 ? `${glowCss(look.glow, ORB_X)}, ${gradCss(look.base)}` : gradCss(look.base);
}

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

/** 太阳落到地平线下 8 度以后（天快黑透）换成夜晚那套云图，太阳升到这个高度以上换回白天那套。
 *  这时白天的云已经压得跟夜晚的云差不多暗，换的时候看不出来 */
const NIGHT_BELOW = -8;

/** 按彩云的天气代码和太阳的位置，决定背景用哪一种天空。
 *  彩云只给晴和多云分了白天、夜晚两种代码，而且分界跟这里不一样：这里只按代码认天气，白天夜里按太阳高度另算 */
export function resolveSkyKind(skycon: string | null | undefined, sun: SunLight): SkyKind {
  const dark = sun.elevation < NIGHT_BELOW;
  if (!skycon) return dark ? 'night' : 'sun';
  const info = skyInfo(skycon);
  if (info.icon === 'thunder') return 'thunder';
  if (info.tone === 'rain') return dark ? 'rainNight' : 'rain';
  if (info.tone === 'snow') return 'snow';
  if (info.icon === 'partly' || info.icon === 'partly-night' || info.tone === 'wind') return dark ? 'partlyNight' : 'partly';
  if (info.tone === 'haze') return 'haze';
  if (info.tone === 'cloud') return dark ? 'overcastNight' : 'overcast';
  return dark ? 'night' : 'sun';
}

// ---------- 把天空放进页面 ----------
/** 一层天空里随时段变的那些元素，mountSky 时找好存起来，setSkyTime 直接改它们 */
interface Mounted {
  kind: SkyKind;
  w: number;
  h: number;
  /** 太阳、月亮的位置和大小倍数 */
  orb: { x: string; y: string; scale: number };
  parts: Partial<Record<'base' | 'glow' | 'light' | 'night' | 'sunGlow' | 'rays' | 'sun' | 'moonGlow' | 'moon' | 'clouds' | 'sunThrough' | 'moonThrough' | 'rain' | 'mist' | 'veil', HTMLElement>>;
  snow: HTMLElement[];
  meteors: HTMLElement[];
  tint: SVGFEColorMatrixElement | null;
  /** 上一次按哪个太阳位置上的色，位置没变就不用再改 */
  applied: string;
}
const mounted = new WeakMap<HTMLElement, Mounted>();
let tintCount = 0;

/** 值很小时整层不画（不占显卡），否则按这个值设不透明度 */
function showAt(node: HTMLElement | undefined, value: number) {
  if (!node) return;
  const visible = value > .003;
  node.style.display = visible ? '' : 'none';
  if (visible) node.style.opacity = String(Math.min(1, value).toFixed(3));
}

export function setSkyTime(sky: HTMLElement, sun: SunLight): void {
  const m = mounted.get(sky);
  if (!m) return;
  const key = `${sun.elevation.toFixed(2)},${sun.rising},${sun.peak.toFixed(1)}`;
  if (m.applied === key) return;
  m.applied = key;
  const K = SKIES[m.kind], P = m.parts, look = lookOf(m.kind, sun);
  const glowAt = (px: number, stops: string) => `radial-gradient(${px * m.orb.scale}px circle at ${m.orb.x} ${m.orb.y}, ${stops})`;

  P.base!.style.background = gradCss(look.base);
  showAt(P.glow, look.glow[1] > .004 ? 1 : 0);
  if (look.glow[1] > .004) P.glow!.style.background = glowCss(look.glow, m.orb.x);
  // 阴天顶上透出来的亮光，天越暗越淡
  showAt(P.light, smooth(.2, .8, look.day));

  if (P.night) {
    if (look.stars > .003 && !P.night.dataset.ready) {
      // 星空图要按容器大小画，用到时才画：白天的天空一直不画
      P.night.dataset.ready = '1';
      const stars = starFieldCopy(m.w, m.h);
      stars.className = 'wx-sky-stars';
      P.night.insertAdjacentHTML('afterbegin', twinklers(Math.round(m.w * m.h / 36000)));
      P.night.prepend(stars);
    }
    showAt(P.night, look.stars);
    m.meteors.forEach(node => { node.style.display = look.meteor ? '' : 'none'; });
  }

  if (K.sun) {
    const [disc, glow, rays, warm] = look.sun;
    const tone = (white: Rgb, orange: Rgb) => mixRgb(white, orange, warm);
    const s = glow * K.sun.glow;
    showAt(P.sunGlow, s > .003 ? 1 : 0);
    // 太阳越低、光越暖，四周那片光铺得越开
    if (s > .003) P.sunGlow!.style.background = glowAt(640 * (1 + .45 * warm), `${rgbCss(tone([255, 248, 228], [255, 196, 128]), .5 * s)}, ${rgbCss(tone([255, 244, 214], [255, 170, 100]), .2 * s)} 22%, ${rgbCss(tone([255, 240, 204], [255, 150, 90]), .07 * s)} 55%, transparent`);
    showAt(P.rays, rays * (K.rays ?? 0));
    showAt(P.sun, disc);
    if (disc > .003) {
      const style = P.sun!.style;
      const set = (name: string, white: Rgb, orange: Rgb) => style.setProperty(name, tone(white, orange).map(v => Math.round(v)).join(' '));
      set('--sun-core', [255, 255, 255], [255, 226, 170]);
      set('--sun-rim', [255, 251, 236], [255, 200, 130]);
      set('--sun-edge', [255, 246, 218], [255, 180, 110]);
      set('--sun-halo1', [255, 248, 226], [255, 190, 120]);
      set('--sun-halo2', [255, 240, 200], [255, 160, 90]);
      set('--sun-halo3', [255, 236, 190], [255, 140, 80]);
    }
    const through = (K.sun.through ?? 0) * disc;
    showAt(P.sunThrough, through ? 1 : 0);
    if (through) P.sunThrough!.style.background = glowAt(400, `${rgbCss(tone([255, 251, 236], [255, 200, 140]), through)}, ${rgbCss(tone([255, 246, 220], [255, 180, 120]), through * .32)} 42%, transparent`);
  }
  showAt(P.moonGlow, look.moon);
  showAt(P.moon, look.moon);
  showAt(P.moonThrough, look.moon);

  // 云的颜色：白天不染色就不挂滤镜，省掉每帧多出来的一遍处理
  if (P.clouds && m.tint) {
    const [r, g, b] = look.cloud;
    const plain = Math.abs(r - 1) + Math.abs(g - 1) + Math.abs(b - 1) < .006;
    if (!plain) m.tint.setAttribute('values', `${r.toFixed(4)} 0 0 0 0 0 ${g.toFixed(4)} 0 0 0 0 0 ${b.toFixed(4)} 0 0 0 0 0 1 0`);
    P.clouds.style.filter = plain ? '' : `url(#${m.tint.parentElement!.id})`;
  }

  // 雨丝、雪花、底部水汽：白天的那套天空到了傍晚跟着暗下去；夜晚那套本来就是按夜里调的
  const night = NIGHT_KINDS.has(m.kind);
  const fall = night ? 1 : mix(.7, 1, look.day);
  if (P.rain) P.rain.style.opacity = fall.toFixed(3);
  m.snow.forEach(node => { node.style.opacity = fall.toFixed(3); });
  if (P.mist) P.mist.style.opacity = (night ? 1 : mix(.5, 1, look.day)).toFixed(3);
  // 顶上和底下各压暗一点：标题栏的字、底部面板里的字压在亮云上也看得清。
  // 霞光重的时候这层暗色偏紫红、底下那层也轻一些，地平线的霞光不会被压成灰褐色
  const shade = mixLab(rgb(6, 12, 32), lch(.17, .05, 320), look.dusk);
  P.veil!.style.background = `linear-gradient(180deg, ${labCss(shade, .2)} 0, transparent 20%), linear-gradient(0deg, ${labCss(shade, .22 * (1 - .4 * look.dusk))}, transparent 52%)`;
}

/** 太阳、月亮默认放在窗口最上面一条里、右上角那排状态标签左边的空位：这一带没有文字，页面内容怎么排都压不到它 */
const ORB_X = 'calc(100% - 380px)';

export function mountSky(host: HTMLElement, kind: SkyKind, sun: SunLight, opts: SkyOptions = {}): HTMLElement {
  const K = SKIES[kind], w = host.clientWidth || 1480, h = host.clientHeight || 920;
  const orb = { x: ORB_X, y: '40px', scale: 1, ...opts.orb };
  const length = (value: number | string) => typeof value === 'number' ? `${value}%` : value;
  const orbX = length(orb.x), orbY = length(orb.y), at = `left:${orbX};top:${orbY}`;
  const calm = { x: 37, y: 29, rx: 34, ry: 20, ...opts.calm };
  const cs = opts.cloudScale || 1;
  const fill = (style: string) => `<div class="wx-sky-fill" style="${style}"></div>`;
  const part = (name: string, style = '') => `<div class="wx-sky-fill" data-part="${name}"${style ? ` style="${style}"` : ''}></div>`;
  const glowAt = (px: number, stops: string) => `radial-gradient(${px * orb.scale}px circle at ${orbX} ${orbY}, ${stops})`;
  const tintId = `wx-sky-tint-${++tintCount}`;
  // 云的上色用一个颜色矩阵滤镜：RGB 各乘一个数，透明度不变
  const out = [`<svg class="wx-sky-defs" aria-hidden="true"><filter id="${tintId}" x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 1 0" /></filter></svg>`];
  out.push(part('base'), part('glow'));
  if (K.light) out.push(part('light', `background:${K.light}`));
  if (K.stars) {
    const meteors = K.meteor ? '<i class="wx-sky-meteor" style="left:58%;top:13%;--dur:17s;--delay:-11s"></i><i class="wx-sky-meteor" style="left:36%;top:6%;--dur:29s;--delay:-9s"></i>' : '';
    out.push(`<div class="wx-sky-night" data-part="night">${meteors}</div>`);
  }
  if (K.sun) {
    out.push(part('sunGlow'));
    if (K.rays) out.push(`<div class="wx-sky-orb" data-part="rays" style="${at};transform:scale(${orb.scale})"><div class="wx-sky-rays"></div></div>`);
    out.push(`<div class="wx-sky-orb" data-part="sun" style="${at};transform:scale(${orb.scale})"><div class="wx-sky-sun"></div></div>`);
  }
  if (K.moon) {
    // 月亮四周一大片很淡的月光，把附近的夜空映亮一点
    out.push(part('moonGlow', `background:${glowAt(520, `rgb(170 192 255 / ${.22 * K.moon.glow}), rgb(150 176 250 / ${.08 * K.moon.glow}) 45%, transparent`)}`));
    out.push(`<div class="wx-sky-orb" data-part="moon" style="${at};transform:scale(${orb.scale})"><div class="wx-sky-moon" style="background-image:url(${imageUrl('moon')})"></div></div>`);
  }
  if (K.clouds) {
    out.push(`<div class="wx-sky-wrap${K.fade ? ' fade' : ''}" data-part="clouds" style="--calm:radial-gradient(ellipse ${calm.rx}% ${calm.ry}% at ${calm.x}% ${calm.y}%, rgb(0 0 0 / .3) 0, rgb(0 0 0 / .42) 55%, #000 100%)">`);
    K.clouds.forEach((c, i) => {
      const tile = Math.round(c.tile / 920 * h * cs), size = IMAGE_SIZE[c.tex];
      out.push(`<div class="wx-sky-cloud" style="top:${c.top * cs}%;height:${Math.round(tile * size[1] / size[0])}px;opacity:${c.opacity};background-image:url(${imageUrl(c.tex)});--tile:${tile}px;--dur:${c.dur}s;--delay:${-(c.dur * (.17 + i * .31)).toFixed(0)}s"></div>`);
    });
    out.push('</div>');
  }
  if (K.shade) out.push(fill(`background:radial-gradient(ellipse ${calm.rx * 1.25}% ${calm.ry * 1.35}% at ${calm.x}% ${calm.y}%, rgb(8 14 34 / ${K.shade}), rgb(8 14 34 / ${K.shade * .7}) 50%, transparent 100%)`));
  // 太阳、月亮被云挡住时，云上还留一团透出来的光
  if (K.sun?.through) out.push(part('sunThrough'));
  if (K.moon?.through) out.push(part('moonThrough', `background:${glowAt(300, `rgb(206 220 255 / ${K.moon.through}), rgb(176 196 255 / ${K.moon.through * .3}) 42%, transparent`)}`));
  if (K.rain) {
    out.push(`<div class="wx-sky-fall-wrap" data-part="rain" style="--tilt:${K.rain.tilt}deg">`);
    K.rain.layers.forEach(([name, dur, op], i) => {
      const o = RAINS[name];
      out.push(`<div class="wx-sky-fall" style="opacity:${op};background-image:url(${cached('rain:' + name, () => rainTex(o))});background-size:${o.w}px ${o.h}px;--th:${o.h}px;--dur:${dur}s;--delay:${-(dur * i * .37).toFixed(2)}s"></div>`);
    });
    out.push('</div>');
  }
  if (K.snow) {
    ([['far', 15, 9], ['mid', 10, 7], ['near', 6.5, 5]] as Array<[keyof typeof SNOWS, number, number]>).forEach(([name, dur, sway], i) => {
      const o = SNOWS[name];
      out.push(`<div class="wx-sky-sway" data-snow style="--dur:${sway}s"><div class="wx-sky-fall" style="background-image:url(${cached('snow:' + name, () => snowTex(o))});background-size:${o.w}px ${o.h}px;--th:${o.h}px;--dur:${dur}s;--delay:${-(dur * i * .41).toFixed(1)}s"></div></div>`);
    });
  }
  if (K.mist) out.push(part('mist', `background:linear-gradient(0deg, ${K.mist}, transparent 46%)`));
  if (K.flash) out.push('<div class="wx-sky-flash f1"></div><div class="wx-sky-flash f2"></div>');
  out.push(part('veil'));

  const el = document.createElement('div');
  el.className = 'wx-sky';
  el.dataset.kind = kind;
  el.innerHTML = out.join('');
  const parts: Mounted['parts'] = {};
  el.querySelectorAll<HTMLElement>('[data-part]').forEach(node => { parts[node.dataset.part as keyof Mounted['parts']] = node; });
  mounted.set(el, {
    kind, w, h, orb: { x: orbX, y: orbY, scale: orb.scale }, parts,
    snow: Array.from(el.querySelectorAll<HTMLElement>('[data-snow]')),
    meteors: Array.from(el.querySelectorAll<HTMLElement>('.wx-sky-meteor')),
    tint: el.querySelector('feColorMatrix'),
    applied: '',
  });
  setSkyTime(el, sun);
  host.appendChild(el);
  return el;
}
