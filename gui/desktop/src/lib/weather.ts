import {
  api,
  ApiError,
  type WeatherDailyItem,
  type WeatherHourlyItem,
  type WeatherRestPeriod,
  type WeatherResponse,
} from './api';
import {
  DEFAULT_WEATHER_LOCATION,
  LOCATED_WEATHER_LOCATION,
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
    if (location.id === LOCATED_WEATHER_LOCATION.id) {
      // "当前位置"：先经后端 IP 定位拿坐标，再不带固定地址请求天气，由后端做逆地理编码。
      // 展示统一为"当前位置 · 实际地名"（逆地理编码不可用时退回 IP 定位的城市名）；
      // name 和 address 都用这个标签，因为后端兜底的 address 是经纬度字符串，界面不能出现坐标。
      const geo = await api.getGeolocate(force);
      const response = await api.getWeather(geo.latitude, geo.longitude, force);
      const placeName = response.location.resolved ? response.location.name : geo.city;
      const label = placeName ? `当前位置 · ${placeName}` : '当前位置';
      const data: WeatherResponse = {
        ...response,
        location: { ...response.location, name: label, address: label, located: true },
      };
      weatherSessions.set(location.id, { data, fetchedAt: Date.now() });
      return data;
    }

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

export interface RestRainDaySlot {
  date: string;
  label: string;
  probability: number | null;
  wet: boolean;
  covered: boolean;
  estimated: boolean;
}

export interface RestRainAdvice {
  mode: 'rest';
  status: 'rain' | 'dry' | 'unknown';
  title: string;
  badge: string;
  detail: string;
  rainDays: number;
  rainHours: number;
  complete: boolean;
  days: RestRainDaySlot[];
  period: WeatherRestPeriod;
  windowStart: number;
  windowEnd: number;
}

export type HelmetRainAdvice =
  | ({ mode: 'night' } & NightRainAdvice)
  | RestRainAdvice;

const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;

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

function isCoveredHour(item: WeatherHourlyItem | undefined): boolean {
  if (!item) return false;
  return Number.isFinite(item.precipitation_probability)
    || Number.isFinite(item.precipitation)
    || Boolean(item.skycon);
}

function isWetDay(item: WeatherDailyItem): boolean {
  const code = item.skycon || '';
  return code.includes('RAIN')
    || code.includes('SNOW')
    || (Number.isFinite(item.precipitation_probability) && (item.precipitation_probability ?? 0) >= 30);
}

function isCoveredDay(item: WeatherDailyItem | undefined): boolean {
  return Boolean(item && (item.skycon || Number.isFinite(item.precipitation_probability)));
}

function shanghaiDayIso(epoch: number): string {
  const date = shanghaiDate(new Date(epoch));
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, '0'),
    String(date.getUTCDate()).padStart(2, '0'),
  ].join('-');
}

function restDayLabel(date: string, today: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  const todayEpoch = new Date(`${today}T00:00:00Z`).getTime();
  const delta = Math.round((parsed.getTime() - todayEpoch) / (24 * HOUR_MS));
  if (delta === 0) return '今天';
  if (delta === 1) return '明天';
  if (delta === -1) return '昨天';
  if (Number.isNaN(parsed.getTime())) return date.slice(5);
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][parsed.getUTCDay()];
}

function windowTimeLabel(epoch: number): string {
  const date = shanghaiDate(new Date(epoch));
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()} ${String(date.getUTCHours()).padStart(2, '0')}:00`;
}

function buildRestRainAdvice(
  hourly: WeatherHourlyItem[],
  daily: WeatherDailyItem[],
  periods: WeatherRestPeriod[],
  now: Date,
  current?: Pick<WeatherResponse['realtime'], 'skycon' | 'precipitation_intensity'>,
): RestRainAdvice | null {
  const nowEpoch = now.getTime();
  const active = periods
    .map(period => {
      const start = new Date(period.window_start).getTime();
      const explicitDisplayStart = period.display_start
        ? new Date(period.display_start).getTime()
        : Number.NaN;
      return {
        period,
        start,
        displayStart: Number.isFinite(explicitDisplayStart)
          ? explicitDisplayStart
          : start - 17 * HOUR_MS,
        end: new Date(period.window_end).getTime(),
      };
    })
    .find(({ displayStart, start, end }) => (
      Number.isFinite(displayStart)
      && Number.isFinite(start)
      && Number.isFinite(end)
      && nowEpoch >= displayStart
      && nowEpoch < end
    ));
  if (!active) return null;

  const effectiveStart = Math.max(nowEpoch, active.start);
  const firstFullHour = Math.ceil(effectiveStart / HOUR_MS) * HOUR_MS;
  const byHour = new Map<number, WeatherHourlyItem>();
  for (const item of hourly) {
    const parsed = new Date(item.datetime);
    if (Number.isNaN(parsed.getTime())) continue;
    byHour.set(Math.floor(parsed.getTime() / HOUR_MS) * HOUR_MS, item);
  }

  const hourSlots: Array<{
    datetime: number;
    probability: number | null;
    wet: boolean;
    covered: boolean;
  }> = [];
  for (
    let datetime = Math.floor(effectiveStart / HOUR_MS) * HOUR_MS;
    datetime < active.end;
    datetime += HOUR_MS
  ) {
    const item = byHour.get(datetime);
    const rawProbability = item?.precipitation_probability;
    const probability = Number.isFinite(rawProbability)
      ? Math.max(0, Math.min(100, rawProbability as number))
      : null;
    let wet = item ? isWetHour(item) : false;
    let covered = isCoveredHour(item);

    // 当前残余小时用实况补齐，保证假后上班日 08:00 前仍能判断正在发生的降水。
    if (datetime < firstFullHour && datetime + HOUR_MS > effectiveStart && current) {
      const currentIntensity = Number.isFinite(current.precipitation_intensity)
        ? Math.max(0, current.precipitation_intensity as number)
        : null;
      const currentSkyconWet = Boolean(current.skycon?.includes('RAIN') || current.skycon?.includes('SNOW'));
      wet = wet || currentSkyconWet || (currentIntensity ?? 0) >= 0.03;
      covered = covered || currentIntensity !== null || Boolean(current.skycon);
    }
    hourSlots.push({ datetime, probability, wet, covered });
  }

  const dailyByDate = new Map(daily.map(item => [item.date, item]));
  const todayIso = shanghaiDayIso(nowEpoch);
  const dates = [...new Set(hourSlots.map(slot => shanghaiDayIso(slot.datetime)))];
  const daySlots: RestRainDaySlot[] = dates.map(date => {
    const hours = hourSlots.filter(slot => shanghaiDayIso(slot.datetime) === date);
    const dailyItem = dailyByDate.get(date);
    const hourlyCovered = hours.length > 0 && hours.every(slot => slot.covered);
    const dailyCovered = isCoveredDay(dailyItem);
    const estimated = !hourlyCovered && dailyCovered;
    const probabilities = hours
      .map(slot => slot.probability)
      .filter((value): value is number => value !== null);
    if (estimated && Number.isFinite(dailyItem?.precipitation_probability)) {
      probabilities.push(dailyItem!.precipitation_probability as number);
    }
    return {
      date,
      label: restDayLabel(date, todayIso),
      probability: probabilities.length ? Math.max(...probabilities) : null,
      wet: hours.some(slot => slot.covered && slot.wet)
        || Boolean(estimated && dailyItem && isWetDay(dailyItem)),
      covered: hourlyCovered || dailyCovered,
      estimated,
    };
  });

  const wetDays = daySlots.filter(slot => slot.covered && slot.wet);
  const rainHours = hourSlots.filter(slot => slot.covered && slot.wet).length;
  const complete = daySlots.length > 0 && daySlots.every(slot => slot.covered);
  const estimated = daySlots.some(slot => slot.estimated);
  const range = `${windowTimeLabel(active.start)}–${windowTimeLabel(active.end)}`;
  const sourceNote = estimated ? ' · 远期时段按日级预报判断' : '';
  const incomplete = complete ? '' : ' · 部分时段预报待补齐';

  if (!wetDays.length && !complete) {
    return {
      mode: 'rest',
      status: 'unknown',
      title: `${active.period.label}雨情待确认，建议先收好头盔`,
      badge: '预报时段未完整',
      detail: `提醒窗口 ${range} · 预报补齐前建议把头盔放进收纳箱${sourceNote}${incomplete}`,
      rainDays: 0,
      rainHours,
      complete,
      days: daySlots,
      period: active.period,
      windowStart: active.start,
      windowEnd: active.end,
    };
  }

  if (!wetDays.length) {
    return {
      mode: 'rest',
      status: 'dry',
      title: `${active.period.label}雨险低，头盔可按日常放置`,
      badge: '剩余时段暂无明显降水',
      detail: `提醒窗口 ${range} · 目前无需因降雨调整头盔存放${sourceNote}`,
      rainDays: 0,
      rainHours,
      complete,
      days: daySlots,
      period: active.period,
      windowStart: active.start,
      windowEnd: active.end,
    };
  }

  const peak = wetDays.reduce((best, slot) => (
    (slot.probability ?? -1) > (best.probability ?? -1) ? slot : best
  ));
  const peakText = peak.probability === null
    ? `${peak.label}有降水`
    : `最高 ${peak.label} ${Math.round(peak.probability)}%`;
  const rainyDayText = wetDays.map(slot => slot.label).join('、');
  return {
    mode: 'rest',
    status: 'rain',
    title: `${active.period.label}有雨，建议收好头盔`,
    badge: peakText,
    detail: `提醒窗口 ${range} · ${rainyDayText}有降水信号，离车时请把头盔放进收纳箱${sourceNote}${incomplete}`,
    rainDays: wetDays.length,
    rainHours,
    complete,
    days: daySlots,
    period: active.period,
    windowStart: active.start,
    windowEnd: active.end,
  };
}

export function buildHelmetRainAdvice(
  data: Pick<WeatherResponse, 'hourly' | 'daily' | 'rest_daily' | 'realtime' | 'rest_periods'>,
  now = new Date(),
): HelmetRainAdvice {
  const restAdvice = buildRestRainAdvice(
    data.hourly,
    data.rest_daily ?? data.daily,
    data.rest_periods ?? [],
    now,
    data.realtime,
  );
  if (restAdvice) return restAdvice;
  return {
    mode: 'night',
    ...buildNightRainAdvice(data.hourly, now, data.realtime),
  };
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
