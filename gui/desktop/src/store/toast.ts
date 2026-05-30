// 全局 toast 队列 —— 应用级临时提示（启动成功/失败等任意页面可触发）
// 视觉与 Settings.tsx 内联 toast 一致，但这是独立的全局机制（不动 Settings 局部 toast）。
import { create } from 'zustand';

export type ToastType = 'ok' | 'err';

export interface ToastItem {
  id: number;
  type: ToastType;
  text: string;
}

interface ToastState {
  items: ToastItem[];
  push: (type: ToastType, text: string, durationMs?: number) => void;
  dismiss: (id: number) => void;
}

let seq = 0;

export const useToastStore = create<ToastState>((set, get) => ({
  items: [],
  push: (type, text, durationMs = 4000) => {
    const id = ++seq;
    set({ items: [...get().items, { id, type, text }] });
    window.setTimeout(() => get().dismiss(id), durationMs);
  },
  dismiss: (id) => set({ items: get().items.filter(t => t.id !== id) }),
}));
