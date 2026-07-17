// 微信 Bark 转发 store —— 监听状态 / 转发时段判定 / 运行日志。
// 数据来源两路：REST 主动拉取（页面轮询兜底、进页首拉），WS 推送增量更新
// （wechat_bark:status 状态、wechat_bark:log 日志行，订阅在 store/bootstrap.ts）。
// 表单里的配置内容不放这里——配置只被独立页面用，留在页面组件本地 state。
import { create } from 'zustand';
import { api, type WechatBarkSchedule } from '../lib/api';

// 与后端日志环容量一致（wechat_bark_service 的 deque(maxlen=600)）
const MAX_LOG_LINES = 600;

/** WS wechat_bark:status 推送的载荷（status 接口的字段去掉 logs） */
interface WsStatusPayload {
  running?: boolean;
  stopping?: boolean;
  platform_supported?: boolean;
  config_path?: string;
}

interface WechatBarkState {
  running: boolean;
  stopping: boolean;
  /** 监听是否受当前平台支持（仅 macOS 为 true）；拉到状态前按 true 处理，避免误弹平台横幅 */
  platformSupported: boolean;
  configPath: string;
  /** 最近 600 行运行日志（每行自带 HH:MM:SS 时间戳） */
  logs: string[];
  schedule: WechatBarkSchedule | null;
  scheduleError: string | null;
  /** 是否成功拉到过一次状态（仪表盘卡片用它区分「还不知道」与「已停止」） */
  hasStatus: boolean;

  refreshStatus: () => Promise<void>;
  refreshSchedule: () => Promise<void>;
  applyWsStatus: (p: WsStatusPayload) => void;
  appendLogs: (lines: string[]) => void;
}

export const useWechatBarkStore = create<WechatBarkState>((set, get) => ({
  running: false,
  stopping: false,
  platformSupported: true,
  configPath: '',
  logs: [],
  schedule: null,
  scheduleError: null,
  hasStatus: false,

  // 拉全量状态：status 接口自带完整日志环，直接整组替换（比 WS 增量更权威）
  async refreshStatus() {
    try {
      const s = await api.getWechatBarkStatus();
      set({
        running: !!s.running,
        stopping: !!s.stopping,
        platformSupported: !!s.platform_supported,
        configPath: s.config_path || '',
        logs: (s.logs || []).slice(-MAX_LOG_LINES),
        hasStatus: true,
      });
    } catch { /* 后端未就绪时静默，下一轮轮询/WS 会补上 */ }
  },

  async refreshSchedule() {
    try {
      const r = await api.getWechatBarkSchedule();
      if (r.success && r.schedule) {
        set({ schedule: r.schedule, scheduleError: null });
      } else {
        set({ scheduleError: r.error || '时段判定不可用' });
      }
    } catch (e) {
      set({ scheduleError: (e as Error).message });
    }
  },

  // WS 状态推送（不含日志）：只覆盖推送里带的字段
  applyWsStatus(p) {
    const cur = get();
    set({
      running: typeof p.running === 'boolean' ? p.running : cur.running,
      stopping: typeof p.stopping === 'boolean' ? p.stopping : cur.stopping,
      platformSupported:
        typeof p.platform_supported === 'boolean' ? p.platform_supported : cur.platformSupported,
      configPath: typeof p.config_path === 'string' ? p.config_path : cur.configPath,
      hasStatus: true,
    });
  },

  // WS 日志推送：增量追加并裁掉最旧的行，保持与后端同样的 600 行上限
  appendLogs(lines) {
    if (!lines.length) return;
    const next = [...get().logs, ...lines];
    if (next.length > MAX_LOG_LINES) next.splice(0, next.length - MAX_LOG_LINES);
    set({ logs: next });
  },
}));
