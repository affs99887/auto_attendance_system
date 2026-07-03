// EPD-nRF5 蓝牙协议常量与纯数据（指令、画布尺寸/驱动表、UC8159 转换、假期编码）。
// 协议定义见 https://github.com/tsl0922/EPD-nRF5

export const EpdCmd = {
  SET_PINS: 0x00,
  INIT: 0x01,
  CLEAR: 0x02,
  SEND_CMD: 0x03,
  SEND_DATA: 0x04,
  REFRESH: 0x05,
  SLEEP: 0x06,

  SET_TIME: 0x20,

  WRITE_IMG: 0x30, // v1.6

  SET_CONFIG: 0x90,
  SYS_RESET: 0x91,
  SYS_SLEEP: 0x92,
  CFG_ERASE: 0x99,

  SET_HOLIDAYS: 0xb6, // 设置假期数据
} as const;

export const EPD_SERVICE_UUID = '62750001-d828-918d-fb46-b6c11c675aec';
export const EPD_CHARACTERISTIC_UUID = '62750002-d828-918d-fb46-b6c11c675aec';
export const EPD_VERSION_CHARACTERISTIC_UUID = '62750003-d828-918d-fb46-b6c11c675aec';

export interface CanvasSize {
  name: string;
  width: number;
  height: number;
}

export const canvasSizes: CanvasSize[] = [
  { name: '1.54_152_152', width: 152, height: 152 },
  { name: '1.54_200_200', width: 200, height: 200 },
  { name: '2.13_212_104', width: 212, height: 104 },
  { name: '2.13_250_122', width: 250, height: 122 },
  { name: '2.66_296_152', width: 296, height: 152 },
  { name: '2.9_296_128', width: 296, height: 128 },
  { name: '2.9_384_168', width: 384, height: 168 },
  { name: '3.5_384_184', width: 384, height: 184 },
  { name: '3.7_416_240', width: 416, height: 240 },
  { name: '3.97_800_480', width: 800, height: 480 },
  { name: '4.2_400_300', width: 400, height: 300 },
  { name: '5.79_792_272', width: 792, height: 272 },
  { name: '5.83_600_448', width: 600, height: 448 },
  { name: '5.83_648_480', width: 648, height: 480 },
  { name: '7.5_640_384', width: 640, height: 384 },
  { name: '7.5_800_480', width: 800, height: 480 },
  { name: '7.5_880_528', width: 880, height: 528 },
  { name: '10.2_960_640', width: 960, height: 640 },
  { name: '10.85_1360_480', width: 1360, height: 480 },
  { name: '11.6_960_640', width: 960, height: 640 },
  { name: '4E_600_400', width: 600, height: 400 },
  { name: '7.3E6', width: 480, height: 800 },
];

export const canvasSizeLabels: Record<string, string> = {
  '1.54_152_152': '1.54 (152x152)',
  '1.54_200_200': '1.54 (200x200)',
  '2.13_212_104': '2.13 (212x104)',
  '2.13_250_122': '2.13 (250x122)',
  '2.66_296_152': '2.66 (296x152)',
  '2.9_296_128': '2.9 (296x128)',
  '2.9_384_168': '2.9 (384x168)',
  '3.5_384_184': '3.5 (384x184)',
  '3.7_416_240': '3.7 (416x240)',
  '3.97_800_480': '3.97 (800x480)',
  '4.2_400_300': '4.2 (400x300)',
  '5.79_792_272': '5.79 (792x272)',
  '5.83_600_448': '5.83 (600x448)',
  '5.83_648_480': '5.83 (648x480)',
  '7.5_640_384': '7.5 (640x384)',
  '7.5_800_480': '7.5 (800x480)',
  '7.5_880_528': '7.5 (880x528)',
  '10.2_960_640': '10.2 (960x640)',
  '10.85_1360_480': '10.85 (1360x480)',
  '11.6_960_640': '11.6 (960x640)',
  '4E_600_400': '4E (600x400)',
  '7.3E6': '7.3E6 (480x800)',
};

import type { DitherMode } from './dithering';

export interface EpdDriver {
  value: string;       // 写入 INIT 指令的驱动 ID（hex 字符串）
  label: string;
  color: DitherMode;   // 匹配的颜色模式
  size: string;        // 匹配的画布尺寸 name
}

export const epdDrivers: EpdDriver[] = [
  { value: '01', label: '4.2寸 (黑白, UC8176)', color: 'blackWhiteColor', size: '4.2_400_300' },
  { value: '03', label: '4.2寸 (三色, UC8176)', color: 'threeColor', size: '4.2_400_300' },
  { value: '04', label: '4.2寸 (黑白, SSD1619)', color: 'blackWhiteColor', size: '4.2_400_300' },
  { value: '02', label: '4.2寸 (三色, SSD1619)', color: 'threeColor', size: '4.2_400_300' },
  { value: '05', label: '4.2寸 (四色, JD79668)', color: 'fourColor', size: '4.2_400_300' },
  { value: '0d', label: '5.83寸 (四色, JD79665)', color: 'fourColor', size: '5.83_648_480' },
  { value: '06', label: '7.5寸 (黑白, UC8179)', color: 'blackWhiteColor', size: '7.5_800_480' },
  { value: '07', label: '7.5寸 (三色, UC8179)', color: 'threeColor', size: '7.5_800_480' },
  { value: '0c', label: '7.5寸 (四色, JD79665)', color: 'fourColor', size: '7.5_800_480' },
  { value: '08', label: '7.5寸低分 (黑白, UC8159)', color: 'blackWhiteColor', size: '7.5_640_384' },
  { value: '09', label: '7.5寸低分 (三色, UC8159)', color: 'threeColor', size: '7.5_640_384' },
  { value: '0a', label: '7.5寸HD (黑白, SSD1677)', color: 'blackWhiteColor', size: '7.5_880_528' },
  { value: '0b', label: '7.5寸HD (三色, SSD1677)', color: 'threeColor', size: '7.5_880_528' },
];

// 严格解析 16 进制字符串：含非 hex 字符或长度为奇数时返回 null，由调用方负责提示。
// 不校验的话 parseInt 会得到 NaN，塞进 Uint8Array 被静默转成 0x00 下发到设备（可能变成危险指令）。
export function hex2bytes(hex: string): Uint8Array | null {
  if (hex.length % 2 !== 0 || !/^[0-9a-fA-F]*$/.test(hex)) return null;
  const bytes: number[] = [];
  for (let c = 0; c < hex.length; c += 2) {
    bytes.push(parseInt(hex.substr(c, 2), 16));
  }
  return new Uint8Array(bytes);
}

export function bytes2hex(data: ArrayLike<number>): string {
  return new Uint8Array(data as Uint8Array).reduce(
    (memo, i) => memo + ('0' + i.toString(16)).slice(-2),
    '',
  );
}

// UC8159（7.5寸低分）专用：黑白层 + 红白层 → 每像素 4bit 的发送格式
export function convertUC8159(blackWhiteData: Uint8Array, redWhiteData: Uint8Array): Uint8Array {
  const halfLength = blackWhiteData.length;
  const payloadData = new Uint8Array(halfLength * 4);
  let payloadIdx = 0;
  let black_data: number, color_data: number, data: number;
  for (let i = 0; i < halfLength; i++) {
    black_data = blackWhiteData[i];
    color_data = redWhiteData[i];
    for (let j = 0; j < 8; j++) {
      if ((color_data & 0x80) === 0x00) data = 0x04;       // red
      else if ((black_data & 0x80) === 0x00) data = 0x00;  // black
      else data = 0x03;                                    // white
      data = (data << 4) & 0xff;
      black_data = (black_data << 1) & 0xff;
      color_data = (color_data << 1) & 0xff;
      j++;
      if ((color_data & 0x80) === 0x00) data |= 0x04;      // red
      else if ((black_data & 0x80) === 0x00) data |= 0x00; // black
      else data |= 0x03;                                   // white
      black_data = (black_data << 1) & 0xff;
      color_data = (color_data << 1) & 0xff;
      payloadData[payloadIdx++] = data;
    }
  }
  return payloadData;
}

// ==================== 假期数据 ====================

// 按月份计算合法天数上限（含闰年判断）。未提供 year 时，2 月按 29 天放宽，
// 避免误杀真实存在的 2-29；提供 year 时（来自 buildHolidayPayload 的同一年份）按实际闰年判定。
function daysInMonth(month: number, year?: number): number {
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month === 2) {
    if (year === undefined) return 29; // 年份未知时放宽到 29，防止误判 2-29
    const isLeap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
    return isLeap ? 29 : 28;
  }
  return monthDays[month - 1];
}

// 解析「月-日-类型」逐行文本（# 与 // 行为注释）→ 设备编码：Bit15-12=工作标志, Bit11-8=月份, Bit7-0=日期
// 可选 year 用于按月份/闰年校验当天合法天数上限，杜绝 2-30 / 4-31 等不存在的日期被编码下发。
export function parseHolidayData(text: string, onInvalidLine?: (line: string) => void, year?: number): number[] {
  const lines = text.trim().split('\n');
  const holidays: number[] = [];

  for (let line of lines) {
    line = line.trim();
    if (!line || line.startsWith('#') || line.startsWith('//')) continue;

    const parts = line.split(/[-\s,]+/);
    if (parts.length >= 3) {
      const month = parseInt(parts[0]);
      const day = parseInt(parts[1]);
      const isWork = parseInt(parts[2]);

      // 先校验月份与工作标志，再按月份（含闰年）的实际天数上限校验日期，过滤非法日期
      if (
        month >= 1 && month <= 12 &&
        (isWork === 0 || isWork === 1) &&
        day >= 1 && day <= daysInMonth(month, year)
      ) {
        const encoded = (isWork << 12) | (month << 8) | day;
        holidays.push(encoded);
      } else {
        onInvalidLine?.(line);
      }
    }
  }

  return holidays;
}

// 构建 SET_HOLIDAYS 数据包: [年份:2] [数量:1] [假期数据:n*2]
export function buildHolidayPayload(year: number, holidays: number[]): Uint8Array {
  const data = new Uint8Array(3 + holidays.length * 2);
  data[0] = (year >> 8) & 0xff;
  data[1] = year & 0xff;
  data[2] = holidays.length;

  for (let i = 0; i < holidays.length; i++) {
    data[3 + i * 2] = (holidays[i] >> 8) & 0xff;
    data[3 + i * 2 + 1] = holidays[i] & 0xff;
  }

  return data;
}

// 2026年默认假期数据
export const DEFAULT_HOLIDAYS_2026 = `1-1-0
1-2-0
1-3-0
1-4-1
2-14-1
2-15-0
2-16-0
2-17-0
2-18-0
2-19-0
2-20-0
2-21-0
2-22-0
2-23-0
2-28-1
4-4-0
4-5-0
4-6-0
5-1-0
5-2-0
5-3-0
5-4-0
5-5-0
5-9-1
6-19-0
6-20-0
6-21-0
9-20-1
9-25-0
9-26-0
9-27-0
10-1-0
10-2-0
10-3-0
10-4-0
10-5-0
10-6-0
10-7-0
10-10-1`;

// 2027年默认假期数据（示例，需要根据实际情况调整）
export const DEFAULT_HOLIDAYS_2027 = `1-1-0
1-2-0
1-3-0
2-6-0
2-7-0
2-8-0
2-9-0
2-10-0
2-11-0
2-12-0
4-3-0
4-4-0
4-5-0
5-1-0
5-2-0
5-3-0
6-9-0
6-10-0
6-11-0
9-15-0
9-16-0
9-17-0
10-1-0
10-2-0
10-3-0
10-4-0
10-5-0
10-6-0
10-7-0`;
