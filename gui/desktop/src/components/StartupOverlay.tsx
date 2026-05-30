// StartupOverlay —— 后端启动期间的"系统启动中"覆盖层（以及失败态）
//
// - status==='starting'：显示"系统启动中，请稍候" + spinner + 阶段文案；可手动关（后台运行）
// - status==='failed'  ：显示失败原因 + 查看日志 + 重试
// - status==='ready'   ：不显示（自动消失）
//
// 关键：容器 top:32px 不遮挡 32px 自绘标题栏，后端卡死时用户仍可最小化/关闭/拖窗。
import * as React from 'react';
import { useStartupStore } from '../store/startup';
import { useToastStore } from '../store/toast';

export function StartupOverlay() {
  const status = useStartupStore(s => s.status);
  const reason = useStartupStore(s => s.reason);
  const phase = useStartupStore(s => s.phase);
  const overlayDismissed = useStartupStore(s => s.overlayDismissed);
  const setOverlayDismissed = useStartupStore(s => s.setOverlayDismissed);
  const setStarting = useStartupStore(s => s.setStarting);

  if (status === 'ready') return null;
  if (status === 'starting' && overlayDismissed) return null;

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
          width: 440,
          maxWidth: 'calc(100% - 48px)',
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
