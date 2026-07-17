// 类型化 REST 客户端 — 自动注入 Bearer token + 统一错误处理
import { getBackend } from './backend';

export interface ErrorGroup {
  timestamp: string;
  content: string[];
}

export interface ConfigAllResponse {
  env: Record<string, string | boolean>;
  whitelist: string[];
}

export interface StatusSnapshot {
  current_time: string;
  is_workday?: boolean | null;
  is_holiday?: boolean | null;
  /** 后端进程已运行秒数（后端字段名就叫 uptime_seconds，不能写成 uptime） */
  uptime_seconds?: number | null;
  /** 后端进程启动时刻（ISO 字符串） */
  started_at?: string | null;
  /** 保留的配置项（当前只剩天气相关），键值由后端决定 */
  config?: Record<string, string | number | boolean | null>;
  resources?: {
    cpu_percent?: number;
    memory_percent?: number;
  };
}

// ===== 汇率（CNY->JPY，后端只产出该方向；JPY->CNY 由前端取倒数）=====
export interface ExchangeRatePoint {
  t: number; // unix 秒
  value: number; // CNY->JPY
}

export interface ExchangeRateResponse {
  base: string;
  quote: string;
  range: string;
  updated_at: number | null; // 缓存最后刷新时刻（unix 秒）
  latest: { price: number; time: number } | null; // price=CNY->JPY，time=报价时间（unix 秒）
  points: ExchangeRatePoint[]; // 按时间升序
}

// ===== 彩云天气（当前地点，后端代调彩云 v2.6 综合接口）=====
export interface WeatherDailyItem {
  date: string;
  skycon: string | null;
  temperature_min: number | null;
  temperature_max: number | null;
  precipitation_probability: number | null;
}

export interface WeatherHourlyItem {
  datetime: string;
  temperature: number | null;
  apparent_temperature: number | null;
  skycon: string | null;
  precipitation: number | null;
  precipitation_probability: number | null;
  humidity: number | null;
  wind_speed: number | null;
  wind_direction: number | null;
  aqi: number | null;
}

export interface WeatherAlertItem {
  id: string;
  title: string;
  description: string;
  code: string;
  status: string;
  location: string;
  source: string;
  published_at: number;
}

export interface GeolocateResponse {
  success: true;
  latitude: number;
  longitude: number;
  /** 城市名（定位服务给的，可能为空串） */
  city: string;
  /** 用的哪家 IP 定位服务 */
  source: string;
  cached: boolean;
  /** true 表示本次探测失败、回退的是旧缓存 */
  stale?: boolean;
}

export interface WeatherResponse {
  success: true;
  source: '彩云天气';
  updated_at: number;
  location: {
    latitude: number;
    longitude: number;
    name: string;
    address: string;
    resolved: boolean;
    located?: boolean; // 前端"当前位置"模式标记（loadWeatherData 写入，后端不返回）；界面据此不显示经纬度
  };
  realtime: {
    temperature: number | null;
    apparent_temperature: number | null;
    humidity: number | null;
    skycon: string | null;
    wind_speed: number | null;
    wind_direction: number | null;
    visibility: number | null;
    pressure: number | null;
    cloudrate: number | null;
    precipitation_intensity: number | null;
    nearest_precipitation_distance: number | null;
    aqi: number | null;
    aqi_description: string | null;
    pm25: number | null;
    pm10: number | null;
    uv_description: string | null;
    comfort_description: string | null;
  };
  forecast_keypoint: string | null;
  hourly_description: string | null;
  minutely_description: string | null;
  hourly: WeatherHourlyItem[];
  daily: WeatherDailyItem[];
  alerts: WeatherAlertItem[];
  alerts_available: boolean;
  alerts_total: number;
  address_warning: string | null;
  cached: boolean;
}

// ===== 日历信息（chinese_calendar 休班标记，后端保留作参考）=====
export interface CalendarDayMark {
  d: number;        // 几号
  off: boolean;     // 休息日（双休/节假日）
  statutory: boolean; // 法定假日
  makeup: boolean;  // 调休补班
}

export interface CalendarInfoResponse {
  available: boolean;
  today: string; // ISO 日期
  year: number;
  month: number;
  days: CalendarDayMark[];
  /** 本周（周一起 7 天，可跨月） */
  week: Array<{ date: string; d: number; off: boolean }>;
  nearest_rest: {
    days: number;          // 距今天数（0 = 今天在休）
    date: string;
    name: string | null;   // 节日名（端午节…）；普通双休为 null
    label: string;         // 「本周双休」/「端午节连休」/「双休进行中」
    span: [string, string]; // 连续休息区间首末日
    kind: 'weekend' | 'holiday';
    next_workday: string;  // 本轮休息结束后的首个工作日（ISO）
  } | null;
  next_holidays: Array<{
    name: string;       // 中文名；连段假期合并（如 国庆中秋）
    start: string;      // 法定假期首日（ISO）
    end: string;        // 法定假期末日（ISO）
    days_until: number;
  }>; // 近期法定假期（最多 2 个）
  next_makeup: string[]; // 后续调休补班日（最多 2 个）
  /** 传入 after 时返回：该日之后的首个工作日 */
  workday_after: string | null;
}

// ===== 微信 Bark 转发（macOS 微信通知 → iPhone Bark；Windows 上仅能改配置/测推送）=====
export interface WechatBarkConfig {
  bark: {
    server: string;
    device_key: string;
    group: string;
    sound: string;
    level: string;
    url: string;
    icon: string;
    use_post: boolean;
  };
  wechat: {
    bundle_ids: string[];
    title_prefix: string;
    show_sender_in_body: boolean;
    sender_label: string;
    ignore_title_patterns: string[];
    ignore_body_patterns: string[];
  };
  listener: {
    poll_interval_seconds: number;
    send_existing_on_start: boolean;
    state_file: string;
    db_path: string;
    max_body_chars: number;
  };
  desktop: {
    auto_start_listener: boolean;
    launch_at_login: boolean;
  };
  schedule: {
    enabled: boolean;
    timezone: string;
    start_time: string; // "HH:MM"
    end_time: string;   // "HH:MM"（后端允许 24:00 表示到当天结束）
    weekends_are_holidays: boolean;
    holiday_source_urls: string[];
    holiday_cache_dir: string;
    holiday_cache_ttl_hours: number;
    allow_on_holiday_fetch_error: boolean;
  };
}

export interface WechatBarkStatus {
  running: boolean;
  stopping: boolean;
  /** 监听是否受当前平台支持（仅 macOS 为 true） */
  platform_supported: boolean;
  config_path: string;
  /** 带 HH:MM:SS 时间戳的最近 600 行运行日志 */
  logs: string[];
}

export interface WechatBarkSchedule {
  allowed: boolean;
  reason: string;
  now: string; // ISO 时间串（带时区偏移）
  timezone: string;
  start_time: string;
  end_time: string;
}

export interface WechatBarkApp {
  identifier: string;
  count: number;
}

export interface ApiOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  /** 单次请求超时（毫秒）；不传走默认 DEFAULT_TIMEOUT_MS，防 fetch 永久挂起卡死 UI */
  timeoutMs?: number;
}

// 默认请求超时：防半死后端 accept 后不响应导致 fetch 永久 pending（loading/busy 永不复位）
const DEFAULT_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  status: number;
  payload: unknown;
  constructor(status: number, payload: unknown, message?: string) {
    super(message ?? `HTTP ${status}`);
    this.status = status;
    this.payload = payload;
  }
}

async function request<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { token, httpUrl } = getBackend();
  const url = `${httpUrl}${path.startsWith('/') ? path : `/${path}`}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';

  // 默认超时 signal；若调用方自带 signal 则用 AbortSignal.any 合并（任一触发即中止）
  const timeoutSignal = AbortSignal.timeout(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = opts.signal ? AbortSignal.any([opts.signal, timeoutSignal]) : timeoutSignal;

  let resp: Response;
  try {
    resp = await fetch(url, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal,
    });
  } catch (e) {
    // 超时/主动取消归一化为 ApiError（status=0），让 loading/busy 能正常复位
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      throw new ApiError(0, null, 'timeout');
    }
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(0, null, 'aborted');
    }
    throw e; // 其余网络错误（断网/连接拒绝）保持原样抛出
  }

  const contentType = resp.headers.get('content-type') ?? '';
  const payload: unknown = contentType.includes('application/json')
    ? await resp.json()
    : await resp.text();

  if (!resp.ok) {
    throw new ApiError(resp.status, payload, `HTTP ${resp.status} ${resp.statusText}`);
  }
  return payload as T;
}

// ===== Endpoints =====

export const api = {
  ping: () => request<{ ok: boolean; service: string }>('/api/v1/ping'),

  getStatus: () => request<StatusSnapshot>('/api/v1/status'),

  getLogsTail: (lines = 200) =>
    request<{ lines: string[]; file: string }>(`/api/v1/logs/tail?lines=${lines}`),

  // 汇率走势（base=CNY quote=JPY）；force=true 跳过缓存强制刷新
  getExchangeRate: (range: string, force?: boolean) => {
    const qs = new URLSearchParams({ range });
    if (force) qs.set('force', '1');
    return request<ExchangeRateResponse>(`/api/v1/exchange-rate?${qs.toString()}`);
  },

  // 彩云天气：精确坐标仅发往本机后端；已知地址可跳过额外的逆地理编码请求。
  getWeather: (latitude: number, longitude: number, force = false, address?: string) =>
    request<WeatherResponse>('/api/v1/weather', {
      method: 'POST',
      body: { latitude, longitude, force, address },
      timeoutMs: 25_000,
    }),

  // IP 定位（城市级），天气"当前位置"用它解析坐标；后端带 30 分钟缓存
  getGeolocate: (force = false) =>
    request<GeolocateResponse>(`/api/v1/geolocate${force ? '?force=1' : ''}`, {
      timeoutMs: 25_000,
    }),

  // 日历信息（当月休班标记/本周条/最近休息日/近期假期/调休补班；后端保留，当前无页面调用）
  // after：可选 ISO 日期，请求该日之后的首个工作日
  getCalendarInfo: (after?: string) =>
    request<CalendarInfoResponse>(`/api/v1/calendar-info${after ? `?after=${after}` : ''}`),

  getErrorLogs: (page = 1, perPage = 5) =>
    request<{ groups: ErrorGroup[]; page: number; total_pages: number; total_groups: number }>(
      `/api/v1/logs/errors?page=${page}&per_page=${perPage}`,
    ),

  getConfigAll: () => request<ConfigAllResponse>('/api/v1/config/all'),

  patchConfig: (patch: Record<string, string | number | boolean>) =>
    request<{ success: boolean; env?: Record<string, string>; note?: string; error?: string }>(
      '/api/v1/config',
      { method: 'PATCH', body: { patch } },
    ),

  systemRestart: () =>
    request<{ success: boolean; note?: string }>('/api/v1/system/restart', { method: 'POST' }),

  // ===== 内置网络加速（mihomo）=====
  getProxyConfig: () => request<ProxyStatus>('/api/v1/proxy/config'),

  setProxyConfig: (patch: { enabled?: boolean; local_port?: number; api_port?: number }) =>
    request<{ success: boolean; config: ProxyStatus; note?: string | null; error?: string }>(
      '/api/v1/proxy/config',
      { method: 'PUT', body: patch },
    ),

  setProxySubscription: (url: string) =>
    request<{ success: boolean; node_count?: number | null; config?: ProxyStatus; error?: string }>(
      '/api/v1/proxy/subscription',
      { method: 'POST', body: { url } },
    ),

  setProxyConfigText: (text: string) =>
    request<{ success: boolean; node_count?: number | null; config?: ProxyStatus; error?: string }>(
      '/api/v1/proxy/config-text',
      { method: 'POST', body: { text } },
    ),

  listProxyNodes: () =>
    request<{ group: string | null; selected: string | null; nodes: ProxyNode[]; running: boolean }>(
      '/api/v1/proxy/nodes',
    ),

  selectProxyNode: (name: string) =>
    request<{ success: boolean; selected: string; error?: string }>('/api/v1/proxy/select', {
      method: 'POST',
      body: { name },
    }),

  testProxyDelay: (name: string) =>
    request<{ success: boolean; name: string; delay: number | null; error?: string }>(
      '/api/v1/proxy/test-delay',
      { method: 'POST', body: { name } },
    ),

  getProxyTraffic: () =>
    request<{ up: number; down: number; up_total: number; down_total: number }>(
      '/api/v1/proxy/traffic',
    ),

  // 下载 mihomo 内核到 bin/（运行时缺内核时自助下载；mirror 为可选 GitHub 加速前缀）
  fetchProxyCore: (mirror?: string) =>
    request<{ success: boolean; message?: string; config?: ProxyStatus; error?: string }>(
      '/api/v1/proxy/fetch-core',
      { method: 'POST', body: mirror ? { mirror } : {} },
    ),

  // 刷新订阅 / 重载配置：复用 PUT /proxy/config 空 body（运行中走 reload，重拉 proxy-provider）
  reloadProxy: () =>
    request<{ success: boolean; config: ProxyStatus; note?: string | null; error?: string }>(
      '/api/v1/proxy/config',
      { method: 'PUT', body: {} },
    ),

  // ===== 多配置文件管理（订阅 / 本地，仿 Clash「配置」页）=====
  // 列出全部配置文件 + 当前激活 id
  listProxyProfiles: () =>
    request<{ profiles: ProxyProfile[]; active_id: string | null }>('/api/v1/proxy/profiles'),

  // 新增配置：订阅 {type:'subscription', name?, url}；本地 {type:'local', name, content}
  addProxyProfile: (
    body:
      | { type: 'subscription'; name?: string; url: string }
      | { type: 'local'; name: string; content: string },
  ) =>
    request<{ success: boolean; profile?: ProxyProfile; error?: string }>('/api/v1/proxy/profiles', {
      method: 'POST',
      body,
    }),

  // 刷新订阅配置（重拉远端、更新流量/节点数）
  refreshProxyProfile: (id: string) =>
    request<{ success: boolean; profile?: ProxyProfile; error?: string }>(
      `/api/v1/proxy/profiles/${id}/refresh`,
      { method: 'POST' },
    ),

  // 切换激活配置
  selectProxyProfile: (id: string) =>
    request<{ success: boolean; active_id?: string; error?: string }>(
      `/api/v1/proxy/profiles/${id}/select`,
      { method: 'POST' },
    ),

  // 删除配置
  deleteProxyProfile: (id: string) =>
    request<{ success: boolean; error?: string }>(`/api/v1/proxy/profiles/${id}`, {
      method: 'DELETE',
    }),

  // 读取本地配置原文（编辑用）
  getProxyProfileContent: (id: string) =>
    request<{ content: string; error?: string }>(`/api/v1/proxy/profiles/${id}/content`),

  // 更新本地配置（改名 / 改内容）
  updateProxyProfile: (id: string, body: { name?: string; content?: string }) =>
    request<{ success: boolean; profile?: ProxyProfile; error?: string }>(
      `/api/v1/proxy/profiles/${id}`,
      { method: 'PUT', body },
    ),

  // ===== 微信 Bark 转发 =====
  getWechatBarkStatus: () => request<WechatBarkStatus>('/api/v1/wechat-bark/status'),

  getWechatBarkConfig: () =>
    request<{ config: WechatBarkConfig; config_path: string }>('/api/v1/wechat-bark/config'),

  // 保存配置：字段校验失败时后端回 HTTP 400 {success:false, error:中文文案}，
  // request() 会抛 ApiError，调用方从 payload.error 取文案展示
  saveWechatBarkConfig: (config: WechatBarkConfig) =>
    request<{ success: boolean; config?: WechatBarkConfig; config_path?: string; note?: string; error?: string }>(
      '/api/v1/wechat-bark/config',
      { method: 'PUT', body: { config } },
    ),

  // 启动监听（Windows 上后端会返回明确的平台错误文案）
  startWechatBark: () =>
    request<{ success: boolean; message?: string; error?: string }>('/api/v1/wechat-bark/start', {
      method: 'POST',
    }),

  stopWechatBark: () =>
    request<{ success: boolean; message?: string; error?: string }>('/api/v1/wechat-bark/stop', {
      method: 'POST',
    }),

  // 发一条测试推送验证 Bark 配置（任意平台可用）
  testWechatBark: () =>
    request<{ success: boolean; message?: string; error?: string }>('/api/v1/wechat-bark/test', {
      method: 'POST',
    }),

  // 当前时刻的转发时段判定（允许/阻止 + 原因），与监听是否运行无关
  getWechatBarkSchedule: () =>
    request<{ success: boolean; schedule?: WechatBarkSchedule; error?: string }>(
      '/api/v1/wechat-bark/schedule',
    ),

  // 通知中心里的应用来源列表（仅 macOS 且有完全磁盘访问权限时成功）
  getWechatBarkApps: () =>
    request<{ success: boolean; apps?: WechatBarkApp[]; error?: string }>('/api/v1/wechat-bark/apps'),
};

export interface ProxyNode {
  name: string;
  type: string;
  delay: number | null;
}

export interface ProxyStatus {
  enabled: boolean;
  running: boolean;
  binary_available: boolean;
  source: 'subscription' | 'config';
  local_port: number;
  api_port: number;
  group: string | null;
  selected_node: string | null;
  subscription_url: string;
  has_config_text: boolean;
  active_profile_id?: string | null; // 当前激活的配置文件 id（多配置管理）
}

// 配置文件（订阅 / 本地），仿 Clash「配置」页的卡片数据
export interface ProxyProfile {
  id: string;
  name: string;
  type: 'subscription' | 'local';
  url: string;
  updated_at: number | null; // epoch 秒
  // 流量信息：仅订阅可能有；字节 / expire 为 epoch 秒
  traffic: { upload: number; download: number; total: number; expire: number | null } | null;
  node_count: number | null;
  active: boolean;
}

export type Api = typeof api;
