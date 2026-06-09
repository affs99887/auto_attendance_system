// 汇率板块 — 人民币 / 日元 (CNY ⇄ JPY)
// 设计稿 fx.jsx 的 TS 化：FxChart（纯 SVG 走势图）/ FxConverter（换算器）/ FxSection（容器）。
// 数据接真实 store useExchangeRateStore（后端只产 CNY->JPY，JPY->CNY 由 toDisplay 取倒数），不使用设计稿的合成数据。
import * as React from 'react';
import { Icon } from '../lib/icons';
import {
  useExchangeRateStore,
  toDisplay,
  type ExchangeRateRange,
  type ExchangeRateDirection,
} from '../store/exchangeRate';
import type { ExchangeRatePoint } from '../lib/api';

// 区间 tab 定义（与 store 的 ExchangeRateRange 一一对应）
const FX_RANGES: { key: ExchangeRateRange; label: string }[] = [
  { key: '7d', label: '7天' },
  { key: '30d', label: '30天' },
  { key: 'quarter', label: '季度' },
  { key: 'year', label: '年' },
  { key: '3y', label: '3年' },
];

// 短区间（7d/30d/quarter）x 轴显示 MM-DD；长区间（year/3y）显示 YY/MM
const SHORT_RANGES = new Set<ExchangeRateRange>(['7d', '30d', 'quarter']);

// unix 秒 → MM-DD
function fmtMD(t: number): string {
  const d = new Date(t * 1000);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
// unix 秒 → YY/MM
function fmtYM(t: number): string {
  const d = new Date(t * 1000);
  return `${String(d.getFullYear()).slice(2)}/${String(d.getMonth() + 1).padStart(2, '0')}`;
}

// 展示用序列点：值已按方向换算（CNY->JPY 原值；JPY->CNY 取倒数），label 已格式化
interface SeriesPoint {
  v: number;
  label: string;
}

// --- 响应式测量容器宽度 ---
function useMeasure(): [React.RefObject<HTMLDivElement>, number] {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useLayoutEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const update = () => setW(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

// --- 走势折线图（纯 SVG）---
function FxChart({ series, direction }: { series: SeriesPoint[]; direction: ExchangeRateDirection }) {
  const [wrapRef, W] = useMeasure();
  const [hover, setHover] = React.useState<number | null>(null);
  const H = 248;
  const padL = 52, padR = 16, padT = 16, padB = 26;
  const innerW = Math.max(W - padL - padR, 10);
  const innerH = H - padT - padB;

  const vals = series.map((p) => p.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const span = (hi - lo) || hi * 0.01;
  lo -= span * 0.18; hi += span * 0.18;
  // y 轴价标小数位：CNY->JPY=3；JPY->CNY=5（与设计稿一致）
  const decimals = direction === 'CNY_JPY' ? 3 : 5;

  const x = (i: number) =>
    padL + (series.length === 1 ? innerW / 2 : (i / (series.length - 1)) * innerW);
  const y = (v: number) => padT + innerH - ((v - lo) / (hi - lo)) * innerH;

  const linePath = series
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`)
    .join(' ');
  const areaPath = `${linePath} L${x(series.length - 1).toFixed(1)},${(padT + innerH).toFixed(1)} L${x(0).toFixed(1)},${(padT + innerH).toFixed(1)} Z`;

  // y 网格线（4 等分 → 5 条）
  const ticks = 4;
  const gridVals = Array.from({ length: ticks + 1 }, (_, i) => lo + ((hi - lo) * i) / ticks);
  // x 标签：~6 个均匀采样，末点必含
  const xStep = Math.max(1, Math.ceil(series.length / 6));
  const tickIdx: number[] = [];
  for (let i = 0; i < series.length; i += xStep) tickIdx.push(i);
  const lastI = series.length - 1;
  if (tickIdx[tickIdx.length - 1] !== lastI) {
    if (lastI - tickIdx[tickIdx.length - 1] < xStep * 0.6) tickIdx[tickIdx.length - 1] = lastI;
    else tickIdx.push(lastI);
  }

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    let idx = Math.round(((mx - padL) / innerW) * (series.length - 1));
    idx = Math.max(0, Math.min(series.length - 1, idx));
    setHover(idx);
  };

  // 涨绿跌红
  const up = series[series.length - 1].v >= series[0].v;
  const lineColor = up ? 'var(--success)' : 'var(--danger)';

  return (
    <div ref={wrapRef} style={{ width: '100%', position: 'relative' }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        <defs>
          <linearGradient id="fxArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.16" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* 网格 + y 价标 */}
        {gridVals.map((gv, i) => (
          <g key={i}>
            <line x1={padL} y1={y(gv)} x2={W - padR} y2={y(gv)} stroke="var(--border-soft)" strokeWidth="1" />
            <text
              x={padL - 8}
              y={y(gv) + 3}
              textAnchor="end"
              fontSize="10"
              fill="var(--text-muted)"
              fontFamily="var(--font-mono)"
            >
              {gv.toFixed(decimals)}
            </text>
          </g>
        ))}
        {/* x 标签 */}
        {tickIdx.map((i) => {
          const p = series[i];
          return (
            <text
              key={i}
              x={x(i)}
              y={H - 8}
              textAnchor="middle"
              fontSize="10"
              fill="var(--text-muted)"
              fontFamily="var(--font-mono)"
            >
              {p.label}
            </text>
          );
        })}
        <path d={areaPath} fill="url(#fxArea)" />
        <path
          d={linePath}
          fill="none"
          stroke={lineColor}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {/* 最新点 marker */}
        <circle
          cx={x(series.length - 1)}
          cy={y(series[series.length - 1].v)}
          r="3.5"
          fill={lineColor}
          stroke="var(--bg-card)"
          strokeWidth="2"
        />
        {/* hover 十字线 + 点 */}
        {hover != null && (
          <g>
            <line
              x1={x(hover)}
              y1={padT}
              x2={x(hover)}
              y2={padT + innerH}
              stroke="var(--text-muted)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            <circle cx={x(hover)} cy={y(series[hover].v)} r="4" fill={lineColor} stroke="var(--bg-card)" strokeWidth="2" />
          </g>
        )}
        <rect
          x={padL}
          y={padT}
          width={innerW}
          height={innerH}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        />
      </svg>
      {hover != null && (
        <div
          style={{
            position: 'absolute',
            top: 6,
            left: Math.min(Math.max(x(hover) - 56, 4), W - 116),
            background: 'var(--bg-card)',
            border: '1px solid var(--border-strong)',
            borderRadius: 'var(--radius)',
            boxShadow: 'var(--shadow)',
            padding: '6px 9px',
            pointerEvents: 'none',
            minWidth: 104,
          }}
        >
          <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {series[hover].label}
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
            {series[hover].v.toFixed(decimals)}
          </div>
        </div>
      )}
    </div>
  );
}

// --- 汇率换算器 ---
function FxConverter({
  direction,
  rate,
  onSwap,
}: {
  direction: ExchangeRateDirection;
  rate: number;
  onSwap: () => void;
}) {
  const cny2jpy = direction === 'CNY_JPY';
  const [amount, setAmount] = React.useState(cny2jpy ? '100' : '10000');
  const from = cny2jpy ? { code: 'CNY', name: '人民币' } : { code: 'JPY', name: '日元' };
  const to = cny2jpy ? { code: 'JPY', name: '日元' } : { code: 'CNY', name: '人民币' };
  const num = parseFloat(amount) || 0;
  const out = num * rate;
  const outStr = cny2jpy
    ? out.toLocaleString('ja-JP', { maximumFractionDigits: 0 })
    : out.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // 切换方向后重置默认输入值
  React.useEffect(() => {
    setAmount(cny2jpy ? '100' : '10000');
  }, [cny2jpy]);

  const quicks = cny2jpy ? [100, 500, 1000, 5000] : [10000, 50000, 100000, 500000];
  const refs = cny2jpy ? [10, 100, 1000, 10000] : [1000, 10000, 100000, 1000000];

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="card-header">
        <div className="card-title">汇率转换器</div>
        <span className="pill pill-neutral mono">{rate.toFixed(cny2jpy ? 4 : 6)}</span>
      </div>
      <div className="card-body" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="fx-conv-field">
          <div className="fx-conv-cur">
            <span className="fx-conv-code mono">{from.code}</span>
            <span className="fx-conv-name">{from.name}</span>
          </div>
          <input
            className="input mono fx-conv-input"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ''))}
          />
        </div>

        <div className="fx-swap-wrap">
          <div className="fx-swap-line"></div>
          <button className="btn btn-ico fx-swap-btn" title="切换方向" onClick={onSwap}>
            <Icon.Refresh size={13} />
          </button>
        </div>

        <div className="fx-conv-field readonly">
          <div className="fx-conv-cur">
            <span className="fx-conv-code mono">{to.code}</span>
            <span className="fx-conv-name">{to.name}</span>
          </div>
          <div className="fx-conv-input mono fx-conv-out">{outStr}</div>
        </div>

        <div className="muted" style={{ fontSize: 11, lineHeight: 1.6, marginTop: 2 }}>
          1 {from.code} ={' '}
          <span className="mono" style={{ color: 'var(--text-secondary)' }}>
            {rate.toFixed(cny2jpy ? 4 : 6)}
          </span>{' '}
          {to.code} · 按最新汇率换算
        </div>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {quicks.map((q) => (
            <button key={q} className="btn btn-sm" style={{ flex: 1 }} onClick={() => setAmount(String(q))}>
              {q.toLocaleString()}
            </button>
          ))}
        </div>
        <div className="divider"></div>
        <div className="kicker" style={{ marginBottom: 2 }}>
          快捷对照 · 按最新汇率
        </div>
        <div className="fx-ref">
          {refs.map((a) => (
            <div className="fx-ref-row" key={a}>
              <span className="fx-ref-from mono">
                {a.toLocaleString()} {from.code}
              </span>
              <span className="fx-ref-to mono">
                {cny2jpy
                  ? '¥ ' + (a * rate).toLocaleString('ja-JP', { maximumFractionDigits: 0 })
                  : '¥ ' + (a * rate).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                <span className="muted" style={{ marginLeft: 4, fontWeight: 400 }}>
                  {to.code}
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- 板块容器：接真实 store ---
export function FxSection() {
  const resp = useExchangeRateStore((s) => s.resp);
  const range = useExchangeRateStore((s) => s.range);
  const direction = useExchangeRateStore((s) => s.direction);
  const loading = useExchangeRateStore((s) => s.loading);
  const lastFetched = useExchangeRateStore((s) => s.lastFetched);
  const setRange = useExchangeRateStore((s) => s.setRange);
  const setDirection = useExchangeRateStore((s) => s.setDirection);
  const refresh = useExchangeRateStore((s) => s.refresh);

  const cny2jpy = direction === 'CNY_JPY';

  // 展示序列：把后端 points（CNY->JPY）按方向换算 + 格式化 x 标签
  const series: SeriesPoint[] = React.useMemo(() => {
    const points: ExchangeRatePoint[] = resp?.points ?? [];
    const labeler = SHORT_RANGES.has(range) ? fmtMD : fmtYM;
    return points.map((p) => ({ v: toDisplay(p.value, direction), label: labeler(p.t) }));
  }, [resp, range, direction]);

  const hasData = series.length > 0;
  // 头部大数字：优先用 latest.price，否则取序列末值
  const rate = resp?.latest
    ? toDisplay(resp.latest.price, direction)
    : hasData
      ? series[series.length - 1].v
      : 0;

  // 涨跌：用展示序列首尾
  const first = hasData ? series[0].v : 0;
  const last = hasData ? series[series.length - 1].v : 0;
  const delta = last - first;
  const pct = first ? (delta / first) * 100 : 0;
  const up = delta >= 0;
  // 头部 / 换算器小数位：CNY->JPY=4；JPY->CNY=6
  const decimals = cny2jpy ? 4 : 6;

  const pair = cny2jpy
    ? { from: 'CNY', to: 'JPY', label: '人民币 → 日元' }
    : { from: 'JPY', to: 'CNY', label: '日元 → 人民币' };

  // 更新时间：优先后端报价时间 latest.time（unix 秒），否则前端 lastFetched
  const updatedAt =
    resp?.latest?.time != null
      ? new Date(resp.latest.time * 1000)
      : lastFetched != null
        ? new Date(lastFetched)
        : null;

  return (
    <div className="grid" style={{ gridTemplateColumns: '1.6fr 1fr', gap: 16, alignItems: 'stretch' }}>
      <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="card-header">
          <div className="row gap-2" style={{ alignItems: 'center', minWidth: 0 }}>
            <Icon.Globe size={16} />
            <div style={{ minWidth: 0 }}>
              <div className="card-title">汇率走势</div>
              <div className="card-sub">
                {pair.from}/{pair.to} · {pair.label} · 中间价
              </div>
            </div>
          </div>
          <div className="tab-bar" style={{ flexShrink: 0 }}>
            {([
              { k: 'CNY_JPY' as ExchangeRateDirection, t: 'CNY → JPY' },
              { k: 'JPY_CNY' as ExchangeRateDirection, t: 'JPY → CNY' },
            ]).map((o) => (
              <button
                key={o.k}
                className={`tab-btn ${direction === o.k ? 'active' : ''}`}
                onClick={() => setDirection(o.k)}
              >
                {o.t}
              </button>
            ))}
          </div>
        </div>
        <div className="card-body" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div className="row spread" style={{ alignItems: 'flex-end' }}>
            <div className="row" style={{ alignItems: 'baseline', gap: 10 }}>
              <div className="mono" style={{ fontSize: 32, fontWeight: 600, lineHeight: 1 }}>
                {hasData ? rate.toFixed(decimals) : '—'}
              </div>
              {hasData && (
                <div
                  className="mono"
                  style={{ fontSize: 13, fontWeight: 600, color: up ? 'var(--success)' : 'var(--danger)' }}
                >
                  {up ? '▲' : '▼'} {Math.abs(delta).toFixed(decimals)} ({up ? '+' : '−'}
                  {Math.abs(pct).toFixed(2)}%)
                </div>
              )}
            </div>
            <div className="muted" style={{ fontSize: 11, textAlign: 'right' }}>
              <div>
                1 {pair.from} = {hasData ? rate.toFixed(decimals) : '—'} {pair.to}
              </div>
              <div className="mono" style={{ marginTop: 2 }}>
                更新于 {updatedAt ? updatedAt.toLocaleTimeString('zh-CN', { hour12: false }) : '—'}
              </div>
            </div>
          </div>
          <div className="row spread" style={{ marginTop: 8, flexWrap: 'wrap', rowGap: 8 }}>
            <div className="tab-bar">
              {FX_RANGES.map((r) => (
                <button
                  key={r.key}
                  className={`tab-btn ${range === r.key ? 'active' : ''}`}
                  onClick={() => setRange(r.key)}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <button className="btn btn-sm" title="手动刷新最新汇率" onClick={() => void refresh(true)} disabled={loading}>
              <span style={{ display: 'inline-flex', animation: loading ? 'spin 0.8s linear infinite' : 'none' }}>
                <Icon.Refresh size={12} />
              </span>
              {loading ? '刷新中…' : '刷新'}
            </button>
          </div>
          {hasData ? (
            <FxChart series={series} direction={direction} />
          ) : (
            <div
              className="muted"
              style={{
                height: 248,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 13,
              }}
            >
              {loading ? '加载中…' : '暂无数据'}
            </div>
          )}
        </div>
      </div>

      <FxConverter
        direction={direction}
        rate={rate}
        onSwap={() => setDirection(cny2jpy ? 'JPY_CNY' : 'CNY_JPY')}
      />
    </div>
  );
}
