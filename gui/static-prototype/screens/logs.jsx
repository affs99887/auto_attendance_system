/* global React */
// 系统日志 — log viewer with filter

const { useState: useStL, useMemo: useMemoL } = React;
const logsApp = window.AAS_useApp;
const logsIcon = window.AAS_ICON;
const logsData = window.AAS_DATA;

function LogsScreen() {
  const [level, setLevel] = useStL("ALL");
  const [q, setQ] = useStL("");
  const [follow, setFollow] = useStL(true);

  const filtered = useMemoL(() => {
    return logsData.SAMPLE_LOGS.filter(l => {
      if (level !== "ALL" && l.lvl !== level) return false;
      if (q && !(l.msg.toLowerCase().includes(q.toLowerCase()) || l.ts.includes(q))) return false;
      return true;
    });
  }, [level, q]);

  const counts = {
    ALL: logsData.SAMPLE_LOGS.length,
    INFO: logsData.SAMPLE_LOGS.filter(l => l.lvl === "INFO").length,
    WARN: logsData.SAMPLE_LOGS.filter(l => l.lvl === "WARN").length,
    ERROR: logsData.SAMPLE_LOGS.filter(l => l.lvl === "ERROR").length,
  };

  return (
    <div className="col gap-4" style={{ height: "100%" }}>
      <div className="row spread">
        <div className="row gap-2">
          <div className="tab-bar">
            {["ALL", "INFO", "WARN", "ERROR"].map(L => (
              <button key={L} className={`tab-btn ${level === L ? "active" : ""}`} onClick={() => setLevel(L)}>
                {L === "ALL" ? "全部" : L}
                <span className="mono" style={{
                  marginLeft: 6, fontSize: 10, padding: "1px 5px", borderRadius: 8,
                  background: "var(--bg-inset)", color: "var(--text-muted)",
                }}>{counts[L]}</span>
              </button>
            ))}
          </div>
          <div style={{ position: "relative", marginLeft: 8 }}>
            <logsIcon.Search size={12} style={{
              position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
              color: "var(--text-muted)",
            }} />
            <input
              className="input mono"
              placeholder="搜索消息或时间戳…"
              value={q}
              onChange={e => setQ(e.target.value)}
              style={{ paddingLeft: 30, width: 260, fontSize: 12 }}
            />
          </div>
        </div>
        <div className="row gap-2">
          <div className="row gap-2" style={{ fontSize: 12 }}>
            <div className={`toggle ${follow ? "on" : ""}`} onClick={() => setFollow(!follow)} />
            <span className="secondary">实时跟踪</span>
          </div>
          <button className="btn"><logsIcon.Download size={12} />导出</button>
          <button className="btn"><logsIcon.Trash size={12} />清空视图</button>
        </div>
      </div>

      <div className="card" style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 360 }}>
        <div className="card-header">
          <div>
            <div className="card-title">attendance_system.log</div>
            <div className="card-sub mono">logs/attendance_system.log · 5MB rotating · backupCount=3</div>
          </div>
          <div className="row gap-2" style={{ fontSize: 11, color: "var(--text-muted)" }}>
            <span className="pill pill-success"><span className="dot" />已连接</span>
            显示 {filtered.length} / {logsData.SAMPLE_LOGS.length} 行
          </div>
        </div>
        <div className="scroll-area" style={{ flex: 1, background: "var(--bg-inset)" }}>
          {filtered.map((l, i) => (
            <div key={i} className="log-line">
              <span className="ts">{l.ts}</span>
              <span className={`lvl ${l.lvl}`}>{l.lvl}</span>
              <span className="msg">{l.msg}</span>
            </div>
          ))}
          {filtered.length === 0 && <div className="empty-state">无匹配日志</div>}
        </div>
        <div style={{
          borderTop: "1px solid var(--border)",
          padding: "6px 16px",
          fontSize: 11,
          color: "var(--text-muted)",
          display: "flex", justifyContent: "space-between",
        }}>
          <span className="mono">tail -f logs/attendance_system.log</span>
          <span>UTF-8 · 27,706 行 · 4.2 MB</span>
        </div>
      </div>
    </div>
  );
}

window.AAS_SCREENS = window.AAS_SCREENS || {};
window.AAS_SCREENS.logs = LogsScreen;
