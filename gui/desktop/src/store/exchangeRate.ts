// 汇率 store — 主动 fetch + WS exchange_rate:update 增量更新
//
// 后端只产出 CNY->JPY 方向（base=CNY quote=JPY）；JPY->CNY 一律由前端对 value/price 取倒数。
// 本轮仅提供数据层（api/store/订阅），不渲染任何图表 / 转换器 UI。
import { create } from 'zustand';
import { api, ApiError, type ExchangeRateResponse } from '../lib/api';

export type ExchangeRateRange = '7d' | '30d' | 'quarter' | 'year' | '3y';
export type ExchangeRateDirection = 'CNY_JPY' | 'JPY_CNY';

interface ExchangeRateState {
  resp: ExchangeRateResponse | null;
  range: ExchangeRateRange;
  direction: ExchangeRateDirection;
  loading: boolean;
  error: string | null;
  lastFetched: number | null;

  /** 设置区间并立即刷新 */
  setRange: (r: ExchangeRateRange) => void;
  /** 切换展示方向（CNY->JPY / JPY->CNY），不重新拉取（方向只影响展示侧取倒数） */
  setDirection: (d: ExchangeRateDirection) => void;
  /** 拉取当前区间汇率；force=true 跳过后端缓存 */
  refresh: (force?: boolean) => Promise<void>;
  /** WS 增量更新：把最新报价合并进 resp.latest */
  applyWsUpdate: (latest: { price: number; time: number }) => void;
  reset: () => void;
}

export const useExchangeRateStore = create<ExchangeRateState>((set, get) => ({
  resp: null,
  range: '30d',
  direction: 'CNY_JPY',
  loading: false,
  error: null,
  lastFetched: null,

  setRange(r) {
    set({ range: r });
    void get().refresh();
  },

  setDirection(d) {
    set({ direction: d });
  },

  async refresh(force) {
    set({ loading: true, error: null });
    try {
      const resp = await api.getExchangeRate(get().range, force);
      set({ resp, lastFetched: Date.now(), loading: false });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} ${e.message}` : (e as Error).message;
      set({ error: msg, loading: false });
    }
  },

  applyWsUpdate(latest) {
    const cur = get().resp;
    if (!cur) return;
    set({ resp: { ...cur, latest }, lastFetched: Date.now() });
  },

  reset() {
    set({ resp: null, loading: false, error: null, lastFetched: null });
  },
}));

/** 按方向换算展示值：JPY->CNY 取倒数；CNY->JPY 原样返回。供后续图表 / 转换器复用。 */
export const toDisplay = (value: number, direction: ExchangeRateDirection): number =>
  direction === 'JPY_CNY' ? 1 / value : value;
