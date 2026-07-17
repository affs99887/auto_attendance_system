// 系统快照 store — 主动 fetch（bootstrap 的 15s 轮询 + 各处事件驱动的 refresh）
import { create } from 'zustand';
import { api, ApiError, type StatusSnapshot } from '../lib/api';

interface SystemState {
  snapshot: StatusSnapshot | null;
  loading: boolean;
  lastFetched: number | null;
  error: string | null;

  refresh: () => Promise<void>;
  /** WS 增量更新：合并新字段到当前 snapshot，不存在则跳过 */
  mergeUpdate: (patch: Partial<StatusSnapshot>) => void;
  reset: () => void;
}

export const useSystemStore = create<SystemState>((set, get) => ({
  snapshot: null,
  loading: false,
  lastFetched: null,
  error: null,

  async refresh() {
    set({ loading: true, error: null });
    try {
      const snapshot = await api.getStatus();
      set({ snapshot, lastFetched: Date.now(), loading: false });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      set({ error: msg, loading: false });
    }
  },

  mergeUpdate(patch) {
    const cur = get().snapshot;
    if (!cur) return;
    set({
      snapshot: { ...cur, ...patch, config: { ...cur.config, ...(patch.config ?? {}) } },
      lastFetched: Date.now(),
    });
  },

  reset() {
    set({ snapshot: null, loading: false, lastFetched: null, error: null });
  },
}));
