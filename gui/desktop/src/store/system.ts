// 系统快照 store — 主动 fetch + WS status:update 增量更新
import { create } from 'zustand';
import { api, ApiError, type StatusSnapshot } from '../lib/api';
import { useToastStore } from './toast';

interface SystemState {
  snapshot: StatusSnapshot | null;
  loading: boolean;
  lastFetched: number | null;
  error: string | null;

  refresh: () => Promise<void>;
  /** WS 增量更新：合并新字段到当前 snapshot，不存在则跳过 */
  mergeUpdate: (patch: Partial<StatusSnapshot>) => void;
  /** 切换自动化模式（Selenium / 无头）：乐观更新 snapshot.config → PUT /config/mode → refresh 校正，失败回滚 */
  setMode: (patch: { use_selenium_login?: boolean; selenium_headless?: boolean }) => Promise<void>;
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

  async setMode(patch) {
    const cur = get().snapshot;
    const prevConfig = cur?.config;
    // 乐观更新（snapshot 为 null 时跳过，成功后 refresh 会补上）
    if (cur) set({ snapshot: { ...cur, config: { ...cur.config, ...patch } } });
    try {
      await api.setConfigMode(patch);
      await get().refresh(); // 拉后端真实值校正
      useToastStore.getState().push(
        'ok',
        'use_selenium_login' in patch
          ? `已切换到 ${patch.use_selenium_login ? 'Selenium' : '图像识别'} 模式`
          : `已切换到 ${patch.selenium_headless ? '无头' : '可见'} 模式（下次打卡生效）`,
      );
    } catch (e) {
      if (cur && prevConfig) set({ snapshot: { ...cur, config: prevConfig } }); // 回滚
      const msg = e instanceof ApiError ? `${e.status}` : (e as Error).message;
      useToastStore.getState().push('err', `切换失败: ${msg}`);
    }
  },

  reset() {
    set({ snapshot: null, loading: false, lastFetched: null, error: null });
  },
}));
