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
import { skyInfo } from './lib/weather';
import { selectActiveWeatherEntry, useWeatherStore } from './store/weather';
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
  weather: '多地点实况、逐时趋势与未来天气',
  news: 'AI HOT 中文 AI 资讯 · 模型 / 产品 / 论文 / 行业动态',
  epaper: '蓝牙连接、日历模式、传图与假期数据',
  settings: '环境变量、动态配置与多账户设置',
  proxy: '内置网络加速（仅代理本程序）· 订阅 / 节点 / 延迟',
  about: 'Telegram 命令、系统组件与版本信息',
};

type WeatherThemeKind = 'sun' | 'rain' | 'night' | 'cloud' | 'thunder';
type WeatherShellPhase = 'off' | 'entering' | 'on' | 'leaving';

const WEATHER_THEME_CROSSFADE_MS = 720;
const WEATHER_SHELL_TRANSITION_MS = 620;

function resolveWeatherTheme(skycon: string | null | undefined, now: Date): WeatherThemeKind {
  if (!skycon) return now.getHours() >= 19 || now.getHours() < 6 ? 'night' : 'sun';
  const info = skyInfo(skycon);
  if (info.icon === 'thunder') return 'thunder';
  if (info.tone === 'rain' || info.tone === 'snow') return 'rain';
  if (info.tone === 'night') return 'night';
  if (info.tone === 'cloud' || info.tone === 'haze' || info.tone === 'wind') return 'cloud';
  return 'sun';
}

function WeatherThemeLayer({
  weather,
  phase,
}: {
  weather: WeatherThemeKind;
  phase: 'current' | 'previous';
}) {
  const rainy = weather === 'rain' || weather === 'thunder';
  const cloudy = weather === 'cloud' || weather === 'thunder';
  return (
    <div className={`weather-theme-field is-${phase}`} data-weather={weather}>
      <div className="weather-theme-vignette" />
      {weather === 'sun' && (
        <>
          <span className="weather-theme-halo" />
          {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(index => (
            <span
              key={`sun-mote-${index}`}
              className="weather-theme-mote"
              style={{
                left: `${(index * 31 + 9) % 96}%`,
                top: `${28 + ((index * 19) % 68)}%`,
                animationDelay: `${-index * .9}s`,
                animationDuration: `${10 + (index % 5) * 1.6}s`,
              }}
            />
          ))}
        </>
      )}
      {weather === 'night' && (
        <>
          <span className="weather-theme-moon" />
          {Array.from({ length: 36 }, (_, index) => (
            <span
              key={`night-star-${index}`}
              className="weather-theme-star"
              style={{
                left: `${(index * 37 + 5) % 97}%`,
                top: `${(index * 23 + 7) % 78}%`,
                width: `${1 + (index % 3) * .65}px`,
                height: `${1 + (index % 3) * .65}px`,
                animationDelay: `${-index * .17}s`,
                animationDuration: `${2.2 + (index % 6) * .42}s`,
              }}
            />
          ))}
        </>
      )}
      {cloudy && [0, 1, 2, 3, 4, 5].map(index => (
        <span
          key={`theme-cloud-${index}`}
          className="weather-theme-cloud"
          style={{
            left: `${[-7, 12, 31, 52, 69, 84][index]}%`,
            top: `${[4, 32, 11, 48, 23, 58][index]}%`,
            width: `${250 + (index % 3) * 92}px`,
            height: `${120 + (index % 3) * 34}px`,
            animationDelay: `${-index * 1.8}s`,
            animationDuration: `${13 + index * 1.3}s`,
          }}
        />
      ))}
      {rainy && Array.from({ length: weather === 'thunder' ? 38 : 30 }, (_, index) => (
        <span
          key={`theme-rain-${index}`}
          className="weather-theme-drop"
          style={{
            left: `${(index * 29 + 3) % 100}%`,
            height: `${42 + (index % 7) * 8}px`,
            opacity: .24 + (index % 5) * .07,
            animationDelay: `${-(index % 13) * .08}s`,
            animationDuration: `${weather === 'thunder' ? .42 + (index % 5) * .055 : .58 + (index % 6) * .06}s`,
          }}
        />
      ))}
      {weather === 'thunder' && <span className="weather-theme-flash" />}
    </div>
  );
}

const WeatherThemeBackdrop = React.memo(function WeatherThemeBackdrop({ weather }: { weather: WeatherThemeKind }) {
  const [current, setCurrent] = React.useState(weather);
  const [previous, setPrevious] = React.useState<WeatherThemeKind | null>(null);
  const cleanupTimer = React.useRef<number | null>(null);

  React.useLayoutEffect(() => {
    if (weather === current) return;
    if (cleanupTimer.current !== null) window.clearTimeout(cleanupTimer.current);
    setPrevious(current);
    setCurrent(weather);
    cleanupTimer.current = window.setTimeout(() => {
      setPrevious(null);
      cleanupTimer.current = null;
    }, WEATHER_THEME_CROSSFADE_MS);
  }, [current, weather]);

  React.useEffect(() => () => {
    if (cleanupTimer.current !== null) window.clearTimeout(cleanupTimer.current);
  }, []);

  return (
    <div className="weather-theme-stack" aria-hidden="true">
      {previous && previous !== current && (
        <WeatherThemeLayer key={previous} weather={previous} phase="previous" />
      )}
      <WeatherThemeLayer key={current} weather={current} phase="current" />
    </div>
  );
});

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
        <span className="tb-ver">v2.0</span>
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
      <div className="row gap-4 toolbar-lead">
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
  const [screen, setRenderedScreen] = React.useState<ScreenId>('dashboard');
  const [weatherShellPhase, setWeatherShellPhase] = React.useState<WeatherShellPhase>('off');
  const weatherNavigationTimer = React.useRef<number | null>(null);
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
  const weatherEntry = useWeatherStore(selectActiveWeatherEntry);
  const weatherSkycon = weatherEntry.data?.realtime.skycon;
  const [weatherTheme, setWeatherTheme] = React.useState<WeatherThemeKind>(() => (
    resolveWeatherTheme(weatherSkycon, new Date())
  ));

  React.useEffect(() => {
    if (!weatherSkycon) return;
    const nextTheme = resolveWeatherTheme(weatherSkycon, new Date());
    setWeatherTheme(current => current === nextTheme ? current : nextTheme);
  }, [weatherSkycon]);

  const clearWeatherNavigationTransition = React.useCallback(() => {
    if (weatherNavigationTimer.current !== null) {
      window.clearTimeout(weatherNavigationTimer.current);
      weatherNavigationTimer.current = null;
    }
  }, []);

  React.useEffect(() => clearWeatherNavigationTransition, [clearWeatherNavigationTransition]);

  const setScreen = React.useCallback((nextScreen: ScreenId) => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    const duration = reduceMotion ? 0 : WEATHER_SHELL_TRANSITION_MS;

    if (nextScreen === screen) return;
    clearWeatherNavigationTransition();

    if (weatherShellPhase === 'leaving' && nextScreen !== 'weather') {
      setRenderedScreen(nextScreen);
      if (duration === 0) {
        setWeatherShellPhase('off');
        return;
      }
      setWeatherShellPhase('leaving');
      weatherNavigationTimer.current = window.setTimeout(() => {
        setWeatherShellPhase('off');
        weatherNavigationTimer.current = null;
      }, duration);
      return;
    }

    if (screen === 'weather' && nextScreen !== 'weather') {
      setRenderedScreen(nextScreen);
      if (duration === 0) {
        setWeatherShellPhase('off');
        return;
      }
      setWeatherShellPhase('leaving');
      weatherNavigationTimer.current = window.setTimeout(() => {
        setWeatherShellPhase('off');
        weatherNavigationTimer.current = null;
      }, duration);
      return;
    }

    setRenderedScreen(nextScreen);
    if (nextScreen !== 'weather') {
      setWeatherShellPhase('off');
      return;
    }
    if (duration === 0) {
      setWeatherShellPhase('on');
      return;
    }

    setWeatherShellPhase('entering');
    weatherNavigationTimer.current = window.setTimeout(() => {
      setWeatherShellPhase('on');
      weatherNavigationTimer.current = null;
    }, duration);
  }, [clearWeatherNavigationTransition, screen, weatherShellPhase]);

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
  const weatherShellVisible = weatherShellPhase === 'entering' || weatherShellPhase === 'on';

  return (
    <AppCtx.Provider value={ctxValue}>
      <div
        className="desktop"
        data-weather={weatherTheme}
        data-immersive={weatherShellVisible ? 'on' : 'off'}
        data-weather-transition={weatherShellPhase}
      >
        <div className="win">
          <WeatherThemeBackdrop weather={weatherTheme} />
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
