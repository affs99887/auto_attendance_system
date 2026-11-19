// 太阳此刻在某个地点的位置。天空背景（lib/sky.ts）按太阳离地平线多高来换时段的样子：
// 同一时刻，拉萨的天还没亮，上海已经出太阳了；冬天和夏天日出日落的钟点也不一样。
// 算法是常用的简化太阳位置公式，误差在 0.1 度以内，定日出日落前后的天色足够用。

export interface SunLight {
  /** 太阳高度：在地平线以上为正、以下为负，单位度 */
  elevation: number;
  /** 太阳是不是还在往上走（半夜到中午）；false 是中午到半夜 */
  rising: boolean;
  /** 这一天正午太阳能升到多高 */
  peak: number;
}

const RAD = Math.PI / 180;

export function sunAt(latitude: number, longitude: number, date: Date): SunLight {
  // 从 2000-01-01 12:00（世界时）起算的天数
  const n = date.getTime() / 86_400_000 - 10_957.5;
  const meanLongitude = 280.46 + 0.9856474 * n;
  const anomaly = (357.528 + 0.9856003 * n) * RAD;
  const eclipticLongitude = (meanLongitude + 1.915 * Math.sin(anomaly) + 0.02 * Math.sin(2 * anomaly)) * RAD;
  const obliquity = (23.439 - 0.0000004 * n) * RAD;
  const rightAscension = Math.atan2(Math.cos(obliquity) * Math.sin(eclipticLongitude), Math.cos(eclipticLongitude)) / RAD;
  const declination = Math.asin(Math.sin(obliquity) * Math.sin(eclipticLongitude)) / RAD;
  const siderealTime = 280.46061837 + 360.98564736629 * n;
  // 时角：太阳离正南方向还差多少度，换算到 -180 ~ 180，负数表示还没到正午
  const hourAngle = (((siderealTime + longitude - rightAscension) % 360) + 540) % 360 - 180;
  const lat = latitude * RAD, dec = declination * RAD;
  const elevation = Math.asin(Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(hourAngle * RAD)) / RAD;
  return { elevation, rising: hourAngle < 0, peak: 90 - Math.abs(latitude - declination) };
}
