// 内置网络加速 store —— 配置 / 节点 / 实时流量
import { create } from 'zustand';
import { api, type ProxyNode, type ProxyStatus } from '../lib/api';

interface ProxyState {
  config: ProxyStatus | null;
  nodes: ProxyNode[];
  selected: string | null;
  running: boolean;
  traffic: { up: number; down: number; up_total: number; down_total: number };

  refreshConfig: () => Promise<void>;
  refreshNodes: () => Promise<void>;
  refreshTraffic: () => Promise<void>;
}

export const useProxyStore = create<ProxyState>((set) => ({
  config: null,
  nodes: [],
  selected: null,
  running: false,
  traffic: { up: 0, down: 0, up_total: 0, down_total: 0 },

  async refreshConfig() {
    try {
      const c = await api.getProxyConfig();
      set({ config: c, running: c.running, selected: c.selected_node });
    } catch { /* ignore */ }
  },
  async refreshNodes() {
    try {
      const r = await api.listProxyNodes();
      set({ nodes: r.nodes || [], selected: r.selected, running: r.running });
    } catch { /* ignore */ }
  },
  async refreshTraffic() {
    try {
      const t = await api.getProxyTraffic();
      set({ traffic: t });
    } catch { /* ignore */ }
  },
}));
