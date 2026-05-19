/* global React */
// 打卡操作 — manual & auto byebye console

const { useState: useStP, useEffect: useEfP, useRef: useRefP } = React;
const punchApp = window.AAS_useApp;
const punchIcon = window.AAS_ICON;
const punchData = window.AAS_DATA;

function OpStep({ state, title, meta }) {
  return (
    <div className={`op-step ${state}`}>
      <div className="op-step-bullet">
        {state === "done" && <punchIcon.Check size={9} stroke={2.5} style={{ color: "white" }} />}
        {state === "active" && <div className="spinner" style={{ borderTopColor: "var(--accent)", width: 8, height: 8 }} />}
        {state === "error" && <punchIcon.X size={9} stroke={2.5} style={{ color: "white" }} />}
      </div>
      <div className="op-step-text">
        <div className="op-step-title">{title}</div>
        {meta && <div className="op-step-meta">{meta}</div>}
      </div>
    </div>
  );
}

function PunchFlowCard({ userId, type, running, stepIdx, error, color, short }) {
  const steps = type === "punch_in" ? punchData.PUNCH_STEPS_IN : punchData.PUNCH_STEPS_OUT;
  const totalSecs = steps.length;
  return (
    <div className="card">
      <div className="card-header">
        <div className="row gap-2">
          <div className="user-avatar" style={{ background: color, width: 24, height: 24, fontSize: 11 }}>{short}</div>
          <div className="card-title">{userId}</div>
          <span className={`pill ${running ? "pill-info" : (error ? "pill-danger" : stepIdx >= totalSecs ? "pill-success" : "pill-neutral")}`}>
            <span className="dot" />
            {running ? "进行中" : error ? "失败" : stepIdx >= totalSecs ? "成功" : "待执行"}
          </span>
        </div>
        <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {Math.min(stepIdx, totalSecs)} / {totalSecs}
        </div>
      </div>
      <div className="card-body">
        {steps.map((s, i) => {
          let st = "pending";
          if (error && i === stepIdx) st = "error";
          else if (i < stepIdx) st = "done";
          else if (i === stepIdx && running) st = "active";
          return <OpStep key={i} state={st} title={s} meta={st === "done" ? "OK" : null} />;
        })}
      </div>
    </div>
  );
}

function PunchControls({ kind, onStart, running, onStop }) {
  const isIn = kind === "punch_in";
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">{isIn ? "上班打卡" : "下班打卡"}</div>
          <div className="card-sub">{isIn ? "并行登录所有已配置用户，最大并发 3" : "校验工时 8h15m，未满则按剩余时间调度重试"}</div>
        </div>
      </div>
      <div className="card-body">
        <div className="row gap-2">
          <button className="btn btn-primary btn-lg" onClick={onStart} disabled={running}>
            <punchIcon.Play size={12} />
            {running ? "执行中…" : (isIn ? "立即上班打卡" : "立即下班打卡")}
          </button>
          <button className="btn btn-danger" onClick={onStop} disabled={!running}>
            <punchIcon.Stop size={12} />
            终止 (/stop)
          </button>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "var(--text-muted)" }}>
            <punchIcon.Bot size={12} />
            等同 Telegram <span className="mono">/{kind}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function PunchScreen() {
  const { setOpState } = punchApp();
  const [kind, setKind] = useStP("punch_in");
  const [running, setRunning] = useStP(false);
  const [progress, setProgress] = useStP({}); // {userId: {idx, error}}
  const timersRef = useRefP([]);

  useEfP(() => () => timersRef.current.forEach(clearTimeout), []);

  const startFlow = () => {
    if (running) return;
    setRunning(true);
    setOpState({ running: true, type: kind, perUser: {} });
    const totalSteps = (kind === "punch_in" ? punchData.PUNCH_STEPS_IN : punchData.PUNCH_STEPS_OUT).length;
    const initial = {};
    punchData.USERS.forEach(u => initial[u.id] = { idx: 0, error: null });
    setProgress(initial);

    timersRef.current = [];
    punchData.USERS.forEach((u, ui) => {
      const offset = ui * 200; // slight stagger
      for (let i = 1; i <= totalSteps; i++) {
        const t = setTimeout(() => {
          setProgress(p => ({ ...p, [u.id]: { ...p[u.id], idx: i } }));
          if (i === totalSteps && ui === punchData.USERS.length - 1) {
            setRunning(false);
            setOpState({ running: false, type: null, perUser: {} });
          }
        }, offset + i * 450);
        timersRef.current.push(t);
      }
    });
  };

  const stopFlow = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
    setRunning(false);
    setOpState({ running: false, type: null, perUser: {} });
  };

  return (
    <div className="col gap-6">
      <div className="row gap-2">
        <div className="tab-bar">
          {[
            { id: "punch_in",  l: "上班打卡" },
            { id: "punch_out", l: "下班打卡" },
            { id: "auto",      l: "自动下班" },
            { id: "parallel",  l: "并行登录测试" },
          ].map(t => (
            <button key={t.id} className={`tab-btn ${kind === t.id ? "active" : ""}`} onClick={() => !running && setKind(t.id)}>
              {t.l}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-muted)" }}>
          <span className="pill pill-neutral"><span className="dot" />当前操作: {running ? "执行中" : "空闲"}</span>
        </div>
      </div>

      {(kind === "punch_in" || kind === "punch_out") && (
        <>
          <PunchControls kind={kind} onStart={startFlow} running={running} onStop={stopFlow} />
          <div className="grid grid-2">
            {punchData.USERS.map(u => (
              <PunchFlowCard
                key={u.id}
                userId={u.id}
                type={kind}
                running={running}
                stepIdx={progress[u.id]?.idx ?? 0}
                error={progress[u.id]?.error}
                color={u.color}
                short={u.short}
              />
            ))}
          </div>
        </>
      )}

      {kind === "auto" && <AutoByeByePanel onSchedule={startFlow} />}

      {kind === "parallel" && <ParallelTestPanel />}
    </div>
  );
}

function AutoByeByePanel({ onSchedule }) {
  return (
    <div className="grid grid-2">
      {punchData.USERS.map(u => {
        const today = punchData.RECORDS[u.id]?.["2026-05"]?.["2026-05-19"] || {};
        const punchIn = today.in || "—";
        let estOut = "—";
        let delay = "—";
        if (today.in) {
          const [h, m, s] = today.in.split(":").map(Number);
          const offsetSec = 8 * 3600 + 15 * 60 + (60 + Math.floor(Math.random() * 120));
          let total = h * 3600 + m * 60 + (s || 0) + offsetSec;
          estOut = `${String(Math.floor(total / 3600)).padStart(2, "0")}:${String(Math.floor((total % 3600) / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
          delay = `+${Math.floor((offsetSec - 8 * 3600 - 15 * 60) / 60)}m${(offsetSec - 8 * 3600 - 15 * 60) % 60}s 随机`;
        }
        return (
          <div className="card" key={u.id}>
            <div className="card-header">
              <div className="row gap-2">
                <div className="user-avatar" style={{ background: u.color, width: 24, height: 24, fontSize: 11 }}>{u.short}</div>
                <div className="card-title">{u.name}</div>
              </div>
              <span className="pill pill-info"><span className="dot" />已调度</span>
            </div>
            <div className="card-body">
              <div className="grid grid-3" style={{ gap: 12 }}>
                <div>
                  <div className="kicker">今日上班</div>
                  <div className="mono" style={{ fontSize: 16 }}>{punchIn}</div>
                </div>
                <div>
                  <div className="kicker">+ 8h15m</div>
                  <div className="mono" style={{ fontSize: 16, color: "var(--text-secondary)" }}>{delay}</div>
                </div>
                <div>
                  <div className="kicker">预计下班</div>
                  <div className="mono" style={{ fontSize: 16, color: "var(--accent)" }}>{estOut}</div>
                </div>
              </div>
              <div className="divider"></div>
              <div className="row gap-2">
                <button className="btn btn-primary" onClick={onSchedule}><punchIcon.Check size={12} />确认调度</button>
                <button className="btn"><punchIcon.X size={12} />取消</button>
                <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>
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

function ParallelTestPanel() {
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">并行登录测试</div>
          <div className="card-sub">仅验证多用户能否并发登录，不会触发打卡按钮</div>
        </div>
        <button className="btn btn-primary"><punchIcon.Zap size={12} />运行测试</button>
      </div>
      <div className="card-body">
        <table className="table">
          <thead>
            <tr>
              <th>用户</th>
              <th>WebDriver</th>
              <th>登录</th>
              <th>页面就绪</th>
              <th>耗时</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            {punchData.USERS.map(u => (
              <tr key={u.id}>
                <td>
                  <div className="row gap-2">
                    <div className="user-avatar" style={{ background: u.color, width: 18, height: 18, fontSize: 9 }}>{u.short}</div>
                    {u.name}
                  </div>
                </td>
                <td><span className="pill pill-success"><span className="dot" />msedgedriver</span></td>
                <td className="mono">200 OK</td>
                <td className="mono">2.1s</td>
                <td className="mono">{(3 + Math.random() * 2).toFixed(1)}s</td>
                <td><span className="pill pill-success"><span className="dot" />success</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

window.AAS_SCREENS = window.AAS_SCREENS || {};
window.AAS_SCREENS.punch = PunchScreen;
