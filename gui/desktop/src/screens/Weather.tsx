import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import type { WeatherDailyItem, WeatherResponse } from '../lib/api';
import { useStartupStore } from '../store/startup';
import {
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
import {
  DEFAULT_WEATHER_LOCATION,
  searchWeatherLocations,
  type WeatherLocation,
} from '../lib/weatherLocations';
import { appAlert, appConfirm } from '../lib/dialog';
import { GlassPanel, usePanelFall } from '../components/GlassPanel';
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

function sameLocation(a: WeatherLocation, b: WeatherLocation): boolean {
  const sameCoordinates = a.latitude.toFixed(4) === b.latitude.toFixed(4)
    && a.longitude.toFixed(4) === b.longitude.toFixed(4);
  const sameAddress = a.address.replace(/\s+/g, '') === b.address.replace(/\s+/g, '');
  return sameCoordinates || sameAddress;
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

/** 页面最上面一行：左边一条玻璃胶囊里放收藏的地点，右边是刷新、设置、外观三个按钮 */
function WeatherLocationRow({
  loading,
  onRefresh,
  onOpenSettings,
}: {
  loading: boolean;
  onRefresh: () => void;
  onOpenSettings: () => void;
}) {
  const locations = useWeatherStore(s => s.locations);
  const activeLocationId = useWeatherStore(s => s.activeLocationId);
  const setActiveLocation = useWeatherStore(s => s.setActiveLocation);
  const addFavorite = useWeatherStore(s => s.addFavorite);
  const removeFavorite = useWeatherStore(s => s.removeFavorite);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [addingId, setAddingId] = React.useState<string | null>(null);
  const addButtonRef = React.useRef<HTMLButtonElement>(null);
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const results = React.useMemo(() => searchWeatherLocations(query), [query]);

  const closeDialog = React.useCallback(() => {
    setDialogOpen(false);
    setQuery('');
    setAddingId(null);
  }, []);

  React.useEffect(() => {
    if (!dialogOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) || []);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.requestAnimationFrame(() => addButtonRef.current?.focus());
    };
  }, [dialogOpen, closeDialog]);

  const handleAdd = async (location: WeatherLocation) => {
    setAddingId(location.id);
    const id = await addFavorite(location);
    setAddingId(null);
    if (!id) {
      await appAlert('最多可收藏 20 个天气地点，请先删除不再使用的地点。', { title: '无法添加地点' });
      return;
    }
    closeDialog();
  };

  const handleDelete = async (location: WeatherLocation) => {
    const confirmed = await appConfirm(`确定删除收藏地点“${location.name}”吗？`, {
      title: '删除收藏地点',
      confirmText: '删除',
      danger: true,
    });
    if (confirmed) await removeFavorite(location.id);
  };

  return (
    <>
      <div className="wx-loc-row">
        <GlassPanel as="section" className="wx-loc-bar" aria-label="收藏天气地点">
          <div className="wx-loc-tabs" role="group" aria-label="切换天气地点">
            {locations.map(location => {
              const active = location.id === activeLocationId;
              return (
                <span className={`wx-loc-tab ${active ? 'active' : ''}`} key={location.id}>
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
            <button ref={addButtonRef} type="button" className="wx-loc-add" onClick={() => setDialogOpen(true)}>
              <Icon.Plus size={12} />添加地点
            </button>
          </div>
        </GlassPanel>
        <div className="wx-loc-meta">
          <button type="button" className="wx-btn" title="刷新当前地点天气" aria-label="刷新当前地点天气" disabled={loading} onClick={onRefresh}>
            <span className={loading ? 'spin-ic' : ''}><Icon.Refresh size={13} /></span>
            {loading ? '刷新中' : '刷新'}
          </button>
          <button type="button" className="wx-btn" onClick={onOpenSettings}><Icon.Settings size={13} />设置</button>
          <GlassTuneControl />
        </div>
      </div>

      {dialogOpen && (
        <div className="ep-overlay" onClick={closeDialog}>
          <div
            className="ep-modal weather-location-modal"
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="weather-location-dialog-title"
            onClick={event => event.stopPropagation()}
          >
            <div className="ep-modal-head">
              <div>
                <div className="ep-modal-title" id="weather-location-dialog-title">添加收藏地点</div>
                <div className="ep-modal-sub">本地搜索城市、区县或行政区编码，不需要额外地图密钥</div>
              </div>
              <button type="button" className="ep-modal-close" onClick={closeDialog} aria-label="关闭">
                <Icon.Close size={12} />
              </button>
            </div>
            <div className="weather-location-search-wrap">
              <Icon.Search size={14} />
              <input
                className="input weather-location-search"
                autoFocus
                aria-label="搜索天气地点"
                value={query}
                maxLength={30}
                placeholder="搜索城市、区县，例如：杭州、长宁区"
                onChange={event => setQuery(event.target.value)}
              />
              {query && (
                <button type="button" className="weather-location-clear" onClick={() => setQuery('')} aria-label="清空搜索">
                  <Icon.X size={11} />
                </button>
              )}
            </div>
            <div className="weather-location-result-head">
              <span>{query.trim() ? '搜索结果' : '常用城市'}</span>
              <span className="mono">显示 {results.length} 个</span>
            </div>
            <div className="weather-location-results">
              {results.map(location => {
                const favorite = locations.find(item => item.id === location.id || sameLocation(item, location));
                const active = favorite?.id === activeLocationId;
                return (
                  <div className="weather-location-result" key={location.id}>
                    <div className="weather-location-result-copy">
                      <strong>{location.name}</strong>
                      <span title={location.address}>{location.address}</span>
                    </div>
                    <button
                      type="button"
                      className={`btn btn-sm ${favorite ? '' : 'btn-primary'}`}
                      disabled={active || addingId === location.id}
                      onClick={() => void handleAdd(location)}
                    >
                      {addingId === location.id ? '添加中…' : active ? '当前地点' : favorite ? '切换' : '收藏并切换'}
                    </button>
                  </div>
                );
              })}
              {!results.length && (
                <div className="weather-location-empty">
                  <Icon.Search size={20} />
                  <strong>未找到匹配地点</strong>
                  <span>请尝试输入城市或区县名称。</span>
                </div>
              )}
            </div>
            <div className="ep-modal-foot weather-location-modal-foot">
              <span>最多收藏 20 个地点 · 数据源：彩云官方行政区划表</span>
              <button type="button" className="btn" onClick={closeDialog}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </>
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

export function WeatherScreen() {
  const { setScreen, weatherKind } = useApp();
  const startupStatus = useStartupStore(s => s.status);
  const startupReason = useStartupStore(s => s.reason);
  const location = useWeatherStore(selectActiveWeatherLocation);
  const { data, loading, error, hasAttempted } = useWeatherStore(selectActiveWeatherEntry);
  const refresh = useWeatherStore(s => s.refresh);
  usePanelFall(weatherKind);

  React.useEffect(() => {
    // 与首页一致：只在后端探活完成后首拉；服务稍后就绪时自动恢复。
    if (startupStatus === 'ready' && !data && !hasAttempted && !loading) void refresh(false);
  }, [startupStatus, data, hasAttempted, loading, refresh]);

  const onRefresh = React.useCallback(() => void refresh(true), [refresh]);
  const onOpenSettings = React.useCallback(() => setScreen('settings'), [setScreen]);
  const locationRow = <WeatherLocationRow loading={loading} onRefresh={onRefresh} onOpenSettings={onOpenSettings} />;

  if (!data && (loading || (!hasAttempted && startupStatus !== 'failed'))) return (
    <div className="wx-page">
      {locationRow}
      <WeatherLoading location={location} />
    </div>
  );

  if (!data) {
    return (
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
  }

  return (
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
