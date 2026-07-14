import {
  api,
  ApiError,
  type WeatherHourlyItem,
  type WeatherResponse,
} from './api';
import {
  DEFAULT_WEATHER_LOCATION,
  type WeatherLocation,
} from './weatherLocations';

export const WEATHER_SESSION_TTL = 10 * 60 * 1000;

export interface SkyInfo {
  label: string;
  glyph: string;
  tone: string;
  icon: WeatherIconKind;
}

export type WeatherIconKind =
  | 'sun'
  | 'moon'
  | 'partly'
  | 'partly-night'
  | 'cloud'
  | 'rain'
  | 'thunder'
  | 'snow'
  | 'haze'
  | 'wind';

const SKYCON: Record<string, SkyInfo> = {
  CLEAR_DAY: { label: '晴', glyph: '☀︎', tone: 'sun', icon: 'sun' },
  CLEAR_NIGHT: { label: '晴夜', glyph: '☾', tone: 'night', icon: 'moon' },
  PARTLY_CLOUDY_DAY: { label: '多云', glyph: '◒', tone: 'cloud', icon: 'partly' },
  PARTLY_CLOUDY_NIGHT: { label: '多云', glyph: '◒', tone: 'night', icon: 'partly-night' },
  CLOUDY: { label: '阴', glyph: '☁︎', tone: 'cloud', icon: 'cloud' },
  LIGHT_HAZE: { label: '轻度雾霾', glyph: '≡', tone: 'haze', icon: 'haze' },
  MODERATE_HAZE: { label: '中度雾霾', glyph: '≡', tone: 'haze', icon: 'haze' },
  HEAVY_HAZE: { label: '重度雾霾', glyph: '≡', tone: 'haze', icon: 'haze' },
  LIGHT_RAIN: { label: '小雨', glyph: '☂︎', tone: 'rain', icon: 'rain' },
  MODERATE_RAIN: { label: '中雨', glyph: '☂︎', tone: 'rain', icon: 'rain' },
  HEAVY_RAIN: { label: '大雨', glyph: '☂︎', tone: 'rain', icon: 'rain' },
  STORM_RAIN: { label: '暴雨', glyph: '☂︎', tone: 'rain', icon: 'thunder' },
  FOG: { label: '雾', glyph: '≡', tone: 'haze', icon: 'haze' },
  LIGHT_SNOW: { label: '小雪', glyph: '❄︎', tone: 'snow', icon: 'snow' },
  MODERATE_SNOW: { label: '中雪', glyph: '❄︎', tone: 'snow', icon: 'snow' },
  HEAVY_SNOW: { label: '大雪', glyph: '❄︎', tone: 'snow', icon: 'snow' },
  STORM_SNOW: { label: '暴雪', glyph: '❄︎', tone: 'snow', icon: 'snow' },
  DUST: { label: '浮尘', glyph: '≡', tone: 'haze', icon: 'haze' },
  SAND: { label: '沙尘', glyph: '≡', tone: 'haze', icon: 'haze' },
  WIND: { label: '大风', glyph: '≋', tone: 'wind', icon: 'wind' },
};

const weatherSessions = new Map<string, { data: WeatherResponse; fetchedAt: number }>();
const weatherPending = new Map<string, Promise<WeatherResponse>>();

export function skyInfo(skycon: string | null | undefined): SkyInfo {
  return (skycon && SKYCON[skycon]) || {
    label: '天气',
    glyph: '·',
    tone: 'cloud',
    icon: 'cloud',
  };
}

export function getCachedWeather(location: WeatherLocation = DEFAULT_WEATHER_LOCATION): WeatherResponse | null {
  const session = weatherSessions.get(location.id);
  return session && Date.now() - session.fetchedAt < WEATHER_SESSION_TTL
    ? session.data
    : null;
}

export async function loadWeatherData(location: WeatherLocation, force: boolean): Promise<WeatherResponse> {
  const cached = getCachedWeather(location);
  if (!force && cached) return cached;
  const pending = weatherPending.get(location.id);
  if (!force && pending) return pending;

  const task = (async () => {
    const response = await api.getWeather(
      location.latitude,
      location.longitude,
      force,
      location.address,
    );
    const data: WeatherResponse = {
      ...response,
      location: {
        ...response.location,
        name: location.name,
        address: location.address,
        resolved: true,
      },
      address_warning: null,
    };
    weatherSessions.set(location.id, { data, fetchedAt: Date.now() });
    return data;
  })();

  if (!force) weatherPending.set(location.id, task);
  try {
    return await task;
  } finally {
    if (weatherPending.get(location.id) === task) weatherPending.delete(location.id);
  }
}

export function weatherErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.payload && typeof error.payload === 'object') {
    const message = (error.payload as { error?: unknown }).error;
    if (typeof message === 'string' && message) return message;
  }
  if (error instanceof Error && error.message) return error.message;
  return '天气加载失败，请稍后重试';
}

export function windDirection(degrees: number | null): string {
  if (degrees === null || !Number.isFinite(degrees)) return '—';
  const labels = ['北', '东北', '东', '东南', '南', '西南', '西', '西北'];
  return `${labels[Math.round((((degrees % 360) + 360) % 360) / 45) % 8]}风`;
}

export function windScale(speed: number | null): string {
  if (speed === null || !Number.isFinite(speed)) return '—';
  const thresholds = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118];
  const level = thresholds.findIndex(limit => speed < limit);
  return `${level === -1 ? 12 : level}级`;
}

export function weatherTransitionLabel(
  currentSkycon: string | null | undefined,
  hourly: WeatherHourlyItem[],
): string {
  const current = skyInfo(currentSkycon);
  const next = hourly.slice(1, 7)
    .map(item => skyInfo(item.skycon))
    .find(item => item.label !== current.label);
  return next ? `${current.label}转${next.label}` : current.label;
}

export interface NightRainSlot {
  datetime: number;
  label: string;
  probability: number | null;
  intensity: number | null;
  wet: boolean;
  covered: boolean;
}

export interface NightRainAdvice {
  status: 'rain' | 'dry' | 'unknown';
  title: string;
  badge: string;
  detail: string;
  rainHours: number;
  complete: boolean;
  slots: NightRainSlot[];
}

const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000;

function shanghaiDate(base: Date): Date {
  return new Date(base.getTime() + SHANGHAI_OFFSET_MS);
}

function atShanghaiHour(base: Date, hour: number, dayOffset = 0): Date {
  const local = shanghaiDate(base);
  return new Date(Date.UTC(
    local.getUTCFullYear(),
    local.getUTCMonth(),
    local.getUTCDate() + dayOffset,
    hour,
  ) - SHANGHAI_OFFSET_MS);
}

function hourLabel(epoch: number): string {
  return `${String(shanghaiDate(new Date(epoch)).getUTCHours()).padStart(2, '0')}:00`;
}

function isWetHour(item: WeatherHourlyItem): boolean {
  const code = item.skycon || '';
  return code.includes('RAIN')
    || code.includes('SNOW')
    || (Number.isFinite(item.precipitation_probability) && (item.precipitation_probability ?? 0) >= 30)
    || (Number.isFinite(item.precipitation) && (item.precipitation ?? 0) >= 0.03);
}

export function buildNightRainAdvice(
  hourly: WeatherHourlyItem[],
  now = new Date(),
  current?: Pick<WeatherResponse['realtime'], 'skycon' | 'precipitation_intensity'>,
): NightRainAdvice {
  // 产品语义是“今天下班后的今晚”，凌晨查看时仍分析今天 17:00 至明天 08:00。
  const windowStart = atShanghaiHour(now, 17);
  const windowEnd = atShanghaiHour(now, 8, 1);
  const effectiveStart = Math.max(now.getTime(), windowStart.getTime());
  const firstFullHour = Math.ceil(effectiveStart / (60 * 60 * 1000)) * 60 * 60 * 1000;
  const byHour = new Map<number, WeatherHourlyItem>();

  for (const item of hourly) {
    const parsed = new Date(item.datetime);
    if (Number.isNaN(parsed.getTime())) continue;
    byHour.set(Math.floor(parsed.getTime() / (60 * 60 * 1000)) * 60 * 60 * 1000, item);
  }

  const slots: NightRainSlot[] = Array.from({ length: 15 }, (_, index) => {
    const datetime = windowStart.getTime() + index * 60 * 60 * 1000;
    const item = byHour.get(datetime);
    const rawProbability = item?.precipitation_probability;
    const rawIntensity = item?.precipitation;
    const probability = Number.isFinite(rawProbability)
      ? Math.max(0, Math.min(100, rawProbability as number))
      : null;
    const intensity = Number.isFinite(rawIntensity)
      ? Math.max(0, rawIntensity as number)
      : null;
    const precipitationSkycon = Boolean(item?.skycon?.includes('RAIN') || item?.skycon?.includes('SNOW'));
    return {
      datetime,
      label: String(shanghaiDate(new Date(datetime)).getUTCHours()).padStart(2, '0'),
      probability,
      intensity,
      wet: item ? isWetHour(item) : false,
      covered: probability !== null || intensity !== null || precipitationSkycon,
    };
  });

  // 小时预报通常从下一整点开始；用实况补当前残余小时，只用于识别正在发生的降水。
  const currentHourStart = Math.floor(now.getTime() / (60 * 60 * 1000)) * 60 * 60 * 1000;
  const currentSlot = slots.find(slot => slot.datetime === currentHourStart);
  if (currentSlot && current && currentSlot.datetime < firstFullHour) {
    const currentIntensity = Number.isFinite(current.precipitation_intensity)
      ? Math.max(0, current.precipitation_intensity as number)
      : null;
    const currentSkyconWet = Boolean(current.skycon?.includes('RAIN') || current.skycon?.includes('SNOW'));
    currentSlot.intensity = currentSlot.intensity ?? currentIntensity;
    currentSlot.wet = currentSlot.wet || currentSkyconWet || (currentIntensity ?? 0) >= 0.03;
    currentSlot.covered = currentSlot.covered || currentIntensity !== null || currentSkyconWet;
  }

  const futureSlots = slots.filter(slot => slot.datetime >= firstFullHour);
  const complete = futureSlots.length > 0 && futureSlots.every(slot => slot.covered);
  const currentPartialSlots = slots.filter(slot => slot.datetime < firstFullHour && slot.datetime + 60 * 60 * 1000 > effectiveStart);
  const wetSlots = [...currentPartialSlots, ...futureSlots].filter(slot => slot.covered && slot.wet);

  if (!wetSlots.length && !complete) {
    return {
      status: 'unknown',
      title: '今晚天气仍待确认',
      badge: '预报时段未完整',
      detail: '彩云逐小时数据尚未覆盖完整夜间，请稍后刷新。',
      rainHours: 0,
      complete,
      slots,
    };
  }

  if (!wetSlots.length) {
    return {
      status: 'dry',
      title: '今晚降雨风险较低',
      badge: '暂无明显降水',
      detail: `${hourLabel(Math.max(windowStart.getTime(), firstFullHour))}–次日 08:00 暂无明显降水信号。`,
      rainHours: 0,
      complete,
      slots,
    };
  }

  const peak = wetSlots.reduce((best, slot) => {
    const intensity = slot.intensity ?? 0;
    const bestIntensity = best.intensity ?? 0;
    if (intensity !== bestIntensity) return intensity > bestIntensity ? slot : best;
    return (slot.probability ?? 0) > (best.probability ?? 0) ? slot : best;
  });
  const peakIndex = slots.findIndex(slot => slot.datetime === peak.datetime);

  const firstWet = wetSlots[0].datetime;
  const lastWetEnd = wetSlots[wetSlots.length - 1].datetime + 60 * 60 * 1000;
  const tailSlots = futureSlots.filter(slot => slot.datetime >= lastWetEnd);
  const dryTailConfirmed = tailSlots.length > 0 && tailSlots.every(slot => slot.covered && !slot.wet);
  const dryTail = lastWetEnd < windowEnd.getTime() && dryTailConfirmed
    ? `，${hourLabel(lastWetEnd)} 后转干`
    : '';
  const incomplete = complete ? '' : ' · 部分时段预报待补齐';
  const hasDryGap = wetSlots.some((slot, index) => index > 0 && slot.datetime - wetSlots[index - 1].datetime > 60 * 60 * 1000);
  const rainWindow = hasDryGap
    ? `${hourLabel(firstWet)}–${hourLabel(lastWetEnd)} 期间有间歇性降水`
    : `预计 ${hourLabel(firstWet)}–${hourLabel(lastWetEnd)} 有雨`;

  return {
    status: 'rain',
    title: '今晚建议收好头盔',
    badge: `预计最强 ${hourLabel(slots[peakIndex].datetime)}–${hourLabel(slots[peakIndex].datetime + 60 * 60 * 1000)}`,
    detail: `停车后把头盔放进收纳箱 · ${rainWindow}${dryTail}${incomplete}`,
    rainHours: wetSlots.length,
    complete,
    slots,
  };
}

export function weatherDayLabel(date: string, index: number): string {
  if (index === 0) return '今天';
  if (index === 1) return '明天';
  const parsed = new Date(`${date}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? date.slice(5)
    : ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][parsed.getDay()];
}

export function weatherHourLabel(datetime: string, index: number): string {
  const parsed = new Date(datetime);
  if (Number.isNaN(parsed.getTime())) return datetime.slice(11, 16) || '—';
  if (index === 0 && Math.abs(parsed.getTime() - Date.now()) <= 30 * 60 * 1000) return '现在';
  const local = shanghaiDate(parsed);
  return `${String(local.getUTCHours()).padStart(2, '0')}:${String(local.getUTCMinutes()).padStart(2, '0')}`;
}

export function roundWeather(value: number | null, suffix = ''): string {
  return value === null || !Number.isFinite(value) ? '—' : `${Math.round(value)}${suffix}`;
}

export function aqiTone(value: number | null): 'neutral' | 'success' | 'info' | 'warning' | 'danger' {
  if (value === null || !Number.isFinite(value)) return 'neutral';
  if (value <= 50) return 'success';
  if (value <= 100) return 'info';
  if (value <= 150) return 'warning';
  return 'danger';
}
