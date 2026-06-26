/* global React, ReactDOM */
const { useState, useEffect, useMemo, useRef } = React;
const { USERS, TODAY } = window.AAS_DATA;
const Icon = window.AAS_ICON;

// --- AppContext ---
const AppCtx = React.createContext(null);
const useApp = () => React.useContext(AppCtx);

// --- Live clock ---
function useClock() {
  const [now, setNow] = useState(() => new Date(`${TODAY}T08:45:32`));
  useEffect(() => {
    const id = setInterval(() => setNow(prev => new Date(prev.getTime() + 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

// --- Sidebar ---
const NAV = [
  { id: "dashboard", label: "概览",     icon: "Dashboard", group: "main" },
  { id: "punch",     label: "打卡操作",  icon: "Punch",     group: "main" },
  { id: "records",   label: "打卡记录",  icon: "Records",   group: "main" },
  { id: "shots",     label: "截图档案",  icon: "Camera",    group: "main" },
  { id: "tasks",     label: "定时任务",  icon: "Tasks",     group: "main", badge: "4" },
  { id: "logs",      label: "系统日志",  icon: "Logs",      group: "main" },
  { id: "settings",  label: "系统设置",  icon: "Settings",  group: "config" },
  { id: "about",     label: "关于 & 命令", icon: "Info",    group: "config" },
];

function Sidebar({ screen, setScreen, currentUser, setCurrentUser, sysStatus }) {
  return (
    <aside className="sidebar">
      <div className="side-section">
        <div className="side-label">工作台</div>
        <nav className="side-nav">
          {NAV.filter(n => n.group === "main").map(n => {
            const IconCmp = Icon[n.icon];
            return (
              <button
                key={n.id}
                className={`side-item ${screen === n.id ? "active" : ""}`}
                onClick={() => setScreen(n.id)}
              >
                <span className="side-ico"><IconCmp /></span>
                <span>{n.label}</span>
                {n.badge && <span className="side-badge mono">{n.badge}</span>}
              </button>
            );
          })}
        </nav>
      </div>
      <div className="side-section">
        <div className="side-label">配置</div>
        <nav className="side-nav">
          {NAV.filter(n => n.group === "config").map(n => {
            const IconCmp = Icon[n.icon];
            return (
              <button
                key={n.id}
                className={`side-item ${screen === n.id ? "active" : ""}`}
                onClick={() => setScreen(n.id)}
              >
                <span className="side-ico"><IconCmp /></span>
                <span>{n.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <div className="side-footer">
        <div style={{display:"flex", flexDirection:"column", gap:6, padding:"4px 8px"}}>
          <div style={{display:"flex", alignItems:"center", gap:6, fontSize:11, color:"var(--text-muted)", whiteSpace:"nowrap"}}>
            <span className="dot" style={{width:6,height:6,borderRadius:"50%", background:"var(--success)"}}></span>
            <span>{sysStatus.serviceLabel}</span>
          </div>
          <div style={{fontSize:10, color:"var(--text-muted)", paddingLeft:12, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>
            模式: <span style={{color:"var(--text-secondary)"}}>{sysStatus.modeLabel}</span>
          </div>
        </div>
        <div className="user-chip" onClick={() => {
          const idx = USERS.findIndex(u => u.id === currentUser);
          setCurrentUser(USERS[(idx + 1) % USERS.length].id);
        }}>
          <div className="user-avatar" style={{background: USERS.find(u => u.id === currentUser).color}}>
            {USERS.find(u => u.id === currentUser).short}
          </div>
          <div className="user-info">
            <div className="user-name">{currentUser}</div>
            <div className="user-status">点击切换用户</div>
          </div>
          <Icon.ChevronDown size={12} />
        </div>
      </div>
    </aside>
  );
}

// --- Title bar ---
function TitleBar() {
  return (
    <div className="titlebar">
      <div className="titlebar-app">
        <div className="app-mark">A</div>
        <span>AAS</span>
        <span style={{color:"var(--text-muted)", fontWeight:400, marginLeft:4}}>v2.0</span>
      </div>
      <div className="titlebar-title">Auto Attendance · 邓蕴哲@localhost</div>
      <div className="window-controls">
        <button className="win-btn"><Icon.Minus size={10} /></button>
        <button className="win-btn"><Icon.Maximize size={10} /></button>
        <button className="win-btn close"><Icon.Close size={10} /></button>
      </div>
    </div>
  );
}

// --- Toolbar ---
function Toolbar({ title, sub, actions, clock }) {
  return (
    <div className="toolbar">
      <div className="row gap-4">
        <div className="toolbar-title">{title}</div>
        {sub && <div className="toolbar-sub">{sub}</div>}
      </div>
      <div className="toolbar-actions">
        {actions}
        <div className="clock">{clock.toLocaleString("zh-CN", { hour12: false })}</div>
      </div>
    </div>
  );
}

// --- App ---
function App() {
  const [screen, setScreen] = useState("dashboard");
  const [currentUser, setCurrentUser] = useState("邓蕴哲");
  const clock = useClock();

  // System state — wired through context
  const [seleniumOn, setSeleniumOn] = useState(true);
  const [headless, setHeadless] = useState(true);
  const [opState, setOpState] = useState({ running: false, type: null, perUser: {} });

  const sysStatus = {
    serviceLabel: "Telegram Bot · 在线",
    modeLabel: seleniumOn ? (headless ? "Selenium · 无头" : "Selenium · 可见") : "图像识别 (PyAutoGUI)",
  };

  const ctxValue = {
    screen, setScreen,
    currentUser, setCurrentUser,
    seleniumOn, setSeleniumOn,
    headless, setHeadless,
    opState, setOpState,
    sysStatus,
    clock,
  };

  const ScreenCmp = window.AAS_SCREENS[screen];
  const screenTitle = NAV.find(n => n.id === screen)?.label || "概览";
  const screenSub = {
    dashboard: "今日打卡、系统状态与最近活动",
    punch:     "手动触发上班、下班或自动下班打卡",
    records:   "按用户、按月份查看与统计打卡历史",
    shots:     "查看每位用户最近 3 张打卡截图",
    tasks:     "查看与终止 schedule 计划任务",
    logs:      "实时日志、过滤错误与导出",
    settings:  "环境变量、动态配置与多账户设置",
    about:     "Telegram 命令、系统组件与版本信息",
  }[screen];

  return (
    <AppCtx.Provider value={ctxValue}>
      <div className="desktop">
        <div className="win">
          <TitleBar />
          <div className="shell">
            <Sidebar
              screen={screen}
              setScreen={setScreen}
              currentUser={currentUser}
              setCurrentUser={setCurrentUser}
              sysStatus={sysStatus}
            />
            <main className="main">
              <Toolbar
                title={screenTitle}
                sub={screenSub}
                actions={null}
                clock={clock}
              />
              <div className="content scroll-area" key={screen}>
                {ScreenCmp ? <ScreenCmp /> : <div className="empty-state">加载中…</div>}
              </div>
            </main>
          </div>
        </div>
      </div>
    </AppCtx.Provider>
  );
}

window.AAS_APP = App;
window.AAS_useApp = useApp;
