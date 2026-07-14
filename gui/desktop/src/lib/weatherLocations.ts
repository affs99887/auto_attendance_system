import adcodeCsv from '../data/caiyun-adcodes.csv?raw';

export interface WeatherLocation {
  id: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
}

export const DEFAULT_WEATHER_LOCATION: WeatherLocation = {
  id: 'fixed:huashan-road-1076',
  name: '华山路1076号',
  address: '上海市长宁区华山路1076号',
  // 公开地图坐标由 BD-09 转为 GCJ-02，供彩云天气查询使用。
  latitude: 31.21126179,
  longitude: 121.43584026,
};

interface CatalogRow {
  adcode: string;
  address: string;
  name: string;
  latitude: number;
  longitude: number;
}

const sourceRows = adcodeCsv
  .trim()
  .split(/\r?\n/)
  .slice(1)
  .map(line => {
    const [adcode, address, longitudeText, latitudeText] = line.split(',');
    return {
      adcode,
      address,
      latitude: Number(latitudeText),
      longitude: Number(longitudeText),
    };
  })
  .filter(row => (
    /^\d{6}$/.test(row.adcode)
    && Boolean(row.address)
    && Number.isFinite(row.latitude)
    && Number.isFinite(row.longitude)
  ));

const sourceByCode = new Map(sourceRows.map(row => [row.adcode, row]));

function parentCode(adcode: string): string | null {
  if (adcode.endsWith('0000')) return null;
  if (adcode.endsWith('00')) return `${adcode.slice(0, 2)}0000`;
  return `${adcode.slice(0, 4)}00`;
}

const catalog: CatalogRow[] = sourceRows.map(row => {
  const parent = parentCode(row.adcode);
  const parentAddress = parent ? sourceByCode.get(parent)?.address || '' : '';
  const shortName = parentAddress && row.address.startsWith(parentAddress)
    ? row.address.slice(parentAddress.length)
    : row.address;
  return {
    ...row,
    name: shortName || row.address,
  };
});

const catalogByCode = new Map(catalog.map(row => [row.adcode, row]));
const POPULAR_AD_CODES = [
  '310100', // 上海
  '110100', // 北京
  '440100', // 广州
  '440300', // 深圳
  '330100', // 杭州
  '510100', // 成都
  '420100', // 武汉
  '610100', // 西安
  '320100', // 南京
  '320500', // 苏州
  '500100', // 重庆
  '120100', // 天津
];

function toWeatherLocation(row: CatalogRow): WeatherLocation {
  return {
    id: `adcode:${row.adcode}`,
    name: row.name,
    address: row.address,
    latitude: row.latitude,
    longitude: row.longitude,
  };
}

function normalizeQuery(value: string): string {
  return value.trim().replace(/\s+/g, '').toLocaleLowerCase('zh-CN');
}

function matchScore(row: CatalogRow, query: string): number | null {
  const name = normalizeQuery(row.name);
  const address = normalizeQuery(row.address);
  if (row.adcode === query || name === query || address === query) return 0;
  if (name.startsWith(query)) return 1;
  if (address.endsWith(query)) return 2;
  if (name.includes(query)) return 3;
  if (address.includes(query)) return 4;
  if (row.adcode.startsWith(query)) return 5;
  return null;
}

function administrativeLevelPriority(row: CatalogRow): number {
  if (row.adcode.endsWith('0000')) return 2;
  if (row.adcode.endsWith('00')) return 1;
  return 0;
}

/**
 * 在彩云官方行政区划坐标表中本地搜索。空关键词返回常用城市，
 * 不发网络请求，也不会把用户输入发送给第三方。
 */
export function searchWeatherLocations(queryText: string, limit = 12): WeatherLocation[] {
  const query = normalizeQuery(queryText);
  const matched = query
    ? catalog
      .map(row => ({ row, score: matchScore(row, query) }))
      .filter((item): item is { row: CatalogRow; score: number } => item.score !== null)
      .sort((a, b) => (
        a.score - b.score
        || a.row.address.length - b.row.address.length
        || administrativeLevelPriority(a.row) - administrativeLevelPriority(b.row)
        || a.row.adcode.localeCompare(b.row.adcode)
      ))
      .map(item => item.row)
    : POPULAR_AD_CODES
      .map(code => catalogByCode.get(code))
      .filter((row): row is CatalogRow => Boolean(row));

  const seenAddresses = new Set<string>();
  const results: WeatherLocation[] = [];
  for (const row of matched) {
    if (seenAddresses.has(row.address)) continue;
    seenAddresses.add(row.address);
    results.push(toWeatherLocation(row));
    if (results.length >= limit) break;
  }
  return results;
}
