// 天空背景组件：把 lib/sky 画的天空放进一个容器里。天气种类变了，新天空叠在旧的上面淡入，淡入完再把旧的拿掉；
// 只是太阳位置变了（时段在变），直接给现有的那层天空改颜色，不重画。
import * as React from 'react';
import { mountSky, setSkyTime, type SkyKind, type SkyOptions } from '../lib/sky';
import { sunAt, type SunLight } from '../lib/sun';
import { DEFAULT_WEATHER_LOCATION } from '../lib/weatherLocations';

const CROSSFADE_MS = 720;
const RESIZE_DELAY = 200;

/** 某个地点此刻的太阳位置。高度只取到 0.1 度：太阳每分钟才挪一点，取整后大多数时候拿到的是同一个对象，天空不用重新上色 */
export function useSunLight(latitude: number, longitude: number, now: Date): SunLight {
  const known = Number.isFinite(latitude) && Number.isFinite(longitude);
  const sun = sunAt(known ? latitude : DEFAULT_WEATHER_LOCATION.latitude, known ? longitude : DEFAULT_WEATHER_LOCATION.longitude, now);
  const elevation = Math.round(sun.elevation * 10) / 10, peak = Math.round(sun.peak * 10) / 10;
  return React.useMemo(() => ({ elevation, rising: sun.rising, peak }), [elevation, sun.rising, peak]);
}

export function WeatherSky({ kind, sun, options, className }: {
  kind: SkyKind;
  /** 当地此刻的太阳位置，决定天空是哪个时段的颜色 */
  sun: SunLight;
  /** 太阳月亮的位置、云层放大倍数等，只在第一次读取，之后变了不会重画 */
  options?: SkyOptions;
  className?: string;
}) {
  const hostRef = React.useRef<HTMLDivElement>(null);
  const optionsRef = React.useRef(options);
  const sunRef = React.useRef(sun);
  sunRef.current = sun;

  React.useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const previous = Array.from(host.children);
    const sky = mountSky(host, kind, sunRef.current, optionsRef.current);
    if (!previous.length) return;
    sky.classList.add('is-entering');
    const timer = window.setTimeout(() => previous.forEach(node => node.remove()), CROSSFADE_MS + 40);
    return () => {
      window.clearTimeout(timer);
      previous.forEach(node => node.remove());
    };
  }, [kind]);

  // 时段变了：给最上面（最新）那层天空重新上色
  React.useEffect(() => {
    const sky = hostRef.current?.lastElementChild;
    if (sky instanceof HTMLElement) setSkyTime(sky, sun);
  }, [sun]);

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
        mountSky(host, kind, sunRef.current, optionsRef.current);
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
