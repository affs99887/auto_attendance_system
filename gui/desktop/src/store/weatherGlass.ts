// 天气面板玻璃效果的设置：模糊多少、底色多浓。天气页右上角"外观"里调，首页的天气卡片也跟着它走。
import { create } from 'zustand';

const GLASS_SETTINGS_KEY = 'aas.weather.glass';

export interface GlassTune {
  /** 面板后面的背景模糊多少像素，0 ~ 40 */
  blur: number;
  /** 面板底色的浓淡，百分数，100 是原样，0 ~ 250 */
  tint: number;
}
export const GLASS_TUNE_DEFAULT: GlassTune = { blur: 20, tint: 125 };
export const GLASS_BLUR_MAX = 40;
export const GLASS_TINT_MAX = 250;

interface GlassState extends GlassTune {
  hydrated: boolean;
  hydrate: () => Promise<void>;
  setTune: (patch: Partial<GlassTune>) => void;
  reset: () => void;
}

/** 读到的值只认合法范围内的数字，别的一律当没读到 */
function normalizeTune(value: unknown): GlassTune | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as { blur?: unknown; tint?: unknown };
  if (typeof raw.blur !== 'number' || !Number.isFinite(raw.blur)) return null;
  if (typeof raw.tint !== 'number' || !Number.isFinite(raw.tint)) return null;
  return {
    blur: Math.min(GLASS_BLUR_MAX, Math.max(0, raw.blur)),
    tint: Math.min(GLASS_TINT_MAX, Math.max(0, raw.tint)),
  };
}

function loadLocalTune(): GlassTune {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(GLASS_SETTINGS_KEY) : null;
    if (raw) return normalizeTune(JSON.parse(raw)) || GLASS_TUNE_DEFAULT;
  } catch { /* 存的内容坏了就用默认值 */ }
  return GLASS_TUNE_DEFAULT;
}

// 打包后的应用以 file:// 加载，localStorage 重启后不一定还在，所以两处都写：
// localStorage 用来在启动的一瞬间就有值可用；主进程的 gui-settings.json（window.AAS_SETTINGS）才是重启后一定还在的那份
function persistTune(tune: GlassTune) {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(GLASS_SETTINGS_KEY, JSON.stringify(tune));
  } catch { /* localStorage 写不进去不影响设置文件那一份 */ }
  if (typeof window !== 'undefined') window.AAS_SETTINGS?.set(GLASS_SETTINGS_KEY, tune);
}

let hydratePromise: Promise<void> | null = null;

export const useWeatherGlassStore = create<GlassState>((set, get) => ({
  ...loadLocalTune(),
  hydrated: false,

  /** 启动后用设置文件里的值覆盖 localStorage 的初值 */
  async hydrate() {
    if (get().hydrated) return;
    if (hydratePromise) return hydratePromise;
    hydratePromise = (async () => {
      let fromFile: GlassTune | null = null;
      if (typeof window !== 'undefined' && window.AAS_SETTINGS) {
        try {
          fromFile = normalizeTune((await window.AAS_SETTINGS.getAll())[GLASS_SETTINGS_KEY]);
        } catch { /* 设置文件读不到时保留 localStorage 的初值 */ }
      }
      set({ ...(fromFile || {}), hydrated: true });
    })();
    return hydratePromise;
  },

  setTune(patch) {
    const next = normalizeTune({ blur: get().blur, tint: get().tint, ...patch });
    if (!next) return;
    set(next);
    persistTune(next);
  },

  reset() {
    set(GLASS_TUNE_DEFAULT);
    persistTune(GLASS_TUNE_DEFAULT);
  },
}));
