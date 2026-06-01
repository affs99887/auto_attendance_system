// 系统横幅 —— 流式（非 fixed）危险提示条，位于 Toolbar 与内容之间，推下内容（非覆盖）。
//
// 互斥优先级：
//   1. 服务已停止（available && !running）→ ServiceStoppedBanner（仅「启动服务」）
//   2. 服务运行中但 Telegram bot 未连接（running && bot_available === false）
//      → BotDisconnectedBanner（「重连 Bot」+ 有桥时「重启服务」）
//   3. 否则不渲染
//
// 样式仿 About.tsx 危险条：--danger-bg / --danger-border / 左 3px --danger 强调条。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { api, ApiError } from '../lib/api';
import { useServiceStore } from '../store/service';
import { useSystemStore } from '../store/system';
import { useToastStore } from '../store/toast';

// 危险横幅外壳：左 Icon + 文案（color:--danger），右按钮组
function DangerBanner({ text, actions }: { text: React.ReactNode; actions: React.ReactNode }) {
  return (
    <div
      style={{
        background: 'var(--danger-bg)',
        border: '1px solid var(--danger-border)',
        borderLeft: '3px solid var(--danger)',
        borderRadius: 'var(--radius)',
        padding: '10px 14px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        margin: '0 0 12px',
      }}
    >
      <div className="row gap-2" style={{ alignItems: 'center', color: 'var(--danger)', fontSize: 13 }}>
        <Icon.Info size={14} />
        <span>{text}</span>
      </div>
      <div className="row gap-2">{actions}</div>
    </div>
  );
}

// 服务已停止：仅给「启动服务」（未运行不给重启/终止）
function ServiceStoppedBanner() {
  const [busy, setBusy] = React.useState(false);
  const start = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await window.AAS_SERVICE?.start();
      useToastStore.getState().push(r?.success === false ? 'err' : 'ok', r?.message ?? '已发送启动指令');
    } finally {
      setBusy(false);
    }
  };
  return (
    <DangerBanner
      text="后端服务已停止 — 各页面数据已暂停更新"
      actions={
        <button className="btn btn-sm" disabled={busy} onClick={start}>
          <Icon.Power size={12} /> 启动服务
        </button>
      }
    />
  );
}

// Telegram bot 未连接：重连 Bot（REST）+ 重启服务（有桥才显示）
function BotDisconnectedBanner({ error }: { error?: string | null }) {
  const [reconnecting, setReconnecting] = React.useState(false);
  const hasService = !!window.AAS_SERVICE;

  const reconnect = async () => {
    if (reconnecting) return;
    setReconnecting(true);
    try {
      const r = await api.botReconnect();
      useToastStore.getState().push(
        r.success ? 'ok' : 'err',
        r.success ? (r.message ?? 'Bot 已重连') : (r.error ?? '重连失败'),
      );
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      useToastStore.getState().push('err', `重连失败: ${msg}`);
    } finally {
      setReconnecting(false);
    }
  };

  const restart = async () => {
    const r = await window.AAS_SERVICE?.restart();
    useToastStore.getState().push(r?.success === false ? 'err' : 'ok', r?.message ?? '已发送重启指令');
  };

  return (
    <DangerBanner
      text={`Telegram Bot 未连接${error ? ` — ${error}` : ''}`}
      actions={
        <>
          <button className="btn btn-sm" disabled={reconnecting} onClick={reconnect}>
            <Icon.Bot size={12} /> {reconnecting ? '重连中…' : '重连 Bot'}
          </button>
          {hasService && (
            <button className="btn btn-sm" onClick={restart}>
              <Icon.Refresh size={12} /> 重启服务
            </button>
          )}
        </>
      }
    />
  );
}

export function SystemBanners() {
  const running = useServiceStore(s => s.running);
  const available = useServiceStore(s => s.available);
  const botAvailable = useSystemStore(s => s.snapshot?.bot_available);
  const botError = useSystemStore(s => s.snapshot?.bot_error);

  if (available && !running) return <ServiceStoppedBanner />;
  if (running && botAvailable === false) return <BotDisconnectedBanner error={botError} />;
  return null;
}
