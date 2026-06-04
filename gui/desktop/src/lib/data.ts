// Mock 数据 — 与设计稿 data.jsx 对齐。阶段 2c 后 RECORDS / RECENT_ACTIVITY /
// SCHEDULED_TASKS 将被后端 API 数据替代；USERS / COMMANDS / PUNCH_STEPS_*
// 保持本地常量。
import type {
  CommandEntry,
  RecentActivityEntry,
  RecordsByUser,
  ScheduledTask,
  User,
} from './types';

export const TODAY = '2026-05-19';

export const USERS: User[] = [
  // 邓蕴哲已离职（2026-06），切单用户后注释保留；恢复双账号时取消下行注释，并把赖得鑫 env 改回 LOGIN_USERNAME2
  // { id: '邓蕴哲', name: '邓蕴哲', env: 'LOGIN_USERNAME', short: '邓', color: 'oklch(0.55 0.13 250)' },
  { id: '赖得鑫', name: '赖得鑫', env: 'LOGIN_USERNAME', short: '赖', color: 'oklch(0.55 0.13 30)' },
];

export const RECORDS: RecordsByUser = {
  邓蕴哲: {
    '2026-05': {
      '2026-05-07': { in: '08:37:00', out: '16:54:00' },
      '2026-05-08': { in: '08:28:00', out: '16:46:00' },
      '2026-05-09': { in: '08:31:00', out: '16:49:00' },
      '2026-05-11': { in: '08:29:00', out: '16:57:00' },
      '2026-05-12': { in: '08:27:00', out: '16:47:00' },
      '2026-05-13': { in: '08:27:00', out: '16:52:00' },
      '2026-05-14': { in: '08:28:00', out: '16:45:00' },
      '2026-05-15': { in: '08:25:00', out: '16:53:00' },
      '2026-05-18': { in: '08:46:00', out: '17:03:00' },
      '2026-05-19': { in: '08:29:47', out: null },
    },
    '2026-04': {
      '2026-04-13': { in: '08:31:00', out: '16:49:00' },
      '2026-04-14': { in: '08:32:00', out: '16:54:00' },
      '2026-04-15': { in: '08:27:00', out: '16:52:00' },
      '2026-04-16': { in: '08:28:00', out: '16:47:00' },
      '2026-04-17': { in: '08:31:00', out: '16:49:00' },
      '2026-04-20': { in: '08:47:00', out: '17:04:00' },
      '2026-04-21': { in: '08:29:00', out: '16:50:00' },
      '2026-04-22': { in: '08:38:00', out: '17:02:00' },
      '2026-04-23': { in: '08:30:00', out: '16:49:00' },
      '2026-04-24': { in: '08:25:00', out: '16:44:00' },
      '2026-04-27': { in: '08:31:00', out: null },
      '2026-04-28': { in: '08:33:00', out: '16:50:00' },
      '2026-04-29': { in: '08:35:00', out: '16:52:00' },
      '2026-04-30': { in: '08:36:00', out: null },
    },
  },
  赖得鑫: {
    '2026-05': {
      '2026-05-07': { in: '08:42:00', out: '17:01:00' },
      '2026-05-08': { in: '08:33:00', out: '16:55:00' },
      '2026-05-11': { in: '08:38:00', out: '17:08:00' },
      '2026-05-12': { in: '08:32:00', out: '16:58:00' },
      '2026-05-13': { in: '08:31:00', out: '17:02:00' },
      '2026-05-14': { in: '08:35:00', out: '16:51:00' },
      '2026-05-15': { in: '08:29:00', out: '17:00:00' },
      '2026-05-18': { in: '08:51:00', out: '17:14:00' },
      '2026-05-19': { in: '08:31:12', out: null },
    },
  },
};

export const SCHEDULED_TASKS: ScheduledTask[] = [
  {
    id: 'daily_reminder',
    name: '每日 8:15 提醒',
    nextRun: '2026-05-20 08:15:00',
    tag: 'daily_reminder',
    fn: 'daily_reminder_job',
    recurring: true,
  },
  {
    id: 'auto_byebye_dyz',
    name: '自动下班 · 邓蕴哲',
    nextRun: '2026-05-19 16:44:47',
    tag: 'punch_out_scheduled',
    fn: 'auto_punch_out (workhours=8h15m)',
    user: '邓蕴哲',
    recurring: false,
  },
  {
    id: 'auto_byebye_ldx',
    name: '自动下班 · 赖得鑫',
    nextRun: '2026-05-19 16:46:12',
    tag: 'punch_out_scheduled',
    fn: 'auto_punch_out (workhours=8h15m)',
    user: '赖得鑫',
    recurring: false,
  },
  {
    id: 'daily_status',
    name: '每日状态推送',
    nextRun: '2026-05-20 08:20:00',
    tag: 'daily_status',
    fn: 'send_daily_status',
    recurring: true,
  },
];

export const RECENT_ACTIVITY: RecentActivityEntry[] = [
  // 邓蕴哲已离职（2026-06），切单用户后注释保留：
  // { ts: '08:29:55', user: '邓蕴哲', type: 'punch_in', status: 'ok', method: 'Selenium', detail: '登录成功 · 打卡按钮点击成功' },
  { ts: '08:30:02', user: '赖得鑫', type: 'punch_in', status: 'ok', method: 'Selenium', detail: '并行打卡 · 全员成功' },
  { ts: '08:20:00', user: 'system', type: 'daily_status', status: 'ok', method: 'schedule', detail: '已发送每日状态推送' },
  { ts: '08:15:00', user: 'system', type: 'reminder', status: 'ok', method: 'schedule', detail: '8:15 每日提醒已触发' },
  { ts: '00:01:13', user: 'system', type: 'log_rotate', status: 'ok', method: 'system', detail: 'attendance_system.log 已轮转' },
  // { ts: '2026-05-18 17:03:00', user: '邓蕴哲', type: 'punch_out', status: 'ok', method: 'Selenium', detail: '工作时长 8h17m' },
  { ts: '2026-05-18 17:14:00', user: '赖得鑫', type: 'punch_out', status: 'ok', method: 'Selenium', detail: '工作时长 8h23m' },
];

export const COMMANDS: CommandEntry[] = [
  { cmd: '/start', desc: '显示帮助信息' },
  { cmd: '/punch_in', desc: '上班打卡（Selenium 模式自动并行）' },
  { cmd: '/punch_out', desc: '下班打卡' },
  { cmd: '/auto_byebye', desc: '根据上班时间计算 8h15m + 1–3min 随机延迟后自动下班' },
  { cmd: '/stop', desc: '终止当前正在进行的打卡操作' },
  { cmd: '/status', desc: '查看系统状态（含当前操作）' },
  { cmd: '/errors', desc: '查看最近错误日志' },
  { cmd: '/kill', desc: '查看并管理定时任务；/kill <ID> 删除指定任务' },
  { cmd: '/set_time', desc: '设置定时打卡时间' },
  { cmd: '/check', desc: '查看最新打卡截图；/check <用户名>' },
  { cmd: '/parallel', desc: '并行登录测试（仅登录、不打卡）' },
  { cmd: '/mode', desc: '切换登录模式（Selenium / 图像识别）' },
  { cmd: '/test_reminder', desc: '测试 8:15 每日提醒' },
  { cmd: '/selenium_complete_punch_in', desc: 'Selenium 完整流程上班打卡（含状态验证）' },
  { cmd: '/selenium_complete_punch_out', desc: 'Selenium 完整流程下班打卡（含状态验证）' },
];

export const PUNCH_STEPS_IN: string[] = [
  '初始化 Selenium WebDriver',
  '打开登录 URL 并处理证书弹窗',
  'OCR 识别用户名/密码字段并粘贴',
  '提交登录表单 · 等待页面加载',
  '扫描首页按钮状态（gotowork/offwork）',
  '点击「上班打卡」按钮',
  '等待按钮状态翻转验证',
  '截图并保存到 screenshots/<user>/punch_in/',
  '更新 punch_records/<user>/YYYY_MM.json',
  'Telegram 通知 + 邮件抄送',
];

export const PUNCH_STEPS_OUT: string[] = [
  '初始化 Selenium WebDriver',
  '打开登录 URL · 处理证书弹窗',
  '登录并等待首页加载',
  '扫描按钮状态 · 计算工作时长',
  '校验是否到达下班时间或工时已满',
  '点击「下班打卡」按钮',
  '解析 left_time / unable_escape 警告',
  '截图保存 · 状态写入记录文件',
  '失败时按最长剩余时间调度重试',
  'Telegram + 邮件通知',
];

// ---------- helpers ----------

export function getUserRecords(userId: string, ym: string) {
  const user = RECORDS[userId];
  if (!user) return {};
  return user[ym] || {};
}

export function flattenUserRecords(userId: string) {
  const user = RECORDS[userId];
  if (!user) return [] as Array<{ date: string; ym: string; in: string | null; out: string | null; user: string }>;
  const rows: Array<{ date: string; ym: string; in: string | null; out: string | null; user: string }> = [];
  Object.entries(user).forEach(([ym, recs]) => {
    Object.entries(recs).forEach(([date, rec]) =>
      rows.push({ date, ym, in: rec.in, out: rec.out, user: userId }),
    );
  });
  rows.sort((a, b) => b.date.localeCompare(a.date));
  return rows;
}

function avgTime(arr: string[]): string {
  if (!arr.length) return '—';
  const secs = arr.map(t => {
    const [h, m, s] = t.split(':').map(Number);
    return h * 3600 + m * 60 + (s || 0);
  });
  const avg = Math.round(secs.reduce((a, b) => a + b, 0) / secs.length);
  const h = String(Math.floor(avg / 3600)).padStart(2, '0');
  const m = String(Math.floor((avg % 3600) / 60)).padStart(2, '0');
  return `${h}:${m}`;
}

export function computeStats(userId: string, ym: string) {
  const recs = getUserRecords(userId, ym);
  const entries = Object.values(recs);
  const total = entries.length;
  const both = entries.filter(r => r.in && r.out).length;
  const inOnly = entries.filter(r => r.in && !r.out).length;
  const avgIn = avgTime(entries.map(r => r.in).filter((x): x is string => Boolean(x)));
  const avgOut = avgTime(entries.map(r => r.out).filter((x): x is string => Boolean(x)));
  return { total, both, inOnly, avgIn, avgOut };
}

export function fmtDuration(inT: string | null, outT: string | null): string {
  if (!inT || !outT) return '—';
  const [ih, im, is] = inT.split(':').map(Number);
  const [oh, om, os] = outT.split(':').map(Number);
  const diff = (oh * 3600 + om * 60 + (os || 0)) - (ih * 3600 + im * 60 + (is || 0));
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  return `${h}h${String(m).padStart(2, '0')}m`;
}

export function buildMonthGrid(ym: string): Array<Date | null> {
  const [y, m] = ym.split('-').map(Number);
  const first = new Date(y, m - 1, 1);
  const startWeekday = (first.getDay() + 6) % 7; // Mon=0
  const last = new Date(y, m, 0);
  const cells: Array<Date | null> = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= last.getDate(); d++) cells.push(new Date(y, m - 1, d));
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

export function dateStr(d: Date | null): string {
  if (!d) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
