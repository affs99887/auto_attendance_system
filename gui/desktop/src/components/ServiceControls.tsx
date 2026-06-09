// 服务控制 — 设计稿 app.jsx 的 ServiceControls 的 TS 化（compact / bar 两种形态）。
// 视觉照设计稿；状态/动作接真实 store/api（从 About.tsx 移植 restart/start/stop/reconnect/confirmStop 逻辑），不使用设计稿 mock svc。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { api, ApiError } from '../lib/api';
import { useServiceStore } from '../store/service';
import { useSystemStore } from '../store/system';
import { useToastStore } from '../store/toast';

// 由 config 推导自动化模式文案（Selenium·无头 / Selenium·可见 / 图像识别(PyAutoGUI)）
function deriveModeLabel(config: {
  use_selenium_login?: boolean;
  selenium_headless?: boolean;
}): string {
  if (config.use_selenium_login) {
    return config.selenium_headless ? 'Selenium·无头' : 'Selenium·可见';
  }
  return '图像识别(PyAutoGUI)';
}

// ISO 时间字符串 → 「Ns 前 / N 分钟前」
function formatHeartbeat(running: boolean, lastIso: string | null | undefined): string {
  if (!running) return '—';
  if (!lastIso) return '—';
  const ms = new Date(lastIso).getTime();
  if (Number.isNaN(ms)) return '—';
  const secs = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  return secs < 60 ? `${secs}s 前` : `${Math.floor(secs / 60)} 分钟前`;
}

export function ServiceControls({ variant = 'compact' }: { variant?: 'compact' | 'bar' }) {
  const running = useServiceStore((s) => s.running);
  const snapshot = useSystemStore((s) => s.snapshot);
  const pushToast = useToastStore((s) => s.push);

  // busy 本地态：驱动 spin-ic + disabled 互斥
  const [busy, setBusy] = React.useState<'restart' | 'reconnect' | null>(null);
  const [confirmStop, setConfirmStop] = React.useState(false);

  // 每秒重渲染让心跳文案走动（与设计稿一致）
  const [, tick] = React.useState(0);
  React.useEffect(() => {
    const id = window.setInterval(() => tick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const heartbeat = formatHeartbeat(running, snapshot?.heartbeat?.last);
  const botOnline = snapshot?.bot_available === true;
  const modeLabel = deriveModeLabel(snapshot?.config ?? {});

  const dotCls = busy ? 'busy' : running ? 'ok' : 'off';
  const statusMain = running ? (busy === 'restart' ? '服务重启中…' : '服务运行中') : '服务已停止';
  const botTxt = !running ? 'Bot 离线' : busy === 'reconnect' ? 'Bot 重连中…' : botOnline ? 'Bot 在线' : 'Bot 离线';

  // 重启：优先 Electron 桥；无桥回退 REST systemRestart
  const handleRestart = async () => {
    if (busy) return;
    setBusy('restart');
    try {
      if (window.AAS_SERVICE) {
        const r = await window.AAS_SERVICE.restart();
        pushToast('ok', r?.message ?? '已发送重启指令');
      } else {
        const r = await api.systemRestart();
        pushToast('ok', r.note ?? '已发出重启信号（由 Electron 处理）');
      }
    } catch (e) {
      pushToast('err', `请求失败: ${e instanceof ApiError ? e.status : (e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  // 启动服务（仅未运行时）
  const handleStart = async () => {
    const r = await window.AAS_SERVICE?.start();
    pushToast('ok', r?.message ?? '已发送启动指令');
  };

  // 终止服务（确认后）
  const handleStop = async () => {
    setConfirmStop(false);
    const r = await window.AAS_SERVICE?.stop();
    pushToast('ok', r?.message ?? '已发送终止指令');
  };

  // 重连 Telegram bot（不重启进程，本地防抖）
  const handleReconnect = async () => {
    if (busy) return;
    setBusy('reconnect');
    try {
      const r = await api.botReconnect();
      pushToast(r.success ? 'ok' : 'err', r.success ? r.message ?? 'Bot 已重连' : r.error ?? '重连失败');
    } catch (e) {
      pushToast('err', `重连失败: ${e instanceof ApiError ? e.status : (e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  // 终止 / 启动按钮：running 时为终止（点开确认），否则为启动
  const onToggle = () => {
    if (running) setConfirmStop(true);
    else void handleStart();
  };

  const acts = (
    <>
      <button className="svc-act" onClick={() => void handleRestart()} disabled={!!busy} title="重启 main.py 服务进程">
        <span className={busy === 'restart' ? 'spin-ic' : ''} style={{ display: 'inline-flex' }}>
          <Icon.Refresh size={15} />
        </span>
        重启服务
      </button>
      <button
        className="svc-act"
        onClick={() => void handleReconnect()}
        disabled={!!busy || !running}
        title="重新连接 Telegram Bot"
      >
        <span className={busy === 'reconnect' ? 'spin-ic' : ''} style={{ display: 'inline-flex' }}>
          <Icon.Bot size={15} />
        </span>
        重连 Bot
      </button>
      <button
        key={running ? 'stop' : 'start'}
        className={`svc-act ${running ? 'danger' : 'start'}`}
        onClick={onToggle}
        disabled={!!busy}
        title={running ? '终止服务' : '启动服务'}
      >
        {running ? <Icon.Power size={15} /> : <Icon.Play size={15} />}
        {running ? '终止服务' : '启动服务'}
      </button>
    </>
  );

  // 终止确认弹窗（照 About.tsx 视觉，内置避免依赖外部）
  const confirmModal = confirmStop ? (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.4)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1500,
      }}
      onClick={() => setConfirmStop(false)}
    >
      <div className="card" style={{ width: 400 }} onClick={(e) => e.stopPropagation()}>
        <div className="card-body">
          <div className="h2" style={{ marginBottom: 8 }}>
            终止后端服务？
          </div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
            终止后端服务？将停止 main.py（含 Telegram bot），可在此页重新启动。
          </div>
          <div className="row gap-2" style={{ justifyContent: 'flex-end' }}>
            <button className="btn" onClick={() => setConfirmStop(false)}>
              取消
            </button>
            <button className="btn btn-danger" onClick={() => void handleStop()}>
              确认终止
            </button>
          </div>
        </div>
      </div>
    </div>
  ) : null;

  if (variant === 'bar') {
    return (
      <>
        <div className="svc svc-bar">
          <span className={`svc-dot ${dotCls}`}></span>
          <div className="svc-bar-info">
            <div className="svc-head-main">{statusMain}</div>
            <div className="svc-head-sub">
              {botTxt} · 上次心跳 {heartbeat} · {modeLabel}
            </div>
          </div>
          <div className="svc-acts svc-acts-bar">{acts}</div>
        </div>
        {confirmModal}
      </>
    );
  }

  return (
    <>
      <div className="svc">
        <div className="svc-head">
          <span className={`svc-dot ${dotCls}`}></span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="svc-head-main">{statusMain}</div>
            <div className="svc-head-sub">
              {botTxt} · 心跳 {heartbeat}
            </div>
          </div>
        </div>
        <div className="svc-acts">{acts}</div>
      </div>
      {confirmModal}
    </>
  );
}
