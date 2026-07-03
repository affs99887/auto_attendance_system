// AI 资讯 —— AI HOT (aihot.virxact.com) 精选资讯页（设计稿 screens/news.jsx 的 TS 平移）。
import * as React from 'react';
import { Icon } from '../lib/icons';
import {
  useAiNewsStore,
  AI_NEWS_CATEGORIES,
  CATEGORY_BY_SLUG,
  ALL_SLUG,
  viewKey,
  relTime,
} from '../store/aiNews';
import type { AiNewsItem } from '../lib/api';
import { useToastStore } from '../store/toast';

// 版块标签：按 slug 取配色 hue 与中文名（兜底 industry），size='lg' 用于更大字号场景
function CatTag({ slug, size = 'sm' }: { slug: string | null | undefined; size?: 'sm' | 'lg' }) {
  const c = (slug ? CATEGORY_BY_SLUG[slug] : undefined) ?? CATEGORY_BY_SLUG.industry;
  return (
    <span
      className="cat-tag"
      style={{
        ['--ch' as any]: c.hue,
        fontSize: size === 'lg' ? 12 : 11,
        padding: size === 'lg' ? '3px 10px' : '1px 8px',
      }}
    >
      {c.label}
    </span>
  );
}

// 「精选」标：金色小徽标（Sparkle 图标 + 精选），标出上游主编精选条目
function SelectedTag() {
  return (
    <span
      className="cat-tag"
      style={{ ['--ch' as any]: 85, fontSize: 11, padding: '1px 8px', gap: 3 }}
    >
      <Icon.Sparkle size={10} /> 精选
    </span>
  );
}

// 来源 · 相对时间（mono）
function SourceMeta({ item }: { item: AiNewsItem }) {
  return (
    <div className="row gap-2" style={{ fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
      <span style={{ color: 'var(--text-secondary)' }}>{item.source}</span>
      <span>·</span>
      <span className="mono">{relTime(item.publishedAt)}</span>
    </div>
  );
}

function NewsItem({ item }: { item: AiNewsItem }) {
  return (
    <a className="news-item" href={item.url} target="_blank" rel="noreferrer">
      <div className="news-item-head">
        <CatTag slug={item.category} />
        {item.selected && <SelectedTag />}
        <SourceMeta item={item} />
        <Icon.External size={13} className="news-ext" />
      </div>
      <div className="news-item-title">{item.title}</div>
      {item.summary && <div className="news-item-sum">{item.summary}</div>}
    </a>
  );
}

// 列表底部：游标懒加载触点 + 加载更多 / 没有更多了 / 重试 状态（bucketKey 指定当前视图）
function NewsListFooter({
  bucketKey,
  hasNext,
  loadingMore,
  moreError,
  onLoadMore,
}: {
  bucketKey: string;
  hasNext: boolean;
  loadingMore: boolean;
  moreError: string | null;
  onLoadMore: () => void;
}) {
  const sentinelRef = React.useRef<HTMLDivElement | null>(null);
  // 该视图已加载条数：变化后重建 observer，使内容不足一屏时也能连续加载至撑满或到底
  const itemCount = useAiNewsStore(s => s.cats[bucketKey]?.items.length ?? 0);
  React.useEffect(() => {
    const el = sentinelRef.current;
    // 出错时停止自动加载，等用户手动点"重试"；无更多时也不观察
    if (!el || !hasNext || moreError) return;
    const io = new IntersectionObserver(
      entries => {
        // loadMore 内部自带防重入（loadingMore / !hasNext / !nextCursor 守卫）
        if (entries.some(e => e.isIntersecting)) void useAiNewsStore.getState().loadMore(bucketKey);
      },
      { rootMargin: '200px' },
    );
    io.observe(el);
    return () => io.disconnect();
    // loadingMore 也要进依赖：加载期间哨兵会卸载，若整页去重后 0 条新增（itemCount 不变），
    // 需在 loadingMore 翻回 false、哨兵重挂载后重建 observer，否则旧 observer 盯着已卸载节点永不触发
  }, [bucketKey, hasNext, moreError, itemCount, loadingMore]);

  if (loadingMore) {
    return (
      <div className="empty-state" style={{ padding: '16px 20px' }}>
        <span className="spinner" style={{ display: 'inline-block', marginRight: 8 }} /> 加载中…
      </div>
    );
  }
  if (moreError) {
    return (
      <div className="empty-state" style={{ padding: '16px 20px' }}>
        <div style={{ marginBottom: 8 }}>加载更多失败</div>
        <button className="btn btn-sm" onClick={onLoadMore}>
          <Icon.Refresh size={12} /> 重试
        </button>
      </div>
    );
  }
  if (hasNext) {
    return (
      <div ref={sentinelRef} style={{ display: 'flex', justifyContent: 'center', padding: '14px 0' }}>
        <button className="btn btn-sm" onClick={onLoadMore}>加载更多</button>
      </div>
    );
  }
  return <div className="empty-state" style={{ padding: '16px 20px' }}>没有更多了</div>;
}

export function NewsScreen() {
  // 各视图独立分桶：读整份 cats（任一视图更新即重渲染），再派生当前视图与计数
  const cats = useAiNewsStore(s => s.cats);
  const refresh = useAiNewsStore(s => s.refresh);
  const loadMore = useAiNewsStore(s => s.loadMore);
  const [cat, setCat] = React.useState<string>(ALL_SLUG);
  const [onlySelected, setOnlySelected] = React.useState(false); // 只看精选筛选
  const key = viewKey(cat, onlySelected);
  const st = cats[key];

  // 进入资讯页 / 切换"只看精选"口径时，预拉取该口径下所有版块（后台并行，切分区免等待）
  React.useEffect(() => {
    useAiNewsStore.getState().prefetchAll(onlySelected);
  }, [onlySelected]);

  // 兜底：切到某视图时若仍从未拉取过（如预拉取失败）则补拉一次（loading 中不重复触发）
  React.useEffect(() => {
    const cur = useAiNewsStore.getState().cats[key];
    if (cur && cur.lastFetched === null && !cur.loading) void refresh(key);
  }, [key, refresh]);

  // 各版块计数：取当前口径下各自已加载条数（0 则不展示徽标，避免误显示"无内容"）
  const counts = React.useMemo(() => {
    const m: Record<string, number> = {};
    [ALL_SLUG, ...AI_NEWS_CATEGORIES.map(c => c.slug)].forEach(slug => {
      m[slug] = cats[viewKey(slug, onlySelected)].items.length;
    });
    return m;
  }, [cats, onlySelected]);

  const { items, loading, loadingMore, hasNext, moreError, error } = st;

  // 手动刷新：失败且列表非空时，空列表错误块不会渲染（只在无数据时出现），
  // 改推全局错误 toast——否则 spinner 停止而列表纹丝不动，用户会误以为已刷到最新
  const doRefresh = async () => {
    await refresh(key, true);
    const cur = useAiNewsStore.getState().cats[key];
    if (cur?.error && cur.items.length) {
      useToastStore.getState().push('err', `AI 资讯刷新失败：${cur.error}`);
    }
  };

  // 当前视图按发布时间倒序
  const shown = React.useMemo(
    () => [...items].sort((a, b) => new Date(b.publishedAt ?? 0).getTime() - new Date(a.publishedAt ?? 0).getTime()),
    [items],
  );

  return (
    <div className="col gap-6">
      {/* 顶部状态条 */}
      <div className="news-banner">
        <div className="row gap-2" style={{ minWidth: 0 }}>
          <div className="news-mark"><Icon.Sparkle size={16} /></div>
          <div className="col" style={{ gap: 2, minWidth: 0 }}>
            <div className="card-title" style={{ fontSize: 14 }}>AI HOT · 中文 AI 资讯</div>
            <div className="card-sub" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              数据来自 aihot.virxact.com · 模型 / 产品 / 论文 / 行业动态
            </div>
          </div>
        </div>
        <button className="btn btn-sm" onClick={() => void doRefresh()} disabled={loading}>
          {loading ? <span className="spinner" /> : <Icon.Refresh size={12} />}
          {loading ? '拉取中…' : '刷新'}
        </button>
      </div>

      {/* 分类筛选：每个版块各自一份 list；「只看精选」为独立开关，叠加到当前版块 */}
      <div className="news-filter scroll-area">
        {/* 只看精选：一键筛选，可与任意版块叠加（金色高亮=已开启） */}
        <button
          className={`chip ${onlySelected ? 'active' : ''}`}
          style={{ ['--ch' as any]: 85 }}
          onClick={() => setOnlySelected(v => !v)}
          title={onlySelected ? '点此取消只看精选' : '只看上游主编精选'}
        >
          <Icon.Sparkle size={12} /> 只看精选
        </button>
        <span style={{ width: 1, alignSelf: 'stretch', background: 'var(--border)', margin: '2px 2px' }} />
        <button className={`chip ${cat === ALL_SLUG ? 'active' : ''}`} onClick={() => setCat(ALL_SLUG)}>
          全部 {counts[ALL_SLUG] > 0 && <span className="chip-n mono">{counts[ALL_SLUG]}</span>}
        </button>
        {AI_NEWS_CATEGORIES.map(c => (
          <button
            key={c.slug}
            className={`chip ${cat === c.slug ? 'active' : ''}`}
            style={{ ['--ch' as any]: c.hue }}
            onClick={() => setCat(c.slug)}
          >
            {c.label} {counts[c.slug] > 0 && <span className="chip-n mono">{counts[c.slug]}</span>}
          </button>
        ))}
      </div>

      {/* 资讯列表（当前视图） */}
      {loading && !items.length ? (
        <div className="empty-state">
          <span className="spinner" style={{ display: 'inline-block', marginRight: 8 }} /> 正在拉取 AI HOT 资讯…
        </div>
      ) : error && !items.length ? (
        <div className="empty-state">
          <div style={{ marginBottom: 10 }}>加载失败：{error}</div>
          <button className="btn btn-sm" onClick={() => void refresh(key, true)}>
            <Icon.Refresh size={12} /> 重试
          </button>
        </div>
      ) : shown.length ? (
        <>
          <div className="news-list">
            {shown.map(it => <NewsItem key={it.id} item={it} />)}
          </div>
          <NewsListFooter
            bucketKey={key}
            hasNext={hasNext}
            loadingMore={loadingMore}
            moreError={moreError}
            onLoadMore={() => void loadMore(key)}
          />
        </>
      ) : (
        <div className="empty-state">{onlySelected ? '该版块暂无精选条目' : '该版块暂无条目'}</div>
      )}
    </div>
  );
}
