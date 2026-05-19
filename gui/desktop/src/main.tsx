// React 入口 — 应用主题 + 渲染 App
import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { useBackendBootstrap } from './store/bootstrap';
import './styles.css';

const THEME_KEY = 'aas.theme';
const ACCENT_KEY = 'aas.accent';
const DEFAULT_ACCENT = '#3b6fb8';

type Theme = 'light' | 'dark';

function detectInitialTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY) as Theme | null;
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme: Theme, accent: string) {
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.setProperty('--accent', accent);
}

// 全局窗口对象，便于 Settings 页 / 浮动按钮 / Electron 主进程操作主题
declare global {
  interface Window {
    AAS_THEME?: {
      get: () => { theme: Theme; accent: string };
      setTheme: (t: Theme) => void;
      setAccent: (a: string) => void;
      toggleTheme: () => void;
      accents: string[];
    };
  }
}

function Root() {
  useBackendBootstrap();

  const [theme, setThemeState] = React.useState<Theme>(detectInitialTheme);
  const [accent, setAccentState] = React.useState<string>(
    () => localStorage.getItem(ACCENT_KEY) || DEFAULT_ACCENT,
  );

  React.useEffect(() => {
    applyTheme(theme, accent);
    localStorage.setItem(THEME_KEY, theme);
    localStorage.setItem(ACCENT_KEY, accent);
  }, [theme, accent]);

  React.useEffect(() => {
    window.AAS_THEME = {
      get: () => ({ theme, accent }),
      setTheme: setThemeState,
      setAccent: setAccentState,
      toggleTheme: () => setThemeState(prev => (prev === 'dark' ? 'light' : 'dark')),
      accents: ['#3b6fb8', '#8b5e3c', '#5b8c4f', '#a04060', '#1f1f24'],
    };
  }, [theme, accent]);

  // 系统主题跟随（用户未显式设过时）
  React.useEffect(() => {
    if (localStorage.getItem(THEME_KEY)) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (e: MediaQueryListEvent) => setThemeState(e.matches ? 'dark' : 'light');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return <App />;
}

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root not found');
createRoot(rootEl).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
