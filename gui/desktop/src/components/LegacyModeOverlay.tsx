// LegacyModeOverlay — 传统 PyAutoGUI 模式下，打卡进行中叠加的全屏覆盖层
//
// browser_controller.py:70 会调 SetForegroundWindow + PyAutoGUI 控制鼠标键盘，
// 此时 GUI 必须禁用所有交互避免用户误操作。
//
// 触发条件：
//   snapshot.config.use_selenium_login === false  AND  current_operation !== null
import * as React from 'react';
import { Icon } from '../lib/icons';
import { useSystemStore } from '../store/system';
import { api, ApiError } from '../lib/api';
import { useToastStore } from '../store/toast';

function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function LegacyModeOverlay() {
  const snapshot = useSystemStore(s => s.snapshot);
  const useSelenium = snapshot?.config?.use_selenium_login;
  const currentOp = snapshot?.current_operation ?? null;
  const startedAt = snapshot?.operation_started_at ?? null;

  // 计时
  const [now, setNow] = React.useState(Date.now());
  React.useEffect(() => {
    if (currentOp === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [currentOp]);

  // cancelling 本地态：驱动取消按钮 disabled/loading，防止 operationStop 在途时重复点击堆积请求
  const [cancelling, setCancelling] = React.useState(false);

  // 只有 use_selenium_login = false 且打卡进行中才显示
  if (useSelenium !== false || !currentOp) return null;

  const startedTs = startedAt ? new Date(startedAt).getTime() : now;
  const elapsedMs = Math.max(0, now - startedTs);

  // 取消当前打卡：原本静默吞错，失败时按钮无反应，用户会误以为界面卡死而乱动鼠标键盘（恰恰是本遮罩要防止的）。
  // 改为：本地 cancelling 态驱动 disabled/loading；失败 toast 报错；成功也给确认提示（status:update 推送前用户无感知）。
  const handleCancel = async () => {
    if (cancelling) return;
    setCancelling(true);
    try {
      const r = await api.operationStop();
      useToastStore.getState().push(
        r.success === false ? 'err' : 'ok',
        r.message ?? '已发送取消指令',
      );
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      useToastStore.getState().push('err', `取消失败: ${msg}`);
    } finally {
      setCancelling(false);
    }
  };

  const opLabel = currentOp === 'punch_in' ? '上班打卡' : '下班打卡';

  return (
    <div
      role="dialog"
      aria-label="传统模式打卡进行中"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(15, 14, 12, 0.72)',
        backdropFilter: 'blur(2px)',
        WebkitBackdropFilter: 'blur(2px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        // 接住所有事件
        pointerEvents: 'auto',
      }}
      onKeyDown={e => e.preventDefault()}
      onWheel={e => e.preventDefault()}
    >
      <div
        style={{
          width: 480,
          maxWidth: 'calc(100% - 48px)',
          background: 'var(--bg-card)',
          border: '1px solid var(--warning-border)',
          borderTop: '4px solid var(--warning)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          padding: '24px 28px',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            width: 56,
            height: 56,
            margin: '0 auto 16px',
            borderRadius: '50%',
            background: 'var(--warning-bg)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--warning)',
          }}
        >
          <Icon.Eye size={26} strokeWidth={2} />
        </div>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
          {opLabel}进行中 · 请勿操作
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          当前为<strong style={{ color: 'var(--text-primary)' }}>传统图像识别模式</strong>（PyAutoGUI），
          后端正在控制鼠标和键盘点击浏览器。
          <br />
          移动鼠标或敲键盘会打断打卡，请耐心等待。
        </div>

        <div
          style={{
            margin: '20px 0 16px',
            padding: '12px',
            background: 'var(--bg-inset)',
            borderRadius: 'var(--radius)',
            display: 'flex',
            justifyContent: 'space-around',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <div>
            <div className="kicker">已用时</div>
            <div style={{ fontSize: 20, fontWeight: 500 }}>{formatElapsed(elapsedMs)}</div>
          </div>
          <div>
            <div className="kicker">通常耗时</div>
            <div style={{ fontSize: 20, fontWeight: 500, color: 'var(--text-muted)' }}>01:30 - 02:00</div>
          </div>
        </div>

        <div className="row gap-2" style={{ justifyContent: 'center' }}>
          <button className="btn btn-danger" onClick={handleCancel} disabled={cancelling}>
            <span className={cancelling ? 'spin-ic' : ''} style={{ display: 'inline-flex' }}>
              <Icon.Stop size={12} />
            </span>
            {cancelling ? '取消中…' : '取消当前打卡 (/stop)'}
          </button>
        </div>

        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
          想避开此模式？切到 设置 → 自动化模式 → 启用 Selenium
        </div>
      </div>
    </div>
  );
}
