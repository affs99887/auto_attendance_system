// 打卡操作 — 设计稿 screens/punch.jsx 的 TS 平移，已接真实后端 API。
import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import { PUNCH_STEPS_IN, PUNCH_STEPS_OUT, RECORDS, USERS } from '../lib/data';
import { api, ApiError } from '../lib/api';
import { useSystemStore } from '../store/system';
import { usePunchStore } from '../store/punch';
import { wsClient } from '../lib/ws';

type StepState = 'pending' | 'active' | 'done' | 'error';

interface OpStepProps {
  state: StepState;
  title: string;
  meta?: string | null;
}

function OpStep({ state, title, meta }: OpStepProps) {
  return (
    <div className={`op-step ${state}`}>
      <div className="op-step-bullet">
        {state === 'done' && <Icon.Check size={9} strokeWidth={2.5} style={{ color: 'white' }} />}
        {state === 'active' && (
          <div
            className="spinner"
            style={{ borderTopColor: 'var(--accent)', width: 8, height: 8 }}
          />
        )}
        {state === 'error' && <Icon.X size={9} strokeWidth={2.5} style={{ color: 'white' }} />}
      </div>
      <div className="op-step-text">
        <div className="op-step-title">{title}</div>
        {meta && <div className="op-step-meta">{meta}</div>}
      </div>
    </div>
  );
}

type PunchKind = 'punch_in' | 'punch_out' | 'auto' | 'fetch';

// 真实进度映射：把后端 punch:progress 的「content」匹配到「已完成步骤数」(0..10)。
// 仅匹配 content，不含 title —— title 恒为「完整上班/下班流程」等，匹配会误判。
// 取所有命中里的最大值，配合 setProgress 的单调推进(只增不减)，后端卡住即停在当前步。
const STEP_RULES_IN: Array<[RegExp, number]> = [
  [/开始执行完整|步骤1|执行登录/, 1],
  [/frameset|登录frame|切换到.*frame/, 1],
  [/用户名|密码/, 2],
  [/登录按钮|点击登录/, 3],
  [/登录成功/, 4],
  [/步骤3|检查上班按钮|按钮状态/, 4],
  [/步骤4|执行上班打卡|点击上班|找到上班按钮/, 5],
  [/验证打卡结果|已变为不可用/, 6],
  [/上班打卡成功/, 7],
  [/步骤5|获取今日考勤|今日状态|状态解析/, 8],
  [/记录已保存/, 9],
  [/成功完成/, 10],
];
const STEP_RULES_OUT: Array<[RegExp, number]> = [
  [/开始执行完整|步骤1|执行登录/, 1],
  [/frameset|登录frame|切换到.*frame|用户名|密码|登录按钮/, 2],
  [/登录成功/, 3],
  [/步骤3|检查下班按钮|按钮状态/, 3],
  [/步骤4|执行下班打卡|点击下班|找到下班按钮/, 5],
  [/下班打卡成功|已变为不可用|验证打卡结果/, 6],
  [/步骤5|检查mainFrame变化|Frame变化检测|时间警告|工作时间|时间解析|剩余|未到下班时间|返回/, 6],
  [/步骤8|获取今日考勤|今日状态|状态解析/, 7],
  [/记录已保存/, 8],
  [/调度.*重试|按剩余时间|重试/, 9],
  [/成功完成/, 10],
];

function mapContentToStep(kind: 'punch_in' | 'punch_out', content: string): number {
  const rules = kind === 'punch_in' ? STEP_RULES_IN : STEP_RULES_OUT;
  let best = -1;
  for (const [re, idx] of rules) {
    if (idx > best && re.test(content)) best = idx;
  }
  return best;
}

interface PunchFlowCardProps {
  userId: string;
  type: 'punch_in' | 'punch_out';
  running: boolean;
  stepIdx: number;
  error: string | null;
  color: string;
  short: string;
}

function PunchFlowCard({ userId, type, running, stepIdx, error, color, short }: PunchFlowCardProps) {
  const steps = type === 'punch_in' ? PUNCH_STEPS_IN : PUNCH_STEPS_OUT;
  const totalSecs = steps.length;
  return (
    <div className="card">
      <div className="card-header">
        <div className="row gap-2">
          <div
            className="user-avatar"
            style={{ background: color, width: 24, height: 24, fontSize: 11 }}
          >
            {short}
          </div>
          <div className="card-title">{userId}</div>
          <span
            className={`pill ${
              running
                ? 'pill-info'
                : error
                ? 'pill-danger'
                : stepIdx >= totalSecs
                ? 'pill-success'
                : 'pill-neutral'
            }`}
          >
            <span className="dot" />
            {running ? '进行中' : error ? '失败' : stepIdx >= totalSecs ? '成功' : '待执行'}
          </span>
        </div>
        <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {Math.min(stepIdx, totalSecs)} / {totalSecs}
        </div>
      </div>
      <div className="card-body">
        {steps.map((s, i) => {
          let st: StepState = 'pending';
          if (error && i === stepIdx) st = 'error';
          else if (i < stepIdx) st = 'done';
          else if (i === stepIdx && running) st = 'active';
          return <OpStep key={i} state={st} title={s} meta={st === 'done' ? 'OK' : null} />;
        })}
      </div>
    </div>
  );
}

interface PunchControlsProps {
  kind: 'punch_in' | 'punch_out';
  onStart: () => void;
  running: boolean;
  onStop: () => void;
}

function PunchControls({ kind, onStart, running, onStop }: PunchControlsProps) {
  const isIn = kind === 'punch_in';
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">{isIn ? '上班打卡' : '下班打卡'}</div>
          <div className="card-sub">
            {isIn
              ? '并行登录所有已配置用户，最大并发 3'
              : '校验工时 8h15m，未满则按剩余时间调度重试'}
          </div>
        </div>
      </div>
      <div className="card-body">
        <div className="row gap-2">
          <button className="btn btn-primary btn-lg" onClick={onStart} disabled={running}>
            <Icon.Play size={12} />
            {running ? '执行中…' : isIn ? '立即上班打卡' : '立即下班打卡'}
          </button>
          <button className="btn btn-danger" onClick={onStop} disabled={!running}>
            <Icon.Stop size={12} />
            终止 (/stop)
          </button>
          <div
            style={{
              marginLeft: 'auto',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              fontSize: 11,
              color: 'var(--text-muted)',
            }}
          >
            <Icon.Bot size={12} />
            等同 Telegram <span className="mono">/{kind}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

interface CalcResult {
  punch_in_time: string | null;
  punch_out_time: string | null;
  message: string;
  scheduled: boolean;
  error: string | null;
  fallbackUsed: boolean;
}

function AutoByeByePanel() {
  const refreshStatus = useSystemStore(s => s.refresh);
  const [calc, setCalc] = React.useState<Record<string, CalcResult>>({});
  const [busy, setBusy] = React.useState<string | null>(null);
  const snapshot = useSystemStore(s => s.snapshot);

  const handleCalc = async (username: string) => {
    setBusy(username);
    try {
      const r = await api.autoByebyeCalc(username);
      setCalc(prev => ({
        ...prev,
        [username]: {
          punch_in_time: r.punch_in_time ?? null,
          punch_out_time: r.punch_out_time ?? null,
          message: r.message ?? '',
          scheduled: false,
          error: r.success ? null : (r.message ?? '计算失败'),
          fallbackUsed: r.fallback_used ?? false,
        },
      }));
      // 计算时若内存无记录会触发登录识别并回写今日上班时间，刷新让卡片「今日上班」同步显示
      if (r.success) void refreshStatus();
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}` : (e as Error).message;
      setCalc(prev => ({
        ...prev,
        [username]: {
          punch_in_time: null,
          punch_out_time: null,
          message: '',
          scheduled: false,
          error: msg,
          fallbackUsed: false,
        },
      }));
    } finally {
      setBusy(null);
    }
  };

  const handleConfirm = async (username: string) => {
    const cur = calc[username];
    if (!cur?.punch_out_time) return;
    const [h, m] = cur.punch_out_time.split(':').map(Number);
    setBusy(username);
    try {
      const r = await api.autoByebyeConfirm(h, m);
      setCalc(prev => ({
        ...prev,
        [username]: { ...prev[username], scheduled: r.success, error: r.success ? null : (r.error ?? '调度失败') },
      }));
      if (r.success) void refreshStatus();
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}` : (e as Error).message;
      setCalc(prev => ({ ...prev, [username]: { ...prev[username], error: msg } }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid grid-2">
      {USERS.map(u => {
        // 优先用真实 snapshot；mock 兜底
        const apiRec = snapshot?.today_records?.[u.id];
        const fallback = RECORDS[u.id]?.['2026-05']?.['2026-05-19'] ?? { in: null, out: null };
        const inRaw = apiRec?.punch_in_time ?? fallback.in ?? null;
        const inDisplay = inRaw && inRaw.includes('T') ? inRaw.split('T')[1].slice(0, 8) : (inRaw ?? '—');
        const c = calc[u.id];
        const isBusy = busy === u.id;
        return (
          <div className="card" key={u.id}>
            <div className="card-header">
              <div className="row gap-2">
                <div
                  className="user-avatar"
                  style={{ background: u.color, width: 24, height: 24, fontSize: 11 }}
                >
                  {u.short}
                </div>
                <div className="card-title">{u.name}</div>
              </div>
              {c?.scheduled ? (
                <span className="pill pill-success"><span className="dot" />已调度</span>
              ) : c?.punch_out_time ? (
                <span className="pill pill-info"><span className="dot" />待确认</span>
              ) : (
                <span className="pill pill-neutral"><span className="dot" />未计算</span>
              )}
            </div>
            <div className="card-body">
              <div className="grid grid-3" style={{ gap: 12 }}>
                <div>
                  <div className="kicker">今日上班</div>
                  <div className="mono" style={{ fontSize: 16 }}>{inDisplay}</div>
                </div>
                <div>
                  <div className="kicker">+ 8h15m + 随机</div>
                  <div className="mono" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                    {c?.message ? '已计算' : '待计算'}
                  </div>
                </div>
                <div>
                  <div className="kicker">预计下班</div>
                  <div className="mono" style={{ fontSize: 16, color: 'var(--accent)' }}>
                    {c?.punch_out_time ?? '—'}
                  </div>
                </div>
              </div>
              {c?.error && (
                <div
                  style={{
                    marginTop: 8,
                    padding: '6px 10px',
                    background: 'var(--danger-bg)',
                    border: '1px solid var(--danger-border)',
                    borderRadius: 'var(--radius)',
                    fontSize: 11,
                    color: 'var(--danger)',
                  }}
                >
                  {c.error}
                </div>
              )}
              {c?.fallbackUsed && c?.punch_out_time && (
                <div
                  style={{
                    marginTop: 8,
                    padding: '6px 10px',
                    background: 'var(--warning-bg)',
                    border: '1px solid var(--warning-border)',
                    borderRadius: 'var(--radius)',
                    fontSize: 11,
                    color: 'var(--warning)',
                  }}
                >
                  今日无上班记录，已按配置上班时间 {c.punch_in_time ?? '—'} 兜底推算下班时间
                </div>
              )}
              <div className="divider" />
              <div className="row gap-2">
                {!c?.punch_out_time ? (
                  <button className="btn btn-primary" disabled={isBusy} onClick={() => handleCalc(u.id)}>
                    <Icon.Clock size={12} />{isBusy ? '计算中…' : '计算下班时间'}
                  </button>
                ) : (
                  <>
                    <button
                      className="btn btn-primary"
                      disabled={isBusy || c.scheduled}
                      onClick={() => handleConfirm(u.id)}
                    >
                      <Icon.Check size={12} />
                      {c.scheduled ? '已调度' : isBusy ? '调度中…' : '确认调度'}
                    </button>
                    <button
                      className="btn"
                      disabled={isBusy}
                      onClick={() => setCalc(prev => ({ ...prev, [u.id]: { ...prev[u.id], punch_out_time: null, scheduled: false, error: null } }))}
                    >
                      <Icon.X size={12} />重算
                    </button>
                  </>
                )}
                <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
                  到点自动执行 · 失败按剩余工时调度一次重试
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function FetchStatusPanel() {
  const refreshStatus = useSystemStore(s => s.refresh);
  const [busy, setBusy] = React.useState(false);
  const [results, setResults] = React.useState<
    Record<string, { success: boolean; punch_in_time: string | null; punch_out_time: string | null; message: string }> | null
  >(null);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErrorMsg(null);
    try {
      const r = await api.fetchPunchStatus();
      if (!r.success) {
        setErrorMsg(r.error ?? '获取失败');
        setResults(null);
        return;
      }
      setResults(r.results ?? {});
      void refreshStatus(); // 回写记录后同步概览/自动下班
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      setErrorMsg(msg);
    } finally {
      setBusy(false);
    }
  };

  const okCount = results ? Object.values(results).filter(v => v.success).length : 0;

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">登录系统获取今日打卡情况</div>
          <div className="card-sub">
            {results
              ? `已读取 ${Object.keys(results).length} 个用户，${okCount} 成功`
              : '登录考勤系统，从页面读取所有用户今日上/下班时间（不触发打卡，结果回写今日记录）'}
          </div>
        </div>
        <button className="btn btn-primary" onClick={run} disabled={busy}>
          {busy ? <div className="spinner" /> : <Icon.Clock size={12} />}
          {busy ? '读取中（最多 3 分钟）' : '登录并读取'}
        </button>
      </div>
      <div className="card-body">
        {errorMsg && (
          <div
            style={{
              marginBottom: 12,
              padding: '8px 12px',
              background: 'var(--danger-bg)',
              border: '1px solid var(--danger-border)',
              borderRadius: 'var(--radius)',
              fontSize: 12,
              color: 'var(--danger)',
            }}
          >
            {errorMsg}
          </div>
        )}
        <table className="table">
          <thead>
            <tr>
              <th>用户</th>
              <th>结果</th>
              <th>今日上班</th>
              <th>今日下班</th>
              <th>消息</th>
            </tr>
          </thead>
          <tbody>
            {USERS.map(u => {
              const r = results?.[u.id];
              return (
                <tr key={u.id}>
                  <td>
                    <div className="row gap-2">
                      <div
                        className="user-avatar"
                        style={{ background: u.color, width: 18, height: 18, fontSize: 9 }}
                      >
                        {u.short}
                      </div>
                      {u.name}
                    </div>
                  </td>
                  <td>
                    {busy ? (
                      <span className="pill pill-info"><span className="dot" />读取中</span>
                    ) : r ? (
                      r.success ? (
                        <span className="pill pill-success"><span className="dot" />成功</span>
                      ) : (
                        <span className="pill pill-danger"><span className="dot" />失败</span>
                      )
                    ) : (
                      <span className="pill pill-neutral"><span className="dot" />未读取</span>
                    )}
                  </td>
                  <td className="mono" style={{ fontSize: 13 }}>{r?.punch_in_time ?? '—'}</td>
                  <td className="mono" style={{ fontSize: 13 }}>{r?.punch_out_time ?? '—'}</td>
                  <td className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                    {r?.message ?? '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface UserProgress {
  idx: number;
  error: string | null;
  done?: boolean;
}

export function PunchScreen() {
  const { setOpState } = useApp();
  const [kind, setKind] = React.useState<PunchKind>('punch_in');
  const [localRunning, setLocalRunning] = React.useState(false);
  const [toast, setToast] = React.useState<string | null>(null);
  const [progress, setProgress] = React.useState<Record<string, UserProgress>>({});
  const timersRef = React.useRef<number[]>([]);

  // 真实运行状态来源：后端 snapshot.current_operation；本地态用于"已启动但 snapshot 还没刷"的过渡
  const currentOp = useSystemStore(s => s.snapshot?.current_operation ?? null);
  const snapshot = useSystemStore(s => s.snapshot);
  const refreshStatus = useSystemStore(s => s.refresh);
  const clearProgress = usePunchStore(s => s.clear);
  const running = localRunning || currentOp !== null;
  const prevOpRef = React.useRef<typeof currentOp>(null);

  React.useEffect(() => () => {
    timersRef.current.forEach(t => clearTimeout(t));
  }, []);

  // 真实进度：订阅 WS punch:progress，按「用户名」把后端每步通知映射到步骤并单调推进。
  // 后端卡住 → 收不到新事件 → 步骤停在当前位置，不再有假定时器自顾自往下流转。
  React.useEffect(() => {
    if (kind !== 'punch_in' && kind !== 'punch_out') return;
    const steps = kind === 'punch_in' ? PUNCH_STEPS_IN : PUNCH_STEPS_OUT;
    const unsub = wsClient.subscribe('punch:progress', data => {
      const d = data as { user?: string; content?: string; done?: boolean; success?: boolean };
      const uid = d?.user;
      if (!uid || !USERS.some(u => u.id === uid)) return; // 仅处理带用户名的事件
      if (d.done) {
        // 终态事件：权威定稿该用户成功/失败（已打卡 already_punched 也算成功）
        setProgress(p => {
          const cur = p[uid] ?? { idx: 0, error: null };
          return {
            ...p,
            [uid]: d.success
              ? { idx: steps.length, error: null, done: true }
              : { idx: cur.idx, error: '打卡失败', done: true },
          };
        });
        return;
      }
      const mapped = mapContentToStep(kind, String(d.content ?? ''));
      if (mapped < 0) return;
      setProgress(p => {
        const cur = p[uid] ?? { idx: 0, error: null };
        if (cur.done || mapped <= cur.idx) return p; // 已定稿或不前进则忽略（单调）
        return { ...p, [uid]: { idx: mapped, error: cur.error, done: cur.done } };
      });
    });
    return unsub;
  }, [kind]);

  // 后端 current_operation 由有值变 null（操作真正结束）→ 按「今日真实记录」定稿每用户结果：
  // 有打卡时间 = 成功(填满)；无 = 失败(停在最后真实步并标错)。不再无条件假装全部完成。
  React.useEffect(() => {
    const was = prevOpRef.current;
    prevOpRef.current = currentOp;
    if (was !== null && currentOp === null && localRunning) {
      timersRef.current.forEach(t => clearTimeout(t));
      timersRef.current = [];
      const steps = kind === 'punch_in' ? PUNCH_STEPS_IN : PUNCH_STEPS_OUT;
      const recs = snapshot?.today_records ?? {};
      setProgress(prev => {
        const final: Record<string, UserProgress> = {};
        USERS.forEach(u => {
          const cur = prev[u.id] ?? { idx: 0, error: null };
          if (cur.done) { final[u.id] = cur; return; } // 已被终态事件定稿，保留
          // 兜底：未收到终态事件时按今日真实记录判定
          const rec = recs[u.id];
          const t = kind === 'punch_in' ? rec?.punch_in_time : rec?.punch_out_time;
          final[u.id] = t
            ? { idx: steps.length, error: null, done: true }
            : { idx: cur.idx, error: '未获取到打卡时间，可能失败', done: true };
        });
        return final;
      });
      setLocalRunning(false);
      setOpState({ running: false, type: null, perUser: {} });
    }
  }, [currentOp, localRunning, kind, snapshot, setOpState]);

  const showToast = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 4000);
  };

  const startFlow = async () => {
    if (running) return;
    if (kind !== 'punch_in' && kind !== 'punch_out') return;
    setLocalRunning(true);
    clearProgress();
    // 步骤归零：真实进度由 WS punch:progress 按用户推进，不再启动假定时器
    const initial: Record<string, UserProgress> = {};
    USERS.forEach(u => { initial[u.id] = { idx: 0, error: null }; });
    setProgress(initial);
    setOpState({ running: true, type: kind, perUser: {} });
    try {
      const resp = kind === 'punch_in' ? await api.punchIn() : await api.punchOut();
      if (!resp.success) {
        showToast(`后端拒绝: ${resp.message}`);
        setLocalRunning(false);
        setOpState({ running: false, type: null, perUser: {} });
        return;
      }
      showToast(`${kind === 'punch_in' ? '上班' : '下班'}打卡已启动 — 进度推送中`);
      // 立即刷新一次 snapshot，让 current_operation 出现
      void refreshStatus();
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}` : (e as Error).message;
      showToast(`触发失败: ${msg}`);
      setLocalRunning(false);
      setOpState({ running: false, type: null, perUser: {} });
    }
  };

  const stopFlow = async () => {
    // 不假装已停 —— 真正"已停"由 currentOp===null 的定稿 effect 统一收尾（按今日记录判定成功/失败），
    // 避免"前端显示停了、后端还在跑"的不一致。清掉可能在跑的刷新补丁定时器。
    timersRef.current.forEach(t => clearTimeout(t));
    timersRef.current = [];
    try {
      const resp = await api.operationStop();
      showToast(resp.success ? '停止信号已确认，正在收尾…' : `停止失败: ${resp.message}`);
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}` : (e as Error).message;
      showToast(`停止异常: ${msg}`);
    }
    // 短间隔补刷 snapshot，待后端 current_operation 归 null 后由 effect 收尾 UI
    void refreshStatus();
    [400, 900, 1500, 2500].forEach(ms => {
      const t = window.setTimeout(() => void refreshStatus(), ms);
      timersRef.current.push(t);
    });
  };

  return (
    <div className="col gap-6">
      <div className="row gap-2">
        <div className="tab-bar">
          {([
            { id: 'punch_in', l: '上班打卡' },
            { id: 'punch_out', l: '下班打卡' },
            { id: 'auto', l: '自动下班' },
            { id: 'fetch', l: '获取打卡情况' },
          ] as const).map(t => (
            <button
              key={t.id}
              className={`tab-btn ${kind === t.id ? 'active' : ''}`}
              onClick={() => !running && setKind(t.id)}
            >
              {t.l}
            </button>
          ))}
        </div>
        <div
          style={{
            marginLeft: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          <span className={`pill ${running ? 'pill-info' : 'pill-neutral'}`}>
            <span className="dot" />
            当前操作: {currentOp ? `${currentOp === 'punch_in' ? '上班' : '下班'}打卡中` : (localRunning ? '启动中…' : '空闲')}
          </span>
        </div>
      </div>

      {toast && (
        <div
          style={{
            position: 'fixed',
            top: 80,
            right: 24,
            zIndex: 200,
            background: 'var(--bg-card)',
            border: '1px solid var(--accent-border)',
            borderLeft: '3px solid var(--accent)',
            borderRadius: 'var(--radius)',
            padding: '10px 16px',
            boxShadow: 'var(--shadow-lg)',
            fontSize: 13,
            color: 'var(--text-primary)',
            maxWidth: 360,
          }}
        >
          {toast}
        </div>
      )}

      {(kind === 'punch_in' || kind === 'punch_out') && (
        <>
          <PunchControls kind={kind} onStart={startFlow} running={running} onStop={stopFlow} />
          <div className="grid grid-2">
            {USERS.map(u => (
              <PunchFlowCard
                key={u.id}
                userId={u.id}
                type={kind}
                running={running}
                stepIdx={progress[u.id]?.idx ?? 0}
                error={progress[u.id]?.error ?? null}
                color={u.color}
                short={u.short}
              />
            ))}
          </div>
        </>
      )}

      {kind === 'auto' && <AutoByeByePanel />}

      {kind === 'fetch' && <FetchStatusPanel />}
    </div>
  );
}
