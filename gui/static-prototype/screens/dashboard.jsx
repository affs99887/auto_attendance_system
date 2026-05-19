/* global React */
// 概览 / Dashboard

const { useMemo: useMemoDash } = React;
const dashApp = window.AAS_useApp;
const dashIcon = window.AAS_ICON;
const dashData = window.AAS_DATA;

function StatusDot({ tone = "success" }) {
  return <span className="dot" style={{
    width: 8, height: 8, borderRadius: "50%",
    background: `var(--${tone})`,
    boxShadow: `0 0 0 3px var(--${tone}-bg)`,
  }} />;
}

function Sparkline({ values, max }) {
  const m = max ?? Math.max(...values, 1);
  return (
    <div className="spark">
      {values.map((v, i) => (
        <div key={i} className="spark-bar" style={{ height: `${(v / m) * 100}%` }} />
      ))}
    </div>
  );
}

function PunchUserCard({ user }) {
  const { setScreen, setCurrentUser } = dashApp();
  const today = dashData.RECORDS[user.id]?.["2026-05"]?.[dashData.TODAY] || {};
  const punchedIn = !!today.in;
  const punchedOut = !!today.out;
  const estOut = punchedIn ? estimateOut(today.in) : null;

  return (
    <div className="card">
      <div className="card-header">
        <div className="row gap-2">
          <div className="user-avatar" style={{ background: user.color, width: 28, height: 28, fontSize: 12 }}>
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
            <div className="mono" style={{ fontSize: 22, fontWeight: 500, color: today.out ? undefined : "var(--text-muted)" }}>
              {today.out || (estOut ? estOut : "--:--:--")}
            </div>
            <div className="muted" style={{ fontSize: 11 }}>
              {today.out ? "已写入" : (estOut ? `预计 · 8h15m + 随机` : "—")}
            </div>
          </div>
        </div>
        <div className="divider"></div>
        <div className="row gap-2">
          <button className="btn btn-primary" disabled={punchedIn}>
            <dashIcon.Punch size={12} /> 上班打卡
          </button>
          <button className="btn" disabled={!punchedIn || punchedOut}>
            <dashIcon.Power size={12} /> 下班打卡
          </button>
          <button className="btn btn-sm" style={{ marginLeft: "auto" }} onClick={() => { setCurrentUser(user.id); setScreen("records"); }}>
            查看记录 <dashIcon.ChevronRight size={10} />
          </button>
        </div>
      </div>
    </div>
  );
}

function estimateOut(inT) {
  if (!inT) return null;
  const [h, m, s] = inT.split(":").map(Number);
  let total = h * 3600 + m * 60 + (s || 0) + 8 * 3600 + 15 * 60 + 120;
  const oh = Math.floor(total / 3600), om = Math.floor((total % 3600) / 60);
  return `${String(oh).padStart(2, "0")}:${String(om).padStart(2, "0")}`;
}

function ActivityRow({ entry }) {
  const tone = entry.status === "ok" ? "success" : entry.status === "warn" ? "warning" : "danger";
  const typeLabel = ({
    punch_in: "上班打卡",
    punch_out: "下班打卡",
    daily_status: "状态推送",
    reminder: "每日提醒",
    log_rotate: "日志轮转",
    error: "异常",
  })[entry.type] || entry.type;
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "84px 1fr auto",
      gap: 12,
      padding: "10px 0",
      borderBottom: "1px solid var(--border-soft)",
      alignItems: "center",
    }}>
      <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>{entry.ts}</div>
      <div style={{ fontSize: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <StatusDot tone={tone} />
          <span style={{ fontWeight: 500 }}>{typeLabel}</span>
          {entry.user !== "system" && <span className="muted">· {entry.user}</span>}
        </div>
        <div className="muted" style={{ fontSize: 11, marginTop: 2, paddingLeft: 14 }}>{entry.detail}</div>
      </div>
      <div className="mono" style={{ fontSize: 10, color: "var(--text-muted)" }}>{entry.method}</div>
    </div>
  );
}

function DashboardScreen() {
  const { sysStatus, seleniumOn, headless, setScreen } = dashApp();
  const monthRecs = dashData.RECORDS["邓蕴哲"]["2026-05"];
  const onTimeCount = Object.values(monthRecs).filter(r => r.in && r.in <= "09:00:00").length;
  const totalInThisMonth = Object.values(monthRecs).filter(r => r.in).length;

  const minutesArr = Object.values(monthRecs).filter(r => r.in).map(r => {
    const [h, m] = r.in.split(":").map(Number);
    return h * 60 + m;
  });
  const earliest = Math.min(...minutesArr);
  const latest = Math.max(...minutesArr);

  // Past 14 punch-in times for sparkline (deviation from 8:30)
  const spark = Object.entries(monthRecs).slice(-14).map(([_, r]) => {
    if (!r.in) return 0;
    const [h, m] = r.in.split(":").map(Number);
    return (h * 60 + m) - 8 * 60; // minutes after 8:00
  });

  return (
    <div className="col gap-6">
      {/* KPI row */}
      <div className="grid grid-4">
        <div className="kpi">
          <div className="kpi-label">今日状态</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: "inherit", fontWeight: 600 }}>工作中</div>
          <div className="kpi-meta">
            <StatusDot tone="success" />
            邓蕴哲 · 08:29:47 上班
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">下次任务</div>
          <div className="kpi-value">16:44</div>
          <div className="kpi-meta">
            <dashIcon.Clock size={12} />
            自动下班 · 邓蕴哲 · 还有 8h14m
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">本月出勤</div>
          <div className="kpi-value">{totalInThisMonth} <span style={{fontSize:14,color:"var(--text-muted)"}}>/ 工作日</span></div>
          <div className="kpi-meta">
            <StatusDot tone="success" />
            准点率 {Math.round(onTimeCount / totalInThisMonth * 100)}%
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">系统</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: "inherit", fontWeight: 600 }}>运行正常</div>
          <div className="kpi-meta">
            <StatusDot tone="success" />
            {sysStatus.modeLabel}
          </div>
        </div>
      </div>

      {/* Per-user punch cards */}
      <div className="col gap-2">
        <div className="row spread">
          <div className="kicker">今日打卡 · {dashData.TODAY} 周二</div>
          <button className="btn btn-sm" onClick={() => setScreen("punch")}>
            打开打卡控制台 <dashIcon.ChevronRight size={10} />
          </button>
        </div>
        <div className="grid grid-2">
          {dashData.USERS.map(u => <PunchUserCard key={u.id} user={u} />)}
        </div>
      </div>

      {/* Bottom: Activity + System health */}
      <div className="grid" style={{ gridTemplateColumns: "1.5fr 1fr", gap: 16 }}>
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">最近活动</div>
              <div className="card-sub">系统、调度与打卡事件流</div>
            </div>
            <button className="btn btn-sm" onClick={() => setScreen("logs")}>
              查看全部日志 <dashIcon.ChevronRight size={10} />
            </button>
          </div>
          <div className="card-body" style={{ padding: "4px 16px" }}>
            {dashData.RECENT_ACTIVITY.map((e, i) => <ActivityRow key={i} entry={e} />)}
          </div>
        </div>

        <div className="col gap-4">
          <div className="card">
            <div className="card-header">
              <div>
                <div className="card-title">本月准点节奏</div>
                <div className="card-sub mono">{earliest >= 60*8 ? `${Math.floor(earliest/60)}:${String(earliest%60).padStart(2,"0")}` : "08:25"} – {Math.floor(latest/60)}:{String(latest%60).padStart(2,"0")} · 上班时间分布</div>
              </div>
            </div>
            <div className="card-body">
              <Sparkline values={spark} max={60} />
              <div className="row spread" style={{ marginTop: 12, fontSize: 11, color: "var(--text-muted)" }}>
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
                { name: "Telegram Bot", v: "已连接 · 轮询中", tone: "success" },
                { name: "SMTP · smtp.qq.com", v: "可达", tone: "success" },
                { name: "Selenium driver", v: headless ? "无头模式" : "可见模式", tone: "success" },
                { name: "Watchdog", v: "存活 · 0 次重启", tone: "success" },
                { name: "Tesseract OCR", v: "v5.3.1", tone: "info" },
              ].map((row, i) => (
                <div key={i} className="row spread" style={{ padding: "8px 0", borderBottom: i < 4 ? "1px solid var(--border-soft)" : "none", whiteSpace: "nowrap" }}>
                  <div className="row gap-2" style={{ fontSize: 12, whiteSpace: "nowrap", minWidth: 0 }}>
                    <StatusDot tone={row.tone} />
                    <span style={{ whiteSpace: "nowrap" }}>{row.name}</span>
                  </div>
                  <span className="mono" style={{ fontSize: 11, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>{row.v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

window.AAS_SCREENS = window.AAS_SCREENS || {};
window.AAS_SCREENS.dashboard = DashboardScreen;
