// 类型化 REST 客户端 — 自动注入 Bearer token + 统一错误处理
import { getBackend } from './backend';

export interface ScreenshotItem {
  path: string;
  filename: string;
  time: number;
  time_str: string;
  type: string;
}

export interface RecordsResponse {
  username: string;
  year: number;
  month: number;
  records: Record<string, { punch_in_time: string | null; punch_out_time: string | null } | { in?: string | null; out?: string | null }>;
  path?: string;
}

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
  is_work_time?: boolean | null;
  current_operation: 'punch_in' | 'punch_out' | null;
  operation_started_at: string | null;
  today_records: Record<string, { punch_in_time: string | null; punch_out_time: string | null }>;
  config: {
    work_start_time?: string;
    work_end_time?: string;
    late_threshold?: number;
    early_leave_threshold?: number;
    use_selenium_login?: boolean;
    selenium_headless?: boolean;
    daily_status_time?: string;
  };
  scheduled_tasks: Array<{
    id: number;
    type: string;
    scheduled_time: string;
    username?: string;
    created_at?: string;
  }>;
  heartbeat?: {
    last: string | null;
    miss_count: number;
  };
  /** Telegram bot 是否已连接（旧后端为 undefined） */
  bot_available?: boolean;
  /** Telegram bot 连接错误信息（无错误为 null；旧后端为 undefined） */
  bot_error?: string | null;
  active_controllers?: number;
  users?: string[];
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

// ===== AI 资讯（AI HOT，后端聚合中文 AI 资讯并按版块归类）=====
export interface AiNewsItem {
  id: string;
  title: string;
  title_en?: string | null;
  url: string;
  source: string;
  publishedAt?: string | null; // 内容发布时间（ISO 字符串）
  summary?: string | null;
  category?: string | null; // 版块 slug，对应 AI_NEWS_CATEGORIES
}

export interface AiNewsResponse {
  updated_at: number | null; // 缓存最后刷新时刻（unix 秒）
  count: number;
  items: AiNewsItem[];
}

export interface ApiOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}

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

  const resp = await fetch(url, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

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

  punchIn: (username?: string) =>
    request<{ success: boolean; message: string }>('/api/v1/punch/in', {
      method: 'POST',
      body: username ? { username } : {},
    }),

  punchOut: (username?: string) =>
    request<{ success: boolean; message: string }>('/api/v1/punch/out', {
      method: 'POST',
      body: username ? { username } : {},
    }),

  operationStop: () =>
    request<{ success: boolean; message: string }>('/api/v1/operation/stop', {
      method: 'POST',
    }),

  getConfigMode: () =>
    request<{ use_selenium_login: boolean; selenium_headless: boolean }>(
      '/api/v1/config/mode',
    ),

  setConfigMode: (patch: { use_selenium_login?: boolean; selenium_headless?: boolean }) =>
    request<{ success: boolean; config: Record<string, boolean> }>('/api/v1/config/mode', {
      method: 'PUT',
      body: patch,
    }),

  listTasks: () =>
    request<{ tasks: StatusSnapshot['scheduled_tasks'] }>('/api/v1/tasks'),

  deleteTask: (id: number) =>
    request<{ success: boolean; task_id: number }>(`/api/v1/tasks/${id}`, {
      method: 'DELETE',
    }),

  listUsers: () =>
    request<{ users: Array<{ username: string; env_key?: string }> }>('/api/v1/users'),

  autoByebyeCalc: (username?: string) =>
    request<{
      success: boolean;
      username?: string | null;
      punch_in_time?: string | null;
      punch_out_time?: string | null;
      message?: string;
      fallback_used?: boolean;
    }>('/api/v1/punch/auto_byebye/calc', {
      method: 'POST',
      body: username ? { username } : {},
    }),

  autoByebyeConfirm: (hour: number, minute: number) =>
    request<{ success: boolean; time?: string; error?: string }>(
      '/api/v1/punch/auto_byebye/confirm',
      { method: 'POST', body: { hour, minute } },
    ),

  parallelLoginTest: () =>
    request<{
      success: boolean;
      count?: number;
      success_count?: number;
      results?: Record<string, { success: boolean; message: string }>;
      error?: string;
    }>('/api/v1/test/parallel_login', { method: 'POST' }),

  // 登录系统读取所有用户今日上/下班时间（不触发打卡），结果回写今日记录
  fetchPunchStatus: () =>
    request<{
      success: boolean;
      count?: number;
      results?: Record<
        string,
        { success: boolean; punch_in_time: string | null; punch_out_time: string | null; message: string }
      >;
      error?: string;
    }>('/api/v1/punch/fetch_status', { method: 'POST' }),

  createTask: (body: {
    type: 'punch_in' | 'punch_out';
    mode: 'absolute' | 'delay';
    hour?: number;
    minute?: number;
    delay_minutes?: number;
    username?: string;
  }) =>
    request<{ success: boolean; message: string; task_id: number | null }>('/api/v1/tasks', {
      method: 'POST',
      body,
    }),

  listScreenshots: (params: { username?: string; type?: 'punch_in' | 'punch_out'; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.username) qs.set('username', params.username);
    qs.set('type', params.type ?? 'punch_in');
    if (params.limit) qs.set('limit', String(params.limit));
    return request<
      | { username: string; type: string; items: ScreenshotItem[] }
      | { type: string; users: string[]; grouped: Record<string, ScreenshotItem[]> }
    >(`/api/v1/screenshots?${qs.toString()}`);
  },

  /** 构造截图二进制 URL（src 直接用） */
  screenshotFileUrl: (path: string) => {
    const { httpUrl, token } = getBackend();
    const qs = new URLSearchParams({ path, token });
    return `${httpUrl}/api/v1/screenshots/file?${qs.toString()}`;
  },

  getRecords: (username: string, year: number, month: number) => {
    const qs = new URLSearchParams({ username, year: String(year), month: String(month) });
    return request<RecordsResponse>(`/api/v1/records?${qs.toString()}`);
  },

  // 汇率走势（base=CNY quote=JPY）；force=true 跳过缓存强制刷新
  getExchangeRate: (range: string, force?: boolean) => {
    const qs = new URLSearchParams({ range });
    if (force) qs.set('force', '1');
    return request<ExchangeRateResponse>(`/api/v1/exchange-rate?${qs.toString()}`);
  },

  // AI 资讯（AI HOT 聚合）；force=true 跳过后端缓存强制刷新
  getAiNews: (force?: boolean) => {
    const qs = new URLSearchParams();
    if (force) qs.set('force', '1');
    const q = qs.toString();
    return request<AiNewsResponse>(`/api/v1/ai-news${q ? `?${q}` : ''}`);
  },

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

  testEmail: () =>
    request<{ success: boolean; message?: string; error?: string }>('/api/v1/email/test', {
      method: 'POST',
    }),

  systemRestart: () =>
    request<{ success: boolean; note?: string }>('/api/v1/system/restart', { method: 'POST' }),

  // 重连 Telegram bot（不重启进程）
  botReconnect: () =>
    request<{ success: boolean; message?: string; error?: string }>('/api/v1/bot/reconnect', {
      method: 'POST',
    }),

  testReminder: () =>
    request<{ success: boolean; message?: string; error?: string }>('/api/v1/test/reminder', {
      method: 'POST',
    }),

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
