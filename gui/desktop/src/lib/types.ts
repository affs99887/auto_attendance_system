// 与后端 API + 设计稿 mock 数据共享的核心类型。
// 实施阶段 2a 阶段仅有 mock 数据；阶段 2c 接入真实 /api/v1/status 时会补充字段。

export type Theme = 'light' | 'dark';

export interface User {
  id: string;
  name: string;
  env: string;
  short: string;
  color: string;
}

export interface PunchRec {
  in: string | null;
  out: string | null;
}

export interface ScheduledTask {
  id: string;
  name: string;
  nextRun: string;
  tag: string;
  fn: string;
  user?: string;
  recurring: boolean;
}

export interface RecentActivityEntry {
  ts: string;
  user: string;
  type:
    | 'punch_in'
    | 'punch_out'
    | 'daily_status'
    | 'reminder'
    | 'log_rotate'
    | 'error'
    | string;
  status: 'ok' | 'warn' | 'error';
  method: string;
  detail: string;
}

export interface LogEntry {
  ts: string;
  lvl: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL' | 'DEBUG';
  msg: string;
}

export interface CommandEntry {
  cmd: string;
  desc: string;
}

export type RecordsByYearMonth = Record<string, Record<string, PunchRec>>;
export type RecordsByUser = Record<string, RecordsByYearMonth>;

export interface OpState {
  running: boolean;
  type: 'punch_in' | 'punch_out' | null;
  perUser: Record<string, unknown>;
}

export interface SysStatus {
  serviceLabel: string;
  modeLabel: string;
}

export type ScreenId =
  | 'dashboard'
  | 'punch'
  | 'records'
  | 'shots'
  | 'tasks'
  | 'logs'
  | 'settings'
  | 'proxy'
  | 'about';
