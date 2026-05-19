// 系统日志 — 设计稿 screens/logs.jsx 的 TS 平移。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { SAMPLE_LOGS } from '../lib/data';
import { useLogsStore } from '../store/logs';
import { wsClient } from '../lib/ws';

type LevelKey = 'ALL' | 'INFO' | 'WARN' | 'ERROR';

export function LogsScreen() {
  const [level, setLevel] = React.useState<LevelKey>('ALL');
  const [q, setQ] = React.useState('');
  const [follow, setFollow] = React.useState(true);

  const storeLines = useLogsStore(s => s.lines);
  const clearStore = useLogsStore(s => s.clear);
  const [wsStatus, setWsStatus] = React.useState(wsClient.getStatus());
  React.useEffect(() => wsClient.onStatus(setWsStatus), []);

  // 没有后端日志时回退到 mock，保证设计稿在 dev 模式可见
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

  return (
    <div className="col gap-4" style={{ height: '100%' }}>
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
                    marginLeft: 6,
                    fontSize: 10,
                    padding: '1px 5px',
                    borderRadius: 8,
                    background: 'var(--bg-inset)',
                    color: 'var(--text-muted)',
                  }}
                >
                  {counts[L]}
                </span>
              </button>
            ))}
          </div>
          <div style={{ position: 'relative', marginLeft: 8 }}>
            <Icon.Search
              size={12}
              style={{
                position: 'absolute',
                left: 10,
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--text-muted)',
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
          <button className="btn"><Icon.Download size={12} />导出</button>
          <button className="btn" onClick={() => clearStore()}>
            <Icon.Trash size={12} />清空视图
          </button>
        </div>
      </div>

      <div
        className="card"
        style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 360 }}
      >
        <div className="card-header">
          <div>
            <div className="card-title">attendance_system.log</div>
            <div className="card-sub mono">
              logs/attendance_system.log · 5MB rotating · backupCount=3
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
        <div className="scroll-area" style={{ flex: 1, background: 'var(--bg-inset)' }}>
          {filtered.map((l, i) => (
            <div key={i} className="log-line">
              <span className="ts">{l.ts}</span>
              <span className={`lvl ${l.lvl}`}>{l.lvl}</span>
              <span className="msg">{l.msg}</span>
            </div>
          ))}
          {filtered.length === 0 && <div className="empty-state">无匹配日志</div>}
        </div>
        <div
          style={{
            borderTop: '1px solid var(--border)',
            padding: '6px 16px',
            fontSize: 11,
            color: 'var(--text-muted)',
            display: 'flex',
            justifyContent: 'space-between',
          }}
        >
          <span className="mono">tail -f logs/attendance_system.log</span>
          <span>UTF-8 · 27,706 行 · 4.2 MB</span>
        </div>
      </div>
    </div>
  );
}
