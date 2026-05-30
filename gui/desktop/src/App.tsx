// 应用主壳 — 设计稿 app.jsx 的 TS 平移：TitleBar + Sidebar + Toolbar + 路由。
import * as React from 'react';
import { Icon, type IconName } from './lib/icons';
import { USERS } from './lib/data';
import type { OpState, ScreenId, SysStatus } from './lib/types';
import { DashboardScreen } from './screens/Dashboard';
import { PunchScreen } from './screens/Punch';
import { RecordsScreen } from './screens/Records';
import { ShotsScreen } from './screens/Shots';
import { TasksScreen } from './screens/Tasks';
import { LogsScreen } from './screens/Logs';
import { SettingsScreen } from './screens/Settings';
import { ProxyScreen } from './screens/Proxy';
import { AboutScreen } from './screens/About';
import { ProgressDrawer } from './components/ProgressDrawer';
import { LegacyModeOverlay } from './components/LegacyModeOverlay';
import { StartupOverlay } from './components/StartupOverlay';
import { ToastHost } from './components/ToastHost';

type ScreenComponent = React.ComponentType;

const SCREENS: Record<ScreenId, ScreenComponent> = {
  dashboard: DashboardScreen,
  punch: PunchScreen,
  records: RecordsScreen,
  shots: ShotsScreen,
  tasks: TasksScreen,
  logs: LogsScreen,
  settings: SettingsScreen,
  proxy: ProxyScreen,
  about: AboutScreen,
};

interface AppContextValue {
  screen: ScreenId;
  setScreen: (s: ScreenId) => void;
  currentUser: string;
  setCurrentUser: (u: string) => void;
  seleniumOn: boolean;
  setSeleniumOn: (v: boolean) => void;
  headless: boolean;
  setHeadless: (v: boolean) => void;
  opState: OpState;
  setOpState: React.Dispatch<React.SetStateAction<OpState>>;
  sysStatus: SysStatus;
  clock: Date;
}

const AppCtx = React.createContext<AppContextValue | null>(null);

export const useApp = (): AppContextValue => {
  const ctx = React.useContext(AppCtx);
  if (!ctx) throw new Error('useApp() must be used within <App>');
  return ctx;
};

function useClock(): Date {
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

interface NavEntry {
  id: ScreenId;
  label: string;
  icon: IconName;
  group: 'main' | 'config';
  badge?: string;
}

const NAV: NavEntry[] = [
  { id: 'dashboard', label: '概览', icon: 'Dashboard', group: 'main' },
  { id: 'punch', label: '打卡操作', icon: 'Punch', group: 'main' },
  { id: 'records', label: '打卡记录', icon: 'Records', group: 'main' },
  { id: 'shots', label: '截图档案', icon: 'Camera', group: 'main' },
  { id: 'tasks', label: '定时任务', icon: 'Tasks', group: 'main', badge: '4' },
  { id: 'logs', label: '系统日志', icon: 'Logs', group: 'main' },
  { id: 'settings', label: '系统设置', icon: 'Settings', group: 'config' },
  { id: 'proxy', label: '网络加速', icon: 'Globe', group: 'config' },
  { id: 'about', label: '关于 & 命令', icon: 'Info', group: 'config' },
];

const SCREEN_SUB: Record<ScreenId, string> = {
  dashboard: '今日打卡、系统状态与最近活动',
  punch: '手动触发上班、下班或自动下班打卡',
  records: '按用户、按月份查看与统计打卡历史',
  shots: '查看每位用户最近 3 张打卡截图',
  tasks: '查看与终止 schedule 计划任务',
  logs: '实时日志、过滤错误与导出',
  settings: '环境变量、动态配置与多账户设置',
  proxy: '内置网络加速（仅代理本程序）· 订阅 / 节点 / 延迟',
  about: 'Telegram 命令、系统组件与版本信息',
};

interface SidebarProps {
  screen: ScreenId;
  setScreen: (s: ScreenId) => void;
  currentUser: string;
  setCurrentUser: (u: string) => void;
  sysStatus: SysStatus;
}

function Sidebar({ screen, setScreen, currentUser, setCurrentUser, sysStatus }: SidebarProps) {
  const user = USERS.find(u => u.id === currentUser) ?? USERS[0];
  return (
    <aside className="sidebar">
      <div className="side-section">
        <div className="side-label">工作台</div>
        <nav className="side-nav">
          {NAV.filter(n => n.group === 'main').map(n => {
            const IconCmp = Icon[n.icon];
            return (
              <button
                key={n.id}
                className={`side-item ${screen === n.id ? 'active' : ''}`}
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
          {NAV.filter(n => n.group === 'config').map(n => {
            const IconCmp = Icon[n.icon];
            return (
              <button
                key={n.id}
                className={`side-item ${screen === n.id ? 'active' : ''}`}
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '4px 8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--success)' }} />
            <span>{sysStatus.serviceLabel}</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', paddingLeft: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            模式: <span style={{ color: 'var(--text-secondary)' }}>{sysStatus.modeLabel}</span>
          </div>
        </div>
        <div
          className="user-chip"
          onClick={() => {
            const idx = USERS.findIndex(u => u.id === currentUser);
            setCurrentUser(USERS[(idx + 1) % USERS.length].id);
          }}
        >
          <div className="user-avatar" style={{ background: user.color }}>
            {user.short}
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

function TitleBar() {
  const win = window.AAS_WINDOW;
  return (
    <div className="titlebar">
      <div className="titlebar-app">
        <div className="app-mark">A</div>
        <span>自动打卡系统</span>
        <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 4 }}>v2.0</span>
      </div>
      <div className="titlebar-title">Auto Attendance · 邓蕴哲@localhost</div>
      <div className="window-controls">
        <button className="win-btn" title="最小化" onClick={() => win?.minimize()}>
          <Icon.Minus size={10} />
        </button>
        <button className="win-btn" title="最大化" onClick={() => win?.maximizeToggle()}>
          <Icon.Maximize size={10} />
        </button>
        <button className="win-btn close" title="关闭" onClick={() => win?.close()}>
          <Icon.Close size={10} />
        </button>
      </div>
    </div>
  );
}

interface ToolbarProps {
  title: string;
  sub?: string;
  actions?: React.ReactNode;
  clock: Date;
}

function Toolbar({ title, sub, actions, clock }: ToolbarProps) {
  return (
    <div className="toolbar">
      <div className="row gap-4">
        <div className="toolbar-title">{title}</div>
        {sub && <div className="toolbar-sub">{sub}</div>}
      </div>
      <div className="toolbar-actions">
        {actions}
        <div className="clock">{clock.toLocaleString('zh-CN', { hour12: false })}</div>
      </div>
    </div>
  );
}

export function App() {
  const [screen, setScreen] = React.useState<ScreenId>('dashboard');
  const [currentUser, setCurrentUser] = React.useState<string>('邓蕴哲');
  const clock = useClock();
  const [seleniumOn, setSeleniumOn] = React.useState(true);
  const [headless, setHeadless] = React.useState(true);
  const [opState, setOpState] = React.useState<OpState>({ running: false, type: null, perUser: {} });

  const sysStatus: SysStatus = {
    serviceLabel: 'Telegram Bot · 在线',
    modeLabel: seleniumOn ? (headless ? 'Selenium · 无头' : 'Selenium · 可见') : '图像识别 (PyAutoGUI)',
  };

  const ctxValue: AppContextValue = {
    screen, setScreen,
    currentUser, setCurrentUser,
    seleniumOn, setSeleniumOn,
    headless, setHeadless,
    opState, setOpState,
    sysStatus,
    clock,
  };

  const ScreenCmp = SCREENS[screen];
  const screenTitle = NAV.find(n => n.id === screen)?.label ?? '概览';
  const screenSub = SCREEN_SUB[screen];

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
              <Toolbar title={screenTitle} sub={screenSub} actions={null} clock={clock} />
              <div className="content scroll-area" key={screen}>
                {ScreenCmp ? <ScreenCmp /> : <div className="empty-state">未知页面: {screen}</div>}
              </div>
            </main>
          </div>
        </div>
        <ProgressDrawer />
        <LegacyModeOverlay />
        <StartupOverlay />
        <ToastHost />
      </div>
    </AppCtx.Provider>
  );
}
