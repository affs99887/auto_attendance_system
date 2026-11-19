import * as React from 'react';
import { flushSync } from 'react-dom';
import { useApp, WEATHER_SHELL_TRANSITION_MS } from '../App';
import { Icon } from '../lib/icons';
import type { WeatherDailyItem, WeatherResponse } from '../lib/api';
import { useStartupStore } from '../store/startup';
import {
  EMPTY_WEATHER_ENTRY,
  selectActiveWeatherEntry,
  selectActiveWeatherLocation,
  useWeatherStore,
} from '../store/weather';
import {
  GLASS_BLUR_MAX,
  GLASS_TINT_MAX,
  useWeatherGlassStore,
} from '../store/weatherGlass';
import {
  roundWeather,
  skyInfo,
  weatherDayLabel,
  weatherTransitionLabel,
  windDirection,
} from '../lib/weather';
import { DEFAULT_WEATHER_LOCATION, type WeatherLocation } from '../lib/weatherLocations';
import { appConfirm } from '../lib/dialog';
import { resolveSkyKind, skyBase, warmSkyTextures, type SkyKind } from '../lib/sky';
import { sunAt, type SunLight } from '../lib/sun';
import { GlassPanel, usePanelFall } from '../components/GlassPanel';
import { PlaceCard, WeatherPlaces } from '../components/WeatherPlaces';
import {
  HelmetPanel,
  WeatherHourlyChart,
  WeatherIcon,
  weatherShortText,
  weatherUpdateTime,
} from '../components/WeatherPanel';

function metricValue(value: number | null, suffix = '', digits = 0): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(digits)}${suffix}`;
}

const SKELETON_DAYS = [0, 1, 2, 3, 4, 5, 6];
const SKELETON_METRICS = [0, 1, 2, 3, 4, 5, 6, 7];

/** 天气数据还没回来时的占位：排版跟正式页面一样，文字和图表的位置先放淡淡的色块，数据一到页面不会跳动 */
function WeatherLoading({ location }: { location: WeatherLocation }) {
  return (
    <>
      <section className="wx-hero" role="status" aria-live="polite" aria-busy="true">
        <div className="wx-hero-now">
          <div className="wx-hero-addr">
            <strong>{location.address}</strong>
            <span className="mono">{location.longitude.toFixed(4)}, {location.latitude.toFixed(4)}</span>
            <span className="wx-loading-tip"><span className="spinner" />正在连接彩云天气</span>
          </div>
          <div className="wx-hero-main wx-skel" aria-hidden="true">
            <div className="wx-hero-temp"><i className="wx-bone wx-skel-temp" /></div>
            <div className="wx-hero-copy">
              <i className="wx-bone" style={{ width: 132, height: 20 }} />
              <i className="wx-bone" style={{ width: 196, height: 12, marginTop: 10 }} />
              <i className="wx-bone" style={{ width: 248, height: 13, marginTop: 26 }} />
            </div>
          </div>
        </div>
        <GlassPanel className="wx-helmet" aria-hidden="true">
          <div className="wx-skel">
            <div className="wx-helmet-head">
              <i className="wx-bone wx-helmet-ico" />
              <div className="wx-helmet-copy">
                <i className="wx-bone" style={{ width: '56%', height: 15, marginTop: 2 }} />
                <i className="wx-bone" style={{ width: '82%', height: 11, marginTop: 9 }} />
              </div>
            </div>
            <i className="wx-bone" style={{ height: 16, marginTop: 40 }} />
            <i className="wx-bone" style={{ height: 9, marginTop: 8, opacity: .5 }} />
          </div>
        </GlassPanel>
      </section>

      <GlassPanel as="section" className="wx-hours" aria-hidden="true">
        <div className="wx-hours-head"><h2 className="wx-title">24 小时</h2></div>
        <div className="wx-skel wx-skel-chart" />
      </GlassPanel>

      <div className="wx-duo" aria-hidden="true">
        <GlassPanel as="section" className="wx-week">
          <h2 className="wx-title">未来天气</h2>
          <div className="wx-skel wx-skel-rows">
            {SKELETON_DAYS.map(index => (
              <div className="wx-drow" key={index}>
                <i className="wx-bone" style={{ height: 11 }} />
                <i className="wx-bone" style={{ height: 9, opacity: .6 }} />
                <i className="wx-bone" style={{ width: 62, height: 11 }} />
                <span />
                <span />
                <i className="wx-bone" style={{ height: 6 }} />
                <span />
              </div>
            ))}
          </div>
        </GlassPanel>
        <GlassPanel as="section" className="wx-metrics">
          <h2 className="wx-title">实况</h2>
          <div className="wx-metrics-grid wx-skel">
            {SKELETON_METRICS.map(index => (
              <div className="wx-metric" key={index}>
                <i className="wx-bone" style={{ width: 46, height: 10, margin: '3px 0', opacity: .6 }} />
                <i className="wx-bone wx-metric-value" style={{ width: 58, height: 18, margin: '2px 0 3px' }} />
                <i className="wx-bone" style={{ width: 84, height: 10, margin: '3px 0', opacity: .6 }} />
              </div>
            ))}
          </div>
        </GlassPanel>
      </div>
    </>
  );
}

/** "外观"按钮和它点开的小面板：调玻璃面板的模糊和底色，改动马上生效并自动保存。
 *  小面板自己也是液态玻璃，拖动条一动它跟着变 */
function GlassTuneControl() {
  const blur = useWeatherGlassStore(s => s.blur);
  const tint = useWeatherGlassStore(s => s.tint);
  const setTune = useWeatherGlassStore(s => s.setTune);
  const reset = useWeatherGlassStore(s => s.reset);
  const [open, setOpen] = React.useState(false);
  const wrapRef = React.useRef<HTMLDivElement>(null);

  // 点小面板外面或按 Esc 关掉
  React.useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="wx-tune" ref={wrapRef}>
      <button type="button" className="wx-btn" aria-expanded={open} aria-controls="wx-glass-pop" onClick={() => setOpen(value => !value)}>
        <Icon.Sliders size={13} />外观
      </button>
      {open && (
        <GlassPanel className="wx-glass-pop" id="wx-glass-pop" role="dialog" aria-label="面板玻璃效果">
          <h3>面板玻璃效果</h3>
          <label className="wx-pop-row">
            <span>模糊</span>
            <input type="range" min={0} max={GLASS_BLUR_MAX} step={1} value={blur} onChange={event => setTune({ blur: Number(event.target.value) })} />
            <output>{blur}</output>
          </label>
          <label className="wx-pop-row">
            <span>底色</span>
            <input type="range" min={0} max={GLASS_TINT_MAX} step={5} value={tint} onChange={event => setTune({ tint: Number(event.target.value) })} />
            <output>{tint}%</output>
          </label>
          <div className="wx-pop-foot">
            <span>改动会自动保存</span>
            <button type="button" onClick={reset}>恢复默认</button>
          </div>
        </GlassPanel>
      )}
    </div>
  );
}

/** 滚轮在地点标签条上滚动时改成左右滑动；滑到头了就不拦，滚轮照常滚动页面 */
function useWheelScrollX(ref: React.RefObject<HTMLElement>) {
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let target = el.scrollLeft, frame = 0;
    // 每一帧往目标位置走剩下距离的四分之一，滚起来是平滑的，连续滚几下也不会卡顿
    const step = () => {
      const rest = target - el.scrollLeft;
      if (Math.abs(rest) < 1) {
        el.scrollLeft = target;
        frame = 0;
        return;
      }
      el.scrollLeft += Math.sign(rest) * Math.max(1, Math.abs(rest) * .25);
      frame = window.requestAnimationFrame(step);
    };
    const onWheel = (event: WheelEvent) => {
      const max = el.scrollWidth - el.clientWidth;
      if (max <= 0) return;
      const raw = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      // deltaMode 为 1 时滚动量按"行"给，换算成像素
      const delta = raw * (event.deltaMode === 1 ? 32 : 1);
      if (!frame) target = el.scrollLeft;
      const next = Math.max(0, Math.min(max, target + delta));
      if (next === target) return;
      event.preventDefault();
      target = next;
      if (!frame) frame = window.requestAnimationFrame(step);
    };
    // 要拦住页面的上下滚动，只能用原生监听并声明 passive: false
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      el.removeEventListener('wheel', onWheel);
      window.cancelAnimationFrame(frame);
    };
  }, [ref]);
}

/** 页面最上面一行：左边一条玻璃胶囊，先是"全部"按钮（进"全部地点"页），后面是收藏的地点，每个地点带一个删除按钮；
 *  右边是刷新、设置、外观三个按钮 */
function WeatherLocationRow({
  loading,
  onRefresh,
  onOpenSettings,
  onOpenPlaces,
}: {
  loading: boolean;
  onRefresh: () => void;
  onOpenSettings: () => void;
  onOpenPlaces: () => void;
}) {
  const locations = useWeatherStore(s => s.locations);
  const activeLocationId = useWeatherStore(s => s.activeLocationId);
  const setActiveLocation = useWeatherStore(s => s.setActiveLocation);
  const removeFavorite = useWeatherStore(s => s.removeFavorite);
  const tabsRef = React.useRef<HTMLDivElement>(null);
  useWheelScrollX(tabsRef);

  const handleDelete = async (location: WeatherLocation) => {
    const confirmed = await appConfirm(`确定删除收藏地点“${location.name}”吗？`, {
      title: '删除收藏地点',
      confirmText: '删除',
      danger: true,
    });
    if (confirmed) await removeFavorite(location.id);
  };

  // 哪一边还有没露出来的地点，就在哪一边渐隐（样式按 data-more 取值）
  React.useEffect(() => {
    const el = tabsRef.current;
    if (!el) return;
    const update = () => {
      const max = el.scrollWidth - el.clientWidth;
      const left = el.scrollLeft > 1, right = el.scrollLeft < max - 1;
      el.dataset.more = left && right ? 'both' : left ? 'left' : right ? 'right' : '';
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => {
      el.removeEventListener('scroll', update);
      observer.disconnect();
    };
  }, [locations.length]);

  // 选中的地点被挡在外面时，滑到能看见它。页面刚出来时直接摆好不滑：一进来标签条就在动，看着像页面跳了一下
  const tabsPlaced = React.useRef(false);
  React.useEffect(() => {
    const el = tabsRef.current;
    const tab = el?.querySelector<HTMLElement>('.wx-loc-tab.active');
    if (!el || !tab) return;
    const behavior: ScrollBehavior = tabsPlaced.current ? 'smooth' : 'auto';
    tabsPlaced.current = true;
    const margin = 28;
    if (tab.offsetLeft < el.scrollLeft + margin) {
      el.scrollTo({ left: tab.offsetLeft - margin, behavior });
    } else if (tab.offsetLeft + tab.offsetWidth > el.scrollLeft + el.clientWidth - margin) {
      el.scrollTo({ left: tab.offsetLeft + tab.offsetWidth - el.clientWidth + margin, behavior });
    }
  }, [activeLocationId, locations.length]);

  return (
    <div className="wx-loc-row">
      <GlassPanel as="section" className="wx-loc-bar" aria-label="收藏天气地点">
        <button
          type="button"
          className="wx-loc-all"
          title="全部地点：一次看所有地点的天气，也在这里添加、删除地点"
          onClick={onOpenPlaces}
        >
          <Icon.Grid size={13} />全部
        </button>
        <i className="wx-loc-sep" aria-hidden="true" />
        <div className="wx-loc-tabs" ref={tabsRef} role="group" aria-label="切换天气地点">
          {locations.map(location => {
            const active = location.id === activeLocationId;
            return (
              <span className={`wx-loc-tab${active ? ' active' : ''}`} key={location.id}>
                <button
                  type="button"
                  className="wx-loc-pick"
                  aria-pressed={active}
                  title={location.address}
                  onClick={() => void setActiveLocation(location.id)}
                >
                  {location.name}
                </button>
                {location.id !== DEFAULT_WEATHER_LOCATION.id && (
                  <button
                    type="button"
                    className="wx-loc-del"
                    title={`删除收藏：${location.name}`}
                    aria-label={`删除收藏地点 ${location.name}`}
                    onClick={() => void handleDelete(location)}
                  >
                    <Icon.X size={10} />
                  </button>
                )}
              </span>
            );
          })}
        </div>
      </GlassPanel>
      <div className="wx-loc-meta">
        <button type="button" className="wx-btn" title="刷新当前地点天气" aria-label="刷新当前地点天气" disabled={loading} onClick={onRefresh}>
          <span className={loading ? 'spin-ic' : ''}><Icon.Refresh size={13} /></span>
          <span className="wx-btn-swap" data-on={loading ? 'busy' : 'idle'}><span>刷新</span><span>刷新中</span></span>
        </button>
        <button type="button" className="wx-btn" onClick={onOpenSettings}><Icon.Settings size={13} />设置</button>
        <GlassTuneControl />
      </div>
    </div>
  );
}

/** 现在的天气：不加底框，直接写在天空上 */
const WeatherHero = React.memo(function WeatherHero({ data }: { data: WeatherResponse }) {
  const current = data.realtime;
  const today = data.daily[0];
  const short = weatherShortText(data);
  return (
    <div className="wx-hero-now">
      <div className="wx-hero-addr">
        <strong>{data.location.address}</strong>
        <span className="mono">{data.location.longitude.toFixed(4)}, {data.location.latitude.toFixed(4)}</span>
        <span>{data.source} · {weatherUpdateTime(data.updated_at, true)} 更新{data.cached ? ' · 缓存' : ''}</span>
      </div>
      <div className="wx-hero-main">
        <div className="wx-hero-temp">{roundWeather(current.temperature)}<sup>°</sup></div>
        <div className="wx-hero-copy">
          <div className="wx-hero-cond"><WeatherIcon skycon={current.skycon} size={30} />{weatherTransitionLabel(current.skycon, data.hourly)}</div>
          <div className="wx-hero-sub">
            <span>体感 {roundWeather(current.apparent_temperature, '°')}</span>
            {today && <><span>最高 {roundWeather(today.temperature_max, '°')}</span><span>最低 {roundWeather(today.temperature_min, '°')}</span></>}
          </div>
          <p className="wx-hero-say" title={short.title}>{short.text}</p>
          {data.hourly_description && data.hourly_description !== short.text && <p className="wx-hero-say2">{data.hourly_description}</p>}
        </div>
      </div>
    </div>
  );
});

/** 气温对应的颜色：越冷越蓝，越热越暖。都取偏亮的颜色，放在深色天空上才看得清 */
function tempColor(value: number): string {
  // 每一档是 [气温, 亮度, 鲜艳程度, 色相]
  const stops = [[0, .8, .1, 245], [10, .87, .09, 215], [19, .93, .1, 105], [27, .86, .14, 70], [36, .74, .18, 35]];
  const lab = (c: number[]) => [c[1], c[2] * Math.cos(c[3] * Math.PI / 180), c[2] * Math.sin(c[3] * Math.PI / 180)];
  const t = Math.min(stops[stops.length - 1][0], Math.max(stops[0][0], value));
  let i = 0;
  while (i < stops.length - 2 && t > stops[i + 1][0]) i++;
  const f = (t - stops[i][0]) / (stops[i + 1][0] - stops[i][0]), a = lab(stops[i]), b = lab(stops[i + 1]);
  return `oklab(${(a[0] + (b[0] - a[0]) * f).toFixed(3)} ${(a[1] + (b[1] - a[1]) * f).toFixed(3)} ${(a[2] + (b[2] - a[2]) * f).toFixed(3)})`;
}

const DROP_ICON = (
  <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
    <path d="M8 1.8S3.6 6.7 3.6 10A4.4 4.4 0 0 0 8 14.4 4.4 4.4 0 0 0 12.4 10C12.4 6.7 8 1.8 8 1.8z" />
  </svg>
);

/** 未来几天：每天一行，中间一条横条表示当天最低到最高气温在这几天里的位置 */
const WeekPanel = React.memo(function WeekPanel({ daily }: { daily: WeatherDailyItem[] }) {
  const temperatures = daily.flatMap(day => [day.temperature_min, day.temperature_max])
    .filter((value): value is number => value !== null && Number.isFinite(value));
  const dailyMin = temperatures.length ? Math.min(...temperatures) : 0;
  const dailyMax = temperatures.length ? Math.max(...temperatures) : 1;
  const dailySpread = Math.max(1, dailyMax - dailyMin);
  const minimumRangeWidth = 8;
  return (
    <GlassPanel as="section" className="wx-week">
      <h2 className="wx-title">{daily.length ? `未来 ${daily.length} 天` : '未来天气'}</h2>
      {daily.length ? daily.map((day, index) => {
        const info = skyInfo(day.skycon);
        const low = day.temperature_min ?? dailyMin, high = day.temperature_max ?? dailyMin;
        const rangeLeft = Math.max(0, Math.min(100 - minimumRangeWidth, (low - dailyMin) / dailySpread * 100));
        const rangeWidth = Math.max(0, Math.min(100 - rangeLeft, Math.max(minimumRangeWidth, (high - low) / dailySpread * 100)));
        const wet = (day.precipitation_probability ?? 0) >= 30;
        return (
          <div className={`wx-drow ${index === 0 ? 'is-today' : ''}`} key={`${day.date}-${index}`}>
            <span className="wx-d-name">{weatherDayLabel(day.date, index)}</span>
            <span className="wx-d-date mono">{day.date.slice(5).replace('-', '/')}</span>
            <span className="wx-d-sky"><WeatherIcon skycon={day.skycon} size={18} />{info.label}</span>
            <span className={`wx-d-rain ${wet ? 'wet' : ''}`} title="降水概率">{DROP_ICON}{roundWeather(day.precipitation_probability, '%')}</span>
            <span className="wx-d-lo">{roundWeather(day.temperature_min, '°')}</span>
            <span className="wx-d-bar" title={`${roundWeather(day.temperature_min, '°')} 至 ${roundWeather(day.temperature_max, '°')}`}>
              <i style={{ left: `${rangeLeft}%`, width: `${rangeWidth}%`, background: `linear-gradient(to right in oklab, ${tempColor(low)}, ${tempColor(high)})` }} />
            </span>
            <span className="wx-d-hi">{roundWeather(day.temperature_max, '°')}</span>
          </div>
        );
      }) : (
        <div className="wx-empty">暂无日级预报</div>
      )}
    </GlassPanel>
  );
});

/** 空气质量指数对应的颜色：50 以内绿，100 以内黄，150 以内橙，再往上红 */
function aqiColor(value: number | null): string | null {
  if (value === null || !Number.isFinite(value)) return null;
  if (value <= 50) return 'oklch(.82 .17 150)';
  if (value <= 100) return 'oklch(.88 .15 95)';
  if (value <= 150) return 'oklch(.8 .15 65)';
  return 'oklch(.7 .19 28)';
}
/** 空气质量那条分段色带：每段是 [占多宽, 颜色]，整条表示 0 ~ 300 */
const AQI_BANDS: Array<[number, string]> = [[50, 'oklch(.82 .17 150)'], [50, 'oklch(.88 .15 95)'], [50, 'oklch(.8 .15 65)'], [50, 'oklch(.7 .19 28)'], [100, 'oklch(.66 .16 330)']];

/** 8 项实况：湿度、风、能见度、气压、空气质量、颗粒物、紫外线、当前降水 */
const MetricsPanel = React.memo(function MetricsPanel({ current }: { current: WeatherResponse['realtime'] }) {
  const tone = aqiColor(current.aqi);
  const nearestRain = current.nearest_precipitation_distance;
  const rainDetail = nearestRain !== null && Number.isFinite(nearestRain)
    ? `最近降水带约 ${metricValue(nearestRain, ' km', 1)}`
    : '当前地点降水强度';
  const windKnown = current.wind_direction !== null && Number.isFinite(current.wind_direction);
  const items: Array<{ label: string; value: React.ReactNode; note: React.ReactNode }> = [
    { label: '相对湿度', value: <><b>{roundWeather(current.humidity)}</b><i>%</i></>, note: `云量 ${roundWeather(current.cloudrate, '%')}` },
    {
      label: '风况',
      value: (
        <>
          {/* 箭头指向风吹去的方向：风向是"风从哪边来"，所以再转半圈 */}
          {windKnown && (
            <svg className="wx-wind-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ transform: `rotate(${(current.wind_direction ?? 0) + 180}deg)` }} aria-hidden="true">
              <path d="M8 13.5v-11M3.8 6.6L8 2.5l4.2 4.1" />
            </svg>
          )}
          <b className="word">{windDirection(current.wind_direction)}</b><b>{roundWeather(current.wind_speed)}</b><i>km/h</i>
        </>
      ),
      note: '地表 10 米风速',
    },
    { label: '能见度', value: <><b>{roundWeather(current.visibility)}</b><i>km</i></>, note: '地表水平能见度' },
    { label: '气压', value: <><b>{roundWeather(current.pressure)}</b><i>hPa</i></>, note: '当前地面气压' },
    {
      label: '空气质量',
      value: <>{tone && <span className="wx-aqi-dot" />}<b>{roundWeather(current.aqi)}</b>{current.aqi_description && <b className="word">{current.aqi_description}</b>}</>,
      note: tone ? (
        <div className="wx-aqi-scale">
          {AQI_BANDS.map(([flex, color], index) => <span key={index} style={{ flex, background: color }} />)}
          <em style={{ left: `${(Math.min(current.aqi ?? 0, 300) / 300 * 100).toFixed(1)}%` }} />
        </div>
      ) : (current.aqi_description || '暂无等级描述'),
    },
    { label: '颗粒物', value: <><i>PM2.5</i><b>{roundWeather(current.pm25)}</b></>, note: `PM10 ${roundWeather(current.pm10)} μg/m³` },
    { label: '紫外线', value: <b className="word">{current.uv_description || '—'}</b>, note: `舒适度 ${current.comfort_description || '—'}` },
    { label: '当前降水', value: <><b>{metricValue(current.precipitation_intensity, '', 2)}</b><i>mm/h</i></>, note: rainDetail },
  ];
  return (
    <GlassPanel as="section" className="wx-metrics">
      <h2 className="wx-title">实况</h2>
      <div className="wx-metrics-grid" style={tone ? { '--tone': tone } as React.CSSProperties : undefined}>
        {items.map(item => (
          <div className="wx-metric" key={item.label}>
            <div className="wx-metric-label">{item.label}</div>
            <div className="wx-metric-value">{item.value}</div>
            <div className="wx-metric-note">{item.note}</div>
          </div>
        ))}
      </div>
    </GlassPanel>
  );
});

const MemoHourlyChart = React.memo(WeatherHourlyChart);
const MemoHelmetPanel = React.memo(HelmetPanel);

// 天气页和"全部地点"之间的切换动画。天气页铺满整个应用窗口，所以从窗口四条边开始收、放到整个窗口；
// 整个过程里字和面板一直都在，只有背景在变（跟 Apple 天气一样）：
//   1. 换底色：页面（或点中的那张卡片）后面的天空很快换成这种天气的底色（天空最底下那层渐变，不带云、雨、雪），字和面板不动
//   2. 收放：页面连同底色一起，四条边收到卡片上（或从卡片放开到整个窗口），节奏像不回弹的弹簧，起步慢、中段快、收尾慢；
//      内容不缩放，钉在左上角跟着移动、被边裁掉，同时原来的内容慢慢换成目标的内容，两边有重叠，中间不会一个字都没有
//   3. 露出来：底色很快淡掉，露出卡片（或整页）后面的天空
// 页面和"全部地点"的互换、窗口背景的切换，都在被盖住的时候做，看不出来
const COVER_MS = 140;
const MOVE_MS = 480;
const REVEAL_MS = 220;
const CARD_RADIUS = 20;
/** 不回弹的弹簧曲线，按时间取一串点写成 CSS 的 linear() 缓动 */
const SPRING_EASE = `linear(${Array.from({ length: 33 }, (_, index) => {
  const w = 8 * index / 32;
  return index === 32 ? '1' : (1 - (1 + w) * Math.exp(-w)).toFixed(4);
}).join(', ')})`;

interface Zoom {
  /** collapse：整页收进"全部地点"里当前地点的卡片；expand：点中的卡片放大成整页 */
  dir: 'collapse' | 'expand';
  /** 收进去 / 放出来的那张卡片对应的地点 */
  id: string;
  /** 底色用哪种天气、哪个时段的 */
  kind: SkyKind;
  sun: SunLight;
  phase: 'cover' | 'move' | 'reveal';
  /** 收拢开始时页面滚到了哪里 */
  scrollTop: number;
}

interface Box { left: number; top: number; width: number; height: number }

/** "全部地点"页里某个地点的卡片 */
function placeCard(id: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`.wxl .wxl-card[data-place-id="${CSS.escape(id)}"]`);
}

/** 整个应用窗口的范围 */
function windowBox(): Box {
  const rect = document.querySelector('.win')?.getBoundingClientRect();
  return rect
    ? { left: rect.left, top: rect.top, width: rect.width, height: rect.height }
    : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
}

const noop = () => {};

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

export function WeatherScreen() {
  const { setScreen, weatherKind, weatherSun, setWeatherPlaces } = useApp();
  const startupStatus = useStartupStore(s => s.status);
  const startupReason = useStartupStore(s => s.reason);
  const location = useWeatherStore(selectActiveWeatherLocation);
  const activeLocationId = useWeatherStore(s => s.activeLocationId);
  const setActiveLocation = useWeatherStore(s => s.setActiveLocation);
  const locations = useWeatherStore(s => s.locations);
  const entries = useWeatherStore(s => s.entries);
  const { data, loading, error, hasAttempted } = useWeatherStore(selectActiveWeatherEntry);
  const refresh = useWeatherStore(s => s.refresh);
  const [view, setView] = React.useState<'page' | 'places'>('page');
  const [zoom, setZoom] = React.useState<Zoom | null>(null);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const stageRef = React.useRef<HTMLDivElement>(null);
  const backRef = React.useRef<HTMLDivElement>(null);
  const boxRef = React.useRef<HTMLDivElement>(null);
  const cardFaceRef = React.useRef<HTMLDivElement>(null);
  /** 放大时点中的那张卡片的位置（点下去的那一刻量好） */
  const cardBoxRef = React.useRef<Box | null>(null);
  /** 放大时整屏天空什么时候在边框后面淡入完 */
  const skyReadyAtRef = React.useRef(0);
  usePanelFall(weatherKind);

  React.useEffect(() => {
    // 与首页一致：只在后端探活完成后首拉；服务稍后就绪时自动恢复。
    if (startupStatus === 'ready' && !data && !hasAttempted && !loading) void refresh(false);
  }, [startupStatus, data, hasAttempted, loading, refresh]);

  // 离开天气页时不停在"全部地点"，下次进来还是整屏天空
  React.useEffect(() => () => setWeatherPlaces('off'), [setWeatherPlaces]);

  React.useEffect(() => warmSkyTextures(), []);

  const onRefresh = React.useCallback(() => void refresh(true), [refresh]);
  const onOpenSettings = React.useCallback(() => setScreen('settings'), [setScreen]);

  const openPlaces = React.useCallback(() => {
    if (zoom) return;
    const content = rootRef.current?.parentElement;
    if (content && !prefersReducedMotion()) {
      setZoom({ dir: 'collapse', id: activeLocationId, kind: weatherKind, sun: weatherSun, phase: 'cover', scrollTop: content.scrollTop });
      return;
    }
    setWeatherPlaces('on');
    setView('places');
    if (content) content.scrollTop = 0;
  }, [zoom, activeLocationId, weatherKind, weatherSun, setWeatherPlaces]);

  const openLocation = React.useCallback(async (id: string) => {
    if (zoom) return;
    const rect = placeCard(id)?.getBoundingClientRect();
    await setActiveLocation(id);
    // 底色跟 App 选天空的算法一致：按这个地点此刻的太阳位置和它的天气算，还没有它的天气就沿用现在的
    const state = useWeatherStore.getState();
    const target = state.locations.find(item => item.id === id);
    const sun = target ? sunAt(target.latitude, target.longitude, new Date()) : weatherSun;
    const skycon = state.entries[id]?.data?.realtime.skycon;
    const kind = skycon ? resolveSkyKind(skycon, sun) : weatherKind;
    const content = rootRef.current?.parentElement;
    if (content && rect && !prefersReducedMotion()) {
      cardBoxRef.current = { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
      skyReadyAtRef.current = performance.now() + WEATHER_SHELL_TRANSITION_MS;
      setWeatherPlaces('closing');
      setZoom({ dir: 'expand', id, kind, sun, phase: 'cover', scrollTop: 0 });
      return;
    }
    setWeatherPlaces('off');
    setView('page');
    if (content) content.scrollTop = 0;
  }, [zoom, setActiveLocation, weatherKind, weatherSun, setWeatherPlaces]);

  // 动画期间把侧栏、标题栏、工具栏抬到动画层上面（样式见 weather.css 的 data-weather-zoom），边框上的字一直看得见
  const zooming = zoom !== null;
  React.useLayoutEffect(() => {
    if (!zooming) return;
    const desktop = document.querySelector<HTMLElement>('.desktop');
    desktop?.setAttribute('data-weather-zoom', '');
    return () => desktop?.removeAttribute('data-weather-zoom');
  }, [zooming]);

  // 动画开始时：动画层铺到起点（收拢是整个窗口，放大是那张卡片），页面放进去、摆在跟内容区一样的位置；动画结束时全部复原
  React.useLayoutEffect(() => {
    if (!zooming) return;
    const stage = stageRef.current, box = boxRef.current, content = rootRef.current?.parentElement;
    if (!stage || !box || !content) return;
    const whole = windowBox();
    const area = content.getBoundingClientRect();
    Object.assign(box.style, {
      left: `${area.left - whole.left}px`,
      top: `${area.top - whole.top}px`,
      width: `${content.clientWidth}px`,
      height: `${content.clientHeight}px`,
      padding: getComputedStyle(content).padding,
    });
    return () => {
      stage.removeAttribute('style');
      box.removeAttribute('style');
    };
  }, [zooming]);

  React.useLayoutEffect(() => {
    if (!zoom) return;
    const stage = stageRef.current, back = backRef.current, box = boxRef.current, content = rootRef.current?.parentElement;
    const cardFace = cardFaceRef.current;
    if (!stage || !back || !box || !content) {
      setZoom(null);
      return;
    }
    const collapse = zoom.dir === 'collapse';
    let stopped = false, frame = 0;
    const animations: Animation[] = [];
    const place = (target: Box, radius: number) => Object.assign(stage.style, {
      left: `${target.left}px`, top: `${target.top}px`, width: `${target.width}px`, height: `${target.height}px`, borderRadius: `${radius}px`,
    });
    const keyframe = (target: Box, radius: number): Keyframe => ({
      left: `${target.left}px`, top: `${target.top}px`, width: `${target.width}px`, height: `${target.height}px`, borderRadius: `${radius}px`,
    });
    /** 透明度动画：from 到 to，在整段时长的 start 到 end 之间完成 */
    const fade = (el: HTMLElement | null, from: number, to: number, start: number, end: number, duration: number) => {
      if (!el) return;
      animations.push(el.animate({ opacity: [from, from, to, to], offset: [0, start, end, 1] }, { duration, easing: 'linear' }));
      el.style.opacity = String(to);
    };
    const whenDone = (animation: Animation, next: () => void) => {
      animation.finished.then(() => { if (!stopped) next(); }, () => {});
    };
    // 新出现的卡片、面板在这两帧里把要算的都算完，再开始动，不会卡顿、跳帧
    const afterTwoFrames = (next: () => void) => {
      frame = window.requestAnimationFrame(() => { frame = window.requestAnimationFrame(next); });
    };

    if (zoom.phase === 'cover') {
      const whole = windowBox();
      if (collapse) {
        place(whole, 0);
        box.scrollTop = zoom.scrollTop;
        box.style.opacity = '1';
        if (cardFace) cardFace.style.opacity = '0';
      } else {
        place(cardBoxRef.current ?? whole, CARD_RADIUS);
        box.style.opacity = '0';
        if (cardFace) {
          cardFace.style.width = `${(cardBoxRef.current ?? whole).width}px`;
          cardFace.style.opacity = '1';
        }
      }
      // 后面的天空换成底色，前面的字和面板不动
      const cover = back.animate({ opacity: [0, 1] }, { duration: COVER_MS, easing: 'ease-out' });
      animations.push(cover);
      back.style.opacity = '1';
      whenDone(cover, () => {
        if (collapse) {
          // 窗口背景这时被底色盖着：换成"全部地点"，窗口换回普通背景
          flushSync(() => {
            setWeatherPlaces('on');
            setView('places');
            setZoom({ ...zoom, phase: 'move' });
          });
        } else {
          // 边框跟着换成天气页的样子：等底色铺到边框下面时，磨砂玻璃透出来的正好是它。
          // 在开始放大前换，换样式的那一下落在动画开始前的两帧里
          flushSync(() => {
            setWeatherPlaces('arriving');
            setZoom({ ...zoom, phase: 'move' });
          });
        }
      });
    } else if (zoom.phase === 'move') {
      const whole = windowBox();
      let from: [Box, number], to: [Box, number];
      if (collapse) {
        content.scrollTop = 0;
        const card = placeCard(zoom.id);
        if (!card) {
          setZoom({ ...zoom, phase: 'reveal' });
          return;
        }
        // 当前地点的卡片排在下面看不到时，先把它滚进来
        const area = content.getBoundingClientRect();
        const hidden = card.getBoundingClientRect().bottom - (area.top + content.clientHeight) + 24;
        if (hidden > 0) content.scrollTop = hidden;
        const rect = card.getBoundingClientRect();
        from = [whole, 0];
        to = [{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }, CARD_RADIUS];
        if (cardFace) cardFace.style.width = `${rect.width}px`;
      } else {
        from = [cardBoxRef.current ?? whole, CARD_RADIUS];
        to = [whole, 0];
      }
      place(...from);
      afterTwoFrames(() => {
        if (stopped) return;
        const move = stage.animate([keyframe(...from), keyframe(...to)], { duration: MOVE_MS, easing: SPRING_EASE });
        animations.push(move);
        place(...to);
        // 原来的内容慢慢淡出，目标的内容早一点开始淡入，两边重叠，字不会断
        if (collapse) {
          fade(box, 1, 0, 0, .6, MOVE_MS);
          fade(cardFace, 0, 1, .1, .5, MOVE_MS);
        } else {
          fade(cardFace, 1, 0, 0, .6, MOVE_MS);
          fade(box, 0, 1, 0, .4, MOVE_MS);
        }
        whenDone(move, () => {
          if (collapse) {
            setZoom({ ...zoom, phase: 'reveal' });
            return;
          }
          // 底色铺满了整个窗口：换回天气页，窗口换回整屏天空（天空已经在边框后面淡入好了）
          flushSync(() => {
            setView('page');
            setWeatherPlaces('off');
            setZoom({ ...zoom, phase: 'reveal' });
          });
        });
      });
    } else {
      afterTwoFrames(async () => {
        if (!collapse) {
          const wait = skyReadyAtRef.current - performance.now();
          if (wait > 0) await new Promise(resolve => window.setTimeout(resolve, wait));
        }
        if (stopped) return;
        // 底色淡掉，露出后面的天空：收拢时是真卡片（上面的字跟底色里那份重合），放大时是整屏天空
        fade(back, 1, 0, 0, 1, REVEAL_MS);
        if (collapse) fade(cardFace, 1, 0, 0, 1, REVEAL_MS);
        whenDone(animations[animations.length - 1], () => {
          if (!collapse) content.scrollTop = 0;
          flushSync(() => setZoom(null));
          const focused = document.activeElement;
          if (!focused || focused === document.body) {
            const next = collapse ? placeCard(zoom.id)?.querySelector<HTMLElement>('.wxl-pick') : document.querySelector<HTMLElement>('.wx-loc-all');
            next?.focus({ preventScroll: true });
          }
        });
      });
    }

    return () => {
      stopped = true;
      window.cancelAnimationFrame(frame);
      animations.forEach(animation => animation.cancel());
    };
  }, [zoom, setWeatherPlaces]);

  // 收拢的整个过程里页面还在（在动画层里收起来）；放大一开始就把新地点的页面放进动画层。
  // 放大时"全部地点"留到底色铺满整个窗口为止，最后露出天空那一步它已经撤掉，不会从后面透出来
  const showPage = view === 'page' || zoom !== null;
  const showPlaces = view === 'places' || (zoom?.dir === 'expand' && zoom.phase !== 'reveal');
  const locationRow = <WeatherLocationRow loading={loading} onRefresh={onRefresh} onOpenSettings={onOpenSettings} onOpenPlaces={openPlaces} />;

  let page: React.ReactNode = null;
  if (!showPage) {
    page = null;
  } else if (!data && (loading || (!hasAttempted && startupStatus !== 'failed'))) {
    page = (
      <div className="wx-page">
        {locationRow}
        <WeatherLoading location={location} />
      </div>
    );
  } else if (!data) {
    page = (
      <div className="wx-page">
        {locationRow}
        <div className="card weather-page-state weather-page-state-error" role="alert">
          <Icon.AlertTriangle size={24} />
          <div style={{ flex: 1 }}>
            <div className="weather-page-state-title">天气数据获取失败</div>
            <div className="muted">
              {error || (startupStatus === 'failed' ? startupReason : null) || '请稍后重试'}
            </div>
          </div>
          <button className="btn btn-sm" onClick={onRefresh}>重新加载</button>
          <button className="btn btn-sm" onClick={onOpenSettings}>检查设置</button>
        </div>
      </div>
    );
  } else {
    page = (
      <div className="wx-page">
        {locationRow}
        {error && (
          <div className="weather-page-inline-error" role="alert">
            <Icon.AlertTriangle size={14} />
            <span>刷新失败：{error}</span>
          </div>
        )}

        <section className="wx-hero" aria-label="现在的天气">
          <WeatherHero data={data} />
          <MemoHelmetPanel data={data} />
        </section>

        {(data.alerts.length > 0 || data.alerts_available !== true) && (
          <section className="wx-alerts" aria-label="天气预警">
            {data.alerts.length ? data.alerts.map(alert => (
              <GlassPanel className="wx-alert" key={alert.id}>
                <Icon.AlertTriangle size={18} className="wx-alert-ico" />
                <div>
                  <h3>{alert.title}</h3>
                  <p>{alert.description}</p>
                  <small>
                    {[alert.status, alert.location, alert.source, alert.published_at ? weatherUpdateTime(alert.published_at, true) : '']
                      .filter(Boolean).join(' · ')}
                  </small>
                </div>
              </GlassPanel>
            )) : (
              <GlassPanel className="wx-alert is-unavailable">
                <Icon.Info size={18} />
                <div>
                  <h3>预警数据暂不可用</h3>
                  <p>暂未确认当前地点的气象预警状态，请稍后刷新。</p>
                </div>
              </GlassPanel>
            )}
          </section>
        )}

        <GlassPanel as="section" className="wx-hours">
          <div className="wx-hours-head">
            <h2 className="wx-title">24 小时</h2>
            <div className="wx-hours-legend"><span><i className="line" />气温</span><span><i className="bar" />降水概率</span></div>
          </div>
          <MemoHourlyChart items={data.hourly} variant="page" />
        </GlassPanel>

        <div className="wx-duo">
          <WeekPanel daily={data.daily} />
          <MetricsPanel current={data.realtime} />
        </div>
      </div>
    );
  }

  const zoomLocation = zoom ? locations.find(item => item.id === zoom.id) : undefined;

  // .wx-view 不占位置，内容区就是它的上一级。.wx-stage 和 .wx-stage-box 平时也不占位置，页面照常排在内容区里；
  // 动画时 .wx-stage 变成动画层（样式见 weather.css）：最底下一层底色，上面是整页内容，再上面是卡片上的字。
  // 页面一直在 .wx-stage-box 里，从"排在内容区里"变成"在动画层里"时不会被重新创建，玻璃面板不用重算
  return (
    <div className="wx-view" ref={rootRef}>
      <div className={`wx-stage${zoom ? ' is-zooming' : ''}`} ref={stageRef} aria-hidden={zoom ? true : undefined}>
        {zoom && <div className="wx-stage-back" ref={backRef} style={{ background: skyBase(zoom.kind, zoom.sun) }} />}
        <div className="wx-stage-box" ref={boxRef}>{page}</div>
        {zoom && zoomLocation && (
          <div className="wx-stage-card" ref={cardFaceRef}>
            <PlaceCard
              bare
              location={zoomLocation}
              entry={entries[zoomLocation.id] || EMPTY_WEATHER_ENTRY}
              active={zoomLocation.id === activeLocationId}
              editing={false}
              now={new Date()}
              onPick={noop}
              onDelete={noop}
            />
          </div>
        )}
      </div>
      {showPlaces && (
        <WeatherPlaces
          busy={zoom !== null}
          onOpen={openLocation}
        />
      )}
    </div>
  );
}
