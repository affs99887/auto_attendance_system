// 液态玻璃面板：天气页和首页天气卡片上的面板都用它。
// 从下到上一共三层，都垫在内容下面（样式见 weather.css 的 .wx-glass）：
//   ::before        把面板后面的背景模糊掉
//   .wx-glass-lens  让背景在面板边缘一圈被弯折（滤镜），上面再叠一张边缘高光的图。两张图都用开源库 @avenra/liquid-glass 算
//   ::after         一层很淡的底色、边缘的亮线和面板下方的投影
// 另外带两张画布，下雨、下雪时由 lib/panelFx 往上画水雾、水珠和积雪。
import * as React from 'react';
import { compute1D, compute2D, computeSpecular, imageDataToURL, maxDisp, nextFilterId } from '@avenra/liquid-glass';
import { attachPanel, detachPanel, setPanelFall } from '../lib/panelFx';
import { skyFall, type SkyKind } from '../lib/sky';

const BEZEL = 20;             // 边缘那圈"弯折带"最宽多少像素；不能超过面板圆角，所以实际取 min(它, 圆角 - 2)
const THICKNESS = 140;        // 玻璃厚度，越大边缘弯折越明显
const REFRACTIVE_INDEX = 1.5; // 玻璃的折射率
const SPECULAR_ALPHA = .7;    // 边缘高光的浓淡
// 弯折用的那张图最多这么多个像素，面板再大就按比例缩小着画，但最多缩到 1/3。
// 滤镜里的图每一帧都要整张交给显卡重新处理，图越大越耗时（集成显卡上，按面板原大小画会让整页掉到 30 多帧）；
// 这张图本身是平滑过渡的，缩小后再拉伸回去看不出差别
const DISP_MAP_PIXELS = 24000;
const DISP_MAP_MAX_SHRINK = 3;
const REBUILD_DELAY = 120;
const SVG_NS = 'http://www.w3.org/2000/svg';

// 同样大小、同样圆角的面板算出来的两张图是一样的。页面重新出现时（比如从"全部地点"放大回天气页）直接用上次算好的，
// 不用再算一遍：算图加转成图片要几十毫秒，正赶上动画开始时会让动画卡一下
const IMAGE_CACHE_MAX = 40;
const imageCache = new Map<string, string>();
function cachedImage(key: string, make: () => string): string {
  let url = imageCache.get(key);
  if (url === undefined) {
    url = make();
    if (imageCache.size >= IMAGE_CACHE_MAX) imageCache.delete(imageCache.keys().next().value as string);
    imageCache.set(key, url);
  }
  return url;
}

/** 建一个只做"按一张图把背景弯折"的滤镜。图会被拉伸到 width × height（面板大小），scale 是图里最大值对应弯折多少像素 */
function createBendFilter(id: string, width: number, height: number, mapUrl: string, scale: number): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('aria-hidden', 'true');
  svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
  svg.innerHTML = `<filter id="${id}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">`
    + `<feImage href="${mapUrl}" x="0" y="0" width="${width}" height="${height}" preserveAspectRatio="none" result="map"/>`
    + `<feDisplacementMap in="SourceGraphic" in2="map" scale="${scale}" xChannelSelector="R" yChannelSelector="G"/>`
    + '</filter>';
  return svg;
}

/** 边缘高光那张图：库算出来的每个点是"一个深浅不同的灰色 + 透明度"，这里换算成"纯白 + 透明度"，当普通图片叠在面板上，
 *  效果和放在滤镜里用"滤色"方式叠加是一样的 */
function specularImageUrl(width: number, height: number, radius: number, bezel: number): string {
  const image = computeSpecular(width, height, radius, bezel), data = image.data;
  for (let i = 0; i < data.length; i += 4) {
    data[i + 3] = Math.round(data[i] * data[i + 3] / 255 * SPECULAR_ALPHA);
    data[i] = data[i + 1] = data[i + 2] = 255;
  }
  return imageDataToURL(image);
}

/** 给 lens 这一层装上"边缘弯折"的滤镜和边缘高光的图。两张图都是按面板大小算的，面板大小变了要重算 */
function useGlassLens(hostRef: React.RefObject<HTMLElement>, lensRef: React.RefObject<HTMLElement>) {
  React.useLayoutEffect(() => {
    const host = hostRef.current, lens = lensRef.current;
    if (!host || !lens) return;
    let svg: SVGSVGElement | null = null;
    let width = 0, height = 0, timer = 0;

    const rebuild = () => {
      const w = host.clientWidth, h = host.clientHeight;
      if (!w || !h || (w === width && h === height)) return;
      width = w; height = h;
      // 胶囊形的圆角写的是 999px，实际圆角最大只到短边的一半
      const radius = Math.min(parseFloat(getComputedStyle(host).borderTopLeftRadius) || 0, w / 2, h / 2);
      const bezel = Math.max(1, Math.min(BEZEL, radius - 2));
      // 从面板边缘往里，每个位置的背景要挪多远
      const bend = compute1D(THICKNESS, bezel, 'convexSquircle', REFRACTIVE_INDEX);
      const maxBend = maxDisp(bend);
      const shrink = Math.min(DISP_MAP_MAX_SHRINK, Math.max(1, Math.sqrt(w * h / DISP_MAP_PIXELS)));
      const shape = `${w}x${h}:${radius}:${bezel}`;
      const mapUrl = cachedImage(`map:${shape}`, () => imageDataToURL(compute2D(
        Math.max(1, Math.round(w / shrink)), Math.max(1, Math.round(h / shrink)),
        radius / shrink, bezel / shrink, maxBend || 1, bend,
      )));
      // 每次重算都新建一个滤镜、换一个新名字，再把旧的删掉：面板引用的名字变了，浏览器就会按新滤镜重画。
      // 模糊不放进这个滤镜，由样式里的 ::before 单独做：改一个样式变量就能马上生效
      const filterId = nextFilterId('wx-glass');
      const filter = createBendFilter(filterId, w, h, mapUrl, maxBend);
      document.body.appendChild(filter);
      lens.style.setProperty('-webkit-backdrop-filter', `url("#${filterId}")`);
      lens.style.setProperty('backdrop-filter', `url("#${filterId}")`);
      lens.style.setProperty('--wx-spec', `url("${cachedImage(`spec:${shape}`, () => specularImageUrl(w, h, radius, bezel))}")`);
      svg?.remove();
      svg = filter;
    };

    rebuild();
    // 拖窗口边缘时大小会连续变很多次，等停下来再重算
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(rebuild, REBUILD_DELAY);
    });
    observer.observe(host);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
      svg?.remove();
    };
  }, [hostRef, lensRef]);
}

type GlassPanelProps = React.HTMLAttributes<HTMLElement> & {
  /** 渲染成什么标签，默认 div */
  as?: 'div' | 'section' | 'button';
  /** 下雪时这块面板最多积多厚的雪（像素）；不写就按面板高度自动定 */
  snowCap?: number;
  /** as="button" 时用 */
  type?: 'button';
  disabled?: boolean;
};

export function GlassPanel({ as = 'div', className, children, snowCap, ...rest }: GlassPanelProps) {
  const hostRef = React.useRef<HTMLElement>(null);
  const lensRef = React.useRef<HTMLSpanElement>(null);
  const topRef = React.useRef<HTMLCanvasElement>(null);
  const faceRef = React.useRef<HTMLCanvasElement>(null);
  useGlassLens(hostRef, lensRef);

  React.useEffect(() => {
    const host = hostRef.current, top = topRef.current, face = faceRef.current;
    if (!host || !top || !face) return;
    attachPanel(host, top, face);
    return () => detachPanel(host);
  }, []);

  const Tag = as as React.ElementType;
  return (
    <Tag ref={hostRef} className={`wx-glass ${className || ''}`} data-snow={snowCap} {...rest}>
      <span className="wx-glass-lens" ref={lensRef} aria-hidden="true" />
      {children}
      <canvas className="wx-fx wx-fx-top" ref={topRef} aria-hidden="true" />
      <canvas className="wx-fx wx-fx-face" ref={faceRef} aria-hidden="true" />
    </Tag>
  );
}

/** 页面告诉面板们现在的天空是哪一种：下雨就溅水、凝水珠，下雪就积雪。页面离开时停掉 */
export function usePanelFall(kind: SkyKind | null) {
  React.useEffect(() => {
    if (!kind) return;
    const fall = skyFall(kind);
    setPanelFall(fall.mode, fall.level);
    return () => setPanelFall('');
  }, [kind]);
}
