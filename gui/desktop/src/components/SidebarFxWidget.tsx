// 侧边栏汇率小组件 —— 仪表盘「汇率走势」卡片的精简小号版，常驻侧栏底部。
// 数据复用 useExchangeRateStore（bootstrap 已全局首拉 + WS 增量更新），本组件不自行首拉。
// 保留两项核心：方向切换（CNY→JPY / JPY→CNY，本地 state，不影响仪表盘）+ 迷你走势图；切换会同步改数字/涨跌/走势。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { useExchangeRateStore, toDisplay, type ExchangeRateDirection } from '../store/exchangeRate';

// 迷你走势图（纯 SVG 折线 + 渐变填充，无坐标轴，涨绿跌红）—— 仪表盘 FxChart 的精简版
function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [W, setW] = React.useState(180);
  React.useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setW(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const H = 44, padT = 4, padB = 4;
  const innerH = H - padT - padB;
  const color = up ? 'var(--success)' : 'var(--danger)';

  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || hi * 0.01 || 1;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => padT + innerH - ((v - lo) / span) * innerH;
  const line = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const base = (padT + innerH).toFixed(1);
  const area = `${line} L${W.toFixed(1)},${base} L0,${base} Z`;

  return (
    <div ref={ref} style={{ width: '100%', height: H }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        <defs>
          <linearGradient id="sideFxArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.18" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#sideFxArea)" />
        <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="2.5" fill={color} stroke="var(--bg-card)" strokeWidth="1.5" />
      </svg>
    </div>
  );
}

export function SidebarFxWidget() {
  const resp = useExchangeRateStore((s) => s.resp);
  const loading = useExchangeRateStore((s) => s.loading);
  const lastFetched = useExchangeRateStore((s) => s.lastFetched);
  const refresh = useExchangeRateStore((s) => s.refresh);

  // 本地方向（独立于仪表盘走势卡），默认 CNY→JPY
  const [dir, setDir] = React.useState<ExchangeRateDirection>('CNY_JPY');
  const cny2jpy = dir === 'CNY_JPY';

  // baseRate = 1 元人民币能换多少日元（后端只产 CNY->JPY；反向由 toDisplay 取倒数）
  const points = resp?.points ?? [];
  const baseRate = resp?.latest?.price ?? (points.length ? points[points.length - 1].value : 0);
  const hasData = baseRate > 0;
  const rate = toDisplay(baseRate, dir);

  // 展示序列（按方向换算）+ 涨跌（序列首尾）
  const series = points.map((p) => toDisplay(p.value, dir));
  const first = series.length ? series[0] : 0;
  const last = series.length ? series[series.length - 1] : rate;
  const pct = first ? ((last - first) / first) * 100 : 0;
  const up = last - first >= 0;

  // 小数位：CNY→JPY 用 4 位，JPY→CNY 值小用 6 位（与仪表盘一致）
  const decimals = cny2jpy ? 4 : 6;

  // 更新时间：优先后端报价时间 latest.time（unix 秒），否则前端 lastFetched
  const updatedAt =
    resp?.latest?.time != null ? new Date(resp.latest.time * 1000)
    : lastFetched != null ? new Date(lastFetched)
    : null;

  const hasChart = hasData && series.length > 1;
  const onRefresh = () => { void refresh(true); };

  return (
    <div className="side-fx">
      <div className="side-fx-head">
        <span className="side-fx-title">
          <Icon.Globe size={12} />
          汇率走势
        </span>
        <button className="side-fx-refresh" title="刷新最新汇率" onClick={onRefresh} disabled={loading}>
          <span style={{ display: 'inline-flex', animation: loading ? 'spin 0.8s linear infinite' : 'none' }}>
            <Icon.Refresh size={11} />
          </span>
        </button>
      </div>

      {/* 货币切换器靠右展示 */}
      <div className="tab-bar side-fx-tabs">
        {([
          { k: 'CNY_JPY' as ExchangeRateDirection, t: 'CNY→JPY' },
          { k: 'JPY_CNY' as ExchangeRateDirection, t: 'JPY→CNY' },
        ]).map((o) => (
          <button
            key={o.k}
            className={`tab-btn ${dir === o.k ? 'active' : ''}`}
            onClick={() => setDir(o.k)}
          >
            {o.t}
          </button>
        ))}
      </div>

      <div className="side-fx-main">
        <span className="side-fx-rate mono">{hasData ? rate.toFixed(decimals) : '—'}</span>
        {hasChart && (
          <span className={`side-fx-delta mono ${up ? 'up' : 'down'}`}>
            {up ? '▲' : '▼'} {up ? '+' : '−'}
            {Math.abs(pct).toFixed(2)}%
          </span>
        )}
      </div>

      {hasChart ? (
        <Sparkline values={series} up={up} />
      ) : (
        <div className="side-fx-empty">{loading ? '加载中…' : '暂无走势'}</div>
      )}

      <div className="side-fx-foot mono">
        更新于 {updatedAt ? updatedAt.toLocaleTimeString('zh-CN', { hour12: false }) : '—'}
      </div>
    </div>
  );
}
