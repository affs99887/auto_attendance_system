// 天气页和首页天气卡片共用的部件：天气图标、头盔提醒、逐小时图，以及首页那张天气卡片。
import * as React from 'react';
import { Icon } from '../lib/icons';
import type { WeatherHourlyItem, WeatherResponse } from '../lib/api';
import {
  buildHelmetRainAdvice,
  roundWeather,
  skyInfo,
  weatherDayLabel,
  weatherHourLabel,
  weatherTransitionLabel,
  type HelmetRainAdvice,
  type WeatherIconKind,
} from '../lib/weather';
import { resolveSkyKind, skyTone, type SkyOptions } from '../lib/sky';
import { GlassPanel, usePanelFall } from './GlassPanel';
import { WeatherSky } from './WeatherSky';

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
      strokeWidth="1.6"
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
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3.8 15a8.2 8.2 0 0 1 16.4 0z" />
      <path d="M20.2 15c1.35.1 2.15-.35 2.35-1.3" />
      <path d="M9.4 8.8l1.2 3M13 8.3l1 3.2" />
    </svg>
  );
}

/** 当前时间，每隔 intervalMs 更新一次 */
export function useNow(intervalMs: number): Date {
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** 更新时间：天气页写到"月/日 时:分"，首页卡片只写"时:分" */
export function weatherUpdateTime(epoch: number, withDate: boolean): string {
  return new Date(epoch * 1000).toLocaleString('zh-CN', withDate
    ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }
    : { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' });
}

/** 短时提示那句话，以及它说的是哪一段时间（鼠标停上去时显示） */
export function weatherShortText(data: WeatherResponse): { text: string; title: string } {
  return {
    text: data.minutely_description || data.forecast_keypoint || data.hourly_description || '暂无短时天气提示',
    title: data.minutely_description ? '未来两小时 · 彩云短时' : '未来 24 小时 · 彩云天气',
  };
}

// ---------- 头盔提醒 ----------
function helmetAria(advice: HelmetRainAdvice): string {
  return advice.mode === 'rest'
    ? `${advice.period.label}提醒时段，从放假前一日17点至假后首个工作日8点，共 ${advice.rainDays} 天有降水信号`
    : `17点至次日8点逐小时降雨时间轴，共 ${advice.rainHours} 个时段有降水信号`;
}

/** 提醒时段的小格子：平时是 17 点到次日 8 点一小时一格，放假前后是一天一格。有雨的格子上色，雨越大颜色越实；没有预报数据的画成空心 */
function HelmetCells({ advice, labels }: { advice: HelmetRainAdvice; labels: boolean }) {
  const cell = (key: string | number, wet: boolean, covered: boolean, strength: number, title: string, text?: string) => (
    <span
      key={key}
      className={`${wet ? 'wet' : ''} ${covered ? '' : 'uncovered'}`}
      title={title}
      style={{ '--s': strength.toFixed(2) } as React.CSSProperties}
    >
      {text}
    </span>
  );
  if (advice.mode === 'rest') {
    return (
      <div className="wx-helmet-cells days" style={{ '--n': Math.max(1, advice.days.length) } as React.CSSProperties}>
        {advice.days.map(slot => cell(
          slot.date,
          slot.wet,
          slot.covered,
          Math.max(.5, (slot.probability ?? 35) / 100),
          `${slot.date} ${slot.label} · 降水概率 ${slot.probability === null ? '暂无' : `${Math.round(slot.probability)}%`}${slot.estimated ? ' · 日级预报' : ''}`,
          labels ? slot.label : undefined,
        ))}
      </div>
    );
  }
  return (
    <div className="wx-helmet-cells" style={{ '--n': Math.max(1, advice.slots.length) } as React.CSSProperties}>
      {advice.slots.map(slot => cell(
        slot.datetime,
        slot.wet,
        slot.covered,
        Math.max(.34, (slot.probability ?? 0) / 100, Math.min(1, (slot.intensity ?? 0) / 3)),
        `${slot.label}:00 · 降水概率 ${slot.probability === null ? '暂无' : `${Math.round(slot.probability)}%`}`,
      ))}
    </div>
  );
}

/** 天气页右上的头盔提醒面板 */
export function HelmetPanel({ data }: { data: WeatherResponse }) {
  const now = useNow(60_000);
  const advice = React.useMemo(() => buildHelmetRainAdvice(data, now), [data, now]);
  const rest = advice.mode === 'rest';
  return (
    <GlassPanel className={`wx-helmet is-${advice.status}`}>
      <div className="wx-helmet-head">
        <span className="wx-helmet-ico"><HelmetIcon size={22} /></span>
        <div className="wx-helmet-copy">
          <div className="wx-helmet-title">
            <h2>{advice.title}</h2>
            <span className="wx-helmet-pill">{advice.badge}</span>
          </div>
          <p className="wx-helmet-detail">{advice.detail}</p>
        </div>
      </div>
      <div className="wx-helmet-line" role="img" aria-label={helmetAria(advice)}>
        <div className="wx-helmet-line-head">
          <span>{rest ? `${advice.period.label}雨情` : '今夜降雨时段'}</span>
          <b>
            {advice.status === 'rain'
              ? rest ? `${advice.rainDays} 天有雨` : `约 ${advice.rainHours} 小时有雨`
              : advice.badge}
          </b>
        </div>
        <HelmetCells advice={advice} labels />
        {rest ? (
          <div className="wx-helmet-axis"><span>放假前一日 17:00</span><span>首个工作日 08:00</span></div>
        ) : (
          <div className="wx-helmet-axis"><span>17</span><span>20</span><span>23</span><span>02</span><span>05</span><span>08</span></div>
        )}
      </div>
    </GlassPanel>
  );
}

/** 首页卡片左下角那条小号的头盔提醒 */
function HelmetStrip({ data }: { data: WeatherResponse }) {
  const now = useNow(60_000);
  const advice = React.useMemo(() => buildHelmetRainAdvice(data, now), [data, now]);
  const firstSlot = advice.mode === 'night' ? advice.slots[0] : null;
  const startLabel = advice.mode === 'rest'
    ? '放假前17时'
    : firstSlot?.covered
      ? firstSlot.wet ? '17时 有雨' : '17时 无雨'
      : '17时';
  const endLabel = advice.mode === 'rest' ? '上班日8时' : '次日8时';
  return (
    <GlassPanel className={`wxc-helmet is-${advice.status}`}>
      <span className="wx-helmet-ico"><HelmetIcon size={19} /></span>
      <div className="wxc-helmet-copy" role="img" aria-label={helmetAria(advice)}>
        <b>{advice.title}</b>
        <HelmetCells advice={advice} labels={false} />
        <div className="wx-helmet-axis"><span>{startLabel}</span><span>{endLabel}</span></div>
      </div>
    </GlassPanel>
  );
}

// ---------- 逐小时图 ----------
// 从上到下依次是 天气图标 / 气温线 / 降水概率柱 / 钟点。天气页画 24 小时，首页卡片画 12 小时，只是尺寸不同。
// icon 是天气图标的大小；其余各项是纵向位置：yIcon 天气图标，yT0~yT1 气温线的上下范围，yRain 降水柱的底边，rainH 降水柱最高多高，yHour 钟点文字
const CHART = {
  page: { n: 24, H: 184, padX: 26, icon: 18, yIcon: 5, yT0: 58, yT1: 100, yRain: 150, rainH: 26, yHour: 173, hover: true },
  card: { n: 12, H: 142, padX: 34, icon: 20, yIcon: 2, yT0: 50, yT1: 74, yRain: 116, rainH: 18, yHour: 135, hover: false },
};
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const f1 = (value: number) => value.toFixed(1);

/** 一个时刻按北京时间是几点、星期几；时间格式认不出来时返回 null */
function hourParts(datetime: string): { hour: number; weekday: string } | null {
  const parsed = new Date(datetime);
  if (Number.isNaN(parsed.getTime())) return null;
  const local = new Date(parsed.getTime() + 8 * 60 * 60 * 1000);
  return { hour: local.getUTCHours(), weekday: WEEKDAYS[local.getUTCDay()] };
}

/** 过一串点的平滑曲线 */
function curveThrough(points: Array<[number, number]>): string {
  let d = `M${f1(points[0][0])},${f1(points[0][1])}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(0, i - 1)], p1 = points[i], p2 = points[i + 1], p3 = points[Math.min(points.length - 1, i + 2)];
    d += ` C${f1(p1[0] + (p2[0] - p0[0]) / 6)},${f1(p1[1] + (p2[1] - p0[1]) / 6)} ${f1(p2[0] - (p3[0] - p1[0]) / 6)},${f1(p2[1] - (p3[1] - p1[1]) / 6)} ${f1(p2[0])},${f1(p2[1])}`;
  }
  return d;
}

/** 元素当前的宽度，随它变宽变窄更新 */
function useElementWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = React.useRef<T>(null);
  const [width, setWidth] = React.useState(0);
  React.useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.clientWidth);
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

export function WeatherHourlyChart({ items, variant }: { items: WeatherHourlyItem[]; variant: 'page' | 'card' }) {
  const o = CHART[variant];
  const gradientId = `wx-area-${React.useId().replace(/:/g, '')}`;
  const [plotRef, width] = useElementWidth<HTMLDivElement>();
  const [hoverIndex, setHoverIndex] = React.useState<number | null>(null);
  const hours = items.slice(0, o.n);

  if (!hours.length) return <div className="wx-chart-empty">当前套餐未返回逐时预报</div>;

  const last = hours.length - 1;
  const step = last > 0 ? (width - o.padX * 2) / last : 0;
  const X = (index: number) => o.padX + index * step;
  const temperatures = hours.map(item => item.temperature).filter((value): value is number => value !== null && Number.isFinite(value));
  const tMin = temperatures.length ? Math.min(...temperatures) : 0;
  const spread = Math.max(4, (temperatures.length ? Math.max(...temperatures) : 1) - tMin);
  const Y = (value: number) => o.yT1 - (value - tMin) / spread * (o.yT1 - o.yT0);
  const hasTemperature = (item: WeatherHourlyItem): item is WeatherHourlyItem & { temperature: number } => item.temperature !== null && Number.isFinite(item.temperature);
  // 中间缺气温数据的小时把线断开，每一段各画各的
  const segments: Array<Array<[number, number]>> = [];
  hours.forEach((item, index) => {
    if (!hasTemperature(item)) return;
    const previous = index > 0 && hasTemperature(hours[index - 1]) ? segments[segments.length - 1] : undefined;
    if (previous) previous.push([X(index), Y(item.temperature)]);
    else segments.push([[X(index), Y(item.temperature)]]);
  });
  // 每小时都画图标、气温和钟点；一格窄到连气温都放不下时，才改成隔一个写一个
  const every = step >= 28 ? 1 : 2;
  // 一格不够宽时钟点只写数字，省掉"时"字
  const hourSuffix = step >= 34 ? '时' : '';
  const floor = o.yT1 + 20;
  const isWet = (item: WeatherHourlyItem) => (item.precipitation_probability ?? 0) >= 30
    || (item.precipitation ?? 0) >= .03
    || Boolean(item.skycon?.includes('RAIN') || item.skycon?.includes('SNOW'));
  const labels = hours.map(item => skyInfo(item.skycon).label);
  const parts = hours.map(item => hourParts(item.datetime));
  const hourText = (index: number) => {
    const part = parts[index];
    return part ? `${part.hour}${hourSuffix}` : weatherHourLabel(hours[index].datetime, index);
  };

  const onMove = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!o.hover || !step) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) * (event.currentTarget.clientWidth / rect.width);
    setHoverIndex(Math.min(last, Math.max(0, Math.round((x - o.padX) / step))));
  };
  const hovered = hoverIndex !== null ? hours[hoverIndex] : null;

  return (
    <div className="wx-chart" ref={plotRef} onMouseMove={onMove} onMouseLeave={() => setHoverIndex(null)}>
      {width > 0 && (
        <svg viewBox={`0 0 ${width} ${o.H}`} height={o.H} role="img" aria-label={`未来 ${hours.length} 小时的天气、气温和降水概率`}>
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".2" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></linearGradient>
          </defs>

          {/* 第一列（现在）加一条很淡的底色 */}
          <rect x={f1(X(0) - step / 2)} y="-2" width={f1(step)} height={o.H} rx="10" fill="#fff" fillOpacity=".07" />

          {/* 天气图标：隔一个画一个的时候，天气变了的那个小时照样画出来 */}
          {hours.map((item, index) => index % every === 0 || labels[index - 1] !== labels[index]
            ? <WeatherIcon key={`icon-${index}`} skycon={item.skycon} size={o.icon} x={f1(X(index) - o.icon / 2)} y={o.yIcon} color="#fff" />
            : null)}

          {segments.map((segment, index) => {
            const path = curveThrough(segment), first = segment[0], end = segment[segment.length - 1];
            return (
              <React.Fragment key={`line-${index}`}>
                <path d={`${path} L${f1(end[0])},${floor} L${f1(first[0])},${floor} Z`} fill={`url(#${gradientId})`} />
                <path d={path} fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </React.Fragment>
            );
          })}
          {hours.map((item, index) => hasTemperature(item) && index % every === 0
            ? <text key={`temp-${index}`} className="wx-c-temp" x={f1(X(index))} y={f1(Y(item.temperature) - 10)}>{roundWeather(item.temperature, '°')}</text>
            : null)}
          {hasTemperature(hours[0]) && <circle cx={f1(X(0))} cy={f1(Y(hours[0].temperature))} r="4" fill="#fff" />}

          {/* 降水概率：一小时一根柱子；判定为有雨的小时用浅青色并标出数字 */}
          {hours.map((item, index) => {
            const probability = item.precipitation_probability;
            if (probability === null || !Number.isFinite(probability)) return null;
            const wet = isWet(item), barHeight = Math.max(3, Math.min(100, probability) / 100 * o.rainH), barWidth = Math.min(10, step * .26);
            return (
              <React.Fragment key={`rain-${index}`}>
                <rect
                  x={f1(X(index) - barWidth / 2)} y={f1(o.yRain - barHeight)} width={f1(barWidth)} height={f1(barHeight)}
                  rx={f1(Math.min(barWidth / 2, barHeight / 2))}
                  className={wet ? 'wx-c-bar wet' : 'wx-c-bar'}
                />
                {wet && <text className="wx-c-rain" x={f1(X(index))} y={f1(o.yRain - barHeight - 5)}>{Math.round(probability)}%</text>}
              </React.Fragment>
            );
          })}

          {/* 钟点：跨过零点的位置写星期几 */}
          {hours.map((item, index) => {
            if (index === 0) return <text key="hour-0" className="wx-c-hour strong" x={f1(X(0))} y={o.yHour}>{weatherHourLabel(item.datetime, 0) === '现在' ? '现在' : hourText(0)}</text>;
            if (parts[index]?.hour === 0) return <text key={`hour-${index}`} className="wx-c-hour strong" x={f1(X(index))} y={o.yHour}>{parts[index]!.weekday}</text>;
            // 隔一个写一个的时候，紧挨着零点的那两个钟点不写，给"星期几"留出地方
            if (every > 1 && (parts[index - 1]?.hour === 0 || parts[index + 1]?.hour === 0)) return null;
            return index % every === 0 ? <text key={`hour-${index}`} className="wx-c-hour" x={f1(X(index))} y={o.yHour}>{hourText(index)}</text> : null;
          })}

          {/* 鼠标停在哪个小时，那一列亮起来，气温线上标一个圆点 */}
          {hovered && hoverIndex !== null && (
            <g>
              <rect x={f1(X(hoverIndex) - step / 2)} y="-2" width={f1(step)} height={o.H} rx="10" fill="#fff" fillOpacity=".09" />
              {hasTemperature(hovered) && <circle cx={f1(X(hoverIndex))} cy={f1(Y(hovered.temperature))} r="4.5" fill="#fff" />}
            </g>
          )}
        </svg>
      )}
      {hovered && hoverIndex !== null && (
        <div
          className="wx-chart-tip"
          style={{
            left: Math.min(width - 70, Math.max(70, X(hoverIndex))),
            top: (hasTemperature(hovered) ? Y(hovered.temperature) : o.yT0) - 26,
          }}
        >
          <b>{parts[hoverIndex] ? `${String(parts[hoverIndex]!.hour).padStart(2, '0')}:00` : hourText(hoverIndex)}　{labels[hoverIndex]}　{roundWeather(hovered.temperature, '°')}</b>
          <span>降水概率 {roundWeather(hovered.precipitation_probability, '%')}</span>
        </div>
      )}
    </div>
  );
}

// ---------- 首页的天气卡片 ----------
// 整张卡片是一小片天空，用的是跟天气页同一套背景；左边把现在的天气直接写在天空上，右边一块玻璃面板放 12 小时图和未来 5 天。
// 卡片比窗口矮得多：太阳、月亮缩小一些，放在左栏的右上角（左栏宽度是固定的，所以位置按像素写；地址那一行在样式里给它留了空）；
// 云层放大后只露出靠上的一段；左边文字那一块的云调淡
const HOME_SKY: SkyOptions = { orb: { x: '302px', y: '42px', scale: .62 }, cloudScale: 1.9, calm: { x: 15, y: 42, rx: 24, ry: 62 } };

export function WeatherHomeCard({
  data,
  loading = false,
  onRefresh,
  onOpenDetails,
}: {
  data: WeatherResponse;
  loading?: boolean;
  onRefresh: () => void;
  onOpenDetails?: () => void;
}) {
  const now = useNow(60_000);
  const kind = resolveSkyKind(data.realtime.skycon, now);
  usePanelFall(kind);

  const current = data.realtime;
  const today = data.daily[0];
  const short = weatherShortText(data);
  const condition = weatherTransitionLabel(current.skycon, data.hourly.filter(item => Boolean(item.skycon)));
  const alert = data.alerts[0];
  const alertsTotal = Math.max(data.alerts.length, data.alerts_total || 0);
  const days = data.daily.slice(0, 5);
  const alertBody = alert && (
    <>
      <Icon.AlertTriangle size={13} className="wx-alert-ico" />
      <span>{alert.title || '气象预警'}</span>
      {alertsTotal > 1 && <em>+{alertsTotal - 1}</em>}
      {onOpenDetails && <Icon.ChevronRight size={10} />}
    </>
  );

  return (
    <section className="wxc" data-tone={skyTone(kind)} aria-busy={loading}>
      <WeatherSky kind={kind} options={HOME_SKY} className="wxc-sky" />

      <div className="wxc-now">
        <div className="wxc-addr">
          <strong title={data.location.address}>{data.location.address}</strong>
          <span>{weatherUpdateTime(data.updated_at, false)} 更新</span>
        </div>
        <div className="wxc-main">
          <div className="wxc-temp">{roundWeather(current.temperature)}<sup>°</sup></div>
          <div className="wxc-copy">
            <div className="wxc-cond"><WeatherIcon skycon={current.skycon} size={17} />{condition}</div>
            <div className="wxc-sub">
              <span>体感 {roundWeather(current.apparent_temperature, '°')}</span>
              {today && <><span>最高 {roundWeather(today.temperature_max, '°')}</span><span>最低 {roundWeather(today.temperature_min, '°')}</span></>}
            </div>
          </div>
        </div>
        <p className="wxc-say" title={`${short.title}：${short.text}`}>{short.text}</p>

        {alert && onOpenDetails ? (
          <GlassPanel as="button" type="button" className="wxc-alert" title={alert.description || alert.title} onClick={onOpenDetails}>{alertBody}</GlassPanel>
        ) : alert ? (
          <GlassPanel className="wxc-alert" title={alert.description || alert.title}>{alertBody}</GlassPanel>
        ) : data.alerts_available !== true ? (
          <GlassPanel className="wxc-alert is-unavailable"><Icon.Info size={13} /><span>预警数据暂不可用</span></GlassPanel>
        ) : null}

        <HelmetStrip data={data} />
      </div>

      <GlassPanel className="wxc-side" snowCap={8}>
        <div className="wxc-side-head">
          <h3>未来 12 小时</h3>
          <div className="wxc-actions">
            <button type="button" className="wx-btn ico" title="刷新当前地点天气" aria-label="刷新当前地点天气" disabled={loading} onClick={onRefresh}>
              <span className={loading ? 'spin-ic' : ''}><Icon.Refresh size={12} /></span>
            </button>
            {onOpenDetails && (
              <button type="button" className="wx-btn" onClick={onOpenDetails}>查看详情<Icon.ChevronRight size={10} /></button>
            )}
          </div>
        </div>
        <div className="wxc-plot"><WeatherHourlyChart items={data.hourly} variant="card" /></div>
        {days.length ? (
          <div className="wxc-days">
            {days.map((day, index) => (
              <div className={`wxc-day ${index === 0 ? 'is-today' : ''}`} key={`${day.date}-${index}`}>
                <b>{weatherDayLabel(day.date, index)}</b>
                <WeatherIcon skycon={day.skycon} size={16} />
                <span><strong>{roundWeather(day.temperature_max, '°')}</strong> <em>/ {roundWeather(day.temperature_min, '°')}</em></span>
              </div>
            ))}
          </div>
        ) : (
          <div className="wxc-days-empty">暂无日级预报</div>
        )}
      </GlassPanel>
    </section>
  );
}
