// 系统日志 — 三 tab：实时流（虚拟滚动）/ 错误聚合 / 全文搜索
import * as React from 'react';
import { FixedSizeList, type ListChildComponentProps } from 'react-window';
import { Icon } from '../lib/icons';
import { SAMPLE_LOGS } from '../lib/data';
import { useLogsStore } from '../store/logs';
import { wsClient } from '../lib/ws';
import { api, ApiError, type ErrorGroup } from '../lib/api';
import type { LogEntry } from '../lib/types';

type TabKey = 'stream' | 'errors';
type LevelKey = 'ALL' | 'INFO' | 'WARN' | 'ERROR';

const ROW_HEIGHT = 24;

function LogRow({ index, style, data }: ListChildComponentProps<LogEntry[]>) {
  const l = data[index];
  return (
    <div className="log-line" style={style}>
      <span className="ts">{l.ts}</span>
      <span className={`lvl ${l.lvl}`}>{l.lvl}</span>
      <span className="msg">{l.msg}</span>
    </div>
  );
}

function StreamTab() {
  const [level, setLevel] = React.useState<LevelKey>('ALL');
  const [q, setQ] = React.useState('');
  const [follow, setFollow] = React.useState(true);

  const storeLines = useLogsStore(s => s.lines);
  const clearStore = useLogsStore(s => s.clear);
  const [wsStatus, setWsStatus] = React.useState(wsClient.getStatus());
  React.useEffect(() => wsClient.onStatus(setWsStatus), []);

  const sourceLines = storeLines.length > 0 ? storeLines : SAMPLE_LOGS;

  const filtered = React.useMemo(() => {
    return sourceLines.filter(l => {
      const lvl = (l.lvl as string) === 'WARNING' ? 'WARN' : l.lvl;
      if (level !== 'ALL' && lvl !== level) return false;
      if (q && !(l.msg.toLowerCase().includes(q.toLowerCase()) || l.ts.includes(q))) return false;
      return true;
    });
  }, [sourceLines, level, q]);

  const counts: Record<LevelKey, number> = {
    ALL: sourceLines.length,
    INFO: sourceLines.filter(l => l.lvl === 'INFO').length,
    WARN: sourceLines.filter(l => (l.lvl as string) === 'WARN' || (l.lvl as string) === 'WARNING').length,
    ERROR: sourceLines.filter(l => l.lvl === 'ERROR' || l.lvl === 'CRITICAL').length,
  };

  // 自动锁底
  const listRef = React.useRef<FixedSizeList>(null);
  React.useEffect(() => {
    if (follow && filtered.length > 0) {
      listRef.current?.scrollToItem(filtered.length - 1, 'end');
    }
  }, [filtered.length, follow]);

  // 列表高度自适应父容器（避免写死 400 导致大屏下底部行被裁、下方留白）
  const listWrapRef = React.useRef<HTMLDivElement>(null);
  const [listH, setListH] = React.useState(400);
  React.useEffect(() => {
    const el = listWrapRef.current;
    if (!el) return;
    const measure = () => setListH(el.clientHeight);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <>
      <div className="row spread">
        <div className="row gap-2">
          <div className="tab-bar">
            {(['ALL', 'INFO', 'WARN', 'ERROR'] as LevelKey[]).map(L => (
              <button
                key={L}
                className={`tab-btn ${level === L ? 'active' : ''}`}
                onClick={() => setLevel(L)}
              >
                {L === 'ALL' ? '全部' : L}
                <span
                  className="mono"
                  style={{
                    marginLeft: 6, fontSize: 10, padding: '1px 5px', borderRadius: 8,
                    background: 'var(--bg-inset)', color: 'var(--text-muted)',
                  }}
                >{counts[L]}</span>
              </button>
            ))}
          </div>
          <div style={{ position: 'relative', marginLeft: 8 }}>
            <Icon.Search
              size={12}
              style={{
                position: 'absolute', left: 10, top: '50%',
                transform: 'translateY(-50%)', color: 'var(--text-muted)',
              }}
            />
            <input
              className="input mono"
              placeholder="搜索消息或时间戳…"
              value={q}
              onChange={e => setQ(e.target.value)}
              style={{ paddingLeft: 30, width: 260, fontSize: 12 }}
            />
          </div>
        </div>
        <div className="row gap-2">
          <div className="row gap-2" style={{ fontSize: 12 }}>
            <div
              className={`toggle ${follow ? 'on' : ''}`}
              onClick={() => setFollow(!follow)}
            />
            <span className="secondary">实时跟踪</span>
          </div>
          <button className="btn" onClick={() => clearStore()}>
            <Icon.Trash size={12} />清空视图
          </button>
        </div>
      </div>

      <div
        className="card"
        style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 360, marginTop: 12 }}
      >
        <div className="card-header">
          <div>
            <div className="card-title">attendance_system.log</div>
            <div className="card-sub mono">
              logs/attendance_system.log · 虚拟滚动 (react-window)
            </div>
          </div>
          <div className="row gap-2" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {wsStatus === 'open' ? (
              <span className="pill pill-success"><span className="dot" />WS 已连接</span>
            ) : wsStatus === 'connecting' ? (
              <span className="pill pill-info"><span className="dot" />连接中</span>
            ) : storeLines.length === 0 ? (
              <span className="pill pill-warning"><span className="dot" />Mock 数据</span>
            ) : (
              <span className="pill pill-warning"><span className="dot" />WS 断开</span>
            )}
            显示 {filtered.length} / {sourceLines.length} 行
          </div>
        </div>
        <div ref={listWrapRef} style={{ flex: 1, background: 'var(--bg-inset)', minHeight: 300 }}>
          {filtered.length === 0 ? (
            <div className="empty-state">无匹配日志</div>
          ) : (
            <FixedSizeList
              ref={listRef}
              height={listH}
              width="100%"
              itemSize={ROW_HEIGHT}
              itemCount={filtered.length}
              itemData={filtered}
            >
              {LogRow}
            </FixedSizeList>
          )}
        </div>
        <div
          style={{
            borderTop: '1px solid var(--border)',
            padding: '6px 16px',
            fontSize: 11,
            color: 'var(--text-muted)',
            display: 'flex', justifyContent: 'space-between',
          }}
        >
          <span className="mono">tail -f logs/attendance_system.log · row={ROW_HEIGHT}px</span>
          <span>{sourceLines.length} 行 · 虚拟化已启用</span>
        </div>
      </div>
    </>
  );
}

function ErrorsTab() {
  const [page, setPage] = React.useState(1);
  const [groups, setGroups] = React.useState<ErrorGroup[]>([]);
  const [totalPages, setTotalPages] = React.useState(1);
  const [totalGroups, setTotalGroups] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback((p: number) => {
    setLoading(true);
    setError(null);
    api.getErrorLogs(p, 5)
      .then(r => {
        setGroups(r.groups ?? []);
        setTotalPages(r.total_pages ?? 1);
        setTotalGroups(r.total_groups ?? 0);
      })
      .catch(e => {
        setError(e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message);
      })
      .finally(() => setLoading(false));
  }, []);

  React.useEffect(() => { load(page); }, [page, load]);

  return (
    <div className="card" style={{ flex: 1 }}>
      <div className="card-header">
        <div>
          <div className="card-title">错误聚合 · 第 {page} / {totalPages} 页</div>
          <div className="card-sub">
            ERROR/CRITICAL 日志按时间戳分组，最新在前。共 {totalGroups} 组
          </div>
        </div>
        <div className="row gap-2">
          <button className="btn" disabled={page <= 1 || loading} onClick={() => setPage(p => Math.max(1, p - 1))}>
            <Icon.ChevronLeft size={12} />上一页
          </button>
          <button className="btn" disabled={page >= totalPages || loading} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>
            下一页<Icon.ChevronRight size={12} />
          </button>
          <button className="btn" disabled={loading} onClick={() => load(page)}>
            <Icon.Refresh size={12} />刷新
          </button>
        </div>
      </div>
      <div className="card-body">
        {error && (
          <div
            style={{
              padding: '8px 12px', background: 'var(--danger-bg)',
              border: '1px solid var(--danger-border)', borderRadius: 'var(--radius)',
              fontSize: 12, color: 'var(--danger)', marginBottom: 12,
            }}
          >{error}</div>
        )}
        {loading && <div className="empty-state">加载中…</div>}
        {!loading && groups.length === 0 && (
          <div className="empty-state">{error ? '加载失败' : '没有错误日志'}</div>
        )}
        {groups.map((g, i) => (
          <div
            key={`${g.timestamp}-${i}`}
            style={{
              padding: 12,
              marginBottom: 10,
              background: 'var(--danger-bg)',
              border: '1px solid var(--danger-border)',
              borderLeft: '3px solid var(--danger)',
              borderRadius: 'var(--radius)',
            }}
          >
            <div className="mono" style={{ fontSize: 11, color: 'var(--danger)', marginBottom: 6 }}>
              ⏱ {g.timestamp}
            </div>
            <div className="mono" style={{ fontSize: 12, color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {g.content.join('\n')}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function LogsScreen() {
  const [tab, setTab] = React.useState<TabKey>('stream');
  return (
    <div className="col gap-4" style={{ height: '100%' }}>
      <div className="row gap-2">
        <div className="tab-bar">
          <button className={`tab-btn ${tab === 'stream' ? 'active' : ''}`} onClick={() => setTab('stream')}>
            <Icon.Activity size={11} style={{ verticalAlign: -1, marginRight: 4 }} />实时流
          </button>
          <button className={`tab-btn ${tab === 'errors' ? 'active' : ''}`} onClick={() => setTab('errors')}>
            <Icon.Zap size={11} style={{ verticalAlign: -1, marginRight: 4 }} />错误聚合
          </button>
        </div>
      </div>
      {tab === 'stream' && <StreamTab />}
      {tab === 'errors' && <ErrorsTab />}
    </div>
  );
}
