// 天空背景组件：把 lib/sky 画的天空放进一个容器里。天气种类变了，新天空叠在旧的上面淡入，淡入完再把旧的拿掉。
import * as React from 'react';
import { mountSky, type SkyKind, type SkyOptions } from '../lib/sky';

const CROSSFADE_MS = 720;
const RESIZE_DELAY = 200;

export function WeatherSky({ kind, options, className }: {
  kind: SkyKind;
  /** 太阳月亮的位置、云层放大倍数等，只在第一次读取，之后变了不会重画 */
  options?: SkyOptions;
  className?: string;
}) {
  const hostRef = React.useRef<HTMLDivElement>(null);
  const optionsRef = React.useRef(options);

  React.useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const previous = Array.from(host.children);
    const sky = mountSky(host, kind, optionsRef.current);
    if (!previous.length) return;
    sky.classList.add('is-entering');
    const timer = window.setTimeout(() => previous.forEach(node => node.remove()), CROSSFADE_MS + 40);
    return () => {
      window.clearTimeout(timer);
      previous.forEach(node => node.remove());
    };
  }, [kind]);

  // 云图铺多宽、星空画多大都是按容器大小算的：容器大小变了（比如窗口最大化），等停下来重画一遍
  React.useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let width = host.clientWidth, height = host.clientHeight, timer = 0;
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (host.clientWidth === width && host.clientHeight === height) return;
        width = host.clientWidth; height = host.clientHeight;
        if (!width || !height) return;
        host.replaceChildren();
        mountSky(host, kind, optionsRef.current);
      }, RESIZE_DELAY);
    });
    observer.observe(host);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, [kind]);

  return <div ref={hostRef} className={className} aria-hidden="true" />;
}
