// 定时任务 — 设计稿 screens/tasks.jsx 的 TS 平移。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { SCHEDULED_TASKS, USERS } from '../lib/data';
import type { ScheduledTask } from '../lib/types';

function timeUntil(target: string): string {
  const now = new Date('2026-05-19T08:45:32');
  const t = new Date(target.replace(' ', 'T'));
  let diff = Math.max(0, t.getTime() - now.getTime());
  const h = Math.floor(diff / 3_600_000);
  diff -= h * 3_600_000;
  const m = Math.floor(diff / 60_000);
  diff -= m * 60_000;
  const s = Math.floor(diff / 1000);
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

export function TasksScreen() {
  const [tasks, setTasks] = React.useState<ScheduledTask[]>(SCHEDULED_TASKS);
  const [confirm, setConfirm] = React.useState<string | null>(null);

  const kill = (id: string) => {
    setTasks(prev => prev.filter(t => t.id !== id));
    setConfirm(null);
  };

  const recurring = tasks.filter(t => t.recurring);
  const oneShot = tasks.filter(t => !t.recurring);

  return (
    <div className="col gap-6">
      <div className="row spread">
        <div className="row gap-2">
          <span className="pill pill-info">
            <span className="dot" />共 {tasks.length} 个任务
          </span>
          <span className="muted" style={{ fontSize: 12 }}>
            schedule 库 · 按 tag 隔离 · 每 60s 心跳记录数量
          </span>
        </div>
        <div className="row gap-2">
          <button className="btn"><Icon.Refresh size={12} />同步</button>
          <button className="btn btn-primary"><Icon.Plus size={12} />新建任务</button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">一次性任务 · 当日</div>
            <div className="card-sub">执行后自动从队列移除</div>
          </div>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th>任务</th>
              <th>用户</th>
              <th>tag</th>
              <th>下次运行</th>
              <th>距现在</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {oneShot.map(t => (
              <tr key={t.id}>
                <td>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: 'var(--warning)',
                    }}
                  />
                </td>
                <td>
                  <div style={{ fontWeight: 500 }}>{t.name}</div>
                  <div className="mono muted" style={{ fontSize: 10 }}>{t.fn}</div>
                </td>
                <td>
                  {t.user ? (
                    <div className="row gap-2">
                      <div
                        className="user-avatar"
                        style={{
                          background: USERS.find(u => u.id === t.user)?.color,
                          width: 18,
                          height: 18,
                          fontSize: 9,
                        }}
                      >
                        {USERS.find(u => u.id === t.user)?.short}
                      </div>
                      {t.user}
                    </div>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  <span className="pill pill-neutral mono" style={{ fontSize: 10 }}>{t.tag}</span>
                </td>
                <td className="mono">{t.nextRun}</td>
                <td className="mono" style={{ color: 'var(--accent)' }}>
                  {timeUntil(t.nextRun)}
                </td>
                <td>
                  <div className="row gap-2">
                    <button className="btn btn-sm" title="立即执行">
                      <Icon.Play size={11} />
                    </button>
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => setConfirm(t.id)}
                    >
                      <Icon.Trash size={11} />Kill
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {oneShot.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-state">无一次性任务</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">循环任务</div>
            <div className="card-sub">每日定时触发 · schedule.tag 隔离防误删</div>
          </div>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th>任务</th>
              <th>tag</th>
              <th>下次运行</th>
              <th>循环</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {recurring.map(t => (
              <tr key={t.id}>
                <td>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: 'var(--accent)',
                    }}
                  />
                </td>
                <td>
                  <div style={{ fontWeight: 500 }}>{t.name}</div>
                  <div className="mono muted" style={{ fontSize: 10 }}>{t.fn}</div>
                </td>
                <td>
                  <span className="pill pill-neutral mono" style={{ fontSize: 10 }}>{t.tag}</span>
                </td>
                <td className="mono">{t.nextRun}</td>
                <td>
                  <span className="pill pill-info">
                    <Icon.Refresh size={9} />每日
                  </span>
                </td>
                <td>
                  <div className="row gap-2">
                    <button className="btn btn-sm" title="测试">
                      <Icon.Zap size={11} />测试
                    </button>
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => setConfirm(t.id)}
                    >
                      <Icon.Trash size={11} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {confirm && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
          }}
          onClick={() => setConfirm(null)}
        >
          <div
            className="card"
            style={{ width: 380, boxShadow: 'var(--shadow-lg)' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="card-body">
              <div className="row gap-2" style={{ marginBottom: 8 }}>
                <Icon.Trash size={16} style={{ color: 'var(--danger)' }} />
                <div className="h2">删除任务？</div>
              </div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 16 }}>
                即将执行{' '}
                <span
                  className="mono"
                  style={{
                    background: 'var(--bg-inset)',
                    padding: '2px 6px',
                    borderRadius: 3,
                  }}
                >
                  schedule.cancel_job(tag={tasks.find(t => t.id === confirm)?.tag})
                </span>
                ，此操作不可撤销。
              </div>
              <div className="row gap-2" style={{ justifyContent: 'flex-end' }}>
                <button className="btn" onClick={() => setConfirm(null)}>取消</button>
                <button className="btn btn-danger" onClick={() => kill(confirm)}>
                  确认 Kill
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
