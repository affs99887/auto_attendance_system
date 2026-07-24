import * as React from 'react';
import { Icon } from '../lib/icons';
import type { WeatherDailyItem, WeatherHourlyItem, WeatherResponse } from '../lib/api';
import {
  aqiTone,
  buildHelmetRainAdvice,
  roundWeather,
  skyInfo,
  weatherDayLabel,
  weatherHourLabel,
  weatherTransitionLabel,
  windDirection,
  windScale,
  type WeatherIconKind,
} from '../lib/weather';

type SvgProps = Omit<React.SVGProps<SVGSVGElement>, 'children'>;

function WeatherIconPaths({ kind }: { kind: WeatherIconKind }) {
  switch (kind) {
    case 'sun':
      return <><circle cx="12" cy="12" r="4" /><path d="M12 2.6v2.2M12 19.2v2.2M21.4 12h-2.2M4.8 12H2.6M18.6 5.4l-1.55 1.55M6.95 17.05L5.4 18.6M18.6 18.6l-1.55-1.55M6.95 6.95L5.4 5.4" /></>;
    case 'moon':
      return <path d="M20.5 14.9A8.3 8.3 0 0 1 9.1 3.5 6.9 6.9 0 1 0 20.5 14.9z" />;
    case 'partly':
      return <><circle cx="8.4" cy="7.9" r="2.7" /><path d="M8.4 2.7v1.7M3.5 7.9h1.7M4.9 4.4l1.2 1.2M11.9 4.4l-1.2 1.2M2.5 12.6h1.6" /><path d="M9.4 19h6.9a2.95 2.95 0 0 0 .28-5.88 4.15 4.15 0 0 0-7.86-1.13A2.95 2.95 0 0 0 9.4 19z" /></>;
    case 'partly-night':
      return <><path d="M12.4 4.1A4.3 4.3 0 0 1 8.3 8 3.5 3.5 0 1 0 12.4 4.1z" /><path d="M9.4 19h6.9a2.95 2.95 0 0 0 .28-5.88 4.15 4.15 0 0 0-7.86-1.13A2.95 2.95 0 0 0 9.4 19z" /></>;
    case 'rain':
      return <><path d="M7.3 15.4h9.1a3.7 3.7 0 0 0 .34-7.38 5.15 5.15 0 0 0-9.88-1.36A3.7 3.7 0 0 0 7.3 15.4z" /><path d="M9 18.1l-1 2.5M12 18.1l-1 2.5M15 18.1l-1 2.5" /></>;
    case 'thunder':
      return <><path d="M7.3 15.1h9.1a3.7 3.7 0 0 0 .34-7.38 5.15 5.15 0 0 0-9.88-1.36A3.7 3.7 0 0 0 7.3 15.1z" /><path d="M12.6 16.6l-2.3 3.4h2.5l-1.1 2.9" /></>;
    case 'snow':
      return <><path d="M7.3 15.1h9.1a3.7 3.7 0 0 0 .34-7.38 5.15 5.15 0 0 0-9.88-1.36A3.7 3.7 0 0 0 7.3 15.1z" /><path d="M9 18.4v2.4M7.95 19v1.2M10.05 19v1.2M14.5 18.4v2.4M13.45 19v1.2M15.55 19v1.2" /></>;
    case 'haze':
      return <path d="M4.5 8h12M5.6 12h13M4.5 16h11.6M7.2 20h9" />;
    case 'wind':
      return <path d="M3 9.4h9.4a2.3 2.3 0 1 0-2.25-2.78M3 14h12.4a2.5 2.5 0 1 1-2.45 3.05" />;
    default:
      return <path d="M7.3 18.4h9.1a3.8 3.8 0 0 0 .35-7.58 5.3 5.3 0 0 0-10.16-1.4A3.8 3.8 0 0 0 7.3 18.4z" />;
  }
}

export function WeatherIcon({
  skycon,
  kind,
  size = 24,
  ...props
}: SvgProps & { skycon?: string | null; kind?: WeatherIconKind; size?: number }) {
  const resolved = kind || skyInfo(skycon).icon;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <WeatherIconPaths kind={resolved} />
    </svg>
  );
}

function HelmetIcon({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3.8 15a8.2 8.2 0 0 1 16.4 0z" />
      <path d="M20.2 15c1.35.1 2.15-.35 2.35-1.3" />
      <path d="M9.4 8.8l1.2 3M13 8.3l1 3.2" />
    </svg>
  );
}

function UtilityIcon({ kind }: { kind: 'droplet' | 'gauge' }) {
  return kind === 'droplet' ? (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 2.2S3.5 7 3.5 10.2A4.5 4.5 0 0 0 8 14.5a4.5 4.5 0 0 0 4.5-4.3C12.5 7 8 2.2 8 2.2z" /></svg>
  ) : (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2.5 12a5.5 5.5 0 1 1 11 0" /><path d="M8 12l3-2.4" /><circle cx="8" cy="12" r=".6" fill="currentColor" stroke="none" /></svg>
  );
}

function SkyAtmosphere({ tone, icon }: { tone: string; icon: WeatherIconKind }) {
  const rainy = tone === 'rain';
  const snowy = tone === 'snow';
  const night = tone === 'night';
  return (
    <div className="weather-sky-atmosphere" aria-hidden="true">
      <span className="weather-sky-glow" />
      {(rainy || snowy) && [1, 2, 3, 4].map(index => (
        <span key={index} className={`${snowy ? 'weather-snow-dot' : 'weather-rain-line'} weather-particle-${index}`} />
      ))}
      {night && [1, 2, 3].map(index => <span key={index} className={`weather-star weather-star-${index}`} />)}
      {tone === 'haze' && <><span className="weather-haze-line weather-haze-1" /><span className="weather-haze-line weather-haze-2" /></>}
      {tone === 'wind' && <><span className="weather-wind-line weather-wind-1" /><span className="weather-wind-line weather-wind-2" /></>}
      {icon === 'thunder' && <span className="weather-lightning-flash" />}
    </div>
  );
}

function updateTime(epoch: number, page: boolean): string {
  return new Date(epoch * 1000).toLocaleString('zh-CN', page
    ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }
    : { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' });
}

export type WeatherCardSize = 's' | 'm' | 'l';

function HelmetAdvice({
  data,
  size = 'l',
}: {
  data: WeatherResponse;
  size?: WeatherCardSize;
}) {
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const advice = React.useMemo(
    () => buildHelmetRainAdvice(data, now),
    [data, now],
  );
  const badgeIcon = advice.status === 'rain' ? 'thunder' : advice.status === 'dry' ? 'partly-night' : 'cloud';
  const compact = size !== 'l';
  const firstSlot = advice.mode === 'night' ? advice.slots[0] : null;
  const compactStartLabel = advice.mode === 'rest'
    ? '放假前17时'
    : firstSlot?.covered
      ? firstSlot.wet
        ? (size === 's' ? '17时 雨' : '17时 有雨')
        : '17时 无雨'
      : '17时';
  const compactEndLabel = advice.mode === 'rest' ? '上班日8时' : size === 's' ? '次日 8时' : '次日8时';

  const timelineBars = advice.mode === 'rest' ? (
    <div
      className="weather-night-bars weather-rest-bars"
      style={{ gridTemplateColumns: `repeat(${Math.max(1, advice.days.length)}, minmax(0, 1fr))` }}
    >
      {advice.days.map(slot => (
        <span
          key={slot.date}
          className={`${slot.wet ? 'wet' : ''} ${slot.covered ? '' : 'uncovered'}`}
          title={`${slot.date} ${slot.label} · 降水概率 ${slot.probability === null ? '暂无' : `${Math.round(slot.probability)}%`}${slot.estimated ? ' · 日级预报' : ''}`}
          style={{ opacity: slot.wet ? Math.max(0.34, (slot.probability ?? 35) / 100) : 0.16 }}
        />
      ))}
    </div>
  ) : (
    <div className="weather-night-bars">
      {advice.slots.map(slot => {
        const strength = slot.wet
          ? Math.max(0.34, (slot.probability ?? 0) / 100, Math.min(1, (slot.intensity ?? 0) / 3))
          : 0.16;
        return (
          <span
            key={slot.datetime}
            className={`${slot.wet ? 'wet' : ''} ${slot.covered ? '' : 'uncovered'}`}
            title={`${slot.label}:00 · 降水概率 ${slot.probability === null ? '暂无' : `${Math.round(slot.probability)}%`}`}
            style={{ opacity: strength }}
          />
        );
      })}
    </div>
  );
  const timelineAria = advice.mode === 'rest'
    ? `${advice.period.label}提醒时段，从放假前一日17点至假后首个工作日8点，共 ${advice.rainDays} 天有降水信号`
    : `17点至次日8点逐小时降雨时间轴，共 ${advice.rainHours} 个时段有降水信号`;

  if (compact) {
    return (
      <div className={`weather-helmet weather-helmet-${advice.status} weather-helmet-${size}`}>
        <div className="weather-helmet-icon">
          <HelmetIcon size={size === 's' ? 18 : 20} />
          <span className="weather-helmet-badge"><WeatherIcon kind={badgeIcon} size={size === 's' ? 8 : 10} /></span>
        </div>
        <div className="weather-helmet-copy">
          <div className="weather-helmet-title-row"><strong>{advice.title}</strong></div>
          <div
            className="weather-night-timeline weather-night-timeline-compact"
            role="img"
            aria-label={timelineAria}
          >
            {timelineBars}
            <div className="weather-night-axis"><span>{compactStartLabel}</span><span>{compactEndLabel}</span></div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`weather-helmet weather-helmet-${advice.status}`}>
      <div className="weather-helmet-icon">
        <HelmetIcon size={23} />
        <span className="weather-helmet-badge"><WeatherIcon kind={badgeIcon} size={10} /></span>
      </div>
      <div className="weather-helmet-copy">
        <div className="weather-helmet-title-row">
          <strong>{advice.title}</strong>
          <span className="weather-helmet-pill"><WeatherIcon kind={badgeIcon} size={11} />{advice.badge}</span>
        </div>
        <div className="weather-helmet-detail">{advice.detail}</div>
      </div>
      <div
        className="weather-night-timeline"
        role="img"
        aria-label={timelineAria}
      >
        <div className="weather-night-timeline-head">
          <span>{advice.mode === 'rest' ? `${advice.period.label}雨情` : '今夜降雨时段'}</span>
          <strong>
            {advice.status === 'rain'
              ? advice.mode === 'rest'
                ? `${advice.rainDays} 天有雨`
                : `约 ${advice.rainHours} 小时有雨`
              : advice.badge}
          </strong>
        </div>
        {timelineBars}
        {advice.mode === 'rest' ? (
          <div className="weather-night-axis"><span>放假前一日 17:00</span><span>首个工作日 08:00</span></div>
        ) : (
          <div className="weather-night-axis"><span>17</span><span>20</span><span>23</span><span>02</span><span>05</span><span>08</span></div>
        )}
      </div>
    </div>
  );
}

export function WeatherSkyPanel({
  data,
  loading = false,
  mode = 'dashboard',
  onRefresh,
  onOpenDetails,
  onOpenSettings,
}: {
  data: WeatherResponse;
  loading?: boolean;
  mode?: 'dashboard' | 'page';
  onRefresh: () => void;
  onOpenDetails?: () => void;
  onOpenSettings?: () => void;
}) {
  const page = mode === 'page';
  const current = data.realtime;
  const sky = skyInfo(current.skycon);
  const today = data.daily[0];
  const shortText = data.minutely_description || data.forecast_keypoint || data.hourly_description || '暂无短时天气提示';
  const shortTitle = data.minutely_description ? '未来两小时 · 彩云短时' : '未来 24 小时 · 彩云天气';

  return (
    <section className={`weather-sky-panel weather-sky-${sky.tone} weather-sky-icon-${sky.icon} ${page ? 'is-page' : ''}`} aria-busy={loading}>
      <SkyAtmosphere tone={sky.tone} icon={sky.icon} />
      <div className="weather-sky-top">
        <div className="weather-sky-location">
          <Icon.Globe size={15} />
          <div className="weather-sky-location-copy">
            <strong>{data.location.address}</strong>
            {page && !data.location.located && <span className="mono">{data.location.longitude.toFixed(4)}, {data.location.latitude.toFixed(4)}</span>}
          </div>
        </div>
        <div className="weather-sky-actions">
          <span className="weather-sky-updated">{page && `${data.source} · `}{updateTime(data.updated_at, page)} 更新{data.cached ? ' · 缓存' : ''}</span>
          {page && onOpenSettings && <button type="button" className="weather-sky-button" onClick={onOpenSettings}><Icon.Settings size={12} />设置</button>}
          {!page && onOpenDetails && <button type="button" className="weather-sky-button" onClick={onOpenDetails}>详细 <Icon.ChevronRight size={10} /></button>}
          <button type="button" className="weather-sky-button weather-sky-refresh" title="刷新当前地点天气" aria-label="刷新当前地点天气" disabled={loading} onClick={onRefresh}>
            <span className={loading ? 'spin-ic' : ''}><Icon.Refresh size={13} /></span>
            {page && <span>{loading ? '刷新中' : '刷新'}</span>}
          </button>
        </div>
      </div>

      <div className="weather-sky-current-row">
        <div className="weather-sky-current">
          <WeatherIcon skycon={current.skycon} size={page ? 84 : 66} className="weather-sky-main-icon" />
          <div>
            <div className="weather-sky-temperature"><span>{roundWeather(current.temperature)}</span><small>°</small></div>
            <div className="weather-sky-condition">{weatherTransitionLabel(current.skycon, data.hourly)}</div>
            <div className="weather-sky-feels">
              体感 {roundWeather(current.apparent_temperature, '°')}
              {today && <> · <span className="mono">{roundWeather(today.temperature_max, '°')} / {roundWeather(today.temperature_min, '°')}</span></>}
            </div>
          </div>
        </div>
        <div className="weather-sky-short">
          <WeatherIcon skycon={data.hourly.find(item => item.skycon !== current.skycon)?.skycon || current.skycon} size={16} />
          <div>
            <div className="weather-sky-short-title">{shortTitle}</div>
            <div className="weather-sky-short-text">{shortText}</div>
            {page && data.hourly_description && data.hourly_description !== shortText && <div className="weather-sky-short-sub">{data.hourly_description}</div>}
          </div>
        </div>
      </div>

      <HelmetAdvice data={data} />
    </section>
  );
}

function WeatherCompactSkyPanel({
  data,
  size,
  loading = false,
  onRefresh,
  onOpenDetails,
}: {
  data: WeatherResponse;
  size: 's' | 'm';
  loading?: boolean;
  onRefresh?: () => void;
  onOpenDetails?: () => void;
}) {
  const current = data.realtime;
  const sky = skyInfo(current.skycon);
  const today = data.daily[0];
  const shortText = data.minutely_description || data.forecast_keypoint || data.hourly_description || '暂无短时天气提示';
  const shortTitle = data.minutely_description ? '未来两小时 · 彩云短时' : '未来 24 小时 · 彩云天气';
  const validSkyHours = data.hourly.filter(item => Boolean(item.skycon));
  const conditionLabel = weatherTransitionLabel(current.skycon, validSkyHours);
  const nextSkycon = validSkyHours.find(item => item.skycon !== current.skycon)?.skycon || current.skycon;
  const isSmall = size === 's';
  const alert = data.alerts[0];
  const alertsAvailable = data.alerts_available === true;
  const alertsTotal = Math.max(data.alerts.length, data.alerts_total || 0);
  const alertContent = alert ? (
    <>
      <Icon.AlertTriangle size={isSmall ? 12 : 13} />
      <span>{alert.title || '气象预警'}</span>
      {alertsTotal > 1 && <em>+{alertsTotal - 1}</em>}
      {onOpenDetails && <Icon.ChevronRight size={10} />}
    </>
  ) : (
    <>
      <Icon.Info size={isSmall ? 12 : 13} />
      <span>预警数据暂不可用</span>
    </>
  );

  return (
    <section
      className={`weather-sky-panel weather-sky-${sky.tone} weather-sky-icon-${sky.icon} weather-sky-compact weather-sky-${size}`}
      aria-busy={loading}
    >
      <SkyAtmosphere tone={sky.tone} icon={sky.icon} />

      <div className="weather-compact-top">
        <Icon.Globe size={isSmall ? 12 : 13} />
        <strong title={data.location.address}>{data.location.address}</strong>
        {isSmall ? (
          <span>{updateTime(data.updated_at, false)}</span>
        ) : (
          <div className="weather-compact-actions">
            <span>{updateTime(data.updated_at, false)}</span>
            {onRefresh && (
              <button type="button" className="weather-sky-button weather-sky-refresh" title="刷新当前地点天气" aria-label="刷新当前地点天气" disabled={loading} onClick={onRefresh}>
                <span className={loading ? 'spin-ic' : ''}><Icon.Refresh size={12} /></span>
              </button>
            )}
            {onOpenDetails && (
              <button type="button" className="weather-sky-button weather-compact-detail" onClick={onOpenDetails}>
                查看详情 <Icon.ChevronRight size={9} />
              </button>
            )}
          </div>
        )}
      </div>

      <div className="weather-compact-current">
        <WeatherIcon skycon={current.skycon} size={isSmall ? 46 : 60} className="weather-sky-main-icon" />
        <div className="weather-compact-current-copy">
          <div className="weather-sky-temperature"><span>{roundWeather(current.temperature)}</span><small>°</small></div>
          {isSmall ? (
            <div className="weather-sky-condition">
              {conditionLabel} · 体感 {roundWeather(current.apparent_temperature, '°')}
            </div>
          ) : (
            <>
              <div className="weather-sky-condition">{conditionLabel}</div>
              <div className="weather-sky-feels">
                体感 {roundWeather(current.apparent_temperature, '°')}
                {today && <> · <span className="mono">{roundWeather(today.temperature_max, '°')} / {roundWeather(today.temperature_min, '°')}</span></>}
              </div>
            </>
          )}
        </div>
        {isSmall && today && (
          <div className="weather-compact-today mono">
            <span>今</span>
            <strong>{roundWeather(today.temperature_max, '°')}/{roundWeather(today.temperature_min, '°')}</strong>
          </div>
        )}
      </div>

      <div className="weather-sky-short weather-compact-short">
        <WeatherIcon skycon={nextSkycon} size={isSmall ? 14 : 15} />
        {isSmall ? (
          <div className="weather-sky-short-text">{shortText}</div>
        ) : (
          <div>
            <div className="weather-sky-short-title">{shortTitle}</div>
            <div className="weather-sky-short-text">{shortText}</div>
          </div>
        )}
      </div>

      {alert && onOpenDetails ? (
        <button type="button" className="weather-compact-alert" title={alert.description || alert.title} onClick={onOpenDetails}>
          {alertContent}
        </button>
      ) : alert ? (
        <div className="weather-compact-alert" title={alert.description || alert.title}>{alertContent}</div>
      ) : !alertsAvailable ? (
        <div className="weather-compact-alert is-unavailable">{alertContent}</div>
      ) : null}

      {!isSmall && <div className="weather-compact-spacer" />}
      <HelmetAdvice data={data} size={size} />
    </section>
  );
}

export function WeatherMetricsStrip({ data }: { data: WeatherResponse }) {
  const current = data.realtime;
  const tone = aqiTone(current.aqi);
  return (
    <div className="weather-metrics-strip">
      <span><UtilityIcon kind="droplet" />湿度 <b className="mono">{roundWeather(current.humidity, '%')}</b></span>
      <i />
      <span><WeatherIcon kind="wind" size={14} />{windDirection(current.wind_direction)} <b className="mono">{windScale(current.wind_speed)}</b></span>
      <i />
      <span><Icon.Eye size={14} />能见度 <b className="mono">{roundWeather(current.visibility, ' km')}</b></span>
      <i />
      <span><UtilityIcon kind="gauge" />气压 <b className="mono">{roundWeather(current.pressure, ' hPa')}</b></span>
      <span className={`weather-aqi weather-aqi-${tone}`}><em />AQI {roundWeather(current.aqi)}{current.aqi_description ? ` · ${current.aqi_description}` : ''}</span>
    </div>
  );
}

interface ChartPoint {
  x: number;
  y: number;
  item: WeatherHourlyItem;
  index: number;
}

function pointSegments(points: Array<ChartPoint | null>): ChartPoint[][] {
  const segments: ChartPoint[][] = [];
  let current: ChartPoint[] = [];
  for (const point of points) {
    if (point) current.push(point);
    if (!point && current.length) {
      segments.push(current);
      current = [];
    }
  }
  if (current.length) segments.push(current);
  return segments;
}

function pathForSegment(segment: ChartPoint[]): string {
  return segment
    .map((entry, index) => `${index ? 'L' : 'M'}${entry.x.toFixed(1)},${entry.y.toFixed(1)}`)
    .join(' ');
}

function compactHourLabel(item: WeatherHourlyItem, index: number, size: 's' | 'm'): string {
  const label = weatherHourLabel(item.datetime, index);
  if (label === '现在') return label;
  if (size === 'm') return label;
  const hour = (label.split(':')[0] || label).replace(/^0/, '');
  return `${hour}时`;
}

function WeatherCompactHourlyChart({
  items,
  size,
}: {
  items: WeatherHourlyItem[];
  size: 's' | 'm';
}) {
  const gradientKey = React.useId().replace(/:/g, '');
  const hours = items.slice(0, 12);
  const isSmall = size === 's';
  const viewBox = isSmall ? '0 -7 360 99' : '0 0 620 150';
  const startX = isSmall ? 16 : 20;
  const endX = isSmall ? 344 : 588;
  const temperatureTop = isSmall ? 14 : 44;
  const temperatureBottom = isSmall ? 38 : 84;
  const temperatureBaseline = isSmall ? 44 : 94;
  const timeY = isSmall ? 56 : 108;
  const dividerY = isSmall ? 61 : 114;
  const rainBaseline = isSmall ? 88 : 146;
  const rainFillBaseline = isSmall ? 89 : 147;
  const rainScale = isSmall ? 0.18 : 0.22;
  const step = hours.length > 1 ? (endX - startX) / (hours.length - 1) : 0;
  const temperatures = hours
    .map(item => item.temperature)
    .filter((value): value is number => value !== null && Number.isFinite(value));
  const minTemperature = temperatures.length ? Math.min(...temperatures) : 0;
  const maxTemperature = temperatures.length ? Math.max(...temperatures) : 1;
  const spread = Math.max(4, maxTemperature - minTemperature);
  const temperatureY = (value: number) => temperatureTop
    + ((maxTemperature - value) / spread) * (temperatureBottom - temperatureTop);
  const temperaturePoints: Array<ChartPoint | null> = hours.map((item, index) => (
    item.temperature === null || !Number.isFinite(item.temperature)
      ? null
      : { x: startX + step * index, y: temperatureY(item.temperature), item, index }
  ));
  const temperatureSegments = pointSegments(temperaturePoints);
  const rainPoints: Array<ChartPoint | null> = hours.map((item, index) => (
    item.precipitation_probability === null || !Number.isFinite(item.precipitation_probability)
      ? null
      : {
          x: startX + step * index,
          y: rainBaseline - Math.max(0, Math.min(100, item.precipitation_probability)) * rainScale,
          item,
          index,
        }
  ));
  const rainSegments = pointSegments(rainPoints);
  const temperatureLabelIndexes = new Set(isSmall
    ? [0, Math.max(0, hours.length - 1)]
    : [0, Math.floor(Math.max(0, hours.length - 1) / 2), Math.max(0, hours.length - 1)]);
  const timeLabelIndexes = new Set((isSmall ? [0, 4, 9, hours.length - 1] : [0, 3, 6, 9, hours.length - 1])
    .filter(index => index >= 0 && index < hours.length));
  const maxRainPoint = rainPoints.reduce<ChartPoint | null>((current, point) => {
    if (!point) return current;
    if (!current) return point;
    return (point.item.precipitation_probability ?? 0) > (current.item.precipitation_probability ?? 0) ? point : current;
  }, null);
  const temperatureGradient = `weather-compact-temperature-${size}-${gradientKey}`;
  const rainGradient = `weather-compact-rain-${size}-${gradientKey}`;

  if (!hours.length) {
    return <div className={`weather-trend weather-trend-${size}`}><div className="weather-trend-empty">当前套餐未返回逐时预报</div></div>;
  }

  return (
    <section className={`weather-trend weather-trend-${size}`}>
      <div className="weather-trend-head">
        <strong>逐小时 · 温度 + 降水</strong>
        <span className="mono">{isSmall ? `${hours.length}h` : `未来 ${hours.length} 小时`}</span>
      </div>
      <div className="weather-trend-scroll">
        <svg viewBox={viewBox} className="weather-trend-chart" role="img" aria-label={`未来 ${hours.length} 小时温度与降水概率趋势`}>
          <defs>
            <linearGradient id={temperatureGradient} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--weather-plot-color)" stopOpacity={isSmall ? '.16' : '.18'} /><stop offset="1" stopColor="var(--weather-plot-color)" stopOpacity="0" /></linearGradient>
            <linearGradient id={rainGradient} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--weather-plot-color)" stopOpacity={isSmall ? '.3' : '.32'} /><stop offset="1" stopColor="var(--weather-plot-color)" stopOpacity=".03" /></linearGradient>
          </defs>

          {!isSmall && hours.map((item, index) => {
            const info = skyInfo(item.skycon);
            return <WeatherIcon key={`compact-icon-${item.datetime}-${index}`} skycon={item.skycon} size={20} x={startX + step * index - 10} y={4} className={`weather-chart-icon tone-${info.tone}`} />;
          })}

          {temperatureSegments.map((segment, index) => {
            const first = segment[0];
            const last = segment[segment.length - 1];
            const path = pathForSegment(segment);
            return (
              <React.Fragment key={`compact-temperature-${index}`}>
                {first && last && <path d={`${path} L${last.x.toFixed(1)},${temperatureBaseline} L${first.x.toFixed(1)},${temperatureBaseline} Z`} fill={`url(#${temperatureGradient})`} />}
                <path d={path} fill="none" stroke="var(--weather-plot-color)" strokeWidth={isSmall ? 2 : 2.5} strokeLinecap="round" strokeLinejoin="round" />
              </React.Fragment>
            );
          })}

          {temperaturePoints.map((point, index) => point && temperatureLabelIndexes.has(index) ? (
            <text key={`compact-temp-${index}`} x={point.x} y={Math.max(isSmall ? 8 : 36, point.y - 8)} className="weather-chart-temp">{roundWeather(point.item.temperature, '°')}</text>
          ) : null)}
          {temperaturePoints[0] && <circle cx={temperaturePoints[0].x} cy={temperaturePoints[0].y} r={isSmall ? 3.2 : 4.5} fill="var(--bg-inset)" stroke="var(--weather-plot-color)" strokeWidth={isSmall ? 2 : 2.5} />}

          {hours.map((item, index) => timeLabelIndexes.has(index) ? (
            <text key={`compact-hour-${index}`} x={startX + step * index} y={timeY} className={`weather-chart-hour ${index === 0 ? 'current' : ''}`}>{compactHourLabel(item, index, size)}</text>
          ) : null)}
          <line x1={isSmall ? 8 : 10} y1={dividerY} x2={isSmall ? 352 : 592} y2={dividerY} stroke="var(--border-soft)" strokeWidth="1" />
          <text x={isSmall ? 4 : 6} y={isSmall ? 84 : 136} className="weather-chart-rain-label">降水</text>

          {rainSegments.map((segment, index) => {
            const first = segment[0];
            const last = segment[segment.length - 1];
            const path = pathForSegment(segment);
            return (
              <React.Fragment key={`compact-rain-${index}`}>
                {first && last && <path d={`${path} L${last.x.toFixed(1)},${rainFillBaseline} L${first.x.toFixed(1)},${rainFillBaseline} Z`} fill={`url(#${rainGradient})`} />}
                <path d={path} fill="none" stroke="var(--weather-plot-color)" strokeWidth={isSmall ? 1.4 : 1.75} strokeLinecap="round" strokeLinejoin="round" opacity=".8" />
              </React.Fragment>
            );
          })}
          {maxRainPoint && (maxRainPoint.item.precipitation_probability ?? 0) > 0 && (
            <text x={maxRainPoint.x} y={Math.max(isSmall ? 66 : 120, maxRainPoint.y - (isSmall ? 3 : 4))} className="weather-chart-rain-value">
              {Math.round(maxRainPoint.item.precipitation_probability ?? 0)}%
            </text>
          )}
        </svg>
      </div>
    </section>
  );
}

export function WeatherHourlyChart({
  items,
  limit = 12,
  variant = 'fusion',
}: {
  items: WeatherHourlyItem[];
  limit?: 12 | 24;
  variant?: 'fusion' | 'page';
}) {
  const gradientKey = React.useId().replace(/:/g, '');
  const hours = items.slice(0, limit);
  const page = variant === 'page';
  const viewWidth = page ? 1120 : 1000;
  const startX = page ? 40 : 44;
  const endX = page ? 1080 : 976;
  const step = hours.length > 1 ? (endX - startX) / (hours.length - 1) : 0;
  const temperatures = hours.map(item => item.temperature).filter((value): value is number => value !== null && Number.isFinite(value));
  const minTemperature = temperatures.length ? Math.min(...temperatures) : 0;
  const maxTemperature = temperatures.length ? Math.max(...temperatures) : 1;
  const spread = Math.max(4, maxTemperature - minTemperature);
  const tempY = (value: number) => 42 + ((maxTemperature - value) / spread) * 70;
  const temperaturePoints: Array<ChartPoint | null> = hours.map((item, index) => item.temperature === null || !Number.isFinite(item.temperature) ? null : ({ x: startX + step * index, y: tempY(item.temperature), item, index }));
  const temperatureSegments = pointSegments(temperaturePoints);
  const rainPoints: Array<ChartPoint | null> = hours.map((item, index) => item.precipitation_probability === null || !Number.isFinite(item.precipitation_probability) ? null : ({
    x: startX + step * index,
    y: 188 - Math.max(0, Math.min(100, item.precipitation_probability)) * 0.31,
    item,
    index,
  }));
  const rainSegments = pointSegments(rainPoints);
  const wetRanges: Array<{ start: number; end: number }> = [];
  hours.forEach((item, index) => {
    const wet = (item.precipitation_probability ?? 0) >= 30
      || (item.precipitation ?? 0) >= 0.03
      || Boolean(item.skycon?.includes('RAIN') || item.skycon?.includes('SNOW'));
    if (!wet) return;
    const previous = wetRanges[wetRanges.length - 1];
    if (previous && previous.end === index - 1) previous.end = index;
    else wetRanges.push({ start: index, end: index });
  });
  const temperatureLabelEvery = page ? 6 : 1;
  const timeLabelEvery = page ? 3 : 1;

  if (!hours.length) return <div className={`weather-trend weather-trend-${variant}`}><div className="weather-trend-empty">当前套餐未返回逐时预报</div></div>;

  return (
    <section className={`weather-trend weather-trend-${variant}`}>
      <div className="weather-trend-head">
        <div>
          <strong>{page ? '24 小时逐时预报' : '逐小时 · 温度 + 降水概率'}</strong>
          {page && <span>温度趋势 · 降水概率</span>}
        </div>
        <span className="mono">未来 {hours.length} 小时</span>
      </div>
      <div className="weather-trend-scroll">
        <svg viewBox={`0 0 ${viewWidth} 200`} className="weather-trend-chart" role="img" aria-label={`未来 ${hours.length} 小时温度与降水概率趋势`}>
          <defs>
            <linearGradient id={`weather-temp-fill-${variant}-${gradientKey}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--weather-plot-color)" stopOpacity=".2" /><stop offset="1" stopColor="var(--weather-plot-color)" stopOpacity="0" /></linearGradient>
            <linearGradient id={`weather-rain-fill-${variant}-${gradientKey}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--weather-plot-color)" stopOpacity=".34" /><stop offset="1" stopColor="var(--weather-plot-color)" stopOpacity=".03" /></linearGradient>
          </defs>
          {wetRanges.map(range => <rect key={`${range.start}-${range.end}`} x={Math.max(18, startX + step * range.start - step * .45)} y="2" width={Math.max(18, step * (range.end - range.start + .9))} height="148" rx="10" fill="var(--weather-plot-color)" opacity=".06" />)}
          <line x1={startX} y1="28" x2={startX} y2="152" stroke="var(--weather-plot-color)" strokeWidth="1" strokeDasharray="2 3" opacity=".45" />
          {temperatureSegments.map((segment, index) => {
            const first = segment[0];
            const last = segment[segment.length - 1];
            const path = pathForSegment(segment);
            return <React.Fragment key={`temperature-${index}`}>
              {first && last && <path d={`${path} L${last.x.toFixed(1)},122 L${first.x.toFixed(1)},122 Z`} fill={`url(#weather-temp-fill-${variant}-${gradientKey})`} />}
              <path d={path} fill="none" stroke="var(--weather-plot-color)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </React.Fragment>;
          })}
          {hours.map((item, index) => {
            const info = skyInfo(item.skycon);
            return <WeatherIcon key={`icon-${item.datetime}-${index}`} skycon={item.skycon} size={20} x={startX + step * index - 10} y={5} className={`weather-chart-icon tone-${info.tone}`} />;
          })}
          {temperaturePoints.map((point, index) => point && (index % temperatureLabelEvery === 0 || index === hours.length - 1) ? <text key={`temp-${index}`} x={point.x} y={Math.max(34, point.y - 9)} className="weather-chart-temp">{roundWeather(point.item.temperature, '°')}</text> : null)}
          {temperaturePoints[0] && <circle cx={temperaturePoints[0]!.x} cy={temperaturePoints[0]!.y} r="3.5" fill="var(--bg-inset)" stroke="var(--weather-plot-color)" strokeWidth="2" />}
          {hours.map((item, index) => (index % timeLabelEvery === 0 || index === hours.length - 1) ? <text key={`hour-${index}`} x={startX + step * index} y="141" className={`weather-chart-hour ${index === 0 ? 'current' : ''}`}>{weatherHourLabel(item.datetime, index).replace(':00', '')}</text> : null)}
          <line x1="20" y1="150" x2={viewWidth - 10} y2="150" stroke="var(--border-soft)" strokeWidth="1" />
          <text x="14" y="187" className="weather-chart-rain-label">降水</text>
          {rainSegments.map((segment, index) => {
            const first = segment[0];
            const last = segment[segment.length - 1];
            const path = pathForSegment(segment);
            return <React.Fragment key={`rain-path-${index}`}>
              <path d={`${path} L${last.x.toFixed(1)},189 L${first.x.toFixed(1)},189 Z`} fill={`url(#weather-rain-fill-${variant}-${gradientKey})`} />
              <path d={path} fill="none" stroke="var(--weather-plot-color)" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" opacity=".82" />
            </React.Fragment>;
          })}
          {rainPoints.map((point, index) => {
            if (!point) return null;
            const probability = Math.round(point.item.precipitation_probability ?? 0);
            if (probability < 30 || (page && index % 2)) return null;
            return <g key={`rain-${index}`}><circle cx={point.x} cy={point.y} r="2" fill="var(--weather-plot-color)" /><text x={point.x} y={point.y - 5} className="weather-chart-rain-value">{probability}%</text></g>;
          })}
        </svg>
      </div>
    </section>
  );
}

function compactDayLabel(date: string, index: number): string {
  const label = weatherDayLabel(date, index);
  if (index === 0) return '今';
  if (index === 1) return '明';
  return label.replace(/^周/, '');
}

export function WeatherDailyStrip({
  items,
  size = 'l',
}: {
  items: WeatherDailyItem[];
  size?: WeatherCardSize;
}) {
  const days = items.slice(0, 5);
  if (!days.length) return <div className={`weather-daily-strip-empty weather-daily-strip-empty-${size}`}>暂无日级预报</div>;
  const compact = size !== 'l';
  return (
    <div className={`weather-daily-strip-wrap weather-daily-strip-wrap-${size}`}>
      <div
        className={`weather-daily-strip weather-daily-strip-${size}`}
        style={{ gridTemplateColumns: `repeat(${days.length}, ${compact ? 'minmax(0, 1fr)' : 'minmax(110px, 1fr)'})` }}
      >
        {days.map((day, index) => {
          const info = skyInfo(day.skycon);
          return (
            <div className={`weather-daily-cell weather-daily-cell-${size}`} key={`${day.date}-${index}`}>
              {size === 'm' ? (
                <div className="weather-daily-date">
                  <span className={index === 0 ? 'today' : ''}>{weatherDayLabel(day.date, index)}</span>
                  <small className="mono">{day.date.slice(5).replace('-', '/')}</small>
                </div>
              ) : (
                <span className={index === 0 ? 'today' : ''}>{size === 's' ? compactDayLabel(day.date, index) : weatherDayLabel(day.date, index)}</span>
              )}
              <WeatherIcon skycon={day.skycon} size={size === 's' ? 18 : size === 'm' ? 22 : 24} className={`tone-${info.tone}`} />
              {size === 's' ? (
                <>
                  <strong className="mono">{roundWeather(day.temperature_max, '°')}</strong>
                  <span className="weather-daily-low mono">{roundWeather(day.temperature_min, '°')}</span>
                </>
              ) : (
                <strong className="mono">{roundWeather(day.temperature_max, '°')} <em>/ {roundWeather(day.temperature_min, '°')}</em></strong>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function WeatherOverviewCard({
  data,
  size,
  loading = false,
  onRefresh,
  onOpenDetails,
}: {
  data: WeatherResponse;
  size: WeatherCardSize;
  loading?: boolean;
  onRefresh: () => void;
  onOpenDetails?: () => void;
}) {
  if (size === 'm') {
    return (
      <div className="weather-fusion-card weather-overview-card weather-overview-m">
        <WeatherCompactSkyPanel
          data={data}
          size="m"
          loading={loading}
          onRefresh={onRefresh}
          onOpenDetails={onOpenDetails}
        />
        <div className="weather-overview-m-main">
          <WeatherCompactHourlyChart items={data.hourly} size="m" />
          <WeatherDailyStrip items={data.daily} size="m" />
        </div>
      </div>
    );
  }

  if (size === 's') {
    return (
      <div className="weather-fusion-card weather-overview-card weather-overview-s">
        <WeatherCompactSkyPanel data={data} size="s" loading={loading} onOpenDetails={onOpenDetails} />
        <WeatherCompactHourlyChart items={data.hourly} size="s" />
        <WeatherDailyStrip items={data.daily} size="s" />
      </div>
    );
  }

  return (
    <div className="weather-fusion-card weather-overview-card weather-overview-l">
      <WeatherSkyPanel
        data={data}
        loading={loading}
        onRefresh={onRefresh}
        onOpenDetails={onOpenDetails}
      />
      <WeatherMetricsStrip data={data} />
      <WeatherHourlyChart items={data.hourly} limit={12} />
      <WeatherDailyStrip items={data.daily} size="l" />
    </div>
  );
}
