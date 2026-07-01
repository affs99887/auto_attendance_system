// AI 资讯 store —— 主动 fetch + WS ai_news:update 触发重拉
//
// 后端聚合中文 AI 资讯并按版块归类；前端按版块各自独立一份 list：
// "全部" + 每个版块都有自己的 items/游标/加载态，后端按 category 服务端过滤续拉，
// 互不干扰（不再"先拉全部再前端分类"）。
import { create } from 'zustand';
import { api, ApiError, type AiNewsItem } from '../lib/api';

// 版块：英文 slug ↔ 中文版块名 ↔ 配色 hue（仿设计稿 aihot.jsx 的分类定义）
export interface AiNewsCategory {
  slug: string;
  label: string;
  hue: number;
}

// "全部"版块的 key：不带 category 过滤，对应上游 mode=selected 全量精选
export const ALL_SLUG = 'all';

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

// 单个版块的状态（"全部"与每个 category 各持有一份）
export interface AiNewsCatState {
  items: AiNewsItem[];        // 该版块已加载条目（渲染时再按时间排序）
  updatedAt: number | null;   // 首屏缓存刷新时刻（unix 秒）
  nextCursor: string | null;  // 下一页游标（null 表示无更多）
  hasNext: boolean;           // 是否还有更多可加载
  loading: boolean;           // 首屏 / 手动刷新加载中
  loadingMore: boolean;       // 加载更多中
  error: string | null;       // 首屏错误（空列表错误态用）
  moreError: string | null;   // 加载更多错误（底部重试用）
  lastFetched: number | null; // 该版块是否已首拉过（null=从未拉取，供切版块时懒加载）
  loadedMore: boolean;        // 用户是否点过"加载更多"（自动刷新据此避免打断深度浏览）
}

function emptyCat(): AiNewsCatState {
  return {
    items: [], updatedAt: null, nextCursor: null, hasNext: false,
    loading: false, loadingMore: false, error: null, moreError: null,
    lastFetched: null, loadedMore: false,
  };
}

// 视图 key：普通视图用 slug 本身（all / ai-models …）；"只看精选"加 sel: 前缀
// （sel:all / sel:ai-models …），与后端 mode=selected 一一对应，各视图独立一份状态。
export function viewKey(slug: string, onlySelected: boolean): string {
  return onlySelected ? `sel:${slug}` : slug;
}

// 视图 key -> 后端查询参数（category：非"全部"才带；mode：只看精选才传 selected）
function keyToParams(key: string): { category?: string; mode?: 'selected' } {
  const onlySelected = key.startsWith('sel:');
  const slug = onlySelected ? key.slice(4) : key;
  return {
    category: slug === ALL_SLUG ? undefined : slug,
    mode: onlySelected ? 'selected' : undefined,
  };
}

// 初始各视图：全部 + 每个版块 × {普通, 只看精选} 都以空态占位（选择器读取恒不为 undefined）
function initialCats(): Record<string, AiNewsCatState> {
  const cats: Record<string, AiNewsCatState> = {};
  [ALL_SLUG, ...AI_NEWS_CATEGORIES.map(c => c.slug)].forEach(slug => {
    cats[viewKey(slug, false)] = emptyCat();
    cats[viewKey(slug, true)] = emptyCat();
  });
  return cats;
}

interface AiNewsState {
  cats: Record<string, AiNewsCatState>;  // 按视图 key（见 viewKey）分桶

  /** 首屏 / 手动刷新指定视图：替换列表并重置游标；force=true 跳过后端缓存（缺省"全部"） */
  refresh: (key?: string, force?: boolean) => Promise<void>;
  /** 加载指定视图下一页：游标续拉并去重追加（缺省"全部"） */
  loadMore: (key?: string) => Promise<void>;
  /** 仅当该视图用户未点过"加载更多"时才刷新（供轮询/WS/可见性等自动触发用，缺省"全部"） */
  refreshIfPristine: (key?: string) => void;
  /** 预拉取：并行首拉某口径(普通/只看精选)下所有"从未拉过且不在加载"的视图（切分区免等待） */
  prefetchAll: (onlySelected?: boolean) => void;
  reset: () => void;
}

export const useAiNewsStore = create<AiNewsState>((set, get) => {
  // 局部更新某视图状态（保持其余视图引用不变，避免无谓重渲染）
  const patchCat = (key: string, patch: Partial<AiNewsCatState>) =>
    set(state => ({
      cats: { ...state.cats, [key]: { ...(state.cats[key] ?? emptyCat()), ...patch } },
    }));

  return {
    cats: initialCats(),

    async refresh(key = ALL_SLUG, force) {
      patchCat(key, { loading: true, error: null });
      try {
        const resp = await api.getAiNews({ force, ...keyToParams(key) });
        patchCat(key, {
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
        patchCat(key, { error: msg, loading: false });
      }
    },

    async loadMore(key = ALL_SLUG) {
      const st = get().cats[key] ?? emptyCat();
      if (st.loadingMore || !st.hasNext || !st.nextCursor) return;
      patchCat(key, { loadingMore: true, moreError: null, loadedMore: true });
      try {
        const resp = await api.getAiNews({ cursor: st.nextCursor, ...keyToParams(key) });
        // 按 id 去重追加（防游标边界重复）
        const seen = new Set(st.items.map(it => it.id));
        const fresh = (resp.items ?? []).filter(it => it.id && !seen.has(it.id));
        patchCat(key, {
          items: [...st.items, ...fresh],
          nextCursor: resp.next_cursor ?? null,
          hasNext: !!resp.has_next,
          loadingMore: false,
        });
      } catch (e) {
        const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
        // 保留 hasNext/nextCursor 以便重试；记 moreError 供底部展示
        patchCat(key, { moreError: msg, loadingMore: false });
      }
    },

    refreshIfPristine(key = ALL_SLUG) {
      // 用户已加载更多：自动刷新不缩回首屏 / 不丢滚动位置
      if ((get().cats[key] ?? emptyCat()).loadedMore) return;
      void get().refresh(key);
    },

    prefetchAll(onlySelected = false) {
      const { cats } = get();
      // 该口径下 全部 + 各版块中"从未拉过且当前不在加载"的，并行首拉（已加载/加载中的跳过）
      [ALL_SLUG, ...AI_NEWS_CATEGORIES.map(c => c.slug)].forEach(slug => {
        const key = viewKey(slug, onlySelected);
        const st = cats[key];
        if (st && st.lastFetched === null && !st.loading) void get().refresh(key);
      });
    },

    reset() {
      set({ cats: initialCats() });
    },
  };
});
