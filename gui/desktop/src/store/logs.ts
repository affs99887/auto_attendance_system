// 日志流 store — 启动时 fetch tail，WS log:stream 增量追加
import { create } from 'zustand';
import { api, ApiError } from '../lib/api';
import type { LogEntry } from '../lib/types';

const MAX_LINES = 5000;
// 后端写的格式: "2026-05-19 08:29:47,418 - INFO - 邓蕴哲 上班打卡 - 登录成功"
const LOG_REGEX = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s*-\s*(INFO|WARN(?:ING)?|ERROR|CRITICAL|DEBUG)\s*-\s*(.*)$/;

function parseLine(raw: string): LogEntry {
  const m = LOG_REGEX.exec(raw);
  if (!m) {
    return { ts: '', lvl: 'INFO', msg: raw };
  }
  let lvl = m[2] as LogEntry['lvl'];
  if ((lvl as string) === 'WARNING') lvl = 'WARN';
  return { ts: m[1], lvl, msg: m[3] };
}

interface LogState {
  lines: LogEntry[];
  loading: boolean;
  error: string | null;

  loadTail: (count?: number) => Promise<void>;
  appendLine: (raw: string) => void;
  clear: () => void;
}

export const useLogsStore = create<LogState>((set, get) => ({
  lines: [],
  loading: false,
  error: null,

  async loadTail(count = 500) {
    set({ loading: true, error: null });
    try {
      const { lines } = await api.getLogsTail(count);
      set({ lines: lines.map(parseLine), loading: false });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      set({ error: msg, loading: false });
    }
  },

  appendLine(raw: string) {
    const entry = parseLine(raw);
    const next = [...get().lines, entry];
    if (next.length > MAX_LINES) next.splice(0, next.length - MAX_LINES);
    set({ lines: next });
  },

  clear() {
    set({ lines: [] });
  },
}));
