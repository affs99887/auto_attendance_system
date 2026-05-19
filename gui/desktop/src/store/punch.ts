// 打卡进度 store — WS punch:progress 累加为时间线
import { create } from 'zustand';

export interface PunchProgressEntry {
  title: string;
  content: string;
  message?: string;
  ts: number;
}

const MAX_ENTRIES = 300;

interface PunchState {
  entries: PunchProgressEntry[];
  current: PunchProgressEntry | null;

  push: (entry: Omit<PunchProgressEntry, 'ts'> & { ts?: number }) => void;
  clear: () => void;
}

export const usePunchStore = create<PunchState>((set, get) => ({
  entries: [],
  current: null,

  push(entry) {
    const e: PunchProgressEntry = { ...entry, ts: entry.ts ?? Date.now() / 1000 };
    const next = [...get().entries, e];
    if (next.length > MAX_ENTRIES) next.splice(0, next.length - MAX_ENTRIES);
    set({ entries: next, current: e });
  },

  clear() {
    set({ entries: [], current: null });
  },
}));
