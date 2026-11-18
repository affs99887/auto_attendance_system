// "全部地点"页：每个收藏的地点一张小卡片，卡片背景是那个地点现在的天空，点一下就切过去看它的天气。
// 卡片按窗口宽度自动排成几列；上面一行可以搜索添加新地点，点"编辑"后可以删除地点。
// 这一页铺在窗口的普通背景上（不铺整屏天空）；进出这一页的收放动画由 screens/Weather.tsx 的 WeatherScreen 负责。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { roundWeather, skyInfo } from '../lib/weather';
import {
  DEFAULT_WEATHER_LOCATION,
  searchWeatherLocations,
  type WeatherLocation,
} from '../lib/weatherLocations';
import { resolveSkyKind, skyTone, type SkyOptions } from '../lib/sky';
import { appAlert, appConfirm } from '../lib/dialog';
import {
  EMPTY_WEATHER_ENTRY,
  MAX_WEATHER_LOCATIONS,
  useWeatherStore,
  type WeatherEntry,
} from '../store/weather';
import { WeatherSky } from './WeatherSky';
import { useNow } from './WeatherPanel';

// 卡片很矮：云层放大 3 倍，只露出靠上的一段；太阳、月亮放在卡片右上角外面，卡片里只看得到它的光。
// 卡片上到处都有文字，所以哪块云都不调淡（把"调淡的那一块"放到卡片外面），文字靠阴影保证看得清
const CARD_SKY: SkyOptions = {
  orb: { x: 'calc(100% - 70px)', y: '-60px', scale: .6 },
  cloudScale: 3,
  calm: { x: 50, y: -400, rx: 1, ry: 1 },
};

/** 打开这一页后过多久再去补拉过期的天气（比收拢动画长一点） */
const PLACES_REFRESH_DELAY = 700;

/** 地址里去掉地点名之后剩下的那段，比如"上海市长宁区华山路1076号"去掉"华山路1076号"是"上海市长宁区" */
function regionOf(location: WeatherLocation): string {
  const { address, name } = location;
  return address !== name && address.endsWith(name) ? address.slice(0, -name.length) : '';
}

/** 预警标题一般是"某某市气象台发布大风蓝色预警"，卡片上只留"大风蓝色预警" */
function shortAlert(title: string): string {
  return /发布(.+预警)/.exec(title)?.[1] || title || '气象预警';
}

function sameLocation(a: WeatherLocation, b: WeatherLocation): boolean {
  const sameCoordinates = a.latitude.toFixed(4) === b.latitude.toFixed(4)
    && a.longitude.toFixed(4) === b.longitude.toFixed(4);
  const sameAddress = a.address.replace(/\s+/g, '') === b.address.replace(/\s+/g, '');
  return sameCoordinates || sameAddress;
}

/** 一个地点的卡片。WeatherScreen 的收放动画里也用它（bare 模式）画卡片上的字 */
export const PlaceCard = React.memo(function PlaceCard({
  location,
  entry,
  active,
  editing,
  bare = false,
  now,
  onPick,
  onDelete,
}: {
  location: WeatherLocation;
  entry: WeatherEntry;
  active: boolean;
  editing: boolean;
  /** 只要卡片上的字、不要天空：收放动画里那块底色上画的就是这样一张，跟真卡片的字摆在同一个位置 */
  bare?: boolean;
  now: Date;
  onPick: (id: string) => void;
  onDelete: (location: WeatherLocation) => void;
}) {
  const data = entry.data;
  // 还没拿到数据时先用阴天的天空垫着
  const kind = resolveSkyKind(data?.realtime.skycon ?? 'CLOUDY', now);
  const today = data?.daily[0];
  const alert = data?.alerts[0];
  const isDefault = location.id === DEFAULT_WEATHER_LOCATION.id;
  const deletable = editing && !isDefault;
  const sub = [regionOf(location), isDefault ? '默认地点' : ''].filter(Boolean).join(' · ');

  let condition: React.ReactNode;
  if (alert) condition = <><Icon.AlertTriangle size={12} />{shortAlert(alert.title)}</>;
  else if (data) condition = skyInfo(data.realtime.skycon).label;
  else if (entry.loading) condition = '正在获取天气';
  else if (entry.error) condition = '获取失败，点开可重试';
  else condition = '还没有天气数据';

  return (
    <div
      className={`wxl-card${active ? ' active' : ''}${deletable ? ' deletable' : ''}${bare ? ' is-bare' : ''}`}
      data-tone={skyTone(kind)}
      data-place-id={location.id}
    >
      {!bare && <WeatherSky kind={kind} options={CARD_SKY} className="wxl-sky" />}
      <button
        type="button"
        className="wxl-pick"
        disabled={editing}
        aria-current={active ? 'true' : undefined}
        title={location.address}
        onClick={() => onPick(location.id)}
      >
        <span className="wxl-name">
          <strong>{location.name}</strong>
          {sub && <span>{sub}</span>}
        </span>
        <span className="wxl-temp">
          {data ? <>{roundWeather(data.realtime.temperature)}<sup>°</sup></> : entry.loading ? <span className="spinner" /> : '—'}
        </span>
        <span className={`wxl-cond${alert ? ' is-alert' : ''}`}>{condition}</span>
        {today && (
          <span className="wxl-range">
            <span>最高 <b>{roundWeather(today.temperature_max, '°')}</b></span>
            <span>最低 <b>{roundWeather(today.temperature_min, '°')}</b></span>
          </span>
        )}
      </button>
      {deletable && (
        <button
          type="button"
          className="wxl-del"
          title={`删除 ${location.name}`}
          aria-label={`删除收藏地点 ${location.name}`}
          onClick={() => onDelete(location)}
        >
          <Icon.Minus size={11} strokeWidth={2.6} />
        </button>
      )}
    </div>
  );
});

/** 搜索框：输入城市、区县，下面弹出结果列表，点一个就收藏并切过去 */
function PlaceSearch({ onAdded }: { onAdded: (id: string) => void }) {
  const locations = useWeatherStore(s => s.locations);
  const activeLocationId = useWeatherStore(s => s.activeLocationId);
  const addFavorite = useWeatherStore(s => s.addFavorite);
  const [query, setQuery] = React.useState('');
  const [open, setOpen] = React.useState(false);
  const [cursor, setCursor] = React.useState(0);
  const [addingId, setAddingId] = React.useState<string | null>(null);
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const results = React.useMemo(() => searchWeatherLocations(query), [query]);
  const full = locations.length >= MAX_WEATHER_LOCATIONS;

  React.useEffect(() => setCursor(0), [query]);

  // 点搜索框和结果以外的地方，结果收起来
  React.useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const pick = async (location: WeatherLocation) => {
    if (addingId) return;
    setAddingId(location.id);
    const id = await addFavorite(location);
    setAddingId(null);
    if (!id) {
      await appAlert(`最多可收藏 ${MAX_WEATHER_LOCATIONS} 个天气地点，请先删除不再使用的地点。`, { title: '无法添加地点' });
      return;
    }
    setQuery('');
    setOpen(false);
    onAdded(id);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOpen(true);
      setCursor(index => Math.min(results.length - 1, index + 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setCursor(index => Math.max(0, index - 1));
    } else if (event.key === 'Enter' && open && results[cursor]) {
      event.preventDefault();
      void pick(results[cursor]);
    } else if (event.key === 'Escape' && (open || query)) {
      // 先收起结果、清空输入，再按一次才退出"全部地点"页
      event.preventDefault();
      if (query) setQuery('');
      else setOpen(false);
    }
  };

  return (
    <div className="wxl-search" ref={wrapRef}>
      <label className="wxl-search-box">
        <Icon.Search size={14} />
        <input
          role="combobox"
          aria-label="搜索城市、区县，添加天气地点"
          aria-expanded={open}
          aria-controls="wxl-results"
          aria-activedescendant={open && results[cursor] ? `wxl-result-${cursor}` : undefined}
          value={query}
          maxLength={30}
          placeholder="搜索城市、区县，添加地点"
          onFocus={() => setOpen(true)}
          onChange={event => { setQuery(event.target.value); setOpen(true); }}
          onKeyDown={onKeyDown}
        />
        {query && (
          <button type="button" className="wxl-clear" onClick={() => setQuery('')} aria-label="清空搜索">
            <Icon.X size={11} />
          </button>
        )}
      </label>
      {open && (
        <div className="wxl-results">
          <div className="wxl-results-head">
            <span>{query.trim() ? '搜索结果' : '常用城市'}</span>
            <span>已收藏 {locations.length} / {MAX_WEATHER_LOCATIONS}</span>
          </div>
          <div className="wxl-results-list" id="wxl-results" role="listbox" aria-label="搜索结果">
            {results.map((location, index) => {
              const favorite = locations.find(item => item.id === location.id || sameLocation(item, location));
              const status = addingId === location.id ? '添加中…'
                : favorite ? (favorite.id === activeLocationId ? '正在查看' : '已收藏')
                  : full ? '已满' : '添加';
              return (
                <button
                  type="button"
                  key={location.id}
                  id={`wxl-result-${index}`}
                  role="option"
                  aria-selected={index === cursor}
                  className="wxl-result"
                  disabled={!favorite && full}
                  onMouseDown={event => event.preventDefault()}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => void pick(location)}
                >
                  <span className="wxl-result-copy">
                    <strong>{location.name}</strong>
                    <small>{location.address}</small>
                  </span>
                  <em className={favorite || full ? 'is-muted' : ''}>{status}</em>
                </button>
              );
            })}
            {!results.length && <div className="wxl-results-empty">没有找到匹配的地点，试试输入城市或区县名称</div>}
          </div>
          <div className="wxl-results-foot">数据源：彩云官方行政区划表，本地搜索</div>
        </div>
      )}
    </div>
  );
}

export function WeatherPlaces({
  busy,
  onOpen,
}: {
  /** 正在做进出这一页的动画，这时不接受点击和按键 */
  busy: boolean;
  /** 打开某个地点的天气（返回按钮、Esc 打开的是当前地点） */
  onOpen: (id: string) => void;
}) {
  const locations = useWeatherStore(s => s.locations);
  const entries = useWeatherStore(s => s.entries);
  const activeLocationId = useWeatherStore(s => s.activeLocationId);
  const removeFavorite = useWeatherStore(s => s.removeFavorite);
  const refreshStale = useWeatherStore(s => s.refreshStale);
  const [editing, setEditing] = React.useState(false);
  const now = useNow(60_000);
  const canEdit = locations.length > 1;

  // 等收拢动画做完再去拉过期的天气：数据一到卡片就要换天空，赶在动画中间会卡一下
  React.useEffect(() => {
    const timer = window.setTimeout(() => void refreshStale(), PLACES_REFRESH_DELAY);
    return () => window.clearTimeout(timer);
  }, [refreshStale]);

  React.useEffect(() => {
    if (editing && !canEdit) setEditing(false);
  }, [editing, canEdit]);

  // Esc：编辑中先退出编辑，否则回到当前地点的天气。弹出的确认框、搜索框自己处理过的 Esc 不算
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || busy) return;
      if (editing) setEditing(false);
      else onOpen(activeLocationId);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editing, busy, activeLocationId, onOpen]);

  // 新加的地点要等它的卡片画出来，才能从卡片放大过去
  const onAdded = React.useCallback((id: string) => {
    window.requestAnimationFrame(() => onOpen(id));
  }, [onOpen]);

  const remove = React.useCallback(async (location: WeatherLocation) => {
    const confirmed = await appConfirm(`确定删除收藏地点“${location.name}”吗？`, {
      title: '删除收藏地点',
      confirmText: '删除',
      danger: true,
    });
    if (confirmed) await removeFavorite(location.id);
  }, [removeFavorite]);

  return (
    <div className={`wx-page wxl${busy ? ' is-busy' : ''}`}>
      <div className="wxl-head">
        <button type="button" className="btn btn-sm" onClick={() => onOpen(activeLocationId)}>
          <Icon.ChevronLeft size={12} />返回
        </button>
        <h2 className="wxl-title">全部地点<span>{locations.length} 个</span></h2>
        <PlaceSearch onAdded={onAdded} />
        <button
          type="button"
          className={`btn btn-sm${editing ? ' btn-primary' : ''}`}
          aria-pressed={editing}
          disabled={!canEdit}
          title={canEdit ? undefined : '只有默认地点，没有可删除的地点'}
          onClick={() => setEditing(value => !value)}
        >
          {editing ? <><Icon.Check size={12} />完成</> : <><Icon.Pencil size={12} />编辑</>}
        </button>
      </div>
      <div className="wxl-grid" role="list" aria-label="收藏的天气地点">
        {locations.map(location => (
          <div role="listitem" key={location.id}>
            <PlaceCard
              location={location}
              entry={entries[location.id] || EMPTY_WEATHER_ENTRY}
              active={location.id === activeLocationId}
              editing={editing}
              now={now}
              onPick={onOpen}
              onDelete={remove}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
