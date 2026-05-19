// 类型化 REST 客户端 — 自动注入 Bearer token + 统一错误处理
import { getBackend } from './backend';

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
};

export type Api = typeof api;
