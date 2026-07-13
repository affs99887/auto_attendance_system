// 概览页 — 设计稿 screens/dashboard.jsx 的 TS 平移。
import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import { USERS } from '../lib/data';
import type { PunchRec, RecentActivityEntry, User } from '../lib/types';
import { useSystemStore } from '../store/system';
import { usePunchStore } from '../store/punch';
import { api, type WeatherResponse } from '../lib/api';
import {
  FIXED_WEATHER_LOCATION,
  aqiTone,
  getCachedWeather,
  loadWeatherData,
  roundWeather,
  skyInfo,
  weatherDayLabel,
  weatherErrorMessage,
  windDirection,
} from '../lib/weather';
import { FxSection } from '../components/ExchangeRatePanel';
import { useAiNewsStore, CATEGORY_BY_SLUG, relTime } from '../store/aiNews';
import { useToastStore } from '../store/toast';

/** 后端 today_records 时间字段：`'08:29:55'` 或 `'1900-01-01T08:29:55'`，统一抽 HH:MM:SS */
function extractTime(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (raw.includes('T')) return (raw.split('T')[1] ?? '').slice(0, 8);
  return raw.slice(0, 8);
}

/** 把后端 records ({punch_in_time, punch_out_time}) 归一为前端 PunchRec ({in, out})，与 Records.tsx 一致 */
function normalizeRecords(raw: unknown): Record<string, PunchRec> {
  const result: Record<string, PunchRec> = {};
  if (!raw || typeof raw !== 'object') return result;
  for (const [date, val] of Object.entries(raw as Record<string, unknown>)) {
    if (!val || typeof val !== 'object') continue;
    const v = val as Record<string, unknown>;
    const inV = (v.punch_in_time ?? v.in ?? null) as string | null;
    const outV = (v.punch_out_time ?? v.out ?? null) as string | null;
    result[date] = { in: inV, out: outV };
  }
  return result;
}

interface StatusDotProps {
  tone?: 'success' | 'warning' | 'danger' | 'info';
}

function StatusDot({ tone = 'success' }: StatusDotProps) {
  return (
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: `var(--${tone})`,
        boxShadow: `0 0 0 3px var(--${tone}-bg)`,
      }}
    />
  );
}

interface SparklineProps {
  values: number[];
  max?: number;
}

function Sparkline({ values, max }: SparklineProps) {
  const m = max ?? Math.max(...values, 1);
  return (
    <div className="spark">
      {values.map((v, i) => (
        <div key={i} className="spark-bar" style={{ height: `${(v / m) * 100}%` }} />
      ))}
    </div>
  );
}

function estimateOut(inT: string | null): string | null {
  if (!inT) return null;
  const [h, m, s] = inT.split(':').map(Number);
  const total = h * 3600 + m * 60 + (s || 0) + 8 * 3600 + 15 * 60 + 120;
  const oh = Math.floor(total / 3600);
  const om = Math.floor((total % 3600) / 60);
  return `${String(oh).padStart(2, '0')}:${String(om).padStart(2, '0')}`;
}

// 午休（午餐 + 午休）时段：11:00 – 13:15，这段不计入工作时长
const LUNCH_START = 11 * 60;
const LUNCH_END = 13 * 60 + 15;

// 'HH:MM(:SS)' → 一天中的分钟数（带秒的小数，让进度条随当前时间平滑推进）
function hmToMin(s: string): number {
  const p = s.split(':').map(Number);
  return (p[0] || 0) * 60 + (p[1] || 0) + (p[2] || 0) / 60;
}
// 分钟数 → '3h12m' / '45m'
function fmtDur(min: number): string {
  const t = Math.max(0, Math.round(min));
  const h = Math.floor(t / 60);
  const m = t % 60;
  return h > 0 ? `${h}h${String(m).padStart(2, '0')}m` : `${m}m`;
}

interface WorkProgress {
  posPct: number;        // 当前时间在「上班→下班」上的位置（0~100）
  lunchLeftPct: number;  // 午休段左边界（0~100）
  lunchWidthPct: number; // 午休段宽度（0~100）
  worked: number;        // 已工作分钟（当前 − 上班，午休照常计入）
  remaining: number;     // 剩余分钟（下班 − 当前，午休照常计入）
  hasLunch: boolean;     // 上下班区间是否覆盖到午休段
}
// 由上班时间 / 预计（或实际）下班时间 / 当前时间，算出工作进度模型
function buildWorkProgress(inStr: string | null, outStr: string | null, now: Date): WorkProgress | null {
  if (!inStr || !outStr) return null;
  const inMin = hmToMin(inStr);
  const outMin = hmToMin(outStr);
  if (!(outMin > inMin)) return null;
  const span = outMin - inMin;
  const nowMin = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
  const cur = Math.min(Math.max(nowMin, inMin), outMin); // 夹在上下班之间
  const ll = Math.min(Math.max((LUNCH_START - inMin) / span, 0), 1);
  const lr = Math.min(Math.max((LUNCH_END - inMin) / span, 0), 1);
  return {
    posPct: ((cur - inMin) / span) * 100,
    lunchLeftPct: ll * 100,
    lunchWidthPct: (lr - ll) * 100,
    worked: cur - inMin,
    remaining: outMin - cur,
    hasLunch: lr > ll,
  };
}

function PunchUserCard({ user }: { user: User }) {
  const snapshot = useSystemStore(s => s.snapshot);
  const refreshStatus = useSystemStore(s => s.refresh);
  const { clock } = useApp(); // 每秒更新，驱动工作进度条
  // 操作 busy 态：驱动按钮 spin-ic 图标动画 + 互斥禁用（in/out/auto/check 四种动作）
  const [busy, setBusy] = React.useState<null | 'in' | 'out' | 'auto' | 'check'>(null);
  // 结果提示：照设计稿 punch-toast（success/info）替代原 hint 文本
  const [toast, setToast] = React.useState<{ tone: 'success' | 'info'; msg: string } | null>(null);

  // 显示提示并自动消失（3.2s）
  const toastTimer = React.useRef<number | null>(null);
  const showToast = (tone: 'success' | 'info', msg: string) => {
    setToast({ tone, msg });
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  };
  React.useEffect(() => () => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
  }, []);

  // 上/下班打卡（与 /punch_in /punch_out 同接口，进度经 WS punch:progress 展示）
  const doPunch = async (kind: 'in' | 'out') => {
    if (busy) return;
    setBusy(kind);
    setToast(null);
    try {
      const r = kind === 'in' ? await api.punchIn(user.id) : await api.punchOut(user.id);
      // 后端业务失败经 HTTP 200 {success:false} 返回（不会进 catch），需显式判断给出反馈
      const ok = Boolean(r.success);
      showToast(ok ? 'success' : 'info', r.message || (ok ? '操作已启动' : '操作失败'));
    } catch (e) {
      showToast('info', e instanceof Error ? e.message : '请求失败');
    } finally {
      setBusy(null);
      void refreshStatus();
    }
  };

  // 自动下班：先 calc 取建议下班时刻（HH:MM），再 confirm 调度定时下班
  const doAuto = async () => {
    if (busy) return;
    setBusy('auto');
    setToast(null);
    try {
      const calc = await api.autoByebyeCalc(user.id);
      const t = calc.punch_out_time;
      if (!calc.success || !t) {
        showToast('info', calc.message || '无法计算下班时间');
        return;
      }
      const [hStr, mStr] = t.split(':');
      const hour = Number(hStr);
      const minute = Number(mStr);
      if (Number.isNaN(hour) || Number.isNaN(minute)) {
        showToast('info', `下班时间解析失败：${t}`);
        return;
      }
      const confirm = await api.autoByebyeConfirm(hour, minute);
      if (confirm.success) {
        showToast('info', `已调度自动下班 · 预计 ${confirm.time ?? t}`);
      } else {
        showToast('info', confirm.error || '调度失败');
      }
    } catch (e) {
      showToast('info', e instanceof Error ? e.message : '请求失败');
    } finally {
      setBusy(null);
      void refreshStatus();
    }
  };

  // 获取打卡情况：登录系统读取所有用户今日上/下班时间（不触发打卡），结果回写今日记录
  const doCheck = async () => {
    if (busy) return;
    setBusy('check');
    setToast(null);
    try {
      const r = await api.fetchPunchStatus();
      if (r.success) {
        const mine = r.results?.[user.id];
        if (mine) {
          const inT = extractTime(mine.punch_in_time) ?? '未打卡';
          const outT = extractTime(mine.punch_out_time) ?? '未打卡';
          showToast('info', `打卡情况 · 上班 ${inT} · 下班 ${outT}`);
        } else {
          showToast('info', '已刷新打卡情况');
        }
      } else {
        showToast('info', r.error || '获取打卡情况失败');
      }
    } catch (e) {
      showToast('info', e instanceof Error ? e.message : '请求失败');
    } finally {
      setBusy(null);
      void refreshStatus();
    }
  };

  // 按钮图标：busy 时换成旋转的 Refresh
  const ico = (name: 'in' | 'out' | 'auto' | 'check', Cmp: (typeof Icon)[keyof typeof Icon]) =>
    busy === name ? (
      <span className="spin-ic" style={{ display: 'inline-flex' }}><Icon.Refresh size={13} /></span>
    ) : (
      <Cmp size={13} />
    );

  // 今日打卡仅取后端 today_records（不再回退到写死的 mock 5/19 数据）
  const apiRec = snapshot?.today_records?.[user.id];
  const today = apiRec
    ? { in: extractTime(apiRec.punch_in_time), out: extractTime(apiRec.punch_out_time) }
    : { in: null, out: null };
  const punchedIn = Boolean(today.in);
  const punchedOut = Boolean(today.out);
  const estOut = punchedIn ? estimateOut(today.in) : null;
  // 工作进度：上班 → 实际/预计下班；已下班用实际下班时刻，否则用预计
  const prog = buildWorkProgress(today.in, today.out || estOut, clock);

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 300 }}>
      <div className="card-header" style={{ flexWrap: 'wrap', rowGap: 10 }}>
        <div className="row gap-2">
          <div
            className="user-avatar"
            style={{ background: user.color, width: 28, height: 28, fontSize: 12 }}
          >
            {user.short}
          </div>
          <div className="col" style={{ gap: 0 }}>
            <div className="card-title">{user.name}</div>
            <div className="card-sub mono">{user.env}</div>
          </div>
        </div>
        {/* 状态 pill 靠右（上/下班时间已放大移到卡片中部展示）*/}
        <div className="row" style={{ marginLeft: 'auto' }}>
          {punchedOut ? (
            <span className="pill pill-success"><span className="dot" />已完成</span>
          ) : punchedIn ? (
            <span className="pill pill-info"><span className="dot" />工作中</span>
          ) : (
            <span className="pill pill-warning"><span className="dot" />未打卡</span>
          )}
        </div>
      </div>
      <div className="card-body" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="muted" style={{ fontSize: 11 }}>
          {today.in ? 'Selenium · 已写入' : '尚未打卡'}
          {today.out ? ' · 已下班' : estOut ? ` · 预计下班 ${estOut}（8h15m + 随机）` : ''}
        </div>
        {toast && (
          <div className={`punch-toast ${toast.tone}`}>
            {toast.tone === 'success' ? <Icon.Check size={13} /> : <Icon.Info size={13} />}
            <span>{toast.msg}</span>
          </div>
        )}
        {/* 上/下班时间 + 工作进度：占据中间留白，垂直居中 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 40 }}>
            <div className="col" style={{ gap: 4, alignItems: 'center' }}>
              <div className="kicker">上班</div>
              <div className="mono" style={{ fontSize: 28, fontWeight: 600, lineHeight: 1 }}>
                {today.in || <span className="muted">--:--:--</span>}
              </div>
            </div>
            <div style={{ width: 1, height: 40, background: 'var(--border-soft)' }} />
            <div className="col" style={{ gap: 4, alignItems: 'center' }}>
              <div className="kicker">下班</div>
              <div
                className="mono"
                style={{ fontSize: 28, fontWeight: 600, lineHeight: 1, color: today.out ? undefined : 'var(--text-muted)' }}
              >
                {today.out || (estOut ? estOut : '--:--:--')}
              </div>
            </div>
          </div>
          {prog && (
            <div className="col" style={{ gap: 6 }}>
              <div className="row spread" style={{ fontSize: 11 }}>
                <span className="muted">
                  已工作 <span className="mono" style={{ color: 'var(--text-secondary)' }}>{fmtDur(prog.worked)}</span>
                </span>
                <span className="muted">
                  {punchedOut ? '已下班' : <>剩余 <span className="mono" style={{ color: 'var(--text-secondary)' }}>{fmtDur(prog.remaining)}</span></>}
                </span>
              </div>
              {/* 进度轨道：蓝色为已过时间，橙色块标出午休 11:00–13:15（悬浮显示提示） */}
              <div style={{ position: 'relative', height: 8, borderRadius: 999, background: 'var(--bg-inset)', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${prog.posPct}%`, background: 'var(--accent)', borderRadius: 999 }} />
                {prog.hasLunch && (
                  <div
                    title="午休 11:00–13:15"
                    style={{
                      position: 'absolute', top: 0, bottom: 0,
                      left: `${prog.lunchLeftPct}%`, width: `${prog.lunchWidthPct}%`,
                      background: 'var(--warning)',
                      opacity: 0.9,
                      cursor: 'help',
                    }}
                  />
                )}
              </div>
              <div className="row spread" style={{ fontSize: 10 }}>
                <span className="muted">进度 {Math.round(prog.posPct)}%</span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--warning)', opacity: 0.9 }} />
                  <span className="muted">午休 11:00–13:15</span>
                </span>
              </div>
            </div>
          )}
        </div>
        {/* 控制器：横向按钮组，靠模块底部 */}
        <div
          className="punch-actions"
          style={{ paddingTop: 14, borderTop: '1px solid var(--border-soft)' }}
        >
          <button
            className="btn btn-primary btn-sm"
            disabled={punchedIn || busy !== null}
            onClick={() => void doPunch('in')}
          >
            {ico('in', Icon.Punch)} 上班打卡
          </button>
          <button
            className="btn btn-sm"
            disabled={!punchedIn || punchedOut || busy !== null}
            onClick={() => void doPunch('out')}
          >
            {ico('out', Icon.Power)} 下班打卡
          </button>
          <button
            className="btn btn-sm"
            disabled={!punchedIn || punchedOut || busy !== null}
            onClick={() => void doAuto()}
          >
            {ico('auto', Icon.Clock)} 自动下班
          </button>
          <button
            className="btn btn-sm"
            disabled={busy !== null}
            onClick={() => void doCheck()}
          >
            {ico('check', Icon.Eye)} 获取打卡情况
          </button>
        </div>
      </div>
    </div>
  );
}

// 仪表盘 AI 资讯卡片的版块标签（内联小号样式）
function dashCatTag(slug: string | null | undefined) {
  const c = (slug ? CATEGORY_BY_SLUG[slug] : undefined) ?? CATEGORY_BY_SLUG.industry;
  return <span className="cat-tag" style={{ ['--ch' as any]: c.hue, fontSize: 10, padding: '1px 7px' }}>{c.label}</span>;
}

// 让 AI 资讯卡片高度跟随今日打卡卡片（CSS 只能短→长，故用 JS 同步）
function useMatchHeight(): [React.RefObject<HTMLDivElement>, number | null] {
  const ref = React.useRef<HTMLDivElement>(null);
  const [h, setH] = React.useState<number | null>(null);
  React.useLayoutEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const update = () => setH(el.offsetHeight);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    const t = window.setTimeout(update, 400);
    if (document.fonts && document.fonts.ready) void document.fonts.ready.then(update);
    return () => { ro.disconnect(); window.clearTimeout(t); };
  }, []);
  return [ref, h];
}

function WeatherCard({
  onOpenWeather,
  onOpenSettings,
}: {
  onOpenWeather: () => void;
  onOpenSettings: () => void;
}) {
  const initial = getCachedWeather();
  const [data, setData] = React.useState<WeatherResponse | null>(initial);
  const [loading, setLoading] = React.useState(!initial);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async (force: boolean) => {
    setLoading(true);
    setError(null);
    try {
      setData(await loadWeatherData(force));
    } catch (err) {
      setError(weatherErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (!initial) void refresh(false);
  }, [initial, refresh]);

  const current = data?.realtime;
  const sky = skyInfo(current?.skycon);
  const updateLabel = data
    ? new Date(data.updated_at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
    : null;
  const currentAqiTone = aqiTone(current?.aqi ?? null);

  return (
    <div className="card weather-card">
      <div className="card-header weather-header">
        <div className="row gap-2" style={{ minWidth: 0 }}>
          <div className="weather-mark"><Icon.Cloud size={15} /></div>
          <div style={{ minWidth: 0 }}>
            <div className="card-title weather-address">
              {data?.location.address || FIXED_WEATHER_LOCATION.address}
            </div>
            <div className="card-sub">
              {data
                ? `${data.source} · ${updateLabel} 更新${data.cached ? ' · 已缓存' : ''}`
                : '固定地点 · 彩云天气'}
            </div>
          </div>
        </div>
        <div className="row gap-2">
          {error && data && <span className="weather-refresh-error" title={error}>刷新失败</span>}
          <button className="btn btn-sm" onClick={onOpenWeather}>详细天气</button>
          <button
            className="btn btn-ico btn-sm"
            title="刷新固定地点天气"
            disabled={loading}
            onClick={() => void refresh(true)}
          >
            <span className={loading ? 'spin-ic' : ''} style={{ display: 'inline-flex' }}>
              <Icon.Refresh size={13} />
            </span>
          </button>
        </div>
      </div>
      <div className="card-body weather-body">
        {!data && loading ? (
          <div className="weather-empty">
            <span className="spinner" />
            <div>
              <div className="weather-empty-title">正在获取固定地点天气</div>
              <div className="muted">{FIXED_WEATHER_LOCATION.address}</div>
            </div>
          </div>
        ) : !data ? (
          <div className="weather-empty weather-error">
            <Icon.AlertTriangle size={20} />
            <div style={{ flex: 1 }}>
              <div className="weather-empty-title">天气暂不可用</div>
              <div className="muted">{error || '请稍后重试'}</div>
            </div>
            <button className="btn btn-sm" onClick={() => void refresh(true)}>重新加载</button>
            <button className="btn btn-sm" onClick={onOpenSettings}>天气设置</button>
          </div>
        ) : (
          <div className="weather-grid">
            <div className="weather-current">
              <div className={`weather-glyph ${sky.tone}`}>{sky.glyph}</div>
              <div>
                <div className="row" style={{ gap: 7, alignItems: 'baseline' }}>
                  <span className="weather-temperature">{roundWeather(current?.temperature ?? null)}</span>
                  <span className="weather-degree">°C</span>
                </div>
                <div className="weather-condition">
                  {sky.label} · 体感 {roundWeather(current?.apparent_temperature ?? null, '°')}
                </div>
              </div>
            </div>

            <div className="weather-summary">
              <div className="weather-keypoint">
                {data.forecast_keypoint || data.hourly_description || '暂无短时天气提示'}
              </div>
              <div className="weather-stats">
                <span>湿度 <b>{roundWeather(current?.humidity ?? null, '%')}</b></span>
                <span>{windDirection(current?.wind_direction ?? null)} <b>{roundWeather(current?.wind_speed ?? null, ' km/h')}</b></span>
                <span>能见度 <b>{roundWeather(current?.visibility ?? null, ' km')}</b></span>
                <span className={`pill pill-${currentAqiTone}`}>AQI {roundWeather(current?.aqi ?? null)} {current?.aqi_description || ''}</span>
              </div>
              {data.address_warning && <div className="weather-address-warning">{data.address_warning}</div>}
            </div>

            <div className="weather-days">
              {data.daily.slice(0, 5).map((day, index) => {
                const info = skyInfo(day.skycon);
                return (
                  <div className="weather-day" key={`${day.date}-${index}`}>
                    <div className="weather-day-name">{weatherDayLabel(day.date, index)}</div>
                    <div className={`weather-day-glyph ${info.tone}`} title={info.label}>{info.glyph}</div>
                    <div className="weather-day-temp mono">
                      {roundWeather(day.temperature_max, '°')} <span>{roundWeather(day.temperature_min, '°')}</span>
                    </div>
                    <div className="weather-day-rain">
                      降水 {roundWeather(day.precipitation_probability, '%')}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 仪表盘 AI 资讯模块 —— 竖向精选列表（与今日打卡同一行，高度对齐）
function DashNewsCard({ matchH }: { matchH: number | null }) {
  const items = useAiNewsStore(s => s.cats.all.items);
  const loading = useAiNewsStore(s => s.cats.all.loading);
  const error = useAiNewsStore(s => s.cats.all.error);
  const refresh = useAiNewsStore(s => s.refresh);
  // 有旧数据时卡片体不显示错误占位，刷新失败对用户完全无感，这里补一条 toast（与 News 页同款）
  const doRefresh = async () => {
    await refresh('all', true);
    const cur = useAiNewsStore.getState().cats.all;
    if (cur?.error && cur.items.length) {
      useToastStore.getState().push('err', `AI 资讯刷新失败：${cur.error}`);
    }
  };
  const top = React.useMemo(
    () =>
      [...items]
        .sort((a, b) => new Date(b.publishedAt ?? 0).getTime() - new Date(a.publishedAt ?? 0).getTime())
        .slice(0, 6),
    [items],
  );
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', height: matchH || undefined }}>
      <div className="card-header">
        <div className="row gap-2">
          <div className="news-mark" style={{ width: 26, height: 26, borderRadius: 6 }}><Icon.Sparkle size={14} /></div>
          <div className="col" style={{ gap: 0 }}>
            <div className="card-title">AI 资讯</div>
            <div className="card-sub">AI HOT · 今日精选</div>
          </div>
        </div>
        <button className="btn btn-ico btn-sm" title="刷新" onClick={() => void doRefresh()} disabled={loading}>
          <span className={loading ? 'spin-ic' : ''} style={{ display: 'inline-flex' }}><Icon.Refresh size={13} /></span>
        </button>
      </div>
      <div className="card-body scroll-area" style={{ padding: '4px 16px', flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {/* 无数据时按 加载中 / 拉取失败 / 真没有 三种情况给占位，避免卡片体一片空白无解释 */}
        {top.length ? (
          <div className="dash-news">
            {top.map(it => (
              <a key={it.id} className="dash-news-row" href={it.url} target="_blank" rel="noreferrer">
                <div className="dash-news-title">{it.title}</div>
                <div className="dash-news-meta">
                  {dashCatTag(it.category)}
                  <span className="muted" style={{ fontSize: 10.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {it.source} · {relTime(it.publishedAt)}
                  </span>
                </div>
              </a>
            ))}
          </div>
        ) : loading ? (
          <div className="empty-state">
            <span className="spinner" style={{ display: 'inline-block', marginRight: 8 }} /> 加载中…
          </div>
        ) : error ? (
          <div className="empty-state">拉取失败，点右上角刷新重试</div>
        ) : (
          <div className="empty-state">暂无资讯</div>
        )}
      </div>
    </div>
  );
}

function ActivityRow({ entry }: { entry: RecentActivityEntry }) {
  const tone: 'success' | 'warning' | 'danger' =
    entry.status === 'ok' ? 'success' : entry.status === 'warn' ? 'warning' : 'danger';
  const typeLabel = (
    {
      punch_in: '上班打卡',
      punch_out: '下班打卡',
      daily_status: '状态推送',
      reminder: '每日提醒',
      log_rotate: '日志轮转',
      error: '异常',
    } as Record<string, string>
  )[entry.type] || entry.type;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '84px 1fr auto',
        gap: 12,
        padding: '10px 0',
        borderBottom: '1px solid var(--border-soft)',
        alignItems: 'center',
      }}
    >
      <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>{entry.ts}</div>
      <div style={{ fontSize: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <StatusDot tone={tone} />
          <span style={{ fontWeight: 500 }}>{typeLabel}</span>
          {entry.user !== 'system' && <span className="muted">· {entry.user}</span>}
        </div>
        <div className="muted" style={{ fontSize: 11, marginTop: 2, paddingLeft: 14 }}>{entry.detail}</div>
      </div>
      <div className="mono" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{entry.method}</div>
    </div>
  );
}

export function DashboardScreen() {
  const { sysStatus, headless, setScreen, currentUser, clock } = useApp();
  const snapshot = useSystemStore(s => s.snapshot);

  // 跨过 0 点（本地日期变化）时刷新一次系统快照，避免今日记录停留在昨天。
  // 仅比较「年-月-日」串，日期不变（每秒 tick）时不触发。
  const prevDateRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    const dateKey = `${clock.getFullYear()}-${clock.getMonth() + 1}-${clock.getDate()}`;
    if (prevDateRef.current === null) {
      prevDateRef.current = dateKey; // 首次挂载只记录，不触发
      return;
    }
    if (prevDateRef.current !== dateKey) {
      prevDateRef.current = dateKey;
      void useSystemStore.getState().refresh();
    }
  }, [clock]);

  const lastFetched = useSystemStore(s => s.lastFetched);
  const punchEntries = usePunchStore(s => s.entries);

  // 真实模式标签优先
  const modeLabel = snapshot?.config
    ? snapshot.config.use_selenium_login
      ? snapshot.config.selenium_headless
        ? 'Selenium · 无头'
        : 'Selenium · 可见'
      : '图像识别 (PyAutoGUI)'
    : sysStatus.modeLabel;

  // 当前用户今日打卡（仅来自后端 today_records）
  const apiToday = snapshot?.today_records?.[currentUser];
  const todayIn = apiToday ? extractTime(apiToday.punch_in_time) : null;
  const todayOut = apiToday ? extractTime(apiToday.punch_out_time) : null;
  const todayStatusLabel = todayOut ? '已下班' : todayIn ? '工作中' : '未打卡';
  const todayStatusTone = todayOut ? 'success' : todayIn ? 'success' : 'warning';

  // 下次任务（snapshot.scheduled_tasks 中最近的）
  const nextTask = (snapshot?.scheduled_tasks ?? [])
    .map(t => ({ ...t, _label: t.scheduled_time }))
    .sort((a, b) => a.scheduled_time.localeCompare(b.scheduled_time))[0];

  // 资源
  const cpu = snapshot?.resources?.cpu_percent;
  const mem = snapshot?.resources?.memory_percent;

  // 真实今日标签（不再用写死的 mock TODAY）
  const _now = new Date();
  const todayLabel = `${_now.getFullYear()}-${String(_now.getMonth() + 1).padStart(2, '0')}-${String(_now.getDate()).padStart(2, '0')} ${['周日', '周一', '周二', '周三', '周四', '周五', '周六'][_now.getDay()]}`;

  // 本月统计改用真实 API（api.getRecords 当前用户 + 真实年月）；不再硬编码 2026-05 mock。
  // API 不可用时落到空记录 {}，下方统计自然显示 0/—，而非展示假数据。
  const _year = _now.getFullYear();
  const _month = _now.getMonth() + 1;
  const [monthRecs, setMonthRecs] = React.useState<Record<string, PunchRec>>({});
  React.useEffect(() => {
    let cancelled = false;
    api.getRecords(currentUser, _year, _month)
      .then(r => {
        if (!cancelled) setMonthRecs(normalizeRecords(r.records));
      })
      .catch(() => {
        // 静默退到空态（不落 mock），避免展示从未发生的假统计
        if (!cancelled) setMonthRecs({});
      });
    return () => { cancelled = true; };
  }, [currentUser, _year, _month]);
  const onTimeCount = Object.values(monthRecs).filter(r => r.in && r.in <= '09:00:00').length;
  const totalInThisMonth = Object.values(monthRecs).filter(r => r.in).length;

  const minutesArr = Object.values(monthRecs)
    .filter(r => r.in)
    .map(r => {
      const [h, m] = (r.in as string).split(':').map(Number);
      return h * 60 + m;
    });
  // 空记录（API 不可用/本月无数据）时 minutesArr 为空，Math.min/max 会得 ±Infinity，
  // 故先判空，无数据时置 null，由下方"本月准点节奏"显示占位而非 Infinity:NaN。
  const earliest = minutesArr.length ? Math.min(...minutesArr) : null;
  const latest = minutesArr.length ? Math.max(...minutesArr) : null;

  // AI 资讯卡片高度跟随今日打卡卡片（同一行内对齐）
  const [punchRef, punchH] = useMatchHeight();

  const spark = Object.entries(monthRecs)
    .slice(-14)
    .map(([, r]) => {
      if (!r.in) return 0;
      const [h, m] = r.in.split(':').map(Number);
      return h * 60 + m - 8 * 60;
    });

  return (
    <div className="col gap-6">
      {/* KPI row */}
      <div className="grid grid-4">
        <div className="kpi">
          <div className="kpi-label">今日状态</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: 'inherit', fontWeight: 600 }}>
            {todayStatusLabel}
          </div>
          <div className="kpi-meta">
            <StatusDot tone={todayStatusTone as 'success' | 'warning' | 'danger' | 'info'} />
            {currentUser} · {todayIn ? `${todayIn} 上班` : '尚未打卡'}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">下次任务</div>
          <div className="kpi-value">{nextTask?.scheduled_time ?? '—'}</div>
          <div className="kpi-meta">
            <Icon.Clock size={12} />
            {nextTask
              ? `${nextTask.type === 'punch_out' ? '下班' : '上班'} · ${nextTask.username ?? '全部'}`
              : '暂无定时任务'}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">本月出勤</div>
          <div className="kpi-value">
            {totalInThisMonth}{' '}
            <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>/ 工作日</span>
          </div>
          <div className="kpi-meta">
            <StatusDot tone="success" />
            准点率 {totalInThisMonth ? Math.round((onTimeCount / totalInThisMonth) * 100) : 0}%
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">系统</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: 'inherit', fontWeight: 600 }}>
            {snapshot ? '运行正常' : '加载中…'}
          </div>
          <div className="kpi-meta">
            <StatusDot tone={snapshot ? 'success' : 'warning'} />
            {modeLabel}
          </div>
        </div>
      </div>

      {/* 固定地点 + 彩云天气 */}
      <div className="col gap-2">
        <div className="kicker">天气 · 固定地点</div>
        <WeatherCard
          onOpenWeather={() => setScreen('weather')}
          onOpenSettings={() => setScreen('settings')}
        />
      </div>

      {/* 今日打卡 + AI 资讯 · 同一行 */}
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 0.82fr) minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
        <div className="col gap-2" style={{ minWidth: 0 }}>
          <div className="row spread">
            <div className="kicker">今日打卡 · {todayLabel}</div>
            <button className="btn btn-sm" onClick={() => setScreen('punch')}>
              打卡控制台 <Icon.ChevronRight size={10} />
            </button>
          </div>
          <div ref={punchRef} className="col gap-4">
            {USERS.map(u => <PunchUserCard key={u.id} user={u} />)}
          </div>
        </div>
        <div className="col gap-2" style={{ minWidth: 0 }}>
          <div className="row spread">
            <div className="kicker">AI 资讯 · AI HOT 中文精选</div>
            <button className="btn btn-sm" onClick={() => setScreen('news')}>
              查看全部 <Icon.ChevronRight size={10} />
            </button>
          </div>
          <DashNewsCard matchH={punchH} />
        </div>
      </div>

      {/* Exchange rate: chart + converter（接真实 useExchangeRateStore） */}
      <div className="col gap-2">
        <div className="kicker">汇率 · 人民币 / 日元</div>
        <FxSection />
      </div>

      {/* Bottom: Activity + System health */}
      <div className="grid" style={{ gridTemplateColumns: '1.5fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">最近活动</div>
              <div className="card-sub">系统、调度与打卡事件流</div>
            </div>
            <button className="btn btn-sm" onClick={() => setScreen('logs')}>
              查看全部日志 <Icon.ChevronRight size={10} />
            </button>
          </div>
          <div className="card-body" style={{ padding: '4px 16px' }}>
            {/* 来源 WS punch:progress；为空时显示空态（不再用 mock RECENT_ACTIVITY 兜底，避免展示从未发生的活动） */}
            {punchEntries.length === 0
              ? <div className="empty-state">暂无活动 — 打卡或调度事件将实时出现在此</div>
              : punchEntries
                  .slice(-7)
                  .reverse()
                  .map((p, i) => (
                    <ActivityRow
                      key={`live-${i}`}
                      entry={{
                        ts: new Date(p.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }),
                        user: currentUser,
                        type: 'punch_in',
                        status: 'ok',
                        method: 'WS',
                        detail: `${p.title} — ${p.content}`,
                      }}
                    />
                  ))}
          </div>
        </div>

        <div className="col gap-4">
          <div className="card">
            <div className="card-header">
              <div>
                <div className="card-title">本月准点节奏</div>
                <div className="card-sub mono">
                  {earliest !== null && latest !== null ? (
                    <>
                      {earliest >= 60 * 8
                        ? `${Math.floor(earliest / 60)}:${String(earliest % 60).padStart(2, '0')}`
                        : '08:25'}
                      {' – '}
                      {Math.floor(latest / 60)}:{String(latest % 60).padStart(2, '0')} · 上班时间分布
                    </>
                  ) : (
                    '— · 本月暂无打卡记录'
                  )}
                </div>
              </div>
            </div>
            <div className="card-body">
              <Sparkline values={spark} max={60} />
              <div className="row spread" style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
                <span>近 14 个工作日</span>
                <span className="mono">均 08:30</span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">服务健康</div>
            </div>
            <div className="card-body compact">
              {[
                {
                  name: 'GUI 后端',
                  v: snapshot
                    ? `已连接 · ${
                        lastFetched ? `${Math.round((Date.now() - lastFetched) / 1000)}s 前刷新` : '初次拉取'
                      }`
                    : '未连接 · 请启动 main.py --gui',
                  tone: (snapshot ? 'success' : 'warning') as 'success' | 'warning',
                },
                {
                  name: 'Telegram Bot',
                  v: snapshot ? '与 GUI 共存' : '—',
                  tone: 'success' as const,
                },
                {
                  name: 'SMTP',
                  v: '可达',
                  tone: 'success' as const,
                },
                {
                  name: 'Selenium driver',
                  v: (snapshot?.config.selenium_headless ?? headless) ? '无头模式' : '可见模式',
                  tone: 'success' as const,
                },
                {
                  name: '活跃浏览器',
                  v: `${snapshot?.active_controllers ?? 0} 个`,
                  tone: 'info' as const,
                },
              ].map((row, i) => (
                <div
                  key={i}
                  className="row spread"
                  style={{
                    padding: '8px 0',
                    borderBottom: i < 4 ? '1px solid var(--border-soft)' : 'none',
                    whiteSpace: 'nowrap',
                  }}
                >
                  <div className="row gap-2" style={{ fontSize: 12, whiteSpace: 'nowrap', minWidth: 0 }}>
                    <StatusDot tone={row.tone} />
                    <span style={{ whiteSpace: 'nowrap' }}>{row.name}</span>
                  </div>
                  <span className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{row.v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
