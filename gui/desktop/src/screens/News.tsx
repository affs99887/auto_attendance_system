// AI 资讯 —— AI HOT (aihot.virxact.com) 精选资讯页（设计稿 screens/news.jsx 的 TS 平移）。
import * as React from 'react';
import { Icon } from '../lib/icons';
import {
  useAiNewsStore,
  AI_NEWS_CATEGORIES,
  CATEGORY_BY_SLUG,
  relTime,
} from '../store/aiNews';
import type { AiNewsItem } from '../lib/api';

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
        <SourceMeta item={item} />
        <Icon.External size={13} className="news-ext" />
      </div>
      <div className="news-item-title">{item.title}</div>
      {item.summary && <div className="news-item-sum">{item.summary}</div>}
    </a>
  );
}

export function NewsScreen() {
  const resp = useAiNewsStore(s => s.resp);
  const loading = useAiNewsStore(s => s.loading);
  const refresh = useAiNewsStore(s => s.refresh);
  const items = resp?.items ?? [];
  const [cat, setCat] = React.useState<string>('all');

  // 各版块计数（all + 各 slug）
  const counts = React.useMemo(() => {
    const m: Record<string, number> = { all: items.length };
    AI_NEWS_CATEGORIES.forEach(c => { m[c.slug] = 0; });
    items.forEach(it => {
      const key = it.category ?? 'industry';
      m[key] = (m[key] || 0) + 1;
    });
    return m;
  }, [items]);

  // 按发布时间倒序
  const sorted = React.useMemo(
    () => [...items].sort((a, b) => new Date(b.publishedAt ?? 0).getTime() - new Date(a.publishedAt ?? 0).getTime()),
    [items],
  );
  const shown = cat === 'all' ? sorted : sorted.filter(it => (it.category ?? 'industry') === cat);

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
        <button className="btn btn-sm" onClick={() => void refresh(true)} disabled={loading}>
          {loading ? <span className="spinner" /> : <Icon.Refresh size={12} />}
          {loading ? '拉取中…' : '刷新'}
        </button>
      </div>

      {/* 分类筛选 */}
      <div className="news-filter scroll-area">
        <button className={`chip ${cat === 'all' ? 'active' : ''}`} onClick={() => setCat('all')}>
          全部 <span className="chip-n mono">{counts.all}</span>
        </button>
        {AI_NEWS_CATEGORIES.map(c => (
          <button
            key={c.slug}
            className={`chip ${cat === c.slug ? 'active' : ''}`}
            style={{ ['--ch' as any]: c.hue }}
            onClick={() => setCat(c.slug)}
          >
            {c.label} <span className="chip-n mono">{counts[c.slug] || 0}</span>
          </button>
        ))}
      </div>

      {/* 资讯列表 */}
      {loading && !items.length ? (
        <div className="empty-state">
          <span className="spinner" style={{ display: 'inline-block', marginRight: 8 }} /> 正在拉取 AI HOT 精选…
        </div>
      ) : shown.length ? (
        <div className="news-list">
          {shown.map(it => <NewsItem key={it.id} item={it} />)}
        </div>
      ) : (
        <div className="empty-state">该版块暂无精选条目</div>
      )}
    </div>
  );
}
