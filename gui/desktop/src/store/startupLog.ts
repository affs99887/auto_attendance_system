// 启动日志 store —— 启动/失败期展示 Electron 转发的 python stdout/stderr 原始行。
//
// 与 useLogsStore（结构化 LogEntry + WS log:stream）物理隔离，仅服务 StartupOverlay：
// useLogsStore 的 parseLine 会把启动期混格式行（欢迎横幅 / [INIT] / 进度条 / 结构化日志）
// 强解析成 LogEntry 并污染 ready 后的日志页，故这里另起一个轻量原始字符串 store。
import { create } from 'zustand';

const MAX_LINES = 500;

interface StartupLogState {
  lines: string[];
  append: (lines: string[]) => void;
  reset: (lines?: string[]) => void;
}

export const useStartupLogStore = create<StartupLogState>((set, get) => ({
  lines: [],
  append: (incoming) => {
    if (!incoming?.length) return;
    const next = get().lines.concat(incoming);
    if (next.length > MAX_LINES) next.splice(0, next.length - MAX_LINES);
    set({ lines: next });
  },
  reset: (lines = []) => set({ lines: [...lines] }),
}));
