// 启动状态 store —— 后端"系统启动中 / 就绪 / 失败"的单向优先状态机
//
// 状态迁移（单向优先，避免抖动）：
//   starting → ready   仅当探活成功（ping + 带 token 的 status 均 200）
//   * → failed         仅当主进程明确 failed
//   failed/ready → starting  仅当主进程发来 starting（后端重启）
//
// epoch：每次 setStarting / setFailed 自增，用于作废"在途"的 ping 探活循环——
// 探活循环开始时捕获 epoch，每轮校验仍是最新才允许写 ready，杜绝迟到的 ping 把 failed 改回 ready。
import { create } from 'zustand';

export type StartupStatus = 'starting' | 'ready' | 'failed';

interface StartupState {
  status: StartupStatus;
  reason: string | null;
  phase: string;
  /** 用户手动关闭了覆盖层（仅隐藏 UI，不改 status） */
  overlayDismissed: boolean;
  /** 代际，作废在途探活 */
  epoch: number;
  /** 已应用的 token，用于去重重复推送 */
  currentToken: string;
  /** 成功 toast 已弹过（一次性） */
  readyToastShown: boolean;

  setStarting: (phase?: string) => void;
  setReady: () => void;
  setFailed: (reason: string) => void;
  setPhase: (phase: string) => void;
  setOverlayDismissed: (v: boolean) => void;
  setCurrentToken: (t: string) => void;
  setReadyToastShown: (v: boolean) => void;
  /** 失败/重试时手动作废在途探活 */
  invalidate: () => void;
}

export const useStartupStore = create<StartupState>((set, get) => ({
  status: 'starting',
  reason: null,
  phase: '正在启动后端服务…',
  overlayDismissed: false,
  epoch: 0,
  currentToken: '',
  readyToastShown: false,

  setStarting: (phase) =>
    set(s => ({
      status: 'starting',
      reason: null,
      // 新一轮 starting（含后端重启）：重现覆盖层、允许再次弹成功 toast、作废旧探活
      overlayDismissed: false,
      readyToastShown: false,
      epoch: s.epoch + 1,
      ...(phase ? { phase } : {}),
    })),

  setReady: () => set({ status: 'ready', reason: null }),

  setFailed: (reason) => set(s => ({ status: 'failed', reason, epoch: s.epoch + 1 })),

  setPhase: (phase) => set({ phase }),

  setOverlayDismissed: (v) => set({ overlayDismissed: v }),

  setCurrentToken: (t) => set({ currentToken: t }),

  setReadyToastShown: (v) => set({ readyToastShown: v }),

  invalidate: () => set(s => ({ epoch: s.epoch + 1 })),
}));
