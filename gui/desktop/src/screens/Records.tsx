// 打卡记录 — 接真实后端 API。打卡记录是核心数据，API 失败时不再静默退回
// data.ts 写死的 mock 假记录（会让用户把假打卡当真，误判漏打卡），改为显示
// 醒目错误条 + 重试，日历/明细/统计走真实空态。
import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import {
  buildMonthGrid,
  dateStr,
  fmtDuration,
} from '../lib/data';
import type { PunchRec } from '../lib/types';
import { api, ApiError } from '../lib/api';

/** 把后端 records ({punch_in_time, punch_out_time}) 归一为前端 PunchRec ({in, out}) */
function normalizeRecords(raw: unknown): Record<string, PunchRec> {
  const result: Record<string, PunchRec> = {};
  if (!raw || typeof raw !== 'object') return result;
  for (const [date, val] of Object.entries(raw as Record<string, unknown>)) {
    if (!val || typeof val !== 'object') continue;
    const v = val as Record<string, unknown>;
    const inV = (v.punch_in_time ?? v.in ?? null) as string | null;
    const outV = (v.punch_out_time ?? v.out ?? null) as string | null;
    result[date] = { in: inV, out: outV };
  }
  return result;
}

function MonthPicker({ ym, setYm }: { ym: string; setYm: (v: string) => void }) {
  const [y, m] = ym.split('-').map(Number);
  const shift = (delta: number) => {
    let nm = m + delta;
    let ny = y;
    if (nm < 1) { nm = 12; ny--; }
    if (nm > 12) { nm = 1; ny++; }
    setYm(`${ny}-${String(nm).padStart(2, '0')}`);
  };
  return (
    <div className="row gap-2">
      <button className="btn btn-ico" onClick={() => shift(-1)}>
        <Icon.ChevronLeft size={12} />
      </button>
      <div
        className="mono"
        style={{ fontSize: 14, fontWeight: 500, minWidth: 80, textAlign: 'center' }}
      >
        {y}年 {String(m).padStart(2, '0')}月
      </div>
      <button className="btn btn-ico" onClick={() => shift(1)}>
        <Icon.ChevronRight size={12} />
      </button>
    </div>
  );
}

interface RecordCellProps {
  d: Date | null;
  recs: Record<string, PunchRec>;
  isToday: boolean;
}

function RecordCell({ d, recs, isToday }: RecordCellProps) {
  if (!d) return <div className="cal-day empty" />;
  const ds = dateStr(d);
  const rec = recs[ds];
  const dow = (d.getDay() + 6) % 7;
  const weekend = dow >= 5;
  let cls = 'cal-day';
  if (rec?.in && rec?.out) cls += ' complete has-record';
  else if (rec?.in) cls += ' partial has-record';
  if (weekend) cls += ' weekend';
  if (isToday) cls += ' today';
  return (
    <div className={cls} title={ds}>
      <div className="row spread">
        <div className="cal-day-num">{d.getDate()}</div>
        {isToday && (
          <span className="pill pill-info" style={{ padding: '0 4px', fontSize: 9 }}>今日</span>
        )}
      </div>
      {rec ? (
        <div className="cal-times">
          {rec.in && (
            <div className="cal-time">
              <span className="arrow">→</span>{rec.in.slice(0, 5)}
            </div>
          )}
          {rec.out ? (
            <div className="cal-time">
              <span className="arrow">←</span>{rec.out.slice(0, 5)}
            </div>
          ) : (
            <div className="cal-time muted">未下班</div>
          )}
        </div>
      ) : weekend ? null : (
        <div className="cal-time muted" style={{ marginTop: 'auto' }}>无记录</div>
      )}
    </div>
  );
}

function Legend({ tone, label }: { tone: string; label: string }) {
  return (
    <span className="row gap-2" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: 3,
          background: `var(--${tone}-bg)`,
          border: `1px solid var(--${tone}-border)`,
        }}
      />
      {label}
    </span>
  );
}

export function RecordsScreen() {
  const { currentUser } = useApp();
  // 真实今天 / 真实当前月份（不再用 data.ts 写死的 mock TODAY）
  const todayStr = React.useMemo(() => dateStr(new Date()), []);
  const [ym, setYm] = React.useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const [view, setView] = React.useState<'calendar' | 'table'>('calendar');
  const [apiRecs, setApiRecs] = React.useState<Record<string, PunchRec> | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // 重试触发器：点「重试」自增，重新执行加载 effect（不改 currentUser/ym 也能重拉）
  const [reloadKey, setReloadKey] = React.useState(0);

  // 拉 API 数据 — cancelled 标志防 race
  React.useEffect(() => {
    const [year, month] = ym.split('-').map(Number);
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getRecords(currentUser, year, month)
      .then(r => {
        if (cancelled) return;
        setApiRecs(normalizeRecords(r.records));
      })
      .catch(e => {
        if (cancelled) return;
        // 失败不再退回 mock 假记录（会误导用户核对考勤）：清空数据并展示醒目错误条
        setApiRecs(null);
        setError(e instanceof ApiError ? `HTTP ${e.status} · ${e.message}` : (e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [currentUser, ym, reloadKey]);

  // 数据源：仅用真实 API 结果；失败/未加载时为空对象（不再 mock 兜底）
  const recs: Record<string, PunchRec> = apiRecs ?? {};
  const cells = React.useMemo(() => buildMonthGrid(ym), [ym]);

  // stats：基于真实 recs 计算；无数据时为空统计（依赖 apiRecs 避免 recs 每次新建引用导致重算）
  const stats = React.useMemo(() => {
    const entries = Object.values(apiRecs ?? {});
    const total = entries.length;
    const both = entries.filter(r => r.in && r.out).length;
    const inOnly = entries.filter(r => r.in && !r.out).length;
    const inTimes = entries.map(r => r.in).filter((x): x is string => Boolean(x));
    const outTimes = entries.map(r => r.out).filter((x): x is string => Boolean(x));
    const avg = (arr: string[]) => {
      if (!arr.length) return '—';
      const secs = arr.map(t => {
        const [h, m, s] = t.split(':').map(Number);
        return h * 3600 + m * 60 + (s || 0);
      });
      const a = Math.round(secs.reduce((x, y) => x + y, 0) / secs.length);
      return `${String(Math.floor(a / 3600)).padStart(2, '0')}:${String(Math.floor((a % 3600) / 60)).padStart(2, '0')}`;
    };
    return { total, both, inOnly, avgIn: avg(inTimes), avgOut: avg(outTimes) };
  }, [apiRecs]);

  return (
    <div className="col gap-6">
      <div className="row spread">
        <div className="row gap-2">
          <MonthPicker ym={ym} setYm={setYm} />
          <div className="tab-bar" style={{ marginLeft: 16 }}>
            <button
              className={`tab-btn ${view === 'calendar' ? 'active' : ''}`}
              onClick={() => setView('calendar')}
            >
              <Icon.Calendar size={11} style={{ verticalAlign: -1, marginRight: 4 }} />日历
            </button>
            <button
              className={`tab-btn ${view === 'table' ? 'active' : ''}`}
              onClick={() => setView('table')}
            >
              <Icon.Records size={11} style={{ verticalAlign: -1, marginRight: 4 }} />明细
            </button>
          </div>
        </div>
        <div className="row gap-2">
          <span className="pill pill-info"><span className="dot" />当前用户 {currentUser}</span>
          {loading ? (
            <span className="pill pill-info"><span className="dot" />加载中</span>
          ) : apiRecs ? (
            <span className="pill pill-success"><span className="dot" />API 已加载</span>
          ) : error ? (
            <span className="pill pill-danger" title={error}><span className="dot" />加载失败</span>
          ) : null}
          <button className="btn"><Icon.Download size={12} />导出 JSON</button>
        </div>
      </div>

      {/* 加载失败醒目错误条 + 重试：不再静默退回 mock 假记录，避免误导考勤核对 */}
      {!loading && !apiRecs && error && (
        <div
          className="row spread"
          style={{
            padding: '12px 16px',
            borderRadius: 'var(--radius-lg)',
            background: 'var(--danger-bg)',
            border: '1px solid var(--danger-border)',
            color: 'var(--danger)',
          }}
        >
          <div className="row gap-2" style={{ minWidth: 0 }}>
            <Icon.AlertTriangle size={16} />
            <div className="col" style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 500, fontSize: 13 }}>打卡记录加载失败</div>
              <div className="mono" style={{ fontSize: 11, opacity: 0.85, wordBreak: 'break-all' }}>
                {error} — 后端不可用，已暂停显示以免误判漏打卡
              </div>
            </div>
          </div>
          <button className="btn btn-danger" onClick={() => setReloadKey(k => k + 1)}>
            <Icon.Refresh size={12} />重试
          </button>
        </div>
      )}

      <div className="grid grid-4">
        <div className="kpi">
          <div className="kpi-label">已记录天数</div>
          <div className="kpi-value">{stats.total}</div>
          <div className="kpi-meta">含未完成</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">完整打卡</div>
          <div className="kpi-value">{stats.both}</div>
          <div className="kpi-meta">含上下班记录</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">仅上班</div>
          <div className="kpi-value">{stats.inOnly}</div>
          <div className="kpi-meta">{stats.inOnly > 0 ? '含今日未下班' : '—'}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">平均时间</div>
          <div className="kpi-value mono" style={{ fontSize: 14 }}>
            {stats.avgIn} · {stats.avgOut}
          </div>
          <div className="kpi-meta">上班 / 下班</div>
        </div>
      </div>

      {view === 'calendar' ? (
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">月历视图</div>
              <div className="card-sub">绿色 = 完整打卡 · 黄色 = 仅上班 · 灰色 = 无记录 / 周末</div>
            </div>
            <div className="row gap-2" style={{ fontSize: 11 }}>
              <Legend tone="success" label="完整" />
              <Legend tone="warning" label="未下班" />
              <Legend tone="neutral" label="无记录" />
            </div>
          </div>
          <div className="card-body">
            {!loading && !apiRecs && error ? (
              // 加载失败时不渲染整月「无记录」格子（会被误读为真实漏打卡），改为空态提示
              <div className="empty-state">打卡记录加载失败，无法显示月历 — 请用上方「重试」重新加载</div>
            ) : (
              <>
                <div className="cal-grid" style={{ marginBottom: 6 }}>
                  {['一', '二', '三', '四', '五', '六', '日'].map(d => (
                    <div key={d} className="cal-head">{d}</div>
                  ))}
                </div>
                <div className="cal-grid">
                  {cells.map((d, i) => (
                    <RecordCell
                      key={i}
                      d={d}
                      recs={recs}
                      isToday={Boolean(d) && dateStr(d) === todayStr}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">打卡明细</div>
              <div className="card-sub mono">
                punch_records/{currentUser}/{ym.replace('-', '_')}.json
              </div>
            </div>
            <button className="btn btn-sm" onClick={() => setReloadKey(k => k + 1)}>
              <Icon.Refresh size={11} />刷新
            </button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>日期</th>
                <th>星期</th>
                <th>上班</th>
                <th>下班</th>
                <th>时长</th>
                <th>来源</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(recs).length === 0 && (
                // 无真实记录时给明确空态，避免空表被误读为「本月零打卡」
                <tr>
                  <td colSpan={7} className="empty-state">
                    {loading
                      ? '加载中…'
                      : error
                        ? '打卡记录加载失败 — 请用上方「重试」重新加载'
                        : '本月暂无打卡记录'}
                  </td>
                </tr>
              )}
              {Object.entries(recs)
                .sort((a, b) => b[0].localeCompare(a[0]))
                .map(([date, r]) => {
                  const dt = new Date(date);
                  const dow = ['日', '一', '二', '三', '四', '五', '六'][dt.getDay()];
                  const dur = fmtDuration(r.in, r.out);
                  const complete = r.in && r.out;
                  return (
                    <tr key={date}>
                      <td className="mono">{date}</td>
                      <td className="muted">周{dow}</td>
                      <td className="mono">{r.in || <span className="muted">—</span>}</td>
                      <td className="mono">{r.out || <span className="muted">—</span>}</td>
                      <td className="mono">{dur}</td>
                      <td className="muted" style={{ fontSize: 11 }}>Selenium</td>
                      <td>
                        {complete ? (
                          <span className="pill pill-success"><span className="dot" />完整</span>
                        ) : (
                          <span className="pill pill-warning"><span className="dot" />未下班</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
