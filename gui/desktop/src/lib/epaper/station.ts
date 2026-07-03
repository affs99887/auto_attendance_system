// 墨水屏信息站渲染器（按设计稿 墨水屏信息站.dc.html —— 400×300 四状态版）。
// 状态机（自动选择）：
//   D 请假中（个人请假，全屏：请假类型标签 + 第 N/M 天进度 + 销假上班日）
//   C 休假中（节假日/双休，全屏：假期第 N/M 天进度 + 假期结束后下个工作日）
//   A 有备忘录（备忘录 | 日历：倒计时 + 本周日历条 + 最近一个假期）
//   B 备忘录为空（日历占满全宽，同样含本周条与最近假期）
// 共用：刊头（日期/星期/农历 + 信息站 + 时间）；A/B 含 Claude 额度条（全英文、突出已用，
// 5h 只显示时间、weekly 显示日期+周几；格式 06-12（Fri）1:39 PM · 1h46m）。
//
// 渲染约定（保证内容均可见、贴合三色墨水屏）：
// - 设计坐标系即 400×300（屏幕原生分辨率），画布恰为 400×300 时 1:1 渲染、不缩放；
//   异常画布尺寸时等比缩放居中兜底。所有边线用整像素保证锐利。
// - 仅使用纯黑/纯白/纯红三色绘制，渲染完成后做像素量化（红判定收紧防抗锯齿误判），
//   预览即推屏效果，无抖动噪点。
// - 所有动态文本走 fitText 测宽截断（省略号）。

import type { ClaudeUsageResponse, CalendarInfoResponse } from '../api';
import clawdUrl from '../../assets/clawd.png';

export interface StationMemoItem {
  id: number;
  text: string;
  done: boolean;
  doneAt?: number; // 划掉时刻（epoch ms），驱动「完成超 3 天自动归档」；未完成时无此字段
}

/** 生效中的个人请假（驱动状态 D） */
export interface StationLeave {
  label: string;  // 请假类型（年假/事假…）
  start: string;  // ISO 日期
  end: string;    // ISO 日期
}

export interface StationData {
  now: Date;                            // 渲染时间戳（刊头时间）
  lunar: string;                        // 农历文本（如 农历四月廿七）
  usage: ClaudeUsageResponse | null;    // Claude 额度（不可用时显示占位）
  calendar: CalendarInfoResponse | null;
  memos: StationMemoItem[];
  clawd: HTMLImageElement | null;       // 已加载的 Clawd 像素图
  leave: StationLeave | null;           // 今天在请假区间内时非空
  leaveWorkdayAfter: string | null;     // 请假结束后的首个工作日（后端计算）
}

// 设计稿坐标系 = 屏幕原生分辨率
const DW = 400;
const DH = 300;

// 三色（纯色，量化后 1:1 映射到墨水屏）
const INK = '#000000';
const PAPER = '#ffffff';
const RED = '#ff0000';

// 字体栈（index.html 的 Google Fonts <link> 已加载 IBM Plex Sans / IBM Plex Sans SC /
// JetBrains Mono 的 400;500;600;700 与 Noto Serif SC 的 700;900——本文件用到的全部字重；
// SERIF 走 Noto Serif SC，缺字/离线时再回退 Source Han Serif SC / 系统宋体）
const SANS = "'IBM Plex Sans SC', 'IBM Plex Sans', 'Microsoft YaHei', sans-serif";
const MONO = "'JetBrains Mono', 'IBM Plex Mono', Consolas, 'Microsoft YaHei', monospace";
const SERIF = "'Noto Serif SC', 'Source Han Serif SC', SimSun, serif";
// 日历日期数字专用字体。JetBrains Mono 的"点零"(0 内嵌圆点)经墨水屏抖动二值化后，圆点与外圈
// 糊成上下两个半环，在小字号日期上极易被误读成 8。Canvas 无法可靠开启 OpenType 斜杠零
// (font-feature-settings:"zero" / font-variant-numeric 在 ctx.font 里不生效)，故改用本身就是
// 斜杠零的等宽字体：Consolas 为 Windows 系统自带(墨水屏在本机 Chromium Canvas 渲染，必可用)，
// 斜杠零、等宽、与原 mono 风格接近，0/8 一眼可分；DejaVu Sans Mono 作非 Windows 兜底。
const CAL_DAY_MONO = "Consolas, 'DejaVu Sans Mono', 'JetBrains Mono', monospace";

const WEEKDAYS_CN = ['日', '一', '二', '三', '四', '五', '六'];
const WEEKDAYS_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// 屏上备忘录最多展示条数（与设计稿一致）
export const STATION_MEMO_MAX = 6;

// ===== 版面常量（400×300）=====
const HEADER_BORDER_Y = 28;   // 刊头底边（2px）
const STRIP_BORDER_Y = 112;   // 额度条底边（2px，状态 A/B）
const BODY_TOP = 114;

// 状态 A 列分界与备忘录列几何。drawMemo（真实绘制）和 estimateVisibleMemoCount（UI 估算）
// 都从这套常量取值，保证"哪些条目能上屏"两处算出来完全一致
const BODY_SPLIT = 182;             // 备忘录列 | 日历列分界（2px 竖线 x，0.92fr/1.08fr）
const MEMO_X0 = 9;                  // 备忘录列左边界（勾选框 x）
const MEMO_X1 = BODY_SPLIT - 9;     // 备忘录列右边界
const MEMO_TEXT_X = MEMO_X0 + 20;   // 文本起点（勾选框右侧）
const MEMO_LINE_H = 16;             // 行高
const MEMO_LIST_TOP = 137;          // 列表区上界
const MEMO_LIST_BOT = 293;          // 列表区下界
const MEMO_FONT = `600 12px ${SANS}`;

// ===== Clawd 图（模块级缓存加载）=====

let clawdImage: HTMLImageElement | null = null;
let clawdPromise: Promise<HTMLImageElement | null> | null = null;

export function loadClawdImage(): Promise<HTMLImageElement | null> {
  if (clawdImage) return Promise.resolve(clawdImage);
  if (!clawdPromise) {
    clawdPromise = new Promise(resolve => {
      const img = new Image();
      img.onload = () => { clawdImage = img; resolve(img); };
      img.onerror = () => { clawdPromise = null; resolve(null); }; // 加载失败不阻塞渲染
      img.src = clawdUrl;
    });
  }
  return clawdPromise;
}

// ===== 小工具 =====

/** 文本超宽时截断加省略号 */
function fitText(ctx: CanvasRenderingContext2D, text: string, maxW: number): string {
  if (ctx.measureText(text).width <= maxW) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + '…').width > maxW) t = t.slice(0, -1);
  return t + '…';
}

/** 按渲染宽度逐字换行（CJK 友好；长串也强制断行，不加省略号） */
function wrapText(ctx: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const lines: string[] = [];
  let cur = '';
  for (const ch of text) {
    if (cur && ctx.measureText(cur + ch).width > maxW) {
      lines.push(cur);
      cur = ch === ' ' ? '' : ch; // 行首吞掉断行处的空格
    } else {
      cur += ch;
    }
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [''];
}

const p2 = (n: number) => String(n).padStart(2, '0');

/** ISO 日期 → 正午 Date（避开时区边界） */
function dateOf(iso: string): Date {
  return new Date(iso + 'T12:00:00');
}

/** 两个 ISO 日期相差天数（b - a） */
function diffDays(aIso: string, bIso: string): number {
  return Math.round((dateOf(bIso).getTime() - dateOf(aIso).getTime()) / 86400000);
}

/** Date → 本地 ISO 日期 */
function isoOf(d: Date): string {
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
}

/** 12 小时制 '1:39 PM' */
function time12(t: Date): string {
  let h = t.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12;
  if (h === 0) h = 12;
  return `${h}:${p2(t.getMinutes())} ${ampm}`;
}

/** ISO 日期 → '06-22（Mon）' */
function dateEn(iso: string): string {
  const d = dateOf(iso);
  return `${p2(d.getMonth() + 1)}-${p2(d.getDate())}（${WEEKDAYS_EN[d.getDay()]}）`;
}

/** 重置时间行。timeOnly（5h）：'1:39 PM · 1h46m'；完整（weekly）：'06-15（Mon）12:00 AM · 3d18h' */
function formatReset(resetsAt: string | null, now: Date, timeOnly: boolean): string | null {
  if (!resetsAt) return null;
  const t = new Date(resetsAt);
  if (isNaN(t.getTime())) return null;
  const when = timeOnly ? time12(t) : `${p2(t.getMonth() + 1)}-${p2(t.getDate())}（${WEEKDAYS_EN[t.getDay()]}）${time12(t)}`;
  const diffMin = Math.max(0, Math.round((t.getTime() - now.getTime()) / 60000));
  let delta: string;
  if (diffMin < 60) delta = `${diffMin}m`;
  else if (diffMin < 1440) delta = `${Math.floor(diffMin / 60)}h${p2(diffMin % 60)}m`;
  else delta = `${Math.floor(diffMin / 1440)}d${Math.floor((diffMin % 1440) / 60)}h`;
  return `${when} · ${delta}`;
}

/** ISO 日期 → 'M/D' */
function md(iso: string): string {
  const [, m, d] = iso.split('-').map(Number);
  return `${m}/${d}`;
}

/** 假期起止 → '6/19–21'（同月）或 '9/27–10/3'（跨月） */
function holidayRange(startIso: string, endIso: string): string {
  const [, sm, sd] = startIso.split('-').map(Number);
  const [, em, ed] = endIso.split('-').map(Number);
  if (startIso === endIso) return `${sm}/${sd}`;
  return sm === em ? `${sm}/${sd}–${ed}` : `${sm}/${sd}–${em}/${ed}`;
}

/** 红黑混排片段 */
interface Seg { t: string; red?: boolean }

/** 最近假期的相对时间：本周内→还有 N 天；下周→就在下周X；更远→还剩 N 周 */
function holidayWhen(startIso: string, todayIso: string): Seg[] {
  const start = dateOf(startIso);
  const today = dateOf(todayIso);
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  const weekDiff = Math.floor((start.getTime() - monday.getTime()) / (7 * 86400000));
  if (weekDiff <= 0) {
    return [{ t: '还有 ' }, { t: String(diffDays(todayIso, startIso)), red: true }, { t: ' 天' }];
  }
  if (weekDiff === 1) {
    return [{ t: '就在' }, { t: `下周${WEEKDAYS_CN[start.getDay()]}`, red: true }];
  }
  return [{ t: '还剩 ' }, { t: String(weekDiff), red: true }, { t: ' 周' }];
}

/** 右对齐绘制红黑混排片段，返回左边界 x */
function drawSegsRight(ctx: CanvasRenderingContext2D, segs: Seg[], x1: number, base: number): number {
  const total = segs.reduce((s, seg) => s + ctx.measureText(seg.t).width, 0);
  let x = x1 - total;
  const x0 = x;
  for (const seg of segs) {
    ctx.fillStyle = seg.red ? RED : INK;
    ctx.fillText(seg.t, x, base);
    x += ctx.measureText(seg.t).width;
  }
  ctx.fillStyle = INK;
  return x0;
}

// ===== 主入口（状态机）=====

export function renderStation(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  data: StationData,
): void {
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, width, height);

  // 画布恰为 400×300（正常情况）时 1:1 渲染；异常尺寸时等比缩放居中兜底，保证内容均可见
  if (width !== DW || height !== DH) {
    const s = Math.min(width / DW, height / DH);
    ctx.translate(Math.floor((width - DW * s) / 2), Math.floor((height - DH * s) / 2));
    ctx.scale(s, s);
  }

  ctx.textBaseline = 'alphabetic';
  drawHeader(ctx, data);

  const todayIso = data.calendar?.today ?? isoOf(data.now);
  const rest = data.calendar?.nearest_rest ?? null;

  if (data.leave) {
    drawFullLeave(ctx, data, todayIso);          // 状态 D · 请假中
  } else if (rest && rest.days === 0) {
    drawFullRest(ctx, data, todayIso);           // 状态 C · 休假中
  } else {
    drawClaudeStrip(ctx, data);
    if (data.memos.length > 0) {
      drawBodyA(ctx, data, todayIso);            // 状态 A · 备忘录 | 日历
    } else {
      drawBodyB(ctx, data, todayIso);            // 状态 B · 日历占满
    }
  }
  ctx.restore();

  quantizeTricolor(ctx, width, height);
}

// ===== 刊头（全状态共用）=====

function drawHeader(ctx: CanvasRenderingContext2D, data: StationData) {
  const { now } = data;
  const baseline = 20;

  // 左：日期 · 星期 · 农历
  let x = 10;
  ctx.fillStyle = INK;
  ctx.textAlign = 'left';
  ctx.font = `900 17px ${SERIF}`;
  const dateText = `${now.getMonth() + 1}月${now.getDate()}日`;
  ctx.fillText(dateText, x, baseline);
  x += ctx.measureText(dateText).width + 7;

  ctx.font = `700 13px ${SANS}`;
  const wd = `星期${WEEKDAYS_CN[now.getDay()]}`;
  ctx.fillText(wd, x, baseline - 1);
  x += ctx.measureText(wd).width + 7;

  // 右：红点 + 信息站 + 刷新时间（从右往左排）
  let rx = 390;
  ctx.font = `700 12px ${MONO}`;
  const timeText = `${p2(now.getHours())}:${p2(now.getMinutes())}`;
  rx -= ctx.measureText(timeText).width;
  ctx.fillText(timeText, rx, baseline - 1);

  // 「刷新于」前缀：内容生成于推送瞬间，屏上时间即上次刷新时间
  ctx.font = `600 11px ${SANS}`;
  const refreshLabel = '刷新于';
  rx -= 4 + ctx.measureText(refreshLabel).width;
  ctx.fillText(refreshLabel, rx, baseline - 1);

  ctx.font = `700 11px ${SANS}`;
  const title = '信息站';
  rx -= 6 + ctx.measureText(title).width;
  ctx.fillText(title, rx, baseline - 2);
  const titleX = rx;

  ctx.fillStyle = RED;
  ctx.beginPath();
  ctx.arc(rx - 9.5, baseline - 6, 3.5, 0, Math.PI * 2);
  ctx.fill();

  // 农历（夹在左组与右组之间，空间不足时省略号）
  if (data.lunar) {
    ctx.fillStyle = INK;
    ctx.font = `600 11px ${MONO}`;
    ctx.fillText(fitText(ctx, data.lunar, titleX - 21 - x), x, baseline - 1);
  }

  // 底边 2px
  ctx.fillStyle = INK;
  ctx.fillRect(0, HEADER_BORDER_Y, DW, 2);
}

// ===== Claude 额度条（状态 A/B）=====

function drawClaudeStrip(ctx: CanvasRenderingContext2D, data: StationData) {
  const top = HEADER_BORDER_Y + 2;            // 30
  const cy = (top + STRIP_BORDER_Y) / 2;      // 71

  // 大 Clawd（66px）
  let x = 10;
  if (data.clawd) {
    const ih = 66;
    const iw = ih * (data.clawd.naturalWidth / data.clawd.naturalHeight || 1);
    const prevSmooth = ctx.imageSmoothingEnabled;
    ctx.imageSmoothingEnabled = false; // 像素图保持锐利
    ctx.drawImage(data.clawd, x, cy - ih / 2, iw, ih);
    ctx.imageSmoothingEnabled = prevSmooth;
    x += iw;
  }
  x += 10;

  // 两条限额：5h 只显示时间，weekly 显示日期+周几
  const u = data.usage;
  drawQuotaGauge(ctx, x, 390, 51, '5h', u?.available ? u.five_hour : null, u?.error ?? null, data.now, true);
  drawQuotaGauge(ctx, x, 390, 88, 'weekly', u?.available ? u.seven_day : null, u?.error ?? null, data.now, false);

  // 底边 2px
  ctx.fillStyle = INK;
  ctx.fillRect(0, STRIP_BORDER_Y, DW, 2);
}

function drawQuotaGauge(
  ctx: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  labelBase: number,
  label: string,
  win: { used_pct: number; resets_at: string | null } | null,
  error: string | null,
  now: Date,
  timeOnly: boolean,
) {
  const barY = labelBase + 4;
  const barH = 10;
  const w = x1 - x0;
  const usedPct = win ? Math.round(win.used_pct) : null;

  // 标签行：左「5h 38%」（突出已用）右「1:39 PM · 1h46m」/「06-15（Mon）12:00 AM · 3d18h」
  ctx.textAlign = 'left';
  ctx.fillStyle = INK;
  ctx.font = `700 14px ${SANS}`;
  ctx.fillText(label, x0, labelBase);
  let lx = x0 + ctx.measureText(label).width + 5;
  ctx.font = `700 16px ${MONO}`;
  const pctText = usedPct != null ? `${usedPct}%` : '—';
  ctx.fillText(pctText, lx, labelBase);
  lx += ctx.measureText(pctText).width;

  ctx.textAlign = 'right';
  const reset = win ? formatReset(win.resets_at, now, timeOnly) : null;
  if (reset) {
    ctx.font = `700 ${timeOnly ? 12 : 11}px ${MONO}`;
    ctx.fillText(fitText(ctx, reset, x1 - lx - 8), x1, labelBase);
  } else {
    ctx.font = `600 10px ${SANS}`;
    ctx.fillText(fitText(ctx, error || '额度数据不可用', x1 - lx - 8), x1, labelBase);
  }
  ctx.textAlign = 'left';

  // 进度条：1px 黑描边方角 + 黑填充（填充 = 已用比例）
  ctx.fillStyle = INK;
  ctx.fillRect(x0, barY, w, barH);
  ctx.fillStyle = PAPER;
  ctx.fillRect(x0 + 1, barY + 1, w - 2, barH - 2);
  if (usedPct != null && usedPct > 0) {
    ctx.fillStyle = INK;
    ctx.fillRect(x0 + 1, barY + 1, Math.max(2, (w - 2) * (usedPct / 100)), barH - 2);
  }
}

// ===== 本周日历条（状态 A/B 共用，尺寸两档）=====

interface WeekStripStyle {
  wdFont: number;     // 星期字号
  dayFont: number;    // 日期字号
  circleR: number;    // 今天红圈半径
  wdBase: number;     // 星期基线 y
  dayCenter: number;  // 日期中心 y
}

function drawWeekStrip(
  ctx: CanvasRenderingContext2D,
  cal: CalendarInfoResponse,
  todayIso: string,
  x0: number,
  x1: number,
  st: WeekStripStyle,
) {
  const week = cal.week ?? [];
  if (week.length === 0) return;
  const colW = (x1 - x0) / 7;
  ctx.textAlign = 'center';
  week.forEach((d, i) => {
    const cx = x0 + colW * i + colW / 2;
    const wdLabel = WEEKDAYS_CN[dateOf(d.date).getDay()];
    const isToday = d.date === todayIso;

    ctx.fillStyle = d.off ? RED : INK;
    ctx.font = `600 ${st.wdFont}px ${SANS}`;
    ctx.fillText(wdLabel, cx, st.wdBase);

    if (isToday) {
      ctx.fillStyle = RED;
      ctx.beginPath();
      ctx.arc(cx, st.dayCenter, st.circleR, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = PAPER;
      ctx.font = `700 ${st.dayFont - 1}px ${CAL_DAY_MONO}`;
      ctx.fillText(String(d.d), cx, st.dayCenter + (st.dayFont - 1) * 0.36);
    } else {
      ctx.fillStyle = d.off ? RED : INK;
      ctx.font = `${d.off ? 700 : 600} ${st.dayFont}px ${CAL_DAY_MONO}`;
      ctx.fillText(String(d.d), cx, st.dayCenter + st.dayFont * 0.36);
    }
  });
  ctx.textAlign = 'left';
  ctx.fillStyle = INK;
}

// ===== 状态 A · 备忘录 | 日历 =====

function drawBodyA(ctx: CanvasRenderingContext2D, data: StationData, todayIso: string) {
  // 列分界竖线（备忘录列几何常量见 BODY_SPLIT / MEMO_* 定义处）
  ctx.fillStyle = INK;
  ctx.fillRect(BODY_SPLIT, BODY_TOP, 2, DH - BODY_TOP);

  drawMemo(ctx, data);

  // --- 日历列 ---
  const cal = data.calendar;
  const x0 = BODY_SPLIT + 12;
  const x1 = 390;
  const headBase = 131;

  ctx.textAlign = 'left';
  ctx.fillStyle = INK;
  ctx.font = `700 13px ${SANS}`;
  ctx.fillText('放假倒计时', x0, headBase);
  ctx.textAlign = 'right';
  ctx.font = `700 11px ${MONO}`;
  ctx.fillText(`${cal?.year ?? data.now.getFullYear()}·${cal?.month ?? data.now.getMonth() + 1}`, x1, headBase);
  ctx.textAlign = 'left';

  if (!cal || !cal.available) {
    ctx.font = `600 11px ${SANS}`;
    ctx.textAlign = 'center';
    ctx.fillText('日历数据不可用', (x0 + x1) / 2, 200);
    ctx.textAlign = 'left';
    return;
  }

  // 倒计时 hero（区域 135–211 垂直居中）
  const rest = cal.nearest_rest;
  const heroNum = rest ? String(rest.days) : '—';
  ctx.fillStyle = RED;
  let numFont = 48;
  ctx.font = `900 ${numFont}px ${SERIF}`;
  while (ctx.measureText(heroNum).width > 58 && numFont > 24) {
    numFont -= 5;
    ctx.font = `900 ${numFont}px ${SERIF}`;
  }
  ctx.fillText(heroNum, x0, 196);
  let hx = x0 + ctx.measureText(heroNum).width + 2;
  ctx.font = `700 15px ${SERIF}`;
  ctx.fillText('天', hx, 190);
  hx += ctx.measureText('天').width + 9;

  ctx.fillStyle = INK;
  ctx.font = `600 10px ${SANS}`;
  ctx.fillText(fitText(ctx, '距最近休息日', x1 - hx), hx, 161);
  ctx.font = `700 16px ${SANS}`;
  ctx.fillText(fitText(ctx, rest?.label ?? '—', x1 - hx), hx, 179);
  ctx.font = `600 10px ${MONO}`;
  if (rest) {
    ctx.fillText(fitText(ctx, `${md(rest.span[0])} 周${WEEKDAYS_CN[dateOf(rest.span[0]).getDay()]} 起`, x1 - hx), hx, 194);
  }

  // 本周日历条（213–253）
  ctx.fillStyle = INK;
  ctx.fillRect(x0, 213, x1 - x0, 2);
  drawWeekStrip(ctx, cal, todayIso, x0, x1, {
    wdFont: 9, dayFont: 13, circleR: 10, wdBase: 228, dayCenter: 242,
  });

  // 最近一个假期（255–293 垂直居中）
  ctx.fillStyle = INK;
  ctx.fillRect(x0, 255, x1 - x0, 2);
  drawNearestHoliday(ctx, cal, todayIso, x0, x1, 279, { nameFont: 15, rangeFont: 10, whenFont: 14, showDuration: false });
}

// ===== 状态 B · 日历占满全宽 =====

function drawBodyB(ctx: CanvasRenderingContext2D, data: StationData, todayIso: string) {
  const cal = data.calendar;
  const x0 = 12;
  const x1 = 388;
  const headBase = 134;

  ctx.textAlign = 'left';
  ctx.fillStyle = INK;
  ctx.font = `700 13px ${SANS}`;
  ctx.fillText('放假倒计时', x0, headBase);
  ctx.textAlign = 'right';
  ctx.font = `700 11px ${MONO}`;
  ctx.fillText(`${cal?.year ?? data.now.getFullYear()} · ${cal?.month ?? data.now.getMonth() + 1}月`, x1, headBase);
  ctx.textAlign = 'left';

  if (!cal || !cal.available) {
    ctx.font = `600 11px ${SANS}`;
    ctx.textAlign = 'center';
    ctx.fillText('日历数据不可用', (x0 + x1) / 2, 210);
    ctx.textAlign = 'left';
    return;
  }

  // 倒计时 hero（138–196，border-bottom 2px at 196）
  const rest = cal.nearest_rest;
  const heroNum = rest ? String(rest.days) : '—';
  ctx.fillStyle = RED;
  let numFont = 50;
  ctx.font = `900 ${numFont}px ${SERIF}`;
  while (ctx.measureText(heroNum).width > 62 && numFont > 24) {
    numFont -= 5;
    ctx.font = `900 ${numFont}px ${SERIF}`;
  }
  ctx.fillText(heroNum, x0, 188);
  let hx = x0 + ctx.measureText(heroNum).width + 3;
  ctx.font = `700 17px ${SERIF}`;
  ctx.fillText('天', hx, 181);
  hx += ctx.measureText('天').width + 14;

  ctx.fillStyle = INK;
  ctx.font = `600 12px ${SANS}`;
  ctx.fillText(fitText(ctx, '距最近休息日', x1 - hx), hx, 164);
  ctx.font = `700 18px ${SANS}`;
  const lbl = rest
    ? `${rest.label} · ${md(rest.span[0])} 周${WEEKDAYS_CN[dateOf(rest.span[0]).getDay()]}起`
    : '—';
  ctx.fillText(fitText(ctx, lbl, x1 - hx), hx, 186);

  ctx.fillStyle = INK;
  ctx.fillRect(x0, 196, x1 - x0, 2);

  // 本周日历条（198–254，border-bottom 2px at 254）
  drawWeekStrip(ctx, cal, todayIso, x0, x1, {
    wdFont: 10, dayFont: 16, circleR: 13, wdBase: 214, dayCenter: 234,
  });
  ctx.fillStyle = INK;
  ctx.fillRect(x0, 254, x1 - x0, 2);

  // 最近一个假期（256–293 垂直居中，含连休天数）
  drawNearestHoliday(ctx, cal, todayIso, x0, x1, 279, { nameFont: 18, rangeFont: 12, whenFont: 15, showDuration: true });
}

/** 最近一个假期行（A/B 共用）：左「端午节 6/19–21（· 连休3天）」右「就在下周五 / 还剩 N 周 / 还有 N 天」 */
function drawNearestHoliday(
  ctx: CanvasRenderingContext2D,
  cal: CalendarInfoResponse,
  todayIso: string,
  x0: number,
  x1: number,
  base: number,
  st: { nameFont: number; rangeFont: number; whenFont: number; showDuration: boolean },
) {
  const nh = (cal.next_holidays ?? [])[0];
  if (!nh) {
    ctx.fillStyle = INK;
    ctx.font = `600 11px ${SANS}`;
    ctx.textAlign = 'center';
    ctx.fillText('暂无近期假期', (x0 + x1) / 2, base);
    ctx.textAlign = 'left';
    return;
  }

  // 右侧相对时间
  ctx.font = `700 ${st.whenFont}px ${SANS}`;
  const whenLeft = drawSegsRight(ctx, holidayWhen(nh.start, todayIso), x1, base);

  // 左侧：假期名（红）+ 起止（· 连休N天）
  ctx.fillStyle = RED;
  ctx.font = `700 ${st.nameFont}px ${SANS}`;
  const name = fitText(ctx, nh.name, whenLeft - x0 - 50);
  ctx.fillText(name, x0, base);
  const nameW = ctx.measureText(name).width;
  ctx.fillStyle = INK;
  ctx.font = `600 ${st.rangeFont}px ${MONO}`;
  const dur = diffDays(nh.start, nh.end) + 1;
  const rangeText = st.showDuration ? `${holidayRange(nh.start, nh.end)} · 连休${dur}天` : holidayRange(nh.start, nh.end);
  ctx.fillText(fitText(ctx, rangeText, whenLeft - x0 - nameW - 14), x0 + nameW + 7, base);
}

// ===== 备忘录（状态 A）=====

// emoji 整段匹配：单个 emoji、肤色修饰、变体选择符（FE0F）、ZWJ 组合（家庭/职业等）、国旗对。
// 墨水屏只有黑白红三色，浅色 emoji 主体会被量化成白色（屏上近乎不可见），
// 逐码点断行还会把 ZWJ 组合从中间拆散，所以绘制前统一替换为占位符「◻」
const EMOJI_RE = /\p{Regional_Indicator}\p{Regional_Indicator}|\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|\uFE0F|\u200D\p{Extended_Pictographic})*/gu;

function sanitizeMemoText(text: string): string {
  return text.replace(EMOJI_RE, '◻');
}

/** 备忘录筛选与断行（drawMemo 与 estimateVisibleMemoCount 共用，保证"哪些条目上屏"口径一致）：
 * 取前 STATION_MEMO_MAX 条 → emoji 换占位符 → 按列宽逐字断行 →
 * 单条行数超过区域上限时截到最后一行加省略号（防止超长单条画穿列表区下界）→
 * 总高度仍超出时从尾部丢弃整项（绝不画半截条目） */
function layoutMemoItems(ctx: CanvasRenderingContext2D, memos: StationMemoItem[]) {
  ctx.font = MEMO_FONT; // 先设字体再量宽
  const maxW = MEMO_X1 - MEMO_TEXT_X;
  const areaH = MEMO_LIST_BOT - MEMO_LIST_TOP;
  const maxLines = Math.max(1, Math.floor(areaH / MEMO_LINE_H)); // 单条行数上限 = 整个区域能装下的整行数
  const items = memos.slice(0, STATION_MEMO_MAX).map(m => {
    const lines = wrapText(ctx, sanitizeMemoText(m.text), maxW);
    if (lines.length > maxLines) {
      lines.length = maxLines;
      lines[maxLines - 1] = fitText(ctx, lines[maxLines - 1] + '…', maxW);
    }
    return { m, lines };
  });
  // 换行后总高可能超出列表区：从尾部丢弃整项，表头计数仍示全量
  const contentH = (arr: typeof items) => arr.reduce((h, it) => h + it.lines.length * MEMO_LINE_H, 0);
  while (items.length > 1 && contentH(items) > areaH) items.pop();
  return items;
}

// 估算专用离屏画布上下文（懒建缓存）：估算发生在 UI 里、手上没有推屏画布，
// measureText 结果只取决于字体不受画布尺寸影响，与 drawMemo 量宽一致
let memoMeasureCtx: CanvasRenderingContext2D | null = null;

/** 实际可上屏的备忘录条数（与 drawMemo 同一套筛选逻辑，供 UI 判断哪些条目在屏外） */
export function estimateVisibleMemoCount(memos: StationMemoItem[]): number {
  if (!memoMeasureCtx) memoMeasureCtx = document.createElement('canvas').getContext('2d');
  if (!memoMeasureCtx) return Math.min(memos.length, STATION_MEMO_MAX); // 拿不到 2d 上下文时退回固定上限
  return layoutMemoItems(memoMeasureCtx, memos).length;
}

function drawMemo(ctx: CanvasRenderingContext2D, data: StationData) {
  const headBase = 131;

  const doneCount = data.memos.filter(m => m.done).length;

  ctx.textAlign = 'left';
  ctx.fillStyle = INK;
  ctx.font = `700 13px ${SANS}`;
  ctx.fillText('备忘录', MEMO_X0, headBase);
  ctx.textAlign = 'right';
  ctx.font = `700 12px ${MONO}`;
  ctx.fillText(`${doneCount}/${data.memos.length}`, MEMO_X1, headBase);
  ctx.textAlign = 'left';

  // 长文本按列宽换行展示（筛选/截断逻辑见 layoutMemoItems）
  const items = layoutMemoItems(ctx, data.memos);
  const areaH = MEMO_LIST_BOT - MEMO_LIST_TOP;
  const usedH = items.reduce((h, it) => h + it.lines.length * MEMO_LINE_H, 0);

  // 均匀分布（设计稿 space-between）：剩余空间均分为每项上下留白，
  // 全单行时与旧版等分槽位的基线完全一致
  const pad = Math.max(0, (areaH - usedH) / items.length / 2);
  let y = MEMO_LIST_TOP;
  items.forEach(({ m, lines }) => {
    const c0 = y + pad + MEMO_LINE_H / 2; // 首行中线（勾选框对齐首行）
    const boxY = Math.round(c0 - 7);

    if (m.done) {
      // 实心方形勾选框 + 白勾
      ctx.fillStyle = INK;
      ctx.fillRect(MEMO_X0, boxY, 14, 14);
      ctx.strokeStyle = PAPER;
      ctx.lineWidth = 2.2;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(MEMO_X0 + 3.2, boxY + 7.4);
      ctx.lineTo(MEMO_X0 + 5.8, boxY + 10);
      ctx.lineTo(MEMO_X0 + 10.8, boxY + 3.9);
      ctx.stroke();
    } else {
      ctx.strokeStyle = INK;
      ctx.lineWidth = 2;
      ctx.strokeRect(MEMO_X0 + 1, boxY + 1, 12, 12);
    }

    // 文本逐行绘制（完成项每行划删除线）
    ctx.fillStyle = INK;
    ctx.font = MEMO_FONT;
    lines.forEach((line, k) => {
      const cy = c0 + MEMO_LINE_H * k;
      ctx.fillText(line, MEMO_TEXT_X, cy + 4);
      if (m.done) {
        ctx.fillRect(MEMO_TEXT_X - 1, cy - 1, ctx.measureText(line).width + 2, 2);
      }
    });

    y = c0 - MEMO_LINE_H / 2 + lines.length * MEMO_LINE_H + pad;
  });
}

// ===== 状态 C / D 共用全屏骨架 =====

interface FullStateContent {
  title: string;                       // 休假中 / 请假中
  titleFont: number;
  tag: string | null;                  // 黑底白字标签（年假…）
  sub: Seg[];                          // 副标题（红黑混排）
  dayN: number;                        // 第 N 天
  dayTotal: number;                    // 共 M 天
  footLabel: string;                   // 假期结束 · 下个工作日 / 销假上班 · 下个工作日
  footDate: string;                    // 06-22（Mon）
}

function drawFullState(ctx: CanvasRenderingContext2D, data: StationData, c: FullStateContent) {
  // --- 中心区（30–258 垂直居中，整体水平居中）---
  const clawdH = 104;
  const clawdW = data.clawd ? clawdH * (data.clawd.naturalWidth / data.clawd.naturalHeight || 1) : 0;

  // 量宽：标题（+标签）/ 副标题 / 进度条行
  ctx.font = `900 ${c.titleFont}px ${SERIF}`;
  let titleRowW = ctx.measureText(c.title).width;
  if (c.tag) {
    ctx.font = `700 12px ${SANS}`;
    titleRowW += 8 + ctx.measureText(c.tag).width + 14;
  }
  ctx.font = `700 17px ${SANS}`;
  const subW = c.sub.reduce((s, seg) => s + ctx.measureText(seg.t).width, 0);
  const remain = c.dayTotal - c.dayN;
  const remainText = `还剩 ${remain} 天`;
  ctx.font = `700 12px ${MONO}`;
  const barRowW = 140 + 7 + ctx.measureText(remainText).width;

  const rightW = Math.max(titleRowW, subW, barRowW);
  const total = (clawdW ? clawdW + 18 : 0) + rightW;
  let x = Math.max(12, (DW - total) / 2);
  const cy = 144; // 中心区垂直中点

  if (data.clawd) {
    const prevSmooth = ctx.imageSmoothingEnabled;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(data.clawd, x, cy - clawdH / 2, clawdW, clawdH);
    ctx.imageSmoothingEnabled = prevSmooth;
    x += clawdW + 18;
  }

  // 标题 + 标签
  ctx.fillStyle = RED;
  ctx.font = `900 ${c.titleFont}px ${SERIF}`;
  const titleBase = 137;
  ctx.fillText(c.title, x, titleBase);
  if (c.tag) {
    const tw = ctx.measureText(c.title).width;
    ctx.font = `700 12px ${SANS}`;
    const tagW = ctx.measureText(c.tag).width + 14;
    const tagX = x + tw + 8;
    const tagY = titleBase - 26;
    ctx.fillStyle = INK;
    ctx.fillRect(tagX, tagY, tagW, 19);
    ctx.fillStyle = PAPER;
    ctx.fillText(c.tag, tagX + 7, tagY + 14);
  }

  // 副标题（红黑混排）
  let sx = x;
  ctx.font = `700 17px ${SANS}`;
  for (const seg of c.sub) {
    ctx.fillStyle = seg.red ? RED : INK;
    ctx.fillText(seg.t, sx, 162);
    sx += ctx.measureText(seg.t).width;
  }

  // 进度条（红填充 = 已休比例）+ 还剩 N 天
  const barY = 172;
  ctx.fillStyle = INK;
  ctx.fillRect(x, barY, 140, 11);
  ctx.fillStyle = PAPER;
  ctx.fillRect(x + 2, barY + 2, 136, 7);
  ctx.fillStyle = RED;
  ctx.fillRect(x + 2, barY + 2, Math.max(3, 136 * Math.min(1, c.dayN / c.dayTotal)), 7);
  ctx.fillStyle = INK;
  ctx.font = `700 12px ${MONO}`;
  ctx.fillText(remainText, x + 140 + 7, barY + 10);

  // --- 页脚（border-top 2px at 260）---
  ctx.fillStyle = INK;
  ctx.fillRect(0, 260, DW, 2);
  ctx.font = `700 13px ${SANS}`;
  ctx.fillText(c.footLabel, 14, 285);
  ctx.textAlign = 'right';
  ctx.font = `700 14px ${MONO}`;
  ctx.fillText(c.footDate, 386, 285);
  ctx.textAlign = 'left';
}

// ===== 状态 C · 休假中（节假日/双休全屏）=====

function drawFullRest(ctx: CanvasRenderingContext2D, data: StationData, todayIso: string) {
  const rest = data.calendar!.nearest_rest!;
  const name = rest.name ?? '周末双休';
  const dayN = diffDays(rest.span[0], todayIso) + 1;
  const total = diffDays(rest.span[0], rest.span[1]) + 1;
  drawFullState(ctx, data, {
    title: '休假中',
    titleFont: 46,
    tag: null,
    sub: [{ t: `${name} · 假期第 ` }, { t: String(dayN), red: true }, { t: ` / ${total} 天` }],
    dayN,
    dayTotal: total,
    footLabel: '假期结束 · 下个工作日',
    footDate: dateEn(rest.next_workday),
  });
}

// ===== 状态 D · 请假中（个人请假全屏）=====

function drawFullLeave(ctx: CanvasRenderingContext2D, data: StationData, todayIso: string) {
  const leave = data.leave!;
  const dayN = diffDays(leave.start, todayIso) + 1;
  const total = diffDays(leave.start, leave.end) + 1;
  // 销假日：后端算的首个工作日；缺失时退化为请假结束次日
  const backIso = data.leaveWorkdayAfter
    ?? isoOf(new Date(dateOf(leave.end).getTime() + 86400000));
  drawFullState(ctx, data, {
    title: '请假中',
    titleFont: 44,
    tag: leave.label || '请假',
    sub: [{ t: '请假第 ' }, { t: String(dayN), red: true }, { t: ` / ${total} 天` }],
    dayN,
    dayTotal: total,
    footLabel: '销假上班 · 下个工作日',
    footDate: dateEn(backIso),
  });
}

// ===== 像素量化（预览即推屏效果）=====

/** 把画布所有像素归到 黑/白/红 三色。
 * 红判定比 processImageData 更严（要求红显著高于绿蓝）：文字抗锯齿的彩色边缘像素
 * 不会被误判为红；量化产物是三种纯色，推屏时 processImageData 与此 1:1 对应。 */
function quantizeTricolor(ctx: CanvasRenderingContext2D, width: number, height: number) {
  const img = ctx.getImageData(0, 0, width, height);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i], g = d[i + 1], b = d[i + 2];
    if (r > 160 && r - g > 60 && r - b > 60) {
      d[i] = 255; d[i + 1] = 0; d[i + 2] = 0;
    } else {
      const lum = 0.299 * r + 0.587 * g + 0.114 * b;
      const v = lum < 140 ? 0 : 255;
      d[i] = v; d[i + 1] = v; d[i + 2] = v;
    }
    d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}
