// 通用应用内对话框 — 替代原生 alert()/confirm()（全程序禁用原生提示框）。
// Promise API 可在任意模块（含非 React 代码）调用：
//   await appAlert('消息');                          // 仅「确定」
//   if (await appConfirm('确认操作？')) { ... }      // 「确定/取消」，danger 选项渲染红色主按钮
// <DialogHost /> 挂载在 App 根部，队列化展示（同一时刻一个，按调用顺序）。
import * as React from 'react';

export interface DialogOpts {
  title?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

interface DialogItem extends DialogOpts {
  id: number;
  type: 'alert' | 'confirm';
  message: string;
  resolve: (ok: boolean) => void;
}

let nextId = 1;
let queue: DialogItem[] = [];
let listeners: Array<(items: DialogItem[]) => void> = [];

function notify() {
  for (const l of listeners) l(queue);
}

function push(item: DialogItem) {
  queue = [...queue, item];
  notify();
}

function remove(id: number) {
  queue = queue.filter(i => i.id !== id);
  notify();
}

/** 应用内 alert（仅确定按钮）。 */
export function appAlert(message: string, opts: DialogOpts = {}): Promise<void> {
  return new Promise(res => {
    push({ id: nextId++, type: 'alert', message, ...opts, resolve: () => res() });
  });
}

/** 应用内 confirm（确定/取消）。 */
export function appConfirm(message: string, opts: DialogOpts = {}): Promise<boolean> {
  return new Promise(res => {
    push({ id: nextId++, type: 'confirm', message, ...opts, resolve: res });
  });
}

export function DialogHost() {
  const [items, setItems] = React.useState<DialogItem[]>(queue);

  React.useEffect(() => {
    const l = (q: DialogItem[]) => setItems(q);
    listeners.push(l);
    return () => { listeners = listeners.filter(x => x !== l); };
  }, []);

  const cur = items[0] ?? null;

  // Enter = 确定，Escape = 取消（alert 时同确定）
  React.useEffect(() => {
    if (!cur) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        cur.resolve(true);
        remove(cur.id);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        cur.resolve(cur.type === 'alert');
        remove(cur.id);
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [cur]);

  if (!cur) return null;

  const done = (ok: boolean) => {
    cur.resolve(ok);
    remove(cur.id);
  };

  return (
    <div className="dlg-overlay">
      <div className="dlg-box" role="dialog" aria-modal="true">
        <div className="dlg-title">{cur.title ?? (cur.type === 'confirm' ? '确认操作' : '提示')}</div>
        <div className="dlg-message">{cur.message}</div>
        <div className="dlg-actions">
          {cur.type === 'confirm' && (
            <button className="btn" onClick={() => done(false)}>{cur.cancelText ?? '取消'}</button>
          )}
          <button
            className={`btn ${cur.danger ? 'btn-danger' : 'btn-primary'}`}
            autoFocus
            onClick={() => done(true)}
          >
            {cur.confirmText ?? '确定'}
          </button>
        </div>
      </div>
    </div>
  );
}
