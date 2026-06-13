// StartupOverlay —— 后端启动期间的"系统启动中"覆盖层（以及失败态）
//
// - status==='starting'：显示"系统启动中，请稍候" + spinner + 阶段文案；可手动关（后台运行）
// - status==='failed'  ：显示失败原因 + 查看日志 + 重试
// - status==='ready'   ：不显示（自动消失）
//
// 关键：容器 top:32px 不遮挡 32px 自绘标题栏，后端卡死时用户仍可最小化/关闭/拖窗。
import * as React from 'react';
import { useStartupStore } from '../store/startup';
import { useStartupLogStore } from '../store/startupLog';
import { useToastStore } from '../store/toast';

export function StartupOverlay() {
  const status = useStartupStore(s => s.status);
  const reason = useStartupStore(s => s.reason);
  const phase = useStartupStore(s => s.phase);
  const overlayDismissed = useStartupStore(s => s.overlayDismissed);
  const setOverlayDismissed = useStartupStore(s => s.setOverlayDismissed);
  const setStarting = useStartupStore(s => s.setStarting);
  const logLines = useStartupLogStore(s => s.lines);

  const logBoxRef = React.useRef<HTMLDivElement>(null);
  const [follow, setFollow] = React.useState(true);
  const onLogScroll = () => {
    const el = logBoxRef.current;
    if (!el) return;
    // 贴底则跟随，用户上滑则暂停自动锁底
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  };
  React.useEffect(() => {
    if (follow && logBoxRef.current) logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
  }, [logLines.length, follow]);

  if (status === 'ready') return null;
  // starting/failed 两态均尊重用户手动关闭（ready 上面已 return）：失败态点"我知道了"也能收起覆盖层
  if (overlayDismissed && status !== 'ready') return null;

  const failed = status === 'failed';
  const tone = failed ? 'danger' : 'accent';

  const openLogs = async () => {
    const err = await window.AAS_SYSTEM?.openLogs();
    if (err) useToastStore.getState().push('err', '无法打开日志目录：' + err);
  };

  // 重试：重新进入"启动中"并重发探活（不重启 python，由 bootstrap 依 epoch 重新探活）。
  // 适用于"HTTP 未在超时内就绪"；若是进程级失败需重启程序。
  const retry = () => setStarting('正在重新确认服务可用…');

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={failed ? '后端启动失败' : '系统启动中'}
      style={{
        position: 'fixed',
        top: 32, left: 0, right: 0, bottom: 0,
        zIndex: 1400,
        background: 'rgba(15, 14, 12, 0.72)',
        backdropFilter: 'blur(2px)',
        WebkitBackdropFilter: 'blur(2px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          width: 'min(900px, calc(100% - 64px))',
          maxWidth: 'calc(100% - 64px)',
          background: 'var(--bg-card)',
          border: `1px solid var(--${tone}-border)`,
          borderTop: `4px solid var(--${tone})`,
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          padding: '24px 28px',
          textAlign: 'center',
        }}
      >
        {!failed && (
          <span
            className="spinner"
            style={{ width: 28, height: 28, borderWidth: 3, margin: '0 auto 16px', display: 'block' }}
          />
        )}
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
          {failed ? '后端启动失败' : '系统启动中，请稍候'}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6, minHeight: 22 }}>
          {failed ? reason : phase}
        </div>

        {/* 日志框随弹窗立即渲染（不再等首条日志才出现）；日志未到时显示占位提示 */}
        <div
          ref={logBoxRef}
          onScroll={onLogScroll}
          className="mono"
          style={{
            marginTop: 16,
            height: 360,
            overflowY: 'auto',
            textAlign: 'left',
            background: 'var(--bg-inset)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            padding: '10px 12px',
            fontSize: 12,
            lineHeight: 1.5,
            color: 'var(--text-secondary)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {logLines.length > 0 ? (
            logLines.map((ln, i) => (
              <div key={i} style={failed ? { color: 'var(--text-primary)' } : undefined}>{ln}</div>
            ))
          ) : (
            <div style={{ color: 'var(--text-muted)' }}>正在收集启动日志…</div>
          )}
        </div>

        <div className="row gap-2" style={{ justifyContent: 'center', marginTop: 20 }}>
          <button className="btn" onClick={openLogs}>查看日志</button>
          {failed && <button className="btn" onClick={retry}>重试</button>}
          <button className="btn btn-primary" onClick={() => setOverlayDismissed(true)}>
            {failed ? '我知道了' : '后台运行'}
          </button>
        </div>
      </div>
    </div>
  );
}
