// AI 资讯 store —— 主动 fetch + WS ai_news:update 触发重拉
//
// 后端聚合中文 AI 资讯并按版块归类；前端只负责拉取/缓存/分类展示。
// 仿 store/exchangeRate.ts 写法，本轮仅提供数据层（api/store/订阅），不渲染 UI。
import { create } from 'zustand';
import { api, ApiError, type AiNewsResponse } from '../lib/api';

// 版块：英文 slug ↔ 中文版块名 ↔ 配色 hue（仿设计稿 aihot.jsx 的分类定义）
export interface AiNewsCategory {
  slug: string;
  label: string;
  hue: number;
}

export const AI_NEWS_CATEGORIES: AiNewsCategory[] = [
  { slug: 'ai-models', label: '模型发布', hue: 250 },
  { slug: 'ai-products', label: '产品发布', hue: 150 },
  { slug: 'paper', label: '论文研究', hue: 290 },
  { slug: 'industry', label: '行业动态', hue: 30 },
  { slug: 'tip', label: '技巧观点', hue: 70 },
];

export const CATEGORY_BY_SLUG: Record<string, AiNewsCategory> = Object.fromEntries(
  AI_NEWS_CATEGORIES.map(c => [c.slug, c]),
);

/**
 * 相对时间格式化（基于内容时间与当前毫秒时间戳，仿设计稿 aihot.jsx relTime）：
 * 刚刚 / X 分钟前 / X 小时前 / X 天前(<30 天) / 否则本地日期字符串；iso 为空返回 ''。
 * nowMs 缺省取当前时间。
 */
export function relTime(iso: string | null | undefined, nowMs?: number): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  const now = nowMs ?? Date.now();
  const diff = Math.max(0, now - t);
  const min = Math.floor(diff / 60000);
  if (min < 1) return '刚刚';
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  return new Date(iso).toLocaleDateString('zh-CN');
}

interface AiNewsState {
  resp: AiNewsResponse | null;
  loading: boolean;
  error: string | null;
  lastFetched: number | null;

  /** 拉取 AI 资讯；force=true 跳过后端缓存 */
  refresh: (force?: boolean) => Promise<void>;
  reset: () => void;
}

export const useAiNewsStore = create<AiNewsState>((set) => ({
  resp: null,
  loading: false,
  error: null,
  lastFetched: null,

  async refresh(force) {
    set({ loading: true, error: null });
    try {
      const resp = await api.getAiNews(force);
      set({ resp, lastFetched: Date.now(), loading: false });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      set({ error: msg, loading: false });
    }
  },

  reset() {
    set({ resp: null, loading: false, error: null, lastFetched: null });
  },
}));
