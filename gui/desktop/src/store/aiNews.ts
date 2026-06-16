// AI 资讯 store —— 主动 fetch + WS ai_news:update 触发重拉
//
// 后端聚合中文 AI 资讯并按版块归类；前端只负责拉取/缓存/分类展示。
// 仿 store/exchangeRate.ts 写法，本轮仅提供数据层（api/store/订阅），不渲染 UI。
import { create } from 'zustand';
import { api, ApiError, type AiNewsItem } from '../lib/api';

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
  items: AiNewsItem[];        // 累积已加载条目（渲染时再按时间排序/分类过滤）
  updatedAt: number | null;   // 首屏缓存刷新时刻（unix 秒）
  nextCursor: string | null;  // 下一页游标（null 表示无更多）
  hasNext: boolean;           // 是否还有更多可加载
  loading: boolean;           // 首屏 / 手动刷新加载中
  loadingMore: boolean;       // 加载更多中
  error: string | null;       // 首屏错误（空列表错误态用）
  moreError: string | null;   // 加载更多错误（底部重试用）
  lastFetched: number | null;
  loadedMore: boolean;        // 用户是否点过"加载更多"（自动刷新据此避免打断深度浏览）

  /** 首屏 / 手动刷新：替换列表并重置游标；force=true 跳过后端缓存 */
  refresh: (force?: boolean) => Promise<void>;
  /** 加载下一页：游标续拉并去重追加 */
  loadMore: () => Promise<void>;
  /** 仅当用户未点过"加载更多"时才刷新（供轮询/WS/可见性等自动触发用） */
  refreshIfPristine: () => void;
  reset: () => void;
}

export const useAiNewsStore = create<AiNewsState>((set, get) => ({
  items: [],
  updatedAt: null,
  nextCursor: null,
  hasNext: false,
  loading: false,
  loadingMore: false,
  error: null,
  moreError: null,
  lastFetched: null,
  loadedMore: false,

  async refresh(force) {
    set({ loading: true, error: null });
    try {
      const resp = await api.getAiNews({ force });
      set({
        items: resp.items ?? [],
        updatedAt: resp.updated_at ?? null,
        nextCursor: resp.next_cursor ?? null,
        hasNext: !!resp.has_next,
        moreError: null,
        loadedMore: false,
        lastFetched: Date.now(),
        loading: false,
      });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      set({ error: msg, loading: false });
    }
  },

  async loadMore() {
    const { loadingMore, hasNext, nextCursor, items } = get();
    if (loadingMore || !hasNext || !nextCursor) return;
    set({ loadingMore: true, moreError: null, loadedMore: true });
    try {
      const resp = await api.getAiNews({ cursor: nextCursor });
      // 按 id 去重追加（防游标边界重复）
      const seen = new Set(items.map(it => it.id));
      const fresh = (resp.items ?? []).filter(it => it.id && !seen.has(it.id));
      set({
        items: [...items, ...fresh],
        nextCursor: resp.next_cursor ?? null,
        hasNext: !!resp.has_next,
        loadingMore: false,
      });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      // 保留 hasNext/nextCursor 以便重试；记 moreError 供底部展示
      set({ moreError: msg, loadingMore: false });
    }
  },

  refreshIfPristine() {
    if (get().loadedMore) return;   // 用户已加载更多：自动刷新不缩回首屏 / 不丢滚动位置
    void get().refresh();
  },

  reset() {
    set({
      items: [], updatedAt: null, nextCursor: null, hasNext: false,
      loading: false, loadingMore: false, error: null, moreError: null,
      lastFetched: null, loadedMore: false,
    });
  },
}));
