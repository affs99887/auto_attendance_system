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
  active_controllers?: number;
  users?: string[];
  resources?: {
    cpu_percent?: number;
    memory_percent?: number;
  };
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

  testReminder: () =>
    request<{ success: boolean; message?: string; error?: string }>('/api/v1/test/reminder', {
      method: 'POST',
    }),
};

export type Api = typeof api;
