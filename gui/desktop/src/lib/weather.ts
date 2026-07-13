import { api, ApiError, type WeatherResponse } from './api';

export const WEATHER_SESSION_TTL = 10 * 60 * 1000;

export const FIXED_WEATHER_LOCATION = {
  address: '上海市长宁区华山路1076号',
  // 公开地图坐标由 BD-09 转为 GCJ-02，供彩云天气查询使用。
  latitude: 31.21126179,
  longitude: 121.43584026,
} as const;

export interface SkyInfo {
  label: string;
  glyph: string;
  tone: string;
}

const SKYCON: Record<string, SkyInfo> = {
  CLEAR_DAY: { label: '晴', glyph: '☀︎', tone: 'sun' },
  CLEAR_NIGHT: { label: '晴夜', glyph: '☾', tone: 'night' },
  PARTLY_CLOUDY_DAY: { label: '多云', glyph: '◒', tone: 'cloud' },
  PARTLY_CLOUDY_NIGHT: { label: '多云', glyph: '◒', tone: 'night' },
  CLOUDY: { label: '阴', glyph: '☁︎', tone: 'cloud' },
  LIGHT_HAZE: { label: '轻度雾霾', glyph: '≡', tone: 'haze' },
  MODERATE_HAZE: { label: '中度雾霾', glyph: '≡', tone: 'haze' },
  HEAVY_HAZE: { label: '重度雾霾', glyph: '≡', tone: 'haze' },
  LIGHT_RAIN: { label: '小雨', glyph: '☂︎', tone: 'rain' },
  MODERATE_RAIN: { label: '中雨', glyph: '☂︎', tone: 'rain' },
  HEAVY_RAIN: { label: '大雨', glyph: '☂︎', tone: 'rain' },
  STORM_RAIN: { label: '暴雨', glyph: '☂︎', tone: 'rain' },
  FOG: { label: '雾', glyph: '≡', tone: 'haze' },
  LIGHT_SNOW: { label: '小雪', glyph: '❄︎', tone: 'snow' },
  MODERATE_SNOW: { label: '中雪', glyph: '❄︎', tone: 'snow' },
  HEAVY_SNOW: { label: '大雪', glyph: '❄︎', tone: 'snow' },
  STORM_SNOW: { label: '暴雪', glyph: '❄︎', tone: 'snow' },
  DUST: { label: '浮尘', glyph: '≡', tone: 'haze' },
  SAND: { label: '沙尘', glyph: '≡', tone: 'haze' },
  WIND: { label: '大风', glyph: '≋', tone: 'wind' },
};

let weatherSession: { data: WeatherResponse; fetchedAt: number } | null = null;
let weatherPending: Promise<WeatherResponse> | null = null;

export function skyInfo(skycon: string | null | undefined): SkyInfo {
  return (skycon && SKYCON[skycon]) || { label: '天气', glyph: '·', tone: 'cloud' };
}

export function getCachedWeather(): WeatherResponse | null {
  return weatherSession && Date.now() - weatherSession.fetchedAt < WEATHER_SESSION_TTL
    ? weatherSession.data
    : null;
}

export async function loadWeatherData(force: boolean): Promise<WeatherResponse> {
  const cached = getCachedWeather();
  if (!force && cached) return cached;
  if (!force && weatherPending) return weatherPending;

  const task = (async () => {
    const response = await api.getWeather(
      FIXED_WEATHER_LOCATION.latitude,
      FIXED_WEATHER_LOCATION.longitude,
      force,
      FIXED_WEATHER_LOCATION.address,
    );
    const data: WeatherResponse = {
      ...response,
      location: {
        ...response.location,
        name: FIXED_WEATHER_LOCATION.address,
        address: FIXED_WEATHER_LOCATION.address,
        resolved: true,
      },
      address_warning: null,
    };
    weatherSession = { data, fetchedAt: Date.now() };
    return data;
  })();

  if (!force) weatherPending = task;
  try {
    return await task;
  } finally {
    if (weatherPending === task) weatherPending = null;
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

export function weatherDayLabel(date: string, index: number): string {
  if (index === 0) return '今天';
  if (index === 1) return '明天';
  const parsed = new Date(`${date}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? date.slice(5)
    : ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][parsed.getDay()];
}

export function weatherHourLabel(datetime: string, index: number): string {
  if (index === 0) return '现在';
  const parsed = new Date(datetime);
  if (Number.isNaN(parsed.getTime())) return datetime.slice(11, 16) || '—';
  return parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
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
