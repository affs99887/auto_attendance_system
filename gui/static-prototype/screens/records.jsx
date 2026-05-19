/* global React */
// 打卡记录 — calendar + table

const { useState: useStR, useMemo: useMemoR } = React;
const recApp = window.AAS_useApp;
const recIcon = window.AAS_ICON;
const recData = window.AAS_DATA;

function buildMonth(ym) { return recData.buildMonthGrid(ym); }

function MonthPicker({ ym, setYm }) {
  const [y, m] = ym.split("-").map(Number);
  const shift = (delta) => {
    let nm = m + delta, ny = y;
    if (nm < 1) { nm = 12; ny--; }
    if (nm > 12) { nm = 1; ny++; }
    setYm(`${ny}-${String(nm).padStart(2, "0")}`);
  };
  return (
    <div className="row gap-2">
      <button className="btn btn-ico" onClick={() => shift(-1)}><recIcon.ChevronLeft size={12} /></button>
      <div className="mono" style={{ fontSize: 14, fontWeight: 500, minWidth: 80, textAlign: "center" }}>
        {y}年 {String(m).padStart(2, "0")}月
      </div>
      <button className="btn btn-ico" onClick={() => shift(1)}><recIcon.ChevronRight size={12} /></button>
    </div>
  );
}

function RecordCell({ d, ym, recs, isToday }) {
  if (!d) return <div className="cal-day empty" />;
  const ds = recData.dateStr(d);
  const rec = recs[ds];
  const dow = (d.getDay() + 6) % 7;
  const weekend = dow >= 5;
  let cls = "cal-day";
  if (rec?.in && rec?.out) cls += " complete has-record";
  else if (rec?.in) cls += " partial has-record";
  if (weekend) cls += " weekend";
  if (isToday) cls += " today";
  return (
    <div className={cls} title={ds}>
      <div className="row spread">
        <div className="cal-day-num">{d.getDate()}</div>
        {isToday && <span className="pill pill-info" style={{ padding: "0 4px", fontSize: 9 }}>今日</span>}
      </div>
      {rec ? (
        <div className="cal-times">
          {rec.in && <div className="cal-time"><span className="arrow">→</span>{rec.in.slice(0, 5)}</div>}
          {rec.out
            ? <div className="cal-time"><span className="arrow">←</span>{rec.out.slice(0, 5)}</div>
            : <div className="cal-time muted">未下班</div>}
        </div>
      ) : (
        weekend ? null : <div className="cal-time muted" style={{ marginTop: "auto" }}>无记录</div>
      )}
    </div>
  );
}

function RecordsScreen() {
  const { currentUser } = recApp();
  const [ym, setYm] = useStR("2026-05");
  const [view, setView] = useStR("calendar");
  const recs = recData.getUserRecords(currentUser, ym);
  const cells = useMemoR(() => buildMonth(ym), [ym]);
  const stats = recData.computeStats(currentUser, ym);

  return (
    <div className="col gap-6">
      <div className="row spread">
        <div className="row gap-2">
          <MonthPicker ym={ym} setYm={setYm} />
          <div className="tab-bar" style={{ marginLeft: 16 }}>
            <button className={`tab-btn ${view === "calendar" ? "active" : ""}`} onClick={() => setView("calendar")}>
              <recIcon.Calendar size={11} style={{ verticalAlign: -1, marginRight: 4 }} />日历
            </button>
            <button className={`tab-btn ${view === "table" ? "active" : ""}`} onClick={() => setView("table")}>
              <recIcon.Records size={11} style={{ verticalAlign: -1, marginRight: 4 }} />明细
            </button>
          </div>
        </div>
        <div className="row gap-2">
          <span className="pill pill-info"><span className="dot" />当前用户 {currentUser}</span>
          <button className="btn"><recIcon.Download size={12} />导出 JSON</button>
        </div>
      </div>

      {/* Stats strip */}
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
          <div className="kpi-meta">{stats.inOnly > 0 ? "含今日未下班" : "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">平均时间</div>
          <div className="kpi-value mono" style={{ fontSize: 14 }}>{stats.avgIn} · {stats.avgOut}</div>
          <div className="kpi-meta">上班 / 下班</div>
        </div>
      </div>

      {view === "calendar" ? (
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
            <div className="cal-grid" style={{ marginBottom: 6 }}>
              {["一", "二", "三", "四", "五", "六", "日"].map(d => (
                <div key={d} className="cal-head">{d}</div>
              ))}
            </div>
            <div className="cal-grid">
              {cells.map((d, i) => (
                <RecordCell key={i} d={d} ym={ym} recs={recs} isToday={d && recData.dateStr(d) === recData.TODAY} />
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">打卡明细</div>
              <div className="card-sub mono">punch_records/{currentUser}/{ym.replace("-", "_")}.json</div>
            </div>
            <button className="btn btn-sm"><recIcon.Refresh size={11} />刷新</button>
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
              {Object.entries(recs).sort((a, b) => b[0].localeCompare(a[0])).map(([date, r]) => {
                const dt = new Date(date);
                const dow = ["日", "一", "二", "三", "四", "五", "六"][dt.getDay()];
                const dur = recData.fmtDuration(r.in, r.out);
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
                      {complete
                        ? <span className="pill pill-success"><span className="dot" />完整</span>
                        : <span className="pill pill-warning"><span className="dot" />未下班</span>}
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

function Legend({ tone, label }) {
  return (
    <span className="row gap-2" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
      <span style={{
        width: 10, height: 10, borderRadius: 3,
        background: `var(--${tone}-bg)`,
        border: `1px solid var(--${tone}-border)`,
      }} />
      {label}
    </span>
  );
}

window.AAS_SCREENS = window.AAS_SCREENS || {};
window.AAS_SCREENS.records = RecordsScreen;
