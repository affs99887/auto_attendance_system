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
import { skyInfo } from './lib/weather';
import { selectActiveWeatherEntry, useWeatherStore } from './store/weather';

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

// 天气沉浸式背景：5 种主题场景（晴/雨/夜/多云/雷暴）
type WeatherThemeKind = 'sun' | 'rain' | 'night' | 'cloud' | 'thunder';
// 天气页沉浸态的四个阶段：off 未激活 / entering 正在进入 / on 完全展示 / leaving 正在退出
type WeatherShellPhase = 'off' | 'entering' | 'on' | 'leaving';

const WEATHER_THEME_CROSSFADE_MS = 720;
const WEATHER_SHELL_TRANSITION_MS = 620;

// 把实时天气 skycon 归纳为 5 种背景主题；没有数据时按当前时间猜白天/夜晚
function resolveWeatherTheme(skycon: string | null | undefined, now: Date): WeatherThemeKind {
  if (!skycon) return now.getHours() >= 19 || now.getHours() < 6 ? 'night' : 'sun';
  const info = skyInfo(skycon);
  if (info.icon === 'thunder') return 'thunder';
  if (info.tone === 'rain' || info.tone === 'snow') return 'rain';
  if (info.tone === 'night') return 'night';
  if (info.tone === 'cloud' || info.tone === 'haze' || info.tone === 'wind') return 'cloud';
  return 'sun';
}

// 单层天气场景：按主题渲染阳光颗粒/星星/云朵/雨丝/闪电等动画元素
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

// 双层背景堆：主题切换时旧层留在底下、新层淡入盖上，720ms 后卸载旧层，
// 保证切换不打断正在播的动画
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
        <span className="tb-ver">v2.0</span>
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
  const clock = useClock();
  // 沉浸式背景主题跟随当前收藏地点的实时天气
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

  // 切页统一入口：页面立即切换，天气页沉浸态（chrome 半透明化）走 620ms 过渡。
  // 每次先清掉旧定时器，避免快速连点造成定时器叠加、状态卡在中间态。
  const setScreen = React.useCallback((nextScreen: ScreenId) => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    const duration = reduceMotion ? 0 : WEATHER_SHELL_TRANSITION_MS;

    if (nextScreen === screen) return;
    clearWeatherNavigationTransition();

    // 退出过渡还没播完又切去别的非天气页：重开一轮 leaving 计时，播完再归 off
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

    // 从天气页离开：先切页面，chrome 做一次 leaving 过渡再回普通主题
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

    // 进入天气页：entering 阶段播 620ms 过渡，播完固定为 on
    setWeatherShellPhase('entering');
    weatherNavigationTimer.current = window.setTimeout(() => {
      setWeatherShellPhase('on');
      weatherNavigationTimer.current = null;
    }, duration);
  }, [clearWeatherNavigationTransition, screen, weatherShellPhase]);

  const ctxValue: AppContextValue = {
    screen, setScreen,
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
