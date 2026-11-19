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
import { useSunLight, WeatherSky } from './components/WeatherSky';
import { resolveSkyKind, skyToneStyle, type SkyKind } from './lib/sky';
import type { SunLight } from './lib/sun';
import { selectActiveWeatherEntry, selectActiveWeatherLocation, useWeatherStore } from './store/weather';
import { useWeatherGlassStore } from './store/weatherGlass';
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
  /** 当前选中地点的天气对应哪一种天空，天气页的整屏背景和面板上的雨雪效果都按它来 */
  weatherKind: SkyKind;
  /** 当前选中地点此刻的太阳位置，天空按它换时段的颜色 */
  weatherSun: SunLight;
  /** 天气页是不是正在显示"全部地点"，见 WeatherPlacesMode */
  weatherPlaces: WeatherPlacesMode;
  setWeatherPlaces: (mode: WeatherPlacesMode) => void;
}

/** off：普通天气页，整个窗口铺在天空上；on：正在看"全部地点"，窗口是普通背景。
 *  从"全部地点"回天气页的路上还有两步：
 *  closing：窗口还是普通背景，整屏天空已经在边框后面先淡入，回到天气页时直接就是满的；
 *  arriving：侧栏、标题栏、工具栏先换成天气页的样子（透出后面的天空），内容区还是普通背景 */
export type WeatherPlacesMode = 'off' | 'on' | 'closing' | 'arriving';

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

type WeatherShellPhase = 'off' | 'entering' | 'on' | 'leaving';

/** 整屏天空淡入淡出、窗口边框换颜色用的时长 */
export const WEATHER_SHELL_TRANSITION_MS = 620;
/** 天气页和"全部地点"互相切换后，过多久再收尾（比收放动画整个做完长一点） */
const PLACES_SETTLE_MS = 1400;

/** 天气页的整屏背景。只有进入天气页（含进出的过渡期间）才把天空放进来，平时不占显存 */
const WeatherThemeBackdrop = React.memo(function WeatherThemeBackdrop({ kind, sun, active }: { kind: SkyKind; sun: SunLight; active: boolean }) {
  return (
    <div className="weather-theme-stack" aria-hidden="true">
      {active && <WeatherSky kind={kind} sun={sun} className="weather-theme-sky" />}
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
  const weatherLocation = useWeatherStore(selectActiveWeatherLocation);
  const weatherSkycon = weatherEntry.data?.realtime.skycon;
  const glassBlur = useWeatherGlassStore(s => s.blur);
  const glassTint = useWeatherGlassStore(s => s.tint);

  // 天气代码变了、或者太阳位置变了（夜里和白天用的云图不一样），重新决定用哪一种天空；这个地点还没拿到数据时沿用上一次的天气。
  // 在渲染时直接算出来：切换地点的同一次渲染里整屏天空就是新地点的，不会先露出上一个地点的天空
  const weatherSun = useSunLight(weatherLocation.latitude, weatherLocation.longitude, clock);
  const lastSkycon = React.useRef<string | null>(null);
  if (weatherSkycon) lastSkycon.current = weatherSkycon;
  const weatherKind = resolveSkyKind(weatherSkycon || lastSkycon.current, weatherSun);
  const toneStyle = React.useMemo(() => skyToneStyle(weatherKind, weatherSun), [weatherKind, weatherSun]);

  React.useEffect(() => { void useWeatherGlassStore.getState().hydrate(); }, []);

  // 天气页里切到"全部地点"时，窗口换回普通背景；换的那一小段时间里侧栏、标题栏、工具栏的颜色慢慢过渡（placesSwitching），
  // 整屏天空淡出完再把它拿掉，平时不占显存
  const [weatherPlaces, setWeatherPlacesState] = React.useState<WeatherPlacesMode>('off');
  const [placesSwitching, setPlacesSwitching] = React.useState(false);
  const weatherPlacesRef = React.useRef<WeatherPlacesMode>('off');
  const placesTimer = React.useRef<number | null>(null);
  const setWeatherPlaces = React.useCallback((mode: WeatherPlacesMode) => {
    if (weatherPlacesRef.current === mode) return;
    weatherPlacesRef.current = mode;
    setWeatherPlacesState(mode);
    if (placesTimer.current !== null) window.clearTimeout(placesTimer.current);
    setPlacesSwitching(true);
    // 等天气页的收放动画整个做完再收尾：收尾时要撤掉整屏天空、整个窗口重新算一遍样式，赶在动画中间会卡一下
    placesTimer.current = window.setTimeout(() => {
      setPlacesSwitching(false);
      placesTimer.current = null;
    }, PLACES_SETTLE_MS);
  }, []);
  React.useEffect(() => () => {
    if (placesTimer.current !== null) window.clearTimeout(placesTimer.current);
  }, []);

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
    weatherKind,
    weatherSun,
    weatherPlaces,
    setWeatherPlaces,
  };

  const ScreenCmp = SCREENS[screen];
  const screenTitle = NAV.find(n => n.id === screen)?.label ?? '仪表盘';
  const screenSub = SCREEN_SUB[screen];
  const weatherShellVisible = (weatherShellPhase === 'entering' || weatherShellPhase === 'on')
    && (weatherPlaces === 'off' || weatherPlaces === 'arriving');

  return (
    <AppCtx.Provider value={ctxValue}>
      <div
        className="desktop"
        data-immersive={weatherShellVisible ? 'on' : 'off'}
        data-weather-transition={weatherShellPhase}
        data-places={weatherPlaces === 'off' ? undefined : weatherPlaces}
        data-places-switch={placesSwitching ? 'on' : undefined}
        style={{ ...toneStyle, '--glass-blur': `${glassBlur}px`, '--glass-k': glassTint / 100 } as React.CSSProperties}
      >
        <div className="win">
          <WeatherThemeBackdrop kind={weatherKind} sun={weatherSun} active={weatherShellPhase !== 'off' && (weatherPlaces !== 'on' || placesSwitching)} />
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
