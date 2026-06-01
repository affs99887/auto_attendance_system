// 后端服务（main.py）运行状态 store —— 仅持有状态，不在 store 内操作 wsClient/定时器。
//
// running：服务进程是否在运行（初值 true，保证无桥/纯浏览器降级时正常路径行为不变）。
// available：是否存在 Electron 服务控制桥 window.AAS_SERVICE（初值 false，纯浏览器恒 false）。
//
// 状态来源（见 store/bootstrap.ts）：
//   有桥 → setAvailable(true)，getStatus 补拉 + onStatus 推送驱动 setRunning；
//   无桥 → setAvailable(false); setRunning(true)（降级恒 running）。
import { create } from 'zustand';

interface ServiceState {
  running: boolean;
  available: boolean;
  setRunning: (b: boolean) => void;
  setAvailable: (b: boolean) => void;
}

export const useServiceStore = create<ServiceState>((set) => ({
  running: true,
  available: false,
  setRunning: (b) => set({ running: b }),
  setAvailable: (b) => set({ available: b }),
}));
