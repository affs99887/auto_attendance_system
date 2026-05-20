// ProgressDrawer — 全局打卡进度抽屉
// 订阅 usePunchStore.entries（WS punch:progress 推送）+ useSystemStore.current_operation
//
// 状态：
//   - hidden（current_operation==null 且无 entries）→ 不渲染
//   - bubble（用户最小化或操作已完成）→ 右下角悬浮按钮
//   - drawer（默认）→ 右侧 420px 时间线
import * as React from 'react';
import { Icon } from '../lib/icons';
import { useSystemStore } from '../store/system';
import { usePunchStore } from '../store/punch';
import { api } from '../lib/api';

type Mode = 'drawer' | 'bubble' | 'hidden';

export function ProgressDrawer() {
  const currentOp = useSystemStore(s => s.snapshot?.current_operation ?? null);
  const entries = usePunchStore(s => s.entries);
  const clear = usePunchStore(s => s.clear);

  // 当 current_operation 从 null 变成有值，自动展开
  const [mode, setMode] = React.useState<Mode>('hidden');
  const prevOpRef = React.useRef<typeof currentOp>(null);
  React.useEffect(() => {
    if (prevOpRef.current === null && currentOp !== null) {
      setMode('drawer');
    }
    if (currentOp !== null && mode === 'hidden') {
      setMode('drawer');
    }
    prevOpRef.current = currentOp;
  }, [currentOp, mode]);

  // 操作结束后保留 5 秒「终态卡片」再变 bubble
  const finishedAtRef = React.useRef<number | null>(null);
  React.useEffect(() => {
    if (currentOp === null && entries.length > 0 && finishedAtRef.current === null) {
      finishedAtRef.current = Date.now();
    }
    if (currentOp !== null) {
      finishedAtRef.current = null;
    }
  }, [currentOp, entries.length]);

  // 完全空 → 不渲染
  if (currentOp === null && entries.length === 0) {
    return null;
  }

  const opLabel = currentOp === 'punch_in' ? '上班打卡' : currentOp === 'punch_out' ? '下班打卡' : '已完成';
  const opIcon = currentOp === 'punch_in' ? <Icon.Punch size={14} /> : <Icon.Power size={14} />;

  const handleCancel = async () => {
    try {
      await api.operationStop();
    } catch {
      // ignore
    }
  };

  const handleDismiss = () => {
    setMode('hidden');
    clear();
  };

  // Bubble 模式
  if (mode === 'bubble') {
    return (
      <button
        onClick={() => setMode('drawer')}
        title="展开打卡进度"
        style={{
          position: 'fixed',
          right: 20,
          bottom: 20,
          zIndex: 150,
          width: 52,
          height: 52,
          borderRadius: '50%',
          background: currentOp ? 'var(--accent)' : 'var(--success)',
          color: 'white',
          border: 'none',
          boxShadow: 'var(--shadow-lg)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          animation: currentOp ? 'pulse 1.4s infinite ease-out' : 'none',
        }}
      >
        {opIcon}
      </button>
    );
  }

  // Drawer 模式
  return (
    <div
      style={{
        position: 'fixed',
        right: 20,
        bottom: 20,
        width: 420,
        maxHeight: 'calc(100vh - 100px)',
        zIndex: 150,
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-lg)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        animation: 'aas-drawer-in 0.25s ease-out',
      }}
    >
      <style>{`
        @keyframes aas-drawer-in {
          from { transform: translateX(40px); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
      `}</style>

      {/* 头部 */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--border-soft)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: currentOp ? 'var(--accent)' : 'var(--success)',
            boxShadow: currentOp ? '0 0 0 3px var(--accent-bg)' : '0 0 0 3px var(--success-bg)',
          }}
        />
        <div style={{ flex: 1, fontWeight: 500, fontSize: 13 }}>
          {opLabel}
          <span className="mono" style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
            {entries.length} 条
          </span>
        </div>
        <button
          onClick={() => setMode('bubble')}
          title="最小化"
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--text-secondary)',
            padding: 4,
            display: 'flex',
          }}
        >
          <Icon.Minus size={14} />
        </button>
        {!currentOp && (
          <button
            onClick={handleDismiss}
            title="关闭并清除"
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              padding: 4,
              display: 'flex',
            }}
          >
            <Icon.Close size={14} />
          </button>
        )}
      </div>

      {/* 时间线 */}
      <div
        className="scroll-area"
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '8px 16px',
          minHeight: 120,
          maxHeight: 360,
          background: 'var(--bg-inset)',
        }}
      >
        {entries.length === 0 ? (
          <div className="empty-state" style={{ padding: 20 }}>等待后端进度推送…</div>
        ) : (
          [...entries].reverse().map((e, i) => (
            <div
              key={`${e.ts}-${i}`}
              style={{
                display: 'grid',
                gridTemplateColumns: '8px 80px 1fr',
                gap: 8,
                padding: '6px 0',
                borderBottom: i < entries.length - 1 ? '1px solid var(--border-soft)' : 'none',
                alignItems: 'flex-start',
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  marginTop: 6,
                  borderRadius: '50%',
                  background: i === 0 && currentOp ? 'var(--accent)' : 'var(--border-strong)',
                }}
              />
              <span className="mono" style={{ fontSize: 10, color: 'var(--text-muted)', paddingTop: 2 }}>
                {new Date(e.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)' }}>
                  {e.title}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: 'var(--text-secondary)',
                    marginTop: 2,
                    wordBreak: 'break-all',
                  }}
                >
                  {e.content}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 底部操作 */}
      {currentOp && (
        <div
          style={{
            padding: '10px 16px',
            borderTop: '1px solid var(--border-soft)',
            display: 'flex',
            gap: 8,
          }}
        >
          <button className="btn btn-danger" onClick={handleCancel} style={{ flex: 1 }}>
            <Icon.Stop size={11} />取消当前操作
          </button>
        </div>
      )}
    </div>
  );
}
