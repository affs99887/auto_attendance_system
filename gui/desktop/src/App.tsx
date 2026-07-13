// 应用主壳 — 设计稿 app.jsx 的 TS 平移：TitleBar + Sidebar + Toolbar + 路由。
import * as React from 'react';
import { Icon, type IconName } from './lib/icons';
import type { OpState, ScreenId, SysStatus } from './lib/types';
import { DashboardScreen } from './screens/Dashboard';
import { PunchScreen } from './screens/Punch';
import { RecordsScreen } from './screens/Records';
import { ShotsScreen } from './screens/Shots';
import { TasksScreen } from './screens/Tasks';
import { LogsScreen } from './screens/Logs';
import { WeatherScreen } from './screens/Weather';
import { NewsScreen } from './screens/News';
import { EpaperScreen } from './screens/Epaper';
import { SettingsScreen } from './screens/Settings';
import { ProxyScreen } from './screens/Proxy';
import { AboutScreen } from './screens/About';
import { ProgressDrawer } from './components/ProgressDrawer';
import { LegacyModeOverlay } from './components/LegacyModeOverlay';
import { StartupOverlay } from './components/StartupOverlay';
import { ToastHost } from './components/ToastHost';
import { DialogHost } from './lib/dialog';
import { ModeQuickToggle } from './components/ModeQuickToggle';
import { SystemBanners } from './components/SystemBanners';
import { ServiceControls } from './components/ServiceControls';
import { SidebarFxWidget } from './components/SidebarFxWidget';
import { useSystemStore } from './store/system';

type ScreenComponent = React.ComponentType;

const SCREENS: Record<ScreenId, ScreenComponent> = {
  dashboard: DashboardScreen,
  punch: PunchScreen,
  records: RecordsScreen,
  shots: ShotsScreen,
  tasks: TasksScreen,
  logs: LogsScreen,
  weather: WeatherScreen,
  news: NewsScreen,
  epaper: EpaperScreen,
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
  group: 'main' | 'news' | 'config';
  badge?: string;
}

const NAV: NavEntry[] = [
  { id: 'dashboard', label: '仪表盘', icon: 'Dashboard', group: 'main' },
  { id: 'punch', label: '打卡操作', icon: 'Punch', group: 'main' },
  { id: 'records', label: '打卡记录', icon: 'Records', group: 'main' },
  { id: 'shots', label: '截图档案', icon: 'Camera', group: 'main' },
  { id: 'tasks', label: '定时任务', icon: 'Tasks', group: 'main', badge: '4' },
  { id: 'logs', label: '系统日志', icon: 'Logs', group: 'main' },
  { id: 'weather', label: '天气预报', icon: 'Cloud', group: 'news' },
  { id: 'news', label: 'AI 资讯', icon: 'Sparkle', group: 'news' },
  { id: 'epaper', label: '墨水屏', icon: 'Epaper', group: 'config' },
  { id: 'settings', label: '系统设置', icon: 'Settings', group: 'config' },
  { id: 'proxy', label: '网络加速', icon: 'Globe', group: 'config' },
  { id: 'about', label: '关于 & 命令', icon: 'Info', group: 'config' },
];

const SCREEN_SUB: Record<ScreenId, string> = {
  dashboard: '今日打卡、汇率行情与最近活动',
  punch: '手动触发上班、下班或自动下班打卡',
  records: '按用户、按月份查看与统计打卡历史',
  shots: '查看每位用户最近 3 张打卡截图',
  tasks: '查看与终止 schedule 计划任务',
  logs: '实时日志、过滤错误与导出',
  weather: '华山路 1076 号 · 实况、逐时趋势与未来天气',
  news: 'AI HOT 中文 AI 资讯 · 模型 / 产品 / 论文 / 行业动态',
  epaper: '蓝牙连接、日历模式、传图与假期数据',
  settings: '环境变量、动态配置与多账户设置',
  proxy: '内置网络加速（仅代理本程序）· 订阅 / 节点 / 延迟',
  about: 'Telegram 命令、系统组件与版本信息',
};

interface SidebarProps {
  screen: ScreenId;
  setScreen: (s: ScreenId) => void;
}

function Sidebar({ screen, setScreen }: SidebarProps) {
  // 按分组渲染导航项（main / news / config 复用同一份逻辑）
  const renderGroup = (group: NavEntry['group']) => (
    <nav className="side-nav">
      {NAV.filter(n => n.group === group).map(n => {
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
  );

  return (
    <aside className="sidebar">
      <div className="side-section">
        <div className="side-label">工作台</div>
        {renderGroup('main')}
      </div>
      <div className="side-section">
        <div className="side-label">资讯</div>
        {renderGroup('news')}
      </div>
      <div className="side-section">
        <div className="side-label">配置</div>
        {renderGroup('config')}
      </div>

      {/* 底部：汇率快查小组件 + 分割线 + 服务控制（已切单用户，去掉账户行）*/}
      <div className="side-footer">
        <SidebarFxWidget />
        <div className="side-footer-sep" />
        <ServiceControls variant="compact" />
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
        <span>AAS</span>
        <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 4 }}>v2.0</span>
      </div>
      <div className="titlebar-title">Auto Attendance · 赖得鑫@localhost</div>
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
  const [currentUser, setCurrentUser] = React.useState<string>('赖得鑫');
  const clock = useClock();
  // 模式状态来自后端真实配置（单一事实源 = snapshot.config）；切换走 setMode（乐观更新+持久化+失败回滚）
  const cfg = useSystemStore(s => s.snapshot?.config);
  const setMode = useSystemStore(s => s.setMode);
  const seleniumOn = cfg?.use_selenium_login ?? true;
  const headless = cfg?.selenium_headless ?? true;
  const setSeleniumOn = (v: boolean) => { void setMode({ use_selenium_login: v }); };
  const setHeadless = (v: boolean) => { void setMode({ selenium_headless: v }); };
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
  const screenTitle = NAV.find(n => n.id === screen)?.label ?? '仪表盘';
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
            />
            <main className="main">
              <Toolbar title={screenTitle} sub={screenSub} actions={<ModeQuickToggle />} clock={clock} />
              <SystemBanners />
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
        <DialogHost />
      </div>
    </AppCtx.Provider>
  );
}
