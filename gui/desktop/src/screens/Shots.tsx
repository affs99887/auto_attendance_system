// 截图档案 — 设计稿 screens/shots.jsx 的 TS 平移。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { USERS } from '../lib/data';

interface PlaceholderImgProps {
  kind: 'punch_in' | 'punch_out';
  ts: string;
  user: string;
  success: boolean;
}

function PlaceholderImg({ kind, ts, user, success }: PlaceholderImgProps) {
  const accent = kind === 'punch_in' ? '#3B82F6' : '#9333EA';
  const patId = `p-${user}-${ts}`;
  return (
    <div
      style={{
        aspectRatio: '16 / 10',
        background: 'var(--bg-inset)',
        borderRadius: 6,
        position: 'relative',
        overflow: 'hidden',
        border: '1px solid var(--border)',
      }}
    >
      <svg
        viewBox="0 0 160 100"
        preserveAspectRatio="xMidYMid slice"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.6 }}
      >
        <defs>
          <pattern
            id={patId}
            patternUnits="userSpaceOnUse"
            width="6"
            height="6"
            patternTransform="rotate(45)"
          >
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--border-strong)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="160" height="100" fill={`url(#${patId})`} />
        <rect x="6" y="6" width="148" height="88" rx="2" fill="white" opacity="0.9" stroke="var(--border)" />
        <rect x="6" y="6" width="148" height="10" fill="var(--bg-sidebar)" />
        <circle cx="11" cy="11" r="1.2" fill="#ff5f57" />
        <circle cx="15" cy="11" r="1.2" fill="#febc2e" />
        <circle cx="19" cy="11" r="1.2" fill="#28c840" />
        <rect x="14" y="36" width="60" height="30" rx="2" fill={accent} opacity="0.15" />
        <rect x="14" y="36" width="60" height="3" fill={accent} opacity="0.4" />
        <rect x="14" y="42" width="40" height="2" fill={accent} opacity="0.3" />
        <rect x="14" y="48" width="50" height="2" fill={accent} opacity="0.3" />
        <rect
          x="84"
          y="36"
          width="60"
          height="44"
          rx="2"
          fill={accent}
          opacity="0.08"
          stroke={accent}
          strokeOpacity="0.2"
        />
        <rect x="98" y="58" width="32" height="8" rx="1" fill={accent} />
        <text x="114" y="64" fontFamily="monospace" fontSize="3.5" fill="white" textAnchor="middle">
          {kind === 'punch_in' ? '上班打卡' : '下班打卡'}
        </text>
      </svg>
      <div
        style={{
          position: 'absolute',
          bottom: 8,
          left: 8,
          right: 8,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          gap: 8,
        }}
      >
        <div
          className="mono"
          style={{
            fontSize: 9,
            color: 'var(--text-muted)',
            background: 'var(--bg-card)',
            padding: '2px 5px',
            borderRadius: 3,
            border: '1px solid var(--border)',
          }}
        >
          {ts}
        </div>
        <span
          className={`pill ${success ? 'pill-success' : 'pill-danger'}`}
          style={{ fontSize: 9, padding: '1px 6px' }}
        >
          <span className="dot" />{success ? 'success' : 'fail'}
        </span>
      </div>
    </div>
  );
}

function formatTs(s: string): string {
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)} ${s.slice(9, 11)}:${s.slice(11, 13)}:${s.slice(13, 15)}`;
}

export function ShotsScreen() {
  const [user, setUser] = React.useState<string>(USERS[0].id);
  const [kind, setKind] = React.useState<'punch_in' | 'punch_out'>('punch_in');

  const samples = [
    { ts: '20260519_082947', success: true },
    { ts: '20260518_084600', success: true },
    { ts: '20260517_085012', success: false },
  ];

  return (
    <div className="col gap-6">
      <div className="row spread">
        <div className="row gap-2">
          <div className="tab-bar">
            {USERS.map(u => (
              <button
                key={u.id}
                className={`tab-btn ${user === u.id ? 'active' : ''}`}
                onClick={() => setUser(u.id)}
              >
                <span
                  className="user-avatar"
                  style={{
                    background: u.color,
                    width: 16,
                    height: 16,
                    fontSize: 9,
                    marginRight: 6,
                    display: 'inline-flex',
                  }}
                >
                  {u.short}
                </span>
                {u.name}
              </button>
            ))}
          </div>
          <div className="tab-bar" style={{ marginLeft: 12 }}>
            <button
              className={`tab-btn ${kind === 'punch_in' ? 'active' : ''}`}
              onClick={() => setKind('punch_in')}
            >
              上班 punch_in/
            </button>
            <button
              className={`tab-btn ${kind === 'punch_out' ? 'active' : ''}`}
              onClick={() => setKind('punch_out')}
            >
              下班 punch_out/
            </button>
          </div>
        </div>
        <div className="row gap-2">
          <button className="btn"><Icon.Refresh size={12} />重新加载</button>
          <button className="btn"><Icon.Bot size={12} />Telegram /check</button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">最近 3 张截图</div>
            <div className="card-sub mono">
              screenshots/{user}/{kind}/ · 每用户每类型最多保留 3 张
            </div>
          </div>
          <div className="row gap-2" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            <Icon.Info size={12} />超过 3 张时自动删除最旧
          </div>
        </div>
        <div className="card-body">
          <div className="grid grid-3" style={{ gap: 16 }}>
            {samples.map((s, i) => (
              <div className="col gap-2" key={i}>
                <PlaceholderImg kind={kind} ts={s.ts} user={user} success={s.success} />
                <div className="row spread" style={{ fontSize: 11 }}>
                  <span className="mono">{formatTs(s.ts)}</span>
                  <span className="muted">{['最新', '前次', '最早'][i]}</span>
                </div>
                <div className="row gap-2">
                  <button className="btn btn-sm" style={{ flex: 1 }}>
                    <Icon.Eye size={11} />查看
                  </button>
                  <button className="btn btn-sm"><Icon.Download size={11} /></button>
                  <button className="btn btn-sm btn-danger"><Icon.Trash size={11} /></button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">存储概览</div>
        </div>
        <div className="card-body compact">
          {USERS.flatMap(u => [
            { user: u.id, color: u.color, short: u.short, kind: 'punch_in', cnt: 3, latest: '2026-05-19 08:29' },
            { user: u.id, color: u.color, short: u.short, kind: 'punch_out', cnt: 3, latest: '2026-05-18 17:03' },
          ]).map((row, i, arr) => (
            <div
              key={i}
              className="row spread"
              style={{
                padding: '10px 0',
                borderBottom: i < arr.length - 1 ? '1px solid var(--border-soft)' : 'none',
              }}
            >
              <div className="row gap-2" style={{ fontSize: 12 }}>
                <div
                  className="user-avatar"
                  style={{ background: row.color, width: 18, height: 18, fontSize: 9 }}
                >
                  {row.short}
                </div>
                <span>{row.user}</span>
                <span className="muted">·</span>
                <span className="mono" style={{ fontSize: 11 }}>{row.kind}/</span>
              </div>
              <div className="row gap-6">
                <span className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  {row.cnt} 张
                </span>
                <span
                  className="mono"
                  style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 130, textAlign: 'right' }}
                >
                  最近 {row.latest}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
