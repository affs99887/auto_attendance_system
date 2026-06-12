// 农历换算（墨水屏信息站刊头用）。
// 经典查表算法：LUNAR_INFO 每项 1 个 16 进制数编码一个农历年（1900–2100）——
// bit 16 为闰月大小（1=30天），bit 15–4 为 12 个月的大小月（1=30天），bit 3–0 为闰月月份（0=无闰月）。
// 仅输出「农历X月XX」文本，范围外返回空串。

/* eslint-disable */
const LUNAR_INFO = [
  0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d2,
  0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977,
  0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970,
  0x06566, 0x0d4a0, 0x0ea50, 0x16a95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950,
  0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557,
  0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0,
  0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0,
  0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b6a0, 0x195a6,
  0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570,
  0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x05ac0, 0x0ab60, 0x096d5, 0x092e0,
  0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5,
  0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930,
  0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530,
  0x05aa0, 0x076a3, 0x096d0, 0x04afb, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45,
  0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0,
  0x14b63, 0x09370, 0x049f8, 0x04970, 0x064b0, 0x168a6, 0x0ea50, 0x06b20, 0x1a6c4, 0x0aae0,
  0x0a2e0, 0x0d2e3, 0x0c960, 0x0d557, 0x0d4a0, 0x0da50, 0x05d55, 0x056a0, 0x0a6d0, 0x055d4,
  0x052d0, 0x0a9b8, 0x0a950, 0x0b4a0, 0x0b6a6, 0x0ad50, 0x055a0, 0x0aba4, 0x0a5b0, 0x052b0,
  0x0b273, 0x06930, 0x07337, 0x06aa0, 0x0ad50, 0x14b55, 0x04b60, 0x0a570, 0x054e4, 0x0d160,
  0x0e968, 0x0d520, 0x0daa0, 0x16aa6, 0x056d0, 0x04ae0, 0x0a9d4, 0x0a2d0, 0x0d150, 0x0f252,
  0x0d520,
];
/* eslint-enable */

const MONTH_CN = ['正', '二', '三', '四', '五', '六', '七', '八', '九', '十', '冬', '腊'];
const DAY_PREFIX = ['初', '十', '廿', '三'];
const DIGIT_CN = ['日', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];

/** 农历 y 年总天数 */
function lunarYearDays(y: number): number {
  let sum = 348;
  for (let i = 0x8000; i > 0x8; i >>= 1) sum += LUNAR_INFO[y - 1900] & i ? 1 : 0;
  return sum + leapDays(y);
}

/** 农历 y 年闰几月（0 = 无闰月） */
function leapMonth(y: number): number {
  return LUNAR_INFO[y - 1900] & 0xf;
}

/** 农历 y 年闰月天数（无闰月为 0） */
function leapDays(y: number): number {
  if (leapMonth(y)) return LUNAR_INFO[y - 1900] & 0x10000 ? 30 : 29;
  return 0;
}

/** 农历 y 年 m 月（非闰）天数 */
function monthDays(y: number, m: number): number {
  return LUNAR_INFO[y - 1900] & (0x10000 >> m) ? 30 : 29;
}

/** 农历日 → 「初一/十五/廿六/三十」 */
function dayCn(d: number): string {
  if (d === 10) return '初十';
  if (d === 20) return '二十';
  if (d === 30) return '三十';
  return DAY_PREFIX[Math.floor(d / 10)] + DIGIT_CN[d % 10];
}

/** 公历 Date → 「农历X月XX」（如 农历四月廿七）；超出 1900–2100 返回空串。 */
export function lunarText(date: Date): string {
  // 以 UTC 天数差计算，规避时区/夏令时
  const base = Date.UTC(1900, 0, 31); // 农历 1900 年正月初一
  let offset = Math.floor((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) - base) / 86400000);
  if (offset < 0) return '';

  let year = 1900;
  for (; year < 2101 && offset >= lunarYearDays(year); year++) offset -= lunarYearDays(year);
  if (year >= 2101) return '';

  const leap = leapMonth(year);
  let isLeap = false;
  let i = 1;
  let temp = 0;
  for (; i < 13 && offset > 0; i++) {
    if (leap > 0 && i === leap + 1 && !isLeap) {
      // 进入闰月：本轮按闰月计，月序号回退一格
      --i;
      isLeap = true;
      temp = leapDays(year);
    } else {
      temp = monthDays(year, i);
    }
    if (isLeap && i === leap + 1) isLeap = false; // 闰月走完，解除标记
    offset -= temp;
  }
  // offset 恰为 0 且下一月正是闰月时的边界修正（经典实现一致）
  if (offset === 0 && leap > 0 && i === leap + 1) {
    if (isLeap) {
      isLeap = false;
    } else {
      isLeap = true;
      --i;
    }
  }
  if (offset < 0) {
    offset += temp;
    --i;
  }

  return `农历${isLeap ? '闰' : ''}${MONTH_CN[i - 1]}月${dayCn(offset + 1)}`;
}
