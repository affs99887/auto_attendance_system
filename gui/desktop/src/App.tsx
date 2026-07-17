// 应用主壳 — TitleBar + Sidebar + Toolbar + 路由。
import * as React from 'react';
import { Icon, type IconName } from './lib/icons';
import type { ScreenId } from './lib/types';
import { DashboardScreen } from './screens/Dashboard';
import { LogsScreen } from './screens/Logs';
import { WeatherScreen } from './screens/Weather';
import { WechatBarkScreen } from './screens/WechatBark';
import { SettingsScreen } from './screens/Settings';
import { ProxyScreen } from './screens/Proxy';
import { AboutScreen } from './screens/About';
import { StartupOverlay } from './components/StartupOverlay';
import { ToastHost } from './components/ToastHost';
import { DialogHost } from './lib/dialog';
import { SystemBanners } from './components/SystemBanners';
import { ServiceControls } from './components/ServiceControls';
import { SidebarFxWidget } from './components/SidebarFxWidget';

type ScreenComponent = React.ComponentType;

const SCREENS: Record<ScreenId, ScreenComponent> = {
  dashboard: DashboardScreen,
  logs: LogsScreen,
  weather: WeatherScreen,
  wechatBark: WechatBarkScreen,
  settings: SettingsScreen,
  proxy: ProxyScreen,
  about: AboutScreen,
};

interface AppContextValue {
  screen: ScreenId;
  setScreen: (s: ScreenId) => void;
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
  group: 'main' | 'weather' | 'config';
  badge?: string;
}

const NAV: NavEntry[] = [
  { id: 'dashboard', label: '仪表盘', icon: 'Dashboard', group: 'main' },
  { id: 'wechatBark', label: '微信转发', icon: 'Bell', group: 'main' },
  { id: 'logs', label: '系统日志', icon: 'Logs', group: 'main' },
  { id: 'weather', label: '天气预报', icon: 'Cloud', group: 'weather' },
  { id: 'settings', label: '系统设置', icon: 'Settings', group: 'config' },
  { id: 'proxy', label: '网络加速', icon: 'Globe', group: 'config' },
  { id: 'about', label: '关于', icon: 'Info', group: 'config' },
];

const SCREEN_SUB: Record<ScreenId, string> = {
  dashboard: '系统状态、天气与汇率行情',
  wechatBark: '微信通知转发到 iPhone Bark · 时段与节假日规则（监听仅 macOS）',
  logs: '实时日志、过滤错误与导出',
  weather: '多地点实况、逐时趋势与未来天气',
  settings: '环境变量与动态配置',
  proxy: '内置网络加速（仅代理本程序）· 订阅 / 节点 / 延迟',
  about: '系统组件与版本信息',
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
        <div className="side-label">天气</div>
        {renderGroup('weather')}
      </div>
      <div className="side-section">
        <div className="side-label">配置</div>
        {renderGroup('config')}
      </div>

      {/* 底部：汇率快查小组件 + 分割线 + 服务控制 */}
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
  // macOS 用系统自带的红绿灯按钮（主进程 titleBarStyle:hiddenInset），
  // 自绘三键只在其它平台渲染；左侧给红绿灯留出空位避免与 logo 重叠
  const isMac = window.AAS_PLATFORM === 'darwin';
  return (
    <div className="titlebar">
      <div className="titlebar-app" style={isMac ? { paddingLeft: 72 } : undefined}>
        <div className="app-mark">A</div>
        <span>AAS</span>
        <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 4 }}>v2.0</span>
      </div>
      <div className="titlebar-title">AAS 桌面工作台 @localhost</div>
      {!isMac && (
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
      )}
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
  const clock = useClock();

  const ctxValue: AppContextValue = {
    screen, setScreen,
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
              <Toolbar title={screenTitle} sub={screenSub} clock={clock} />
              <SystemBanners />
              <div className="content scroll-area" key={screen}>
                {ScreenCmp ? <ScreenCmp /> : <div className="empty-state">未知页面: {screen}</div>}
              </div>
            </main>
          </div>
        </div>
        <StartupOverlay />
        <ToastHost />
        <DialogHost />
      </div>
    </AppCtx.Provider>
  );
}
