import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import { useStartupStore } from '../store/startup';
import {
  selectActiveWeatherEntry,
  selectActiveWeatherLocation,
  useWeatherStore,
} from '../store/weather';
import {
  aqiTone,
  roundWeather,
  skyInfo,
  weatherDayLabel,
  windDirection,
} from '../lib/weather';
import {
  DEFAULT_WEATHER_LOCATION,
  searchWeatherLocations,
  type WeatherLocation,
} from '../lib/weatherLocations';
import { appAlert, appConfirm } from '../lib/dialog';
import {
  WeatherHourlyChart,
  WeatherIcon,
  WeatherSkyPanel,
} from '../components/WeatherPanel';

function metricValue(value: number | null, suffix = '', digits = 0): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(digits)}${suffix}`;
}

function updateTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function MetricCard({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <div className={`weather-page-metric ${tone ? `tone-${tone}` : ''}`}>
      <div className="weather-page-metric-icon">{icon}</div>
      <div className="weather-page-metric-copy">
        <div className="weather-page-metric-label">{label}</div>
        <div className="weather-page-metric-value mono">{value}</div>
        <div className="weather-page-metric-detail">{detail}</div>
      </div>
    </div>
  );
}

function WeatherLoading({ address }: { address: string }) {
  return (
    <div className="card weather-page-state" role="status" aria-live="polite" aria-busy="true">
      <span className="spinner" />
      <div>
        <div className="weather-page-state-title">正在连接彩云天气</div>
        <div className="muted">{address}</div>
      </div>
    </div>
  );
}

function sameLocation(a: WeatherLocation, b: WeatherLocation): boolean {
  const sameCoordinates = a.latitude.toFixed(4) === b.latitude.toFixed(4)
    && a.longitude.toFixed(4) === b.longitude.toFixed(4);
  const sameAddress = a.address.replace(/\s+/g, '') === b.address.replace(/\s+/g, '');
  return sameCoordinates || sameAddress;
}

function WeatherLocationBar() {
  const locations = useWeatherStore(s => s.locations);
  const activeLocationId = useWeatherStore(s => s.activeLocationId);
  const setActiveLocation = useWeatherStore(s => s.setActiveLocation);
  const addFavorite = useWeatherStore(s => s.addFavorite);
  const removeFavorite = useWeatherStore(s => s.removeFavorite);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [addingId, setAddingId] = React.useState<string | null>(null);
  const addButtonRef = React.useRef<HTMLButtonElement>(null);
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const results = React.useMemo(() => searchWeatherLocations(query), [query]);

  const closeDialog = React.useCallback(() => {
    setDialogOpen(false);
    setQuery('');
    setAddingId(null);
  }, []);

  React.useEffect(() => {
    if (!dialogOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) || []);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.requestAnimationFrame(() => addButtonRef.current?.focus());
    };
  }, [dialogOpen, closeDialog]);

  const handleAdd = async (location: WeatherLocation) => {
    setAddingId(location.id);
    const id = await addFavorite(location);
    setAddingId(null);
    if (!id) {
      await appAlert('最多可收藏 20 个天气地点，请先删除不再使用的地点。', { title: '无法添加地点' });
      return;
    }
    closeDialog();
  };

  const handleDelete = async (location: WeatherLocation) => {
    const confirmed = await appConfirm(`确定删除收藏地点“${location.name}”吗？`, {
      title: '删除收藏地点',
      confirmText: '删除',
      danger: true,
    });
    if (confirmed) await removeFavorite(location.id);
  };

  return (
    <>
      <section className="card weather-location-bar" aria-label="收藏天气地点">
        <div className="weather-location-tabs" role="group" aria-label="切换天气地点">
          {locations.map(location => {
            const active = location.id === activeLocationId;
            return (
              <div className={`weather-location-chip ${active ? 'active' : ''}`} key={location.id}>
                <button
                  type="button"
                  className="weather-location-select"
                  aria-pressed={active}
                  title={location.address}
                  onClick={() => void setActiveLocation(location.id)}
                >
                  <Icon.Globe size={12} />
                  <span>{location.name}</span>
                </button>
                {location.id !== DEFAULT_WEATHER_LOCATION.id && (
                  <button
                    type="button"
                    className="weather-location-remove"
                    title={`删除收藏：${location.name}`}
                    aria-label={`删除收藏地点 ${location.name}`}
                    onClick={() => void handleDelete(location)}
                  >
                    <Icon.X size={10} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
        <button ref={addButtonRef} type="button" className="btn btn-sm weather-location-add" onClick={() => setDialogOpen(true)}>
          <Icon.Plus size={12} />添加地点
        </button>
      </section>

      {dialogOpen && (
        <div className="ep-overlay" onClick={closeDialog}>
          <div
            className="ep-modal weather-location-modal"
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="weather-location-dialog-title"
            onClick={event => event.stopPropagation()}
          >
            <div className="ep-modal-head">
              <div>
                <div className="ep-modal-title" id="weather-location-dialog-title">添加收藏地点</div>
                <div className="ep-modal-sub">本地搜索城市、区县或行政区编码，不需要额外地图密钥</div>
              </div>
              <button type="button" className="ep-modal-close" onClick={closeDialog} aria-label="关闭">
                <Icon.Close size={12} />
              </button>
            </div>
            <div className="weather-location-search-wrap">
              <Icon.Search size={14} />
              <input
                className="input weather-location-search"
                autoFocus
                aria-label="搜索天气地点"
                value={query}
                maxLength={30}
                placeholder="搜索城市、区县，例如：杭州、长宁区"
                onChange={event => setQuery(event.target.value)}
              />
              {query && (
                <button type="button" className="weather-location-clear" onClick={() => setQuery('')} aria-label="清空搜索">
                  <Icon.X size={11} />
                </button>
              )}
            </div>
            <div className="weather-location-result-head">
              <span>{query.trim() ? '搜索结果' : '常用城市'}</span>
              <span className="mono">显示 {results.length} 个</span>
            </div>
            <div className="weather-location-results">
              {results.map(location => {
                const favorite = locations.find(item => item.id === location.id || sameLocation(item, location));
                const active = favorite?.id === activeLocationId;
                return (
                  <div className="weather-location-result" key={location.id}>
                    <div className="weather-location-result-copy">
                      <strong>{location.name}</strong>
                      <span title={location.address}>{location.address}</span>
                    </div>
                    <button
                      type="button"
                      className={`btn btn-sm ${favorite ? '' : 'btn-primary'}`}
                      disabled={active || addingId === location.id}
                      onClick={() => void handleAdd(location)}
                    >
                      {addingId === location.id ? '添加中…' : active ? '当前地点' : favorite ? '切换' : '收藏并切换'}
                    </button>
                  </div>
                );
              })}
              {!results.length && (
                <div className="weather-location-empty">
                  <Icon.Search size={20} />
                  <strong>未找到匹配地点</strong>
                  <span>请尝试输入城市或区县名称。</span>
                </div>
              )}
            </div>
            <div className="ep-modal-foot weather-location-modal-foot">
              <span>最多收藏 20 个地点 · 数据源：彩云官方行政区划表</span>
              <button type="button" className="btn" onClick={closeDialog}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function WeatherScreen() {
  const { setScreen } = useApp();
  const startupStatus = useStartupStore(s => s.status);
  const startupReason = useStartupStore(s => s.reason);
  const location = useWeatherStore(selectActiveWeatherLocation);
  const { data, loading, error, hasAttempted } = useWeatherStore(selectActiveWeatherEntry);
  const refresh = useWeatherStore(s => s.refresh);

  React.useEffect(() => {
    // 与首页一致：只在后端探活完成后首拉；服务稍后就绪时自动恢复。
    if (startupStatus === 'ready' && !data && !hasAttempted && !loading) void refresh(false);
  }, [startupStatus, data, hasAttempted, loading, refresh]);

  const locationBar = <WeatherLocationBar />;

  if (!data && (loading || (!hasAttempted && startupStatus !== 'failed'))) return (
    <div className="weather-page">
      {locationBar}
      <WeatherLoading address={location.address} />
    </div>
  );

  if (!data) {
    return (
      <div className="weather-page">
        {locationBar}
        <div className="card weather-page-state weather-page-state-error" role="alert">
          <Icon.AlertTriangle size={24} />
          <div style={{ flex: 1 }}>
            <div className="weather-page-state-title">天气数据获取失败</div>
            <div className="muted">
              {error || (startupStatus === 'failed' ? startupReason : null) || '请稍后重试'}
            </div>
          </div>
          <button className="btn btn-sm" onClick={() => void refresh(true)}>重新加载</button>
          <button className="btn btn-sm" onClick={() => setScreen('settings')}>检查设置</button>
        </div>
      </div>
    );
  }

  const current = data.realtime;
  const currentAqiTone = aqiTone(current.aqi);
  const nearestRain = current.nearest_precipitation_distance;
  const rainDetail = nearestRain !== null && Number.isFinite(nearestRain)
    ? `最近降水带约 ${metricValue(nearestRain, ' km', 1)}`
    : '当前地点降水强度';
  const dailyTemperatures = data.daily.flatMap(day => [day.temperature_min, day.temperature_max])
    .filter((value): value is number => value !== null && Number.isFinite(value));
  const dailyMin = dailyTemperatures.length ? Math.min(...dailyTemperatures) : 0;
  const dailyMax = dailyTemperatures.length ? Math.max(...dailyTemperatures) : 1;
  const dailySpread = Math.max(1, dailyMax - dailyMin);

  return (
    <div className="weather-page">
      {locationBar}
      {error && (
        <div className="weather-page-inline-error" role="alert">
          <Icon.AlertTriangle size={14} />
          <span>刷新失败：{error}</span>
        </div>
      )}

      <WeatherSkyPanel
        data={data}
        mode="page"
        loading={loading}
        onRefresh={() => void refresh(true)}
        onOpenSettings={() => setScreen('settings')}
      />

      {(data.alerts.length > 0 || data.alerts_available !== true) && (
        <section className={`weather-page-alerts ${data.alerts.length ? '' : 'is-unavailable'}`} aria-label="天气预警">
          {data.alerts.length ? data.alerts.map(alert => (
            <div className="weather-page-alert" key={alert.id}>
              <Icon.AlertTriangle size={18} />
              <div style={{ minWidth: 0 }}>
                <div className="weather-page-alert-title">{alert.title}</div>
                <div className="weather-page-alert-desc">{alert.description}</div>
                <div className="weather-page-alert-meta">
                  {[alert.status, alert.location, alert.source, alert.published_at ? updateTime(alert.published_at) : '']
                    .filter(Boolean).join(' · ')}
                </div>
              </div>
            </div>
          )) : (
            <div className="weather-page-alert weather-page-alert-unavailable">
              <Icon.Info size={18} />
              <div>
                <div className="weather-page-alert-title">预警数据暂不可用</div>
                <div className="weather-page-alert-desc">暂未确认当前地点的气象预警状态，请稍后刷新。</div>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="weather-page-metrics">
        <MetricCard
          icon={<Icon.Activity size={16} />}
          label="相对湿度"
          value={roundWeather(current.humidity, '%')}
          detail={`云量 ${roundWeather(current.cloudrate, '%')}`}
        />
        <MetricCard
          icon={<Icon.Refresh size={16} />}
          label="风况"
          value={`${windDirection(current.wind_direction)} ${roundWeather(current.wind_speed, ' km/h')}`}
          detail="地表 10 米风速"
        />
        <MetricCard
          icon={<Icon.Eye size={16} />}
          label="能见度"
          value={roundWeather(current.visibility, ' km')}
          detail="地表水平能见度"
        />
        <MetricCard
          icon={<Icon.Globe size={16} />}
          label="气压"
          value={metricValue(current.pressure, ' hPa')}
          detail="当前地面气压"
        />
        <MetricCard
          icon={<Icon.Activity size={16} />}
          label="空气质量"
          value={`AQI ${roundWeather(current.aqi)}`}
          detail={current.aqi_description || '暂无等级描述'}
          tone={currentAqiTone}
        />
        <MetricCard
          icon={<Icon.Cloud size={16} />}
          label="颗粒物"
          value={`PM2.5 ${roundWeather(current.pm25)}`}
          detail={`PM10 ${roundWeather(current.pm10)} μg/m³`}
        />
        <MetricCard
          icon={<Icon.Zap size={16} />}
          label="紫外线"
          value={current.uv_description || '—'}
          detail={`舒适度 ${current.comfort_description || '—'}`}
        />
        <MetricCard
          icon={<Icon.Cloud size={16} />}
          label="当前降水"
          value={metricValue(current.precipitation_intensity, ' mm/h', 2)}
          detail={rainDetail}
        />
      </section>

      <WeatherHourlyChart items={data.hourly} limit={24} variant="page" />

      <section className="card weather-page-panel">
        <div className="card-header weather-page-panel-head">
          <div>
            <div className="card-title">未来天气</div>
            <div className="card-sub">高低温区间 · 天气状况 · 降水概率</div>
          </div>
          <span className="pill pill-neutral mono">{data.daily.length} 天</span>
        </div>
        <div className="weather-page-daily">
          {data.daily.length ? data.daily.map((day, index) => {
            const info = skyInfo(day.skycon);
            const minimumRangeWidth = 8;
            const rangeLeft = Math.max(0, Math.min(100 - minimumRangeWidth, ((day.temperature_min ?? dailyMin) - dailyMin) / dailySpread * 100));
            const rawRangeWidth = ((day.temperature_max ?? dailyMin) - (day.temperature_min ?? dailyMin)) / dailySpread * 100;
            const rangeWidth = Math.max(0, Math.min(100 - rangeLeft, Math.max(minimumRangeWidth, rawRangeWidth)));
            return (
              <div className="weather-page-daily-item" key={`${day.date}-${index}`}>
                <div className="weather-page-daily-date">
                  <strong>{weatherDayLabel(day.date, index)}</strong>
                  <span className="mono">{day.date.slice(5).replace('-', '/')}</span>
                </div>
                <div className="weather-page-daily-sky">
                  <WeatherIcon skycon={day.skycon} size={26} className={`tone-${info.tone}`} />
                  <span>{info.label}</span>
                </div>
                <div className="weather-page-daily-range" title={`${roundWeather(day.temperature_min, '°')} 至 ${roundWeather(day.temperature_max, '°')}`}>
                  <span
                    style={{
                      left: `${rangeLeft}%`,
                      width: `${rangeWidth}%`,
                    }}
                  />
                </div>
                <div className="weather-page-daily-temp mono">
                  <strong>{roundWeather(day.temperature_max, '°')}</strong>
                  <span>{roundWeather(day.temperature_min, '°')}</span>
                </div>
                <div className="weather-page-daily-rain">
                  <span className="weather-page-rain-dot" />
                  降水概率 {roundWeather(day.precipitation_probability, '%')}
                </div>
              </div>
            );
          }) : (
            <div className="weather-page-panel-empty">暂无日级预报</div>
          )}
        </div>
      </section>
    </div>
  );
}
