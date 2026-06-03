// 概览页 — 设计稿 screens/dashboard.jsx 的 TS 平移。
import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import { RECENT_ACTIVITY, RECORDS, USERS } from '../lib/data';
import type { RecentActivityEntry, User } from '../lib/types';
import { useSystemStore } from '../store/system';
import { usePunchStore } from '../store/punch';
import { api } from '../lib/api';

/** 后端 today_records 时间字段：`'08:29:55'` 或 `'1900-01-01T08:29:55'`，统一抽 HH:MM:SS */
function extractTime(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (raw.includes('T')) return (raw.split('T')[1] ?? '').slice(0, 8);
  return raw.slice(0, 8);
}

interface StatusDotProps {
  tone?: 'success' | 'warning' | 'danger' | 'info';
}

function StatusDot({ tone = 'success' }: StatusDotProps) {
  return (
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: `var(--${tone})`,
        boxShadow: `0 0 0 3px var(--${tone}-bg)`,
      }}
    />
  );
}

interface SparklineProps {
  values: number[];
  max?: number;
}

function Sparkline({ values, max }: SparklineProps) {
  const m = max ?? Math.max(...values, 1);
  return (
    <div className="spark">
      {values.map((v, i) => (
        <div key={i} className="spark-bar" style={{ height: `${(v / m) * 100}%` }} />
      ))}
    </div>
  );
}

function estimateOut(inT: string | null): string | null {
  if (!inT) return null;
  const [h, m, s] = inT.split(':').map(Number);
  const total = h * 3600 + m * 60 + (s || 0) + 8 * 3600 + 15 * 60 + 120;
  const oh = Math.floor(total / 3600);
  const om = Math.floor((total % 3600) / 60);
  return `${String(oh).padStart(2, '0')}:${String(om).padStart(2, '0')}`;
}

function PunchUserCard({ user }: { user: User }) {
  const { setScreen, setCurrentUser } = useApp();
  const snapshot = useSystemStore(s => s.snapshot);
  const refreshStatus = useSystemStore(s => s.refresh);
  // 触发该用户的上/下班打卡（与 /punch_in /punch_out 同接口，进度经 WS punch:progress 展示）
  const [busy, setBusy] = React.useState<null | 'in' | 'out'>(null);
  const [hint, setHint] = React.useState<{ ok: boolean; text: string } | null>(null);
  const doPunch = async (kind: 'in' | 'out') => {
    setBusy(kind);
    setHint(null);
    try {
      const r = kind === 'in' ? await api.punchIn(user.id) : await api.punchOut(user.id);
      // 后端业务失败经 HTTP 200 {success:false} 返回（不会进 catch），需显式判断给出反馈
      setHint({ ok: Boolean(r.success), text: r.message || (r.success ? '操作已启动' : '操作失败') });
    } catch (e) {
      setHint({ ok: false, text: e instanceof Error ? e.message : '请求失败' });
    } finally {
      setBusy(null);
      void refreshStatus();
    }
  };
  // 今日打卡仅取后端 today_records（不再回退到写死的 mock 5/19 数据）
  const apiRec = snapshot?.today_records?.[user.id];
  const today = apiRec
    ? { in: extractTime(apiRec.punch_in_time), out: extractTime(apiRec.punch_out_time) }
    : { in: null, out: null };
  const punchedIn = Boolean(today.in);
  const punchedOut = Boolean(today.out);
  const estOut = punchedIn ? estimateOut(today.in) : null;

  return (
    <div className="card">
      <div className="card-header">
        <div className="row gap-2">
          <div
            className="user-avatar"
            style={{ background: user.color, width: 28, height: 28, fontSize: 12 }}
          >
            {user.short}
          </div>
          <div className="col" style={{ gap: 0 }}>
            <div className="card-title">{user.name}</div>
            <div className="card-sub mono">{user.env}</div>
          </div>
        </div>
        {punchedOut ? (
          <span className="pill pill-success"><span className="dot" />已完成</span>
        ) : punchedIn ? (
          <span className="pill pill-info"><span className="dot" />工作中</span>
        ) : (
          <span className="pill pill-warning"><span className="dot" />未打卡</span>
        )}
      </div>
      <div className="card-body">
        <div className="grid grid-2" style={{ gap: 12 }}>
          <div className="col" style={{ gap: 4 }}>
            <div className="kicker">上班</div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 500 }}>
              {today.in || <span className="muted">--:--:--</span>}
            </div>
            {today.in && <div className="muted" style={{ fontSize: 11 }}>Selenium · 已写入</div>}
          </div>
          <div className="col" style={{ gap: 4 }}>
            <div className="kicker">下班</div>
            <div
              className="mono"
              style={{ fontSize: 22, fontWeight: 500, color: today.out ? undefined : 'var(--text-muted)' }}
            >
              {today.out || (estOut ? estOut : '--:--:--')}
            </div>
            <div className="muted" style={{ fontSize: 11 }}>
              {today.out ? '已写入' : estOut ? '预计 · 8h15m + 随机' : '—'}
            </div>
          </div>
        </div>
        <div className="divider" />
        <div className="row gap-2">
          <button
            className="btn btn-primary"
            disabled={punchedIn || busy !== null}
            onClick={() => doPunch('in')}
          >
            <Icon.Punch size={12} /> {busy === 'in' ? '打卡中…' : '上班打卡'}
          </button>
          <button
            className="btn"
            disabled={busy !== null}
            onClick={() => doPunch('out')}
          >
            <Icon.Power size={12} /> {busy === 'out' ? '打卡中…' : '下班打卡'}
          </button>
          <button
            className="btn btn-sm"
            style={{ marginLeft: 'auto' }}
            onClick={() => {
              setCurrentUser(user.id);
              setScreen('records');
            }}
          >
            查看记录 <Icon.ChevronRight size={10} />
          </button>
        </div>
        {hint && (
          <div
            className="mono"
            style={{
              marginTop: 8,
              fontSize: 11,
              color: hint.ok ? 'var(--success)' : 'var(--danger)',
            }}
          >
            {hint.ok ? '✓ ' : '✗ '}{hint.text}
          </div>
        )}
      </div>
    </div>
  );
}

function ActivityRow({ entry }: { entry: RecentActivityEntry }) {
  const tone: 'success' | 'warning' | 'danger' =
    entry.status === 'ok' ? 'success' : entry.status === 'warn' ? 'warning' : 'danger';
  const typeLabel = (
    {
      punch_in: '上班打卡',
      punch_out: '下班打卡',
      daily_status: '状态推送',
      reminder: '每日提醒',
      log_rotate: '日志轮转',
      error: '异常',
    } as Record<string, string>
  )[entry.type] || entry.type;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '84px 1fr auto',
        gap: 12,
        padding: '10px 0',
        borderBottom: '1px solid var(--border-soft)',
        alignItems: 'center',
      }}
    >
      <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>{entry.ts}</div>
      <div style={{ fontSize: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <StatusDot tone={tone} />
          <span style={{ fontWeight: 500 }}>{typeLabel}</span>
          {entry.user !== 'system' && <span className="muted">· {entry.user}</span>}
        </div>
        <div className="muted" style={{ fontSize: 11, marginTop: 2, paddingLeft: 14 }}>{entry.detail}</div>
      </div>
      <div className="mono" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{entry.method}</div>
    </div>
  );
}

export function DashboardScreen() {
  const { sysStatus, headless, setScreen, currentUser } = useApp();
  const snapshot = useSystemStore(s => s.snapshot);
  const lastFetched = useSystemStore(s => s.lastFetched);
  const punchEntries = usePunchStore(s => s.entries);

  // 真实模式标签优先
  const modeLabel = snapshot?.config
    ? snapshot.config.use_selenium_login
      ? snapshot.config.selenium_headless
        ? 'Selenium · 无头'
        : 'Selenium · 可见'
      : '图像识别 (PyAutoGUI)'
    : sysStatus.modeLabel;

  // 当前用户今日打卡（仅来自后端 today_records）
  const apiToday = snapshot?.today_records?.[currentUser];
  const todayIn = apiToday ? extractTime(apiToday.punch_in_time) : null;
  const todayOut = apiToday ? extractTime(apiToday.punch_out_time) : null;
  const todayStatusLabel = todayOut ? '已下班' : todayIn ? '工作中' : '未打卡';
  const todayStatusTone = todayOut ? 'success' : todayIn ? 'success' : 'warning';

  // 下次任务（snapshot.scheduled_tasks 中最近的）
  const nextTask = (snapshot?.scheduled_tasks ?? [])
    .map(t => ({ ...t, _label: t.scheduled_time }))
    .sort((a, b) => a.scheduled_time.localeCompare(b.scheduled_time))[0];

  // 资源
  const cpu = snapshot?.resources?.cpu_percent;
  const mem = snapshot?.resources?.memory_percent;

  // 真实今日标签（不再用写死的 mock TODAY）
  const _now = new Date();
  const todayLabel = `${_now.getFullYear()}-${String(_now.getMonth() + 1).padStart(2, '0')}-${String(_now.getDate()).padStart(2, '0')} ${['周日', '周一', '周二', '周三', '周四', '周五', '周六'][_now.getDay()]}`;

  const monthRecs = RECORDS['邓蕴哲']['2026-05'];
  const onTimeCount = Object.values(monthRecs).filter(r => r.in && r.in <= '09:00:00').length;
  const totalInThisMonth = Object.values(monthRecs).filter(r => r.in).length;

  const minutesArr = Object.values(monthRecs)
    .filter(r => r.in)
    .map(r => {
      const [h, m] = (r.in as string).split(':').map(Number);
      return h * 60 + m;
    });
  const earliest = Math.min(...minutesArr);
  const latest = Math.max(...minutesArr);

  const spark = Object.entries(monthRecs)
    .slice(-14)
    .map(([, r]) => {
      if (!r.in) return 0;
      const [h, m] = r.in.split(':').map(Number);
      return h * 60 + m - 8 * 60;
    });

  return (
    <div className="col gap-6">
      {/* KPI row */}
      <div className="grid grid-4">
        <div className="kpi">
          <div className="kpi-label">今日状态</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: 'inherit', fontWeight: 600 }}>
            {todayStatusLabel}
          </div>
          <div className="kpi-meta">
            <StatusDot tone={todayStatusTone as 'success' | 'warning' | 'danger' | 'info'} />
            {currentUser} · {todayIn ? `${todayIn} 上班` : '尚未打卡'}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">下次任务</div>
          <div className="kpi-value">{nextTask?.scheduled_time ?? '—'}</div>
          <div className="kpi-meta">
            <Icon.Clock size={12} />
            {nextTask
              ? `${nextTask.type === 'punch_out' ? '下班' : '上班'} · ${nextTask.username ?? '全部'}`
              : '暂无定时任务'}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">本月出勤</div>
          <div className="kpi-value">
            {totalInThisMonth}{' '}
            <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>/ 工作日</span>
          </div>
          <div className="kpi-meta">
            <StatusDot tone="success" />
            准点率 {Math.round((onTimeCount / totalInThisMonth) * 100)}%
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">系统</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: 'inherit', fontWeight: 600 }}>
            {snapshot ? '运行正常' : '加载中…'}
          </div>
          <div className="kpi-meta">
            <StatusDot tone={snapshot ? 'success' : 'warning'} />
            {modeLabel}
          </div>
        </div>
      </div>

      {/* Per-user punch cards */}
      <div className="col gap-2">
        <div className="row spread">
          <div className="kicker">今日打卡 · {todayLabel}</div>
          <button className="btn btn-sm" onClick={() => setScreen('punch')}>
            打开打卡控制台 <Icon.ChevronRight size={10} />
          </button>
        </div>
        <div className="grid grid-2">
          {USERS.map(u => <PunchUserCard key={u.id} user={u} />)}
        </div>
      </div>

      {/* Bottom: Activity + System health */}
      <div className="grid" style={{ gridTemplateColumns: '1.5fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">最近活动</div>
              <div className="card-sub">系统、调度与打卡事件流</div>
            </div>
            <button className="btn btn-sm" onClick={() => setScreen('logs')}>
              查看全部日志 <Icon.ChevronRight size={10} />
            </button>
          </div>
          <div className="card-body" style={{ padding: '4px 16px' }}>
            {/* 优先显示 WS punch:progress；不足或为空时用 mock 兜底 */}
            {punchEntries.length === 0
              ? RECENT_ACTIVITY.map((e, i) => <ActivityRow key={i} entry={e} />)
              : punchEntries
                  .slice(-7)
                  .reverse()
                  .map((p, i) => (
                    <ActivityRow
                      key={`live-${i}`}
                      entry={{
                        ts: new Date(p.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }),
                        user: currentUser,
                        type: 'punch_in',
                        status: 'ok',
                        method: 'WS',
                        detail: `${p.title} — ${p.content}`,
                      }}
                    />
                  ))}
          </div>
        </div>

        <div className="col gap-4">
          <div className="card">
            <div className="card-header">
              <div>
                <div className="card-title">本月准点节奏</div>
                <div className="card-sub mono">
                  {earliest >= 60 * 8
                    ? `${Math.floor(earliest / 60)}:${String(earliest % 60).padStart(2, '0')}`
                    : '08:25'}
                  {' – '}
                  {Math.floor(latest / 60)}:{String(latest % 60).padStart(2, '0')} · 上班时间分布
                </div>
              </div>
            </div>
            <div className="card-body">
              <Sparkline values={spark} max={60} />
              <div className="row spread" style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
                <span>近 14 个工作日</span>
                <span className="mono">均 08:30</span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">服务健康</div>
            </div>
            <div className="card-body compact">
              {[
                {
                  name: 'GUI 后端',
                  v: snapshot
                    ? `已连接 · ${
                        lastFetched ? `${Math.round((Date.now() - lastFetched) / 1000)}s 前刷新` : '初次拉取'
                      }`
                    : '未连接 · 请启动 main.py --gui',
                  tone: (snapshot ? 'success' : 'warning') as 'success' | 'warning',
                },
                {
                  name: 'Telegram Bot',
                  v: snapshot ? '与 GUI 共存' : '—',
                  tone: 'success' as const,
                },
                {
                  name: 'SMTP',
                  v: '可达',
                  tone: 'success' as const,
                },
                {
                  name: 'Selenium driver',
                  v: (snapshot?.config.selenium_headless ?? headless) ? '无头模式' : '可见模式',
                  tone: 'success' as const,
                },
                {
                  name: '活跃浏览器',
                  v: `${snapshot?.active_controllers ?? 0} 个`,
                  tone: 'info' as const,
                },
              ].map((row, i) => (
                <div
                  key={i}
                  className="row spread"
                  style={{
                    padding: '8px 0',
                    borderBottom: i < 4 ? '1px solid var(--border-soft)' : 'none',
                    whiteSpace: 'nowrap',
                  }}
                >
                  <div className="row gap-2" style={{ fontSize: 12, whiteSpace: 'nowrap', minWidth: 0 }}>
                    <StatusDot tone={row.tone} />
                    <span style={{ whiteSpace: 'nowrap' }}>{row.name}</span>
                  </div>
                  <span className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{row.v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
