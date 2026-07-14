import { create } from 'zustand';
import type { WeatherResponse } from '../lib/api';
import {
  getCachedWeather,
  loadWeatherData,
  weatherErrorMessage,
} from '../lib/weather';
import {
  DEFAULT_WEATHER_LOCATION,
  type WeatherLocation,
} from '../lib/weatherLocations';

const WEATHER_SETTINGS_KEY = 'aas.weather.locations.v1';
const WEATHER_SETTINGS_VERSION = 1;
const MAX_WEATHER_LOCATIONS = 20;

export interface WeatherEntry {
  data: WeatherResponse | null;
  loading: boolean;
  error: string | null;
  hasAttempted: boolean;
  lastFetched: number | null;
}

export const EMPTY_WEATHER_ENTRY: WeatherEntry = {
  data: null,
  loading: false,
  error: null,
  hasAttempted: false,
  lastFetched: null,
};

interface WeatherPreferences {
  version: 1;
  activeLocationId: string;
  locations: WeatherLocation[];
}

export interface WeatherState {
  locations: WeatherLocation[];
  activeLocationId: string;
  entries: Record<string, WeatherEntry>;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  refresh: (force?: boolean) => Promise<void>;
  refreshLocation: (locationId: string, force?: boolean) => Promise<void>;
  refreshAfterCurrent: (force?: boolean) => void;
  refreshLocationAfterCurrent: (locationId: string, force?: boolean) => void;
  setActiveLocation: (locationId: string) => Promise<void>;
  addFavorite: (location: WeatherLocation) => Promise<string | null>;
  removeFavorite: (locationId: string) => Promise<boolean>;
}

function cleanText(value: unknown, maxLength: number): string {
  if (typeof value !== 'string') return '';
  return Array.from(value.replace(/[\u0000-\u001f\u007f]/g, ' ').trim())
    .slice(0, maxLength)
    .join('');
}

function normalizeLocation(value: unknown): WeatherLocation | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const id = cleanText(raw.id, 80);
  const address = cleanText(raw.address, 120);
  const name = cleanText(raw.name, 40) || address;
  const latitude = typeof raw.latitude === 'number' ? raw.latitude : Number(raw.latitude);
  const longitude = typeof raw.longitude === 'number' ? raw.longitude : Number(raw.longitude);
  if (
    !id
    || !address
    || !name
    || !Number.isFinite(latitude)
    || !Number.isFinite(longitude)
    || latitude < -90
    || latitude > 90
    || longitude < -180
    || longitude > 180
  ) return null;
  return { id, name, address, latitude, longitude };
}

function coordinateKey(location: WeatherLocation): string {
  return `${location.latitude.toFixed(4)},${location.longitude.toFixed(4)}`;
}

function addressKey(location: WeatherLocation): string {
  return location.address.replace(/\s+/g, '').toLocaleLowerCase('zh-CN');
}

function normalizePreferences(value: unknown): WeatherPreferences | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as { version?: unknown; activeLocationId?: unknown; locations?: unknown };
  if (raw.version !== WEATHER_SETTINGS_VERSION || !Array.isArray(raw.locations)) return null;

  const locations: WeatherLocation[] = [{ ...DEFAULT_WEATHER_LOCATION }];
  const seenIds = new Set([DEFAULT_WEATHER_LOCATION.id]);
  const seenCoordinates = new Set([coordinateKey(DEFAULT_WEATHER_LOCATION)]);
  const seenAddresses = new Set([addressKey(DEFAULT_WEATHER_LOCATION)]);
  for (const item of raw.locations) {
    const location = normalizeLocation(item);
    if (
      !location
      || seenIds.has(location.id)
      || seenCoordinates.has(coordinateKey(location))
      || seenAddresses.has(addressKey(location))
    ) continue;
    locations.push(location);
    seenIds.add(location.id);
    seenCoordinates.add(coordinateKey(location));
    seenAddresses.add(addressKey(location));
    if (locations.length >= MAX_WEATHER_LOCATIONS) break;
  }

  const requestedActiveId = cleanText(raw.activeLocationId, 80);
  const activeLocationId = seenIds.has(requestedActiveId)
    ? requestedActiveId
    : DEFAULT_WEATHER_LOCATION.id;
  return {
    version: WEATHER_SETTINGS_VERSION,
    activeLocationId,
    locations,
  };
}

function defaultPreferences(): WeatherPreferences {
  return {
    version: WEATHER_SETTINGS_VERSION,
    activeLocationId: DEFAULT_WEATHER_LOCATION.id,
    locations: [{ ...DEFAULT_WEATHER_LOCATION }],
  };
}

function loadLocalPreferences(): WeatherPreferences {
  try {
    const raw = typeof localStorage !== 'undefined'
      ? localStorage.getItem(WEATHER_SETTINGS_KEY)
      : null;
    if (raw) return normalizePreferences(JSON.parse(raw)) || defaultPreferences();
  } catch { /* 损坏的浏览器缓存回退默认地点 */ }
  return defaultPreferences();
}

function persistPreferences(preferences: WeatherPreferences) {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(WEATHER_SETTINGS_KEY, JSON.stringify(preferences));
    }
  } catch { /* localStorage 只是同步回退，文件持久化仍会继续 */ }
  if (typeof window !== 'undefined') {
    window.AAS_SETTINGS?.set(WEATHER_SETTINGS_KEY, preferences);
  }
}

function createEntry(location: WeatherLocation): WeatherEntry {
  const data = getCachedWeather(location);
  return data
    ? { data, loading: false, error: null, hasAttempted: true, lastFetched: Date.now() }
    : { ...EMPTY_WEATHER_ENTRY };
}

function entriesForLocations(
  existing: Record<string, WeatherEntry>,
  locations: WeatherLocation[],
): Record<string, WeatherEntry> {
  return Object.fromEntries(locations.map(location => [
    location.id,
    existing[location.id] || createEntry(location),
  ]));
}

const initialPreferences = loadLocalPreferences();
const queuedRefreshes = new Map<string, boolean>();
let hydratePromise: Promise<void> | null = null;

export const useWeatherStore = create<WeatherState>((set, get) => {
  const runRefresh = async (locationId: string, force: boolean): Promise<void> => {
    const before = get();
    const location = before.locations.find(item => item.id === locationId);
    const entry = before.entries[locationId] || EMPTY_WEATHER_ENTRY;
    if (!location || entry.loading) return;

    set(state => ({
      entries: {
        ...state.entries,
        [locationId]: {
          ...(state.entries[locationId] || EMPTY_WEATHER_ENTRY),
          loading: true,
          error: null,
          hasAttempted: true,
        },
      },
    }));

    try {
      const data = await loadWeatherData(location, force);
      set(state => {
        if (!state.locations.some(item => item.id === locationId)) return state;
        return {
          entries: {
            ...state.entries,
            [locationId]: {
              data,
              loading: false,
              error: null,
              hasAttempted: true,
              lastFetched: Date.now(),
            },
          },
        };
      });
    } catch (error) {
      set(state => {
        if (!state.locations.some(item => item.id === locationId)) return state;
        const current = state.entries[locationId] || EMPTY_WEATHER_ENTRY;
        return {
          entries: {
            ...state.entries,
            [locationId]: {
              ...current,
              loading: false,
              error: weatherErrorMessage(error),
              hasAttempted: true,
            },
          },
        };
      });
    } finally {
      if (queuedRefreshes.has(locationId)) {
        const replayForce = queuedRefreshes.get(locationId) === true;
        queuedRefreshes.delete(locationId);
        await runRefresh(locationId, replayForce);
      }
    }
  };

  const runRefreshAfterCurrent = async (locationId: string, force: boolean): Promise<void> => {
    await get().hydrate();
    const entry = get().entries[locationId] || EMPTY_WEATHER_ENTRY;
    if (entry.loading) {
      queuedRefreshes.set(locationId, (queuedRefreshes.get(locationId) || false) || force);
      return;
    }
    await runRefresh(locationId, force);
  };

  return {
    locations: initialPreferences.locations,
    activeLocationId: initialPreferences.activeLocationId,
    entries: entriesForLocations({}, initialPreferences.locations),
    hydrated: false,

    async hydrate() {
      if (get().hydrated) return;
      if (hydratePromise) return hydratePromise;
      hydratePromise = (async () => {
        let preferences: WeatherPreferences = {
          version: WEATHER_SETTINGS_VERSION,
          activeLocationId: get().activeLocationId,
          locations: get().locations,
        };
        if (typeof window !== 'undefined' && window.AAS_SETTINGS) {
          try {
            const all = await window.AAS_SETTINGS.getAll();
            const fromFile = normalizePreferences(all[WEATHER_SETTINGS_KEY]);
            if (fromFile) preferences = fromFile;
          } catch { /* 文件读取失败时保留 localStorage 初值 */ }
        }
        set(state => ({
          locations: preferences.locations,
          activeLocationId: preferences.activeLocationId,
          entries: entriesForLocations(state.entries, preferences.locations),
          hydrated: true,
        }));
        persistPreferences(preferences);
      })().finally(() => { hydratePromise = null; });
      return hydratePromise;
    },

    async refresh(force = false) {
      await get().hydrate();
      await runRefresh(get().activeLocationId, force);
    },

    async refreshLocation(locationId, force = false) {
      await get().hydrate();
      await runRefresh(locationId, force);
    },

    refreshAfterCurrent(force = false) {
      void get().hydrate().then(() => runRefreshAfterCurrent(get().activeLocationId, force));
    },

    refreshLocationAfterCurrent(locationId, force = false) {
      void runRefreshAfterCurrent(locationId, force);
    },

    async setActiveLocation(locationId) {
      await get().hydrate();
      if (!get().locations.some(item => item.id === locationId)) return;
      set({ activeLocationId: locationId });
      const current = get();
      persistPreferences({
        version: WEATHER_SETTINGS_VERSION,
        activeLocationId: locationId,
        locations: current.locations,
      });
      void runRefresh(locationId, false);
    },

    async addFavorite(value) {
      await get().hydrate();
      const location = normalizeLocation(value);
      if (!location) return null;
      const current = get();
      const same = current.locations.find(item => (
        item.id === location.id
        || coordinateKey(item) === coordinateKey(location)
        || addressKey(item) === addressKey(location)
      ));
      if (same) {
        await get().setActiveLocation(same.id);
        return same.id;
      }
      if (current.locations.length >= MAX_WEATHER_LOCATIONS) return null;

      const locations = [...current.locations, location];
      const entries = {
        ...current.entries,
        [location.id]: current.entries[location.id] || createEntry(location),
      };
      set({ locations, activeLocationId: location.id, entries });
      persistPreferences({
        version: WEATHER_SETTINGS_VERSION,
        activeLocationId: location.id,
        locations,
      });
      void runRefresh(location.id, false);
      return location.id;
    },

    async removeFavorite(locationId) {
      await get().hydrate();
      if (locationId === DEFAULT_WEATHER_LOCATION.id) return false;
      const current = get();
      if (!current.locations.some(item => item.id === locationId)) return false;
      const locations = current.locations.filter(item => item.id !== locationId);
      const activeLocationId = current.activeLocationId === locationId
        ? DEFAULT_WEATHER_LOCATION.id
        : current.activeLocationId;
      const entries = { ...current.entries };
      delete entries[locationId];
      queuedRefreshes.delete(locationId);
      set({ locations, activeLocationId, entries });
      persistPreferences({
        version: WEATHER_SETTINGS_VERSION,
        activeLocationId,
        locations,
      });
      if (current.activeLocationId === locationId) void runRefresh(activeLocationId, false);
      return true;
    },
  };
});

export const selectActiveWeatherLocation = (state: WeatherState): WeatherLocation => (
  state.locations.find(item => item.id === state.activeLocationId) || DEFAULT_WEATHER_LOCATION
);

export const selectActiveWeatherEntry = (state: WeatherState): WeatherEntry => (
  state.entries[state.activeLocationId] || EMPTY_WEATHER_ENTRY
);

export const selectDefaultWeatherEntry = (state: WeatherState): WeatherEntry => (
  state.entries[DEFAULT_WEATHER_LOCATION.id] || EMPTY_WEATHER_ENTRY
);
