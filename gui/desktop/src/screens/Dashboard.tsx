// 概览页 — 系统状态 KPI + 天气 + 微信转发 + 汇率。
import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import { api } from '../lib/api';
import { useSystemStore } from '../store/system';
import { useStartupStore } from '../store/startup';
import { useWechatBarkStore } from '../store/wechatBark';
import { useToastStore } from '../store/toast';
import {
  selectDefaultWeatherEntry,
  useWeatherStore,
} from '../store/weather';
import { DEFAULT_WEATHER_LOCATION } from '../lib/weatherLocations';
import {
  WeatherOverviewCard,
} from '../components/WeatherPanel';
import { FxSection } from '../components/ExchangeRatePanel';

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

// 秒数 → 「2d 3h」/「3h 05m」/「12m」
function fmtUptime(secs: number): string {
  const t = Math.max(0, Math.floor(secs));
  const d = Math.floor(t / 86400);
  const h = Math.floor((t % 86400) / 3600);
  const m = Math.floor((t % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  return `${m}m`;
}

function WeatherCard({
  onOpenWeather,
  onOpenSettings,
}: {
  onOpenWeather: () => void;
  onOpenSettings: () => void;
}) {
  const startupStatus = useStartupStore(s => s.status);
  const startupReason = useStartupStore(s => s.reason);
  const location = DEFAULT_WEATHER_LOCATION;
  const { data, loading, error, hasAttempted } = useWeatherStore(selectDefaultWeatherEntry);
  const refreshLocation = useWeatherStore(s => s.refreshLocation);

  React.useEffect(() => {
    // Electron 窗口会先于 Python HTTP 服务出现；等统一探活确认 ready 后再首拉，
    // 后端从 starting → ready 时也会自动补拉，避免首次 Failed to fetch 永久停在错误态。
    if (startupStatus === 'ready' && !data && !hasAttempted && !loading) {
      void refreshLocation(DEFAULT_WEATHER_LOCATION.id, false);
    }
  }, [startupStatus, data, hasAttempted, loading, refreshLocation]);

  return (
    <div className="weather-fusion-shell">
      {!data && (loading || (!hasAttempted && startupStatus !== 'failed')) ? (
        <div className="card weather-empty" role="status" aria-live="polite" aria-busy="true">
          <span className="spinner" />
          <div>
            <div className="weather-empty-title">正在获取华山路1076号天气</div>
            <div className="muted">{location.address}</div>
          </div>
        </div>
      ) : !data ? (
        <div className="card weather-empty weather-error" role="alert">
          <Icon.AlertTriangle size={20} />
          <div style={{ flex: 1 }}>
            <div className="weather-empty-title">天气暂不可用</div>
            <div className="muted">
              {error || (startupStatus === 'failed' ? startupReason : null) || '请稍后重试'}
            </div>
          </div>
          <button className="btn btn-sm" onClick={() => void refreshLocation(DEFAULT_WEATHER_LOCATION.id, true)}>重新加载</button>
          <button className="btn btn-sm" onClick={onOpenSettings}>天气设置</button>
        </div>
      ) : (
        <>
          {error && (
            <div className="weather-fusion-inline-error" title={error} role="alert">
              <Icon.AlertTriangle size={13} />刷新失败，当前展示上次成功的数据
            </div>
          )}
          <WeatherOverviewCard
            data={data}
            size="m"
            loading={loading}
            onRefresh={() => void refreshLocation(DEFAULT_WEATHER_LOCATION.id, true)}
            onOpenDetails={onOpenWeather}
          />
        </>
      )}
    </div>
  );
}

// 微信转发（Bark）紧凑卡：监听状态 + 转发窗口速览 + 启停快捷按钮；点卡片其余区域进详情页。
// 数据全部来自 useWechatBarkStore（WS 推送保持新鲜），这里只在就绪后补拉一次兜底。
function WechatBarkCard({ onOpen }: { onOpen: () => void }) {
  const startupStatus = useStartupStore(s => s.status);
  const running = useWechatBarkStore(s => s.running);
  const stopping = useWechatBarkStore(s => s.stopping);
  const platformSupported = useWechatBarkStore(s => s.platformSupported);
  const schedule = useWechatBarkStore(s => s.schedule);
  const hasStatus = useWechatBarkStore(s => s.hasStatus);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    // 与 WeatherCard 同款守卫：等后端探活通过再拉，避免首拉 Failed to fetch
    if (startupStatus !== 'ready') return;
    void useWechatBarkStore.getState().refreshStatus();
    void useWechatBarkStore.getState().refreshSchedule();
  }, [startupStatus]);

  // 启停快捷键（stopPropagation：点按钮不触发卡片跳转）
  const quickToggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setBusy(true);
    try {
      const r = running ? await api.stopWechatBark() : await api.startWechatBark();
      useToastStore.getState().push(
        r.success ? 'ok' : 'err',
        r.message || r.error || (r.success ? '指令已发送' : '操作失败'),
      );
      await useWechatBarkStore.getState().refreshStatus();
    } catch (err) {
      useToastStore.getState().push('err', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const stateLabel = !hasStatus ? '加载中…' : stopping ? '停止中' : running ? '运行中' : '已停止';
  const statePill = stopping ? 'pill-warning' : running ? 'pill-success' : 'pill-neutral';

  return (
    <div
      className="card"
      role="button"
      onClick={onOpen}
      style={{ cursor: 'pointer' }}
      title="打开微信转发详情"
    >
      <div className="card-body compact row" style={{ gap: 14, alignItems: 'center' }}>
        <div className="weather-mark" style={{ flexShrink: 0 }}>
          <Icon.Bell size={14} />
        </div>
        <div className="col" style={{ gap: 3, minWidth: 0, flex: 1 }}>
          <div className="row gap-2" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>微信转发</span>
            <span className={`pill ${statePill}`}><span className="dot" />{stateLabel}</span>
            {schedule && (
              <span className={`pill ${schedule.allowed ? 'pill-success' : 'pill-warning'}`}>
                <span className="dot" />窗口{schedule.allowed ? '允许' : '阻止'}
              </span>
            )}
          </div>
          <div
            className="kicker"
            style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            title={schedule?.reason}
          >
            {schedule
              ? `${schedule.start_time} – ${schedule.end_time} · ${schedule.reason}`
              : hasStatus && !platformSupported
                ? '监听仅 macOS 生效 · 当前平台可先完成配置'
                : '微信通知 → iPhone Bark'}
          </div>
        </div>
        <button
          className="btn btn-sm"
          disabled={busy || stopping || (!running && !platformSupported)}
          title={!running && !platformSupported ? '监听仅支持 macOS' : undefined}
          onClick={quickToggle}
        >
          {running ? <Icon.Power size={11} /> : <Icon.Play size={11} />}
          {stopping ? '停止中…' : running ? '停止监听' : '启动监听'}
        </button>
        <Icon.ChevronRight size={11} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
      </div>
    </div>
  );
}

export function DashboardScreen() {
  const { setScreen, clock } = useApp();
  const snapshot = useSystemStore(s => s.snapshot);
  const lastFetched = useSystemStore(s => s.lastFetched);

  // 跨过 0 点（本地日期变化）时刷新一次系统快照，避免工作日标记停留在昨天。
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

  // 资源占用
  const cpu = snapshot?.resources?.cpu_percent;
  const mem = snapshot?.resources?.memory_percent;

  // 今日日期标签
  const _now = new Date();
  const todayLabel = `${_now.getFullYear()}-${String(_now.getMonth() + 1).padStart(2, '0')}-${String(_now.getDate()).padStart(2, '0')} ${['周日', '周一', '周二', '周三', '周四', '周五', '周六'][_now.getDay()]}`;

  // 工作日 / 节假日标记（后端 chinese_calendar；无快照时显示占位）
  const dayLabel = snapshot
    ? snapshot.is_holiday
      ? '节假日'
      : snapshot.is_workday
        ? '工作日'
        : '休息日'
    : '—';

  const openHomeWeatherDetails = React.useCallback(() => {
    void useWeatherStore.getState()
      .setActiveLocation(DEFAULT_WEATHER_LOCATION.id)
      .then(() => setScreen('weather'));
  }, [setScreen]);

  return (
    <div className="col gap-6">
      {/* KPI row */}
      <div className="grid grid-4">
        <div className="kpi">
          <div className="kpi-label">系统</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: 'inherit', fontWeight: 600 }}>
            {snapshot ? '运行正常' : '加载中…'}
          </div>
          <div className="kpi-meta">
            <StatusDot tone={snapshot ? 'success' : 'warning'} />
            {snapshot
              ? `已连接 · ${lastFetched ? `${Math.round((Date.now() - lastFetched) / 1000)}s 前刷新` : '初次拉取'}`
              : '等待后端就绪'}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">今日</div>
          <div className="kpi-value" style={{ fontSize: 18, fontFamily: 'inherit', fontWeight: 600 }}>
            {dayLabel}
          </div>
          <div className="kpi-meta">
            <Icon.Calendar size={12} />
            {todayLabel}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">CPU 占用</div>
          <div className="kpi-value">
            {typeof cpu === 'number' ? `${Math.round(cpu)}%` : '—'}
          </div>
          <div className="kpi-meta">
            <StatusDot tone={typeof cpu === 'number' && cpu >= 85 ? 'warning' : 'success'} />
            后端进程所在主机
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">内存占用</div>
          <div className="kpi-value">
            {typeof mem === 'number' ? `${Math.round(mem)}%` : '—'}
          </div>
          <div className="kpi-meta">
            <StatusDot tone={typeof mem === 'number' && mem >= 85 ? 'warning' : 'success'} />
            {typeof snapshot?.uptime_seconds === 'number' ? `已运行 ${fmtUptime(snapshot.uptime_seconds)}` : '—'}
          </div>
        </div>
      </div>

      {/* 首页固定地点 + 彩云天气 */}
      <div className="col gap-2">
        <div className="row spread">
          <div className="kicker">天气 · 华山路1076号</div>
          <button className="btn btn-sm" onClick={() => setScreen('weather')}>
            天气详情 <Icon.ChevronRight size={10} />
          </button>
        </div>
        <WeatherCard
          onOpenWeather={openHomeWeatherDetails}
          onOpenSettings={() => setScreen('settings')}
        />
      </div>

      {/* 微信转发（Bark）快捷卡 */}
      <div className="col gap-2">
        <div className="row spread">
          <div className="kicker">微信转发 · Bark 推送</div>
          <button className="btn btn-sm" onClick={() => setScreen('wechatBark')}>
            转发详情 <Icon.ChevronRight size={10} />
          </button>
        </div>
        <WechatBarkCard onOpen={() => setScreen('wechatBark')} />
      </div>

      {/* Exchange rate: chart + converter（接真实 useExchangeRateStore） */}
      <div className="col gap-2">
        <div className="kicker">汇率 · 人民币 / 日元</div>
        <FxSection />
      </div>
    </div>
  );
}
