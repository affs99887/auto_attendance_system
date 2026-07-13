import * as React from 'react';
import { useApp } from '../App';
import { Icon } from '../lib/icons';
import type { WeatherResponse } from '../lib/api';
import {
  FIXED_WEATHER_LOCATION,
  aqiTone,
  getCachedWeather,
  loadWeatherData,
  roundWeather,
  skyInfo,
  weatherDayLabel,
  weatherErrorMessage,
  weatherHourLabel,
  windDirection,
} from '../lib/weather';

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

function WeatherLoading() {
  return (
    <div className="card weather-page-state">
      <span className="spinner" />
      <div>
        <div className="weather-page-state-title">正在连接彩云天气</div>
        <div className="muted">{FIXED_WEATHER_LOCATION.address}</div>
      </div>
    </div>
  );
}

export function WeatherScreen() {
  const { setScreen } = useApp();
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

  if (!data && loading) return <WeatherLoading />;

  if (!data) {
    return (
      <div className="card weather-page-state weather-page-state-error">
        <Icon.AlertTriangle size={24} />
        <div style={{ flex: 1 }}>
          <div className="weather-page-state-title">天气数据获取失败</div>
          <div className="muted">{error || '请稍后重试'}</div>
        </div>
        <button className="btn btn-sm" onClick={() => void refresh(true)}>重新加载</button>
        <button className="btn btn-sm" onClick={() => setScreen('settings')}>检查设置</button>
      </div>
    );
  }

  const current = data.realtime;
  const sky = skyInfo(current.skycon);
  const today = data.daily[0];
  const currentAqiTone = aqiTone(current.aqi);
  const nearestRain = current.nearest_precipitation_distance;
  const rainDetail = nearestRain !== null && Number.isFinite(nearestRain)
    ? `最近降水带约 ${metricValue(nearestRain, ' km', 1)}`
    : '当前地点降水强度';
  const hasMinutelySummary = Boolean(data.minutely_description);

  return (
    <div className="weather-page">
      {error && (
        <div className="weather-page-inline-error">
          <Icon.AlertTriangle size={14} />
          <span>刷新失败：{error}</span>
        </div>
      )}

      <section className={`weather-page-hero tone-${sky.tone}`}>
        <div className="weather-page-hero-top">
          <div className="weather-page-location">
            <div className="weather-page-location-icon"><Icon.Globe size={16} /></div>
            <div style={{ minWidth: 0 }}>
              <div className="weather-page-location-name">{data.location.address}</div>
              <div className="weather-page-location-meta mono">
                {data.location.longitude.toFixed(4)}, {data.location.latitude.toFixed(4)}
              </div>
            </div>
          </div>
          <div className="row gap-2">
            <span className="weather-page-source">
              {data.source} · {updateTime(data.updated_at)}{data.cached ? ' · 缓存' : ''}
            </span>
            <button className="btn btn-sm weather-page-hero-btn" onClick={() => setScreen('settings')}>
              <Icon.Settings size={12} />设置
            </button>
            <button
              className="btn btn-sm weather-page-hero-btn"
              disabled={loading}
              onClick={() => void refresh(true)}
            >
              {loading ? <span className="spinner" /> : <Icon.Refresh size={12} />}
              {loading ? '刷新中' : '刷新'}
            </button>
          </div>
        </div>

        <div className="weather-page-hero-main">
          <div className={`weather-page-hero-glyph ${sky.tone}`}>{sky.glyph}</div>
          <div className="weather-page-now">
            <div className="weather-page-now-temp mono">
              {roundWeather(current.temperature)}<span>°</span>
            </div>
            <div className="weather-page-now-condition">{sky.label}</div>
            <div className="weather-page-now-feels">
              体感 {roundWeather(current.apparent_temperature, '°')}
              {today && <> · 今日 {roundWeather(today.temperature_max, '°')} / {roundWeather(today.temperature_min, '°')}</>}
            </div>
          </div>
          <div className="weather-page-hero-brief">
            <div className="weather-page-hero-kicker">
              {hasMinutelySummary ? '未来两小时' : '未来 24 小时'}
            </div>
            <div className="weather-page-hero-summary">
              {data.minutely_description || data.forecast_keypoint || data.hourly_description || '暂无天气提示'}
            </div>
            <div className="weather-page-hero-sub">
              {hasMinutelySummary
                ? (data.forecast_keypoint || data.hourly_description || '逐小时预报已更新')
                : '逐小时预报已更新'}
            </div>
          </div>
        </div>
      </section>

      {data.alerts.length > 0 && (
        <section className="weather-page-alerts">
          {data.alerts.map(alert => (
            <div className="weather-page-alert" key={alert.id}>
              <Icon.AlertTriangle size={18} />
              <div style={{ minWidth: 0 }}>
                <div className="weather-page-alert-title">{alert.title}</div>
                <div className="weather-page-alert-desc">{alert.description}</div>
                <div className="weather-page-alert-meta">
                  {[alert.location, alert.source, alert.published_at ? updateTime(alert.published_at) : '']
                    .filter(Boolean).join(' · ')}
                </div>
              </div>
            </div>
          ))}
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

      <section className="card weather-page-panel">
        <div className="card-header weather-page-panel-head">
          <div>
            <div className="card-title">24 小时逐时预报</div>
            <div className="card-sub">温度 · 降水概率 · 风况</div>
          </div>
          <span className="pill pill-neutral mono">{data.hourly.length} 小时</span>
        </div>
        <div className="weather-page-hourly-scroll">
          {data.hourly.length ? data.hourly.map((hour, index) => {
            const info = skyInfo(hour.skycon);
            return (
              <div className="weather-page-hour" key={`${hour.datetime}-${index}`}>
                <div className="weather-page-hour-time mono">{weatherHourLabel(hour.datetime, index)}</div>
                <div className={`weather-page-hour-glyph ${info.tone}`} title={info.label}>{info.glyph}</div>
                <div className="weather-page-hour-temp mono">{roundWeather(hour.temperature, '°')}</div>
                <div className="weather-page-hour-rain">降水 {roundWeather(hour.precipitation_probability, '%')}</div>
                <div className="weather-page-hour-wind">
                  {windDirection(hour.wind_direction)} {roundWeather(hour.wind_speed)}
                </div>
              </div>
            );
          }) : (
            <div className="weather-page-panel-empty">当前套餐未返回逐时预报</div>
          )}
        </div>
      </section>

      <section className="card weather-page-panel">
        <div className="card-header weather-page-panel-head">
          <div>
            <div className="card-title">未来天气</div>
            <div className="card-sub">每日高低温与降水概率</div>
          </div>
          <span className="pill pill-neutral mono">{data.daily.length} 天</span>
        </div>
        <div className="weather-page-daily">
          {data.daily.length ? data.daily.map((day, index) => {
            const info = skyInfo(day.skycon);
            return (
              <div className="weather-page-daily-item" key={`${day.date}-${index}`}>
                <div className="weather-page-daily-date">
                  <strong>{weatherDayLabel(day.date, index)}</strong>
                  <span className="mono">{day.date.slice(5).replace('-', '/')}</span>
                </div>
                <div className="weather-page-daily-sky">
                  <span className={`weather-page-daily-glyph ${info.tone}`}>{info.glyph}</span>
                  <span>{info.label}</span>
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
