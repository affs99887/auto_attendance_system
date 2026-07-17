// 系统横幅 —— 流式（非 fixed）危险提示条，位于 Toolbar 与内容之间，推下内容（非覆盖）。
// 仅一种：服务已停止（available && !running）→ ServiceStoppedBanner（仅「启动服务」）。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { useServiceStore } from '../store/service';
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

export function SystemBanners() {
  const running = useServiceStore(s => s.running);
  const available = useServiceStore(s => s.available);

  if (available && !running) return <ServiceStoppedBanner />;
  return null;
}
