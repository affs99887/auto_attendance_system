// ToastHost —— 渲染全局 toast 队列（store/toast.ts）。点击可手动关闭。
import * as React from 'react';
import { useToastStore } from '../store/toast';

export function ToastHost() {
  const items = useToastStore(s => s.items);
  const dismiss = useToastStore(s => s.dismiss);
  if (items.length === 0) return null;
  return (
    <div
      style={{
        position: 'fixed',
        top: 80,
        right: 24,
        zIndex: 2000,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      {items.map(t => (
        <div
          key={t.id}
          onClick={() => dismiss(t.id)}
          style={{
            background: 'var(--bg-card)',
            border: `1px solid var(--${t.type === 'ok' ? 'success' : 'danger'}-border)`,
            borderLeft: `3px solid var(--${t.type === 'ok' ? 'success' : 'danger'})`,
            borderRadius: 'var(--radius)',
            padding: '10px 16px',
            boxShadow: 'var(--shadow-lg)',
            fontSize: 13,
            maxWidth: 360,
            cursor: 'pointer',
          }}
        >
          {t.text}
        </div>
      ))}
    </div>
  );
}
