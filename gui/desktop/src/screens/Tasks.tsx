// 定时任务 — 接真实后端 API。
// 数据源：useSystemStore.snapshot.scheduled_tasks（由 status snapshot 提供）
// 操作：api.createTask / api.deleteTask
import * as React from 'react';
import { Icon } from '../lib/icons';
import { USERS } from '../lib/data';
import { api, ApiError } from '../lib/api';
import { useSystemStore } from '../store/system';
import { useToastStore } from '../store/toast';

interface TaskRow {
  id: number;
  type: string;
  scheduled_time: string;
  created_at?: string;
  username?: string;
}

/** 从 HH:MM 字符串计算今日剩余时间（粗略） */
function timeUntil(timeStr: string): string {
  const [h, m] = timeStr.split(':').map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return '—';
  const now = new Date();
  const target = new Date(now);
  target.setHours(h, m, 0, 0);
  let diff = target.getTime() - now.getTime();
  if (diff < 0) diff += 24 * 3600 * 1000; // 已过 → 显示明日剩余
  const hh = Math.floor(diff / 3_600_000);
  const mm = Math.floor((diff % 3_600_000) / 60_000);
  const ss = Math.floor((diff % 60_000) / 1000);
  if (hh > 0) return `${hh}h${String(mm).padStart(2, '0')}m`;
  if (mm > 0) return `${mm}m${String(ss).padStart(2, '0')}s`;
  return `${ss}s`;
}

function CreateTaskForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [type, setType] = React.useState<'punch_in' | 'punch_out'>('punch_out');
  const [mode, setMode] = React.useState<'absolute' | 'delay'>('absolute');
  const [hour, setHour] = React.useState('17');
  const [minute, setMinute] = React.useState('30');
  const [delay, setDelay] = React.useState('5');
  const [username, setUsername] = React.useState<string>('');
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const handleSubmit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body: Parameters<typeof api.createTask>[0] = {
        type, mode, username: username || undefined,
      };
      if (mode === 'absolute') {
        body.hour = parseInt(hour, 10);
        body.minute = parseInt(minute, 10);
      } else {
        body.delay_minutes = parseInt(delay, 10);
      }
      const r = await api.createTask(body);
      if (!r.success) {
        setErr(r.message ?? '创建失败');
        return;
      }
      onCreated();
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // 预览
  let preview = '—';
  if (mode === 'absolute') {
    preview = `每天 ${hour.padStart(2, '0')}:${minute.padStart(2, '0')} 执行${type === 'punch_in' ? '上班' : '下班'}打卡`;
  } else {
    const d = parseInt(delay, 10);
    if (!Number.isNaN(d)) {
      const t = new Date(Date.now() + d * 60_000);
      preview = `约 ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')} 执行${type === 'punch_in' ? '上班' : '下班'}打卡 (${d} 分钟后)`;
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ width: 480, boxShadow: 'var(--shadow-lg)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="card-header">
          <div className="card-title">新建定时任务</div>
          <button className="btn btn-ico" onClick={onClose}><Icon.Close size={12} /></button>
        </div>
        <div className="card-body">
          <div className="field">
            <div className="field-label">打卡类型</div>
            <div className="tab-bar">
              <button
                className={`tab-btn ${type === 'punch_in' ? 'active' : ''}`}
                onClick={() => setType('punch_in')}
              >上班</button>
              <button
                className={`tab-btn ${type === 'punch_out' ? 'active' : ''}`}
                onClick={() => setType('punch_out')}
              >下班</button>
            </div>
          </div>
          <div className="field">
            <div className="field-label">执行模式</div>
            <div className="tab-bar">
              <button
                className={`tab-btn ${mode === 'absolute' ? 'active' : ''}`}
                onClick={() => setMode('absolute')}
              >指定时间</button>
              <button
                className={`tab-btn ${mode === 'delay' ? 'active' : ''}`}
                onClick={() => setMode('delay')}
              >延迟执行</button>
            </div>
          </div>

          {mode === 'absolute' ? (
            <div className="field-row">
              <div className="field">
                <div className="field-label">小时 (0-23)</div>
                <input className="input mono" value={hour} onChange={e => setHour(e.target.value)} />
              </div>
              <div className="field">
                <div className="field-label">分钟 (0-59)</div>
                <input className="input mono" value={minute} onChange={e => setMinute(e.target.value)} />
              </div>
            </div>
          ) : (
            <div className="field">
              <div className="field-label">延迟分钟数</div>
              <input className="input mono" value={delay} onChange={e => setDelay(e.target.value)} />
            </div>
          )}

          <div className="field">
            <div className="field-label">绑定用户 (可选)</div>
            <select className="input" value={username} onChange={e => setUsername(e.target.value)}>
              <option value="">— 全部用户 —</option>
              {USERS.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </div>

          <div
            style={{
              padding: 10,
              background: 'var(--accent-bg)',
              borderLeft: '3px solid var(--accent)',
              borderRadius: 'var(--radius)',
              fontSize: 12,
              color: 'var(--accent-fg)',
              marginBottom: 12,
            }}
          >
            <strong>预览：</strong>{preview}
          </div>

          {err && (
            <div
              style={{
                padding: '8px 12px', background: 'var(--danger-bg)',
                border: '1px solid var(--danger-border)', borderRadius: 'var(--radius)',
                fontSize: 12, color: 'var(--danger)', marginBottom: 12,
              }}
            >{err}</div>
          )}

          <div className="row gap-2" style={{ justifyContent: 'flex-end' }}>
            <button className="btn" onClick={onClose}>取消</button>
            <button className="btn btn-primary" disabled={busy} onClick={handleSubmit}>
              <Icon.Plus size={12} />{busy ? '创建中…' : '创建任务'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function TasksScreen() {
  const snapshot = useSystemStore(s => s.snapshot);
  const refresh = useSystemStore(s => s.refresh);
  const tasks: TaskRow[] = (snapshot?.scheduled_tasks ?? []) as TaskRow[];
  const [confirmDel, setConfirmDel] = React.useState<TaskRow | null>(null);
  const [showCreate, setShowCreate] = React.useState(false);
  const [tick, setTick] = React.useState(0);

  // 每秒推进倒计时
  React.useEffect(() => {
    const id = window.setInterval(() => setTick(t => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const toast = (type: 'ok' | 'err', text: string) => useToastStore.getState().push(type, text);

  const handleDelete = async (id: number) => {
    setConfirmDel(null);
    try {
      const r = await api.deleteTask(id);
      // 后端可能返回 success === false（任务已不存在等），需显式提示而非静默关闭
      if (r.success === false) {
        toast('err', `删除任务 #${id} 失败`);
      } else {
        toast('ok', `任务 #${id} 已删除`);
      }
    } catch (e) {
      // 网络错误 / 4xx 等：弹 toast 告知用户，避免误以为定时打卡已取消
      toast('err', e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message);
    } finally {
      // 无论成败都刷新，确保列表与后端真实状态一致
      void refresh();
    }
  };

  return (
    <div className="col gap-6">
      <div className="row spread">
        <div className="row gap-2">
          <span className="pill pill-info">
            <span className="dot" />共 {tasks.length} 个任务
          </span>
          <span className="muted" style={{ fontSize: 12 }}>
            schedule 库 · 数据来自 GET /api/v1/status
          </span>
        </div>
        <div className="row gap-2">
          <button className="btn" onClick={() => void refresh()}>
            <Icon.Refresh size={12} />同步
          </button>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Icon.Plus size={12} />新建任务
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">定时任务</div>
            <div className="card-sub">从 scheduled_tasks.json 读取；删除立刻取消 schedule job</div>
          </div>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 40 }}>ID</th>
              <th>类型</th>
              <th>用户</th>
              <th>计划时间</th>
              <th>距执行 <span data-tick={tick} style={{ display: 'none' }} /></th>
              <th>创建于</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-state">
                  暂无定时任务 — 点击右上角「新建任务」创建
                </td>
              </tr>
            )}
            {tasks.map(t => {
              const user = USERS.find(u => u.id === t.username);
              return (
                <tr key={t.id}>
                  <td className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>#{t.id}</td>
                  <td>
                    <span className={`pill ${t.type === 'punch_in' ? 'pill-info' : 'pill-warning'}`}>
                      <span className="dot" />
                      {t.type === 'punch_in' ? '上班' : '下班'}
                    </span>
                  </td>
                  <td>
                    {user ? (
                      <div className="row gap-2">
                        <div
                          className="user-avatar"
                          style={{
                            background: user.color, width: 18, height: 18, fontSize: 9,
                          }}
                        >{user.short}</div>
                        {user.name}
                      </div>
                    ) : (
                      <span className="muted">全部</span>
                    )}
                  </td>
                  <td className="mono">{t.scheduled_time}</td>
                  <td className="mono" style={{ color: 'var(--accent)' }}>
                    {timeUntil(t.scheduled_time)}
                  </td>
                  <td className="mono muted" style={{ fontSize: 11 }}>
                    {t.created_at ?? '—'}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => setConfirmDel(t)}
                    >
                      <Icon.Trash size={11} />Kill
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {confirmDel && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
          onClick={() => setConfirmDel(null)}
        >
          <div
            className="card"
            style={{ width: 380, boxShadow: 'var(--shadow-lg)' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="card-body">
              <div className="row gap-2" style={{ marginBottom: 8 }}>
                <Icon.Trash size={16} style={{ color: 'var(--danger)' }} />
                <div className="h2">删除任务 #{confirmDel.id}？</div>
              </div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
                {confirmDel.type === 'punch_in' ? '上班' : '下班'}打卡 · 计划 {confirmDel.scheduled_time}
                <br />
                此操作不可撤销。
              </div>
              <div className="row gap-2" style={{ justifyContent: 'flex-end' }}>
                <button className="btn" onClick={() => setConfirmDel(null)}>取消</button>
                <button className="btn btn-danger" onClick={() => handleDelete(confirmDel.id)}>
                  确认 Kill
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showCreate && (
        <CreateTaskForm
          onClose={() => setShowCreate(false)}
          onCreated={() => void refresh()}
        />
      )}
    </div>
  );
}
