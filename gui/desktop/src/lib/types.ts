// 与后端 API 共享的核心类型。

export type Theme = 'light' | 'dark';

export interface LogEntry {
  ts: string;
  lvl: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL' | 'DEBUG';
  msg: string;
}

export type ScreenId =
  | 'dashboard'
  | 'logs'
  | 'weather'
  | 'wechatBark'
  | 'settings'
  | 'proxy'
  | 'about';
