// 墨水屏 store — 持有 EpdBleClient 单例与连接状态/日志/设备配置/扫描状态。
// 放在 store 而非组件里，使切换页面后蓝牙连接与日志不丢失。
// 蓝牙选择改为页面自定义 modal：主进程拦截 select-bluetooth-device 后经 AAS_EPD IPC
// 把扫到的设备实时推到这里（scanDevices），用户在 modal 内回选 → epdClient 继续连接。
import { create } from 'zustand';
import { EpdBleClient } from '../lib/epaper/ble';
import { api } from '../lib/api';
import { lunarText } from '../lib/epaper/lunar';
import { renderStation, loadClawdImage, type StationData, type StationMemoItem } from '../lib/epaper/station';
import { sendCanvasToEpd, epdSendBusy } from '../lib/epaper/sendImage';
import { epdDrivers, canvasSizes } from '../lib/epaper/protocol';
import { appAlert, appConfirm } from '../lib/dialog';

export interface EpdLogLine {
  id: number;
  time: string;   // HH:MM:SS
  action: string; // '⇑' / '⇓' / ''
  text: string;
}

export interface EpdScanDevice {
  deviceId: string;
  deviceName: string; // 空串 = 无名设备（modal 不展示，仅计入「已隐藏」）
}

const MAX_LOG_LINES = 20;
let logId = 0;

// ===== 持久化 =====
// 打包应用以 file:// 加载，localStorage 跨重启不可靠（这正是「重启后丢失上次连接/备忘录」的根因）。
// 所有需要记忆的数据双写：localStorage（同步初值/纯浏览器回退）+ 主进程 gui-settings.json（权威，
// 经 AAS_SETTINGS IPC），启动时 hydrateFromFile() 用文件值回灌 store。
function persist(key: string, value: unknown) {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(key, JSON.stringify(value));
  } catch { /* 忽略写入失败 */ }
  if (typeof window !== 'undefined') window.AAS_SETTINGS?.set(key, value);
}

/** 上次成功连接的设备（一键重连按 id 优先匹配，名称作回退） */
export interface EpdLastDevice {
  id: string;   // 主进程 select-bluetooth-device 回传的 deviceId（蓝牙地址，跨重启稳定）
  name: string;
}

// 连接历史：last = 上次连接的设备名，paired = 曾成功连接过的设备名集合，lastDevice = 一键重连目标
const DEV_KEY = 'aas.epd.devices';
interface DevHistory { last: string | null; paired: string[]; lastDevice: EpdLastDevice | null }
function parseDevHistory(o: Record<string, unknown> | null | undefined): DevHistory | null {
  if (!o || typeof o !== 'object') return null;
  const ld = o.lastDevice as EpdLastDevice | null | undefined;
  return {
    last: typeof o.last === 'string' ? o.last : null,
    paired: Array.isArray(o.paired) ? (o.paired as string[]) : [],
    lastDevice: ld && typeof ld === 'object' && typeof ld.id === 'string' && ld.id
      ? { id: ld.id, name: typeof ld.name === 'string' ? ld.name : '' }
      : null,
  };
}
function loadDevHistory(): DevHistory {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(DEV_KEY) : null;
    if (raw) {
      const parsed = parseDevHistory(JSON.parse(raw));
      if (parsed) return parsed;
    }
  } catch { /* 忽略损坏的本地数据 */ }
  return { last: null, paired: [], lastDevice: null };
}
function saveDevHistory(last: string | null, paired: string[], lastDevice: EpdLastDevice | null) {
  persist(DEV_KEY, { last, paired, lastDevice });
}

// 倒置渲染（屏幕倒挂安装）：发送/推送时旋转 180°
const INVERT_KEY = 'aas.epd.invert';
function loadInvert(): boolean {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(INVERT_KEY) : null;
    if (raw) return JSON.parse(raw) === true;
  } catch { /* 忽略损坏的本地数据 */ }
  return false;
}

// 信息站备忘录与推送设置（localStorage 持久化）
const MEMO_KEY = 'aas.epd.memos';
const STATION_KEY = 'aas.epd.station';

/** 已归档备忘录（完成超 3 天自动移入，不再上屏/占列表位） */
export interface ArchivedMemo extends StationMemoItem {
  archivedAt: number; // epoch ms
}

const MEMO_ARCHIVE_MS = 3 * 86400000; // 划掉超过 3 天自动归档

/** 稳定分区排序：未完成在上，已完成沉底（两组各保持原相对顺序）。
 *  仅在展示/上屏时派生使用 —— 底层 memos 数组始终保持添加顺序不重排，
 *  因此取消勾选后条目精确回到勾选前的位置。 */
export function sortMemos(items: StationMemoItem[]): StationMemoItem[] {
  return [...items.filter(m => !m.done), ...items.filter(m => m.done)];
}

// 逐条校验+规范化持久化的备忘录：localStorage / gui-settings.json 可能被外部改坏或写入
// 非法元素（缺 text 的对象、字符串、null 等），不过滤会让 sortMemos / drawMemo(wrapText)
// / Epaper.tsx 渲染因 undefined 崩溃。这里丢弃非对象/text 为空的项，并把字段强制成
// 合法类型（id→number、text→非空 string、done→boolean、doneAt 仅保留有限数）。
function normalizeMemoBase(m: unknown): { id: number; text: string; done: boolean; doneAt?: number } | null {
  if (!m || typeof m !== 'object') return null;
  const o = m as Record<string, unknown>;
  if (typeof o.text !== 'string' || !o.text.trim()) return null; // text 必须为非空字符串
  const item: { id: number; text: string; done: boolean; doneAt?: number } = {
    id: typeof o.id === 'number' && Number.isFinite(o.id) ? o.id : 0, // id 先占位，下方统一重排去重
    text: o.text,
    done: o.done === true,
  };
  if (typeof o.doneAt === 'number' && Number.isFinite(o.doneAt)) item.doneAt = o.doneAt;
  return item;
}

/** 规范化备忘录主列表：过滤非法项并重算 id（递增去重，防止外部改动产生重复 id 影响
 *  React key 命中与 toggleMemo），返回规范化后的 items 与下一个可用 nextId。 */
function normalizeMemos(rawItems: unknown, rawNextId: unknown): { items: StationMemoItem[]; nextId: number } {
  const arr = Array.isArray(rawItems) ? rawItems : [];
  const items: StationMemoItem[] = [];
  let nextId = typeof rawNextId === 'number' && Number.isFinite(rawNextId) ? Math.floor(rawNextId) : 1;
  for (const raw of arr) {
    const base = normalizeMemoBase(raw);
    if (!base) continue;
    // 重新分配自增 id，确保唯一：以历史 nextId 与已有 id 取最大递增
    const id = nextId++;
    items.push({ id, text: base.text, done: base.done, ...(base.doneAt != null ? { doneAt: base.doneAt } : {}) });
  }
  return { items, nextId };
}

/** 规范化归档列表：复用 normalizeMemoBase，并保留/补齐 archivedAt（缺失或非法时补当前时刻）。
 *  归档项 id 同样重排去重，避免与主列表 / 彼此冲突。 */
function normalizeArchive(rawArchive: unknown, startId: number): { archive: ArchivedMemo[]; nextId: number } {
  const arr = Array.isArray(rawArchive) ? rawArchive : [];
  const archive: ArchivedMemo[] = [];
  let nextId = startId;
  for (const raw of arr) {
    const base = normalizeMemoBase(raw);
    if (!base) continue;
    const o = raw as Record<string, unknown>;
    const archivedAt = typeof o.archivedAt === 'number' && Number.isFinite(o.archivedAt) ? o.archivedAt : Date.now();
    const id = nextId++;
    archive.push({ id, text: base.text, done: base.done, archivedAt, ...(base.doneAt != null ? { doneAt: base.doneAt } : {}) });
  }
  return { archive, nextId };
}

function loadMemos(): { items: StationMemoItem[]; nextId: number; archive: ArchivedMemo[] } {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(MEMO_KEY) : null;
    if (raw) {
      const o = JSON.parse(raw);
      if (o && typeof o === 'object' && Array.isArray(o.items)) {
        const m = normalizeMemos(o.items, o.nextId);
        const a = normalizeArchive(o.archive, m.nextId);
        return { items: m.items, nextId: a.nextId, archive: a.archive };
      }
    }
  } catch { /* 忽略损坏的本地数据 */ }
  return { items: [], nextId: 1, archive: [] };
}
function saveMemos(items: StationMemoItem[], nextId: number, archive: ArchivedMemo[]) {
  persist(MEMO_KEY, { items, nextId, archive });
}

/** 请假设置（驱动信息站「请假中」全屏状态） */
export interface StationLeaveCfg {
  enabled: boolean;
  label: string;  // 请假类型（年假/事假…）
  start: string;  // ISO 日期（YYYY-MM-DD）
  end: string;    // ISO 日期
}

const DEFAULT_LEAVE: StationLeaveCfg = { enabled: false, label: '年假', start: '', end: '' };

function loadStationCfg(): { autoMin: number; lastPush: number | null; leave: StationLeaveCfg } {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(STATION_KEY) : null;
    if (raw) {
      const o = JSON.parse(raw);
      return {
        autoMin: typeof o.autoMin === 'number' ? o.autoMin : 0,
        lastPush: typeof o.lastPush === 'number' ? o.lastPush : null,
        leave: o.leave && typeof o.leave === 'object' ? { ...DEFAULT_LEAVE, ...o.leave } : { ...DEFAULT_LEAVE },
      };
    }
  } catch { /* 忽略损坏的本地数据 */ }
  return { autoMin: 0, lastPush: null, leave: { ...DEFAULT_LEAVE } };
}
function saveStationCfg(autoMin: number, lastPush: number | null, leave: StationLeaveCfg) {
  persist(STATION_KEY, { autoMin, lastPush, leave });
}

interface EpaperState {
  logs: EpdLogLine[];
  connected: boolean;
  canReconnect: boolean;
  deviceName: string | null;
  firmware: number | null;   // 已连接时的固件版本号（如 0x16）
  pins: string;     // 设备引脚配置（hex，设备连接后回传）
  driver: string;   // 驱动 ID（hex，设备连接后回传）
  mtu: number;
  debug: boolean;   // 开发模式（替代原网页 ?debug=true）

  // 蓝牙扫描（自定义 modal）
  scanning: boolean;            // modal 扫描中
  scanDevices: EpdScanDevice[]; // 主进程实时推送的设备流
  connectingId: string | null;  // 正在连接的设备（显示加载圈）

  // 连接历史（驱动「上次连接 / 已配对」标记 + 一键重连）
  lastConnectedName: string | null;
  pairedNames: string[];
  lastDevice: EpdLastDevice | null; // 上次成功连接的设备（跨重启记忆）
  quickConnecting: boolean;         // 一键重连进行中（后台扫描，发现目标即自动连接）

  // 倒置渲染（发送/推送时旋转 180°，跨重启记忆）
  invertRender: boolean;

  // 信息站（备忘录 + 定时推送 + 请假设置）
  memos: StationMemoItem[];
  memoArchive: ArchivedMemo[];   // 已归档（完成超 3 天自动移入）
  stationAutoMin: number;        // 自动推送间隔（分钟，0 = 关闭）
  stationPushing: boolean;       // 信息站推送进行中
  stationLastPush: number | null; // 上次成功推送（epoch ms）
  stationLeave: StationLeaveCfg; // 请假设置（区间内渲染「请假中」全屏）

  addLog: (text: string, action?: string) => void;
  clearLog: () => void;
  setPins: (v: string) => void;
  setDriver: (v: string) => void;
  setMtu: (v: number) => void;
  toggleDebug: () => void;

  addMemo: (text: string) => void;
  toggleMemo: (id: number) => void;
  updateMemo: (id: number, text: string) => void;
  removeMemo: (id: number) => void;
  archiveMemo: (id: number) => void;        // 手动归档：把主列表项移入归档箱
  restoreMemo: (id: number) => void;        // 归档项恢复为未完成，回到主列表
  removeArchivedMemo: (id: number) => void; // 彻底删除单条归档
  clearMemoArchive: () => void;             // 清空归档
  setStationAutoMin: (min: number) => void;
  setStationLeave: (patch: Partial<StationLeaveCfg>) => void;
  pushStation: (reason?: 'manual' | 'auto') => Promise<boolean>; // 离屏渲染并发送到屏幕

  openScan: () => void;                    // 打开 modal 并开始扫描
  closeScan: () => void;                   // 取消扫描 / 关闭 modal
  selectScanDevice: (deviceId: string) => void; // 回选某设备开始连接
  quickReconnect: () => void;              // 一键重连上次设备（无需打开扫描 modal）
  cancelQuickReconnect: () => void;        // 取消一键重连
  setInvertRender: (v: boolean) => void;   // 倒置渲染开关
  reconnect: () => Promise<void>;
  disconnect: () => void;
}

const initHistory = loadDevHistory();
const initMemos = loadMemos();
const initStation = loadStationCfg();
let memoNextId = initMemos.nextId;

// 本次「回选 → 连接」流程中选中的 deviceId（modal 点选或一键重连自动回选），
// 连接成功时与设备名一起存为 lastDevice 供下次一键重连。
let pendingSelectId: string | null = null;
// 定时推送发起的自动重连：连接成功后补推一次（蓝牙会自动断开，到点先重连再推送）
let autoPushAfterConnect = false;
// 等待设备首条配置回传后再补推：连上后置 true，onConfigReceived（INIT 后首条通知，
// 携带正确 driver→画布尺寸/颜色模式）到达时再触发 pushStation('auto')，避免固定盲等导致
// driver/MTU 未更新就用错误画布渲染。兜底定时器仅在配置迟迟不来时收尾（见下）。
let pendingAutoPushAfterConfig = false;
let autoPushFallbackTimer: number | null = null;
function clearAutoPushFallback() {
  if (autoPushFallbackTimer != null) {
    window.clearTimeout(autoPushFallbackTimer);
    autoPushFallbackTimer = null;
  }
}
// 配置就绪即补推：复核自动推送仍开启、设备在线、无并发发送后再推（重连窗口内用户可能已关闭）
function triggerAutoPushAfterConfig() {
  if (!pendingAutoPushAfterConfig) return;
  pendingAutoPushAfterConfig = false;
  clearAutoPushFallback();
  const s = useEpaperStore.getState();
  if (s.stationAutoMin > 0 && s.connected && !s.stationPushing && !epdSendBusy()) {
    void s.pushStation('auto');
  }
}
// 一键重连超时定时器（目标设备一直未被扫到时收尾）
let quickTimer: number | null = null;
function clearQuickTimer() {
  if (quickTimer != null) {
    window.clearTimeout(quickTimer);
    quickTimer = null;
  }
}

export const useEpaperStore = create<EpaperState>((set, get) => ({
  logs: [],
  connected: false,
  canReconnect: false,
  deviceName: null,
  firmware: null,
  pins: '',
  driver: '01',
  mtu: 20,
  debug: false,

  scanning: false,
  scanDevices: [],
  connectingId: null,

  lastConnectedName: initHistory.last,
  pairedNames: initHistory.paired,
  lastDevice: initHistory.lastDevice,
  quickConnecting: false,

  invertRender: loadInvert(),

  memos: initMemos.items,
  memoArchive: initMemos.archive,
  stationAutoMin: initStation.autoMin,
  stationPushing: false,
  stationLastPush: initStation.lastPush,
  stationLeave: initStation.leave,

  addLog(text, action = '') {
    const now = new Date();
    const time = String(now.getHours()).padStart(2, '0') + ':' +
      String(now.getMinutes()).padStart(2, '0') + ':' +
      String(now.getSeconds()).padStart(2, '0');
    const next = [...get().logs, { id: ++logId, time, action, text }];
    if (next.length > MAX_LOG_LINES) next.splice(0, next.length - MAX_LOG_LINES);
    set({ logs: next });
    // 持久化：内存仅留最近 MAX_LOG_LINES 行供 UI 展示，完整历史经 IPC 落到主进程 logs/epaper.log
    // （带日期前缀以便跨天翻查；主进程防抖合并写盘，发送图片时的高频 hex 不会拖慢刷屏）
    if (typeof window !== 'undefined') {
      const date = now.getFullYear() + '-' +
        String(now.getMonth() + 1).padStart(2, '0') + '-' +
        String(now.getDate()).padStart(2, '0');
      window.AAS_EPD?.appendLog?.(`${date} ${time}${action ? ' ' + action : ''} ${text}`);
    }
  },

  clearLog() {
    set({ logs: [] });
  },

  setPins(v) { set({ pins: v }); },
  setDriver(v) { set({ driver: v }); },
  setMtu(v) { set({ mtu: v }); },

  toggleDebug() {
    const debug = !get().debug;
    set({ debug });
    if (debug) get().addLog('注意：开发模式功能已开启！不懂请不要随意修改，否则后果自负！');
  },

  // ===== 信息站：备忘录 =====

  addMemo(text) {
    const t = text.trim();
    if (!t) return;
    const memos = [...get().memos, { id: memoNextId++, text: t, done: false }];
    set({ memos });
    saveMemos(memos, memoNextId, get().memoArchive);
  },

  toggleMemo(id) {
    // 划掉记录 doneAt（驱动 3 天自动归档）；沉底是展示层 sortMemos 派生的，
    // 底层顺序不动 —— 取消划掉自然回到勾选前的位置
    const memos = get().memos.map(m => {
      if (m.id !== id) return m;
      return m.done ? { ...m, done: false, doneAt: undefined } : { ...m, done: true, doneAt: Date.now() };
    });
    set({ memos });
    saveMemos(memos, memoNextId, get().memoArchive);
  },

  updateMemo(id, text) {
    const t = text.trim();
    if (!t) return; // 改空视为放弃，保留原文
    const memos = get().memos.map(m => (m.id === id ? { ...m, text: t } : m));
    set({ memos });
    saveMemos(memos, memoNextId, get().memoArchive);
  },

  removeMemo(id) {
    const memos = get().memos.filter(m => m.id !== id);
    set({ memos });
    saveMemos(memos, memoNextId, get().memoArchive);
  },

  archiveMemo(id) {
    // 手动归档：把主列表里的某条事项立即移入归档箱（与「完成超 3 天自动归档」殊途同归）。
    // 未完成项也允许手动归档；归档箱保留其 done 状态用于展示，恢复时统一回到未完成。
    const item = get().memos.find(m => m.id === id);
    if (!item) return;
    const memos = get().memos.filter(m => m.id !== id);
    const memoArchive = [...get().memoArchive, { ...item, archivedAt: Date.now() }];
    set({ memos, memoArchive });
    saveMemos(memos, memoNextId, memoArchive);
  },

  restoreMemo(id) {
    const item = get().memoArchive.find(m => m.id === id);
    if (!item) return;
    const memoArchive = get().memoArchive.filter(m => m.id !== id);
    const memos = [...get().memos, { id: item.id, text: item.text, done: false }];
    set({ memos, memoArchive });
    saveMemos(memos, memoNextId, memoArchive);
  },

  removeArchivedMemo(id) {
    const memoArchive = get().memoArchive.filter(m => m.id !== id);
    set({ memoArchive });
    saveMemos(get().memos, memoNextId, memoArchive);
  },

  clearMemoArchive() {
    set({ memoArchive: [] });
    saveMemos(get().memos, memoNextId, []);
  },

  // ===== 信息站：推送 =====

  setStationAutoMin(min) {
    set({ stationAutoMin: min });
    saveStationCfg(min, get().stationLastPush, get().stationLeave);
    if (min > 0) get().addLog(`信息站自动推送已开启：每 ${min} 分钟（断开时自动重连后推送）`);
    else get().addLog('信息站自动推送已关闭');
  },

  setStationLeave(patch) {
    const leave = { ...get().stationLeave, ...patch };
    set({ stationLeave: leave });
    saveStationCfg(get().stationAutoMin, get().stationLastPush, leave);
  },

  async pushStation(reason = 'manual') {
    const st = get();
    if (!st.connected) {
      st.addLog(reason === 'auto' ? '自动推送跳过：设备未连接' : '推送失败：请先连接设备');
      return false;
    }
    if (st.stationPushing || epdSendBusy()) {
      if (reason === 'manual') st.addLog('已有发送任务进行中，请等待屏幕刷新完成');
      return false;
    }

    set({ stationPushing: true });
    try {
      st.addLog(reason === 'auto' ? '定时推送信息站…' : '推送信息站…');
      const data = await buildStationData();

      // 画布尺寸/颜色模式跟随设备驱动（设备连接时已回传）
      const drv = epdDrivers.find(d => d.value === get().driver);
      const size = canvasSizes.find(c => c.name === drv?.size) ?? { width: 400, height: 300 };
      const ditherMode = drv?.color ?? 'blackWhiteColor';

      const canvas = document.createElement('canvas');
      canvas.width = size.width;
      canvas.height = size.height;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('无法创建离屏画布');
      renderStation(ctx, canvas.width, canvas.height, data);

      const seconds = await sendCanvasToEpd(epdClient, canvas, ctx, {
        driver: get().driver,
        ditherMode,
        mtu: get().mtu,
        interleaved: 50,
        rotate180: get().invertRender,
        onStatus: () => { /* 进度走日志末行即可，避免刷屏 */ },
      });

      const now = Date.now();
      set({ stationLastPush: now });
      saveStationCfg(get().stationAutoMin, now, get().stationLeave);
      get().addLog(`信息站推送完成！耗时: ${seconds}s`);
      get().addLog('屏幕刷新完成前请不要操作。');
      return true;
    } catch (e) {
      get().addLog(`信息站推送失败: ${(e as Error).message ?? e}`);
      return false;
    } finally {
      set({ stationPushing: false });
    }
  },

  openScan() {
    if (get().scanning || get().quickConnecting) return;
    set({ scanning: true, scanDevices: [], connectingId: null });
    // requestDevice 会触发主进程 select-bluetooth-device，设备经 IPC 流回 scanDevices
    void epdClient.preConnect();
  },

  closeScan() {
    // 通知主进程取消本次设备请求（空串=取消），requestDevice 随之 reject
    window.AAS_EPD?.select('');
    set({ scanning: false, scanDevices: [], connectingId: null });
  },

  selectScanDevice(deviceId) {
    if (get().connectingId) return;
    pendingSelectId = deviceId;
    set({ connectingId: deviceId });
    window.AAS_EPD?.select(deviceId);
  },

  // 一键重连：后台发起扫描（不开 modal），设备流中发现上次设备（按 id，名称回退）即自动回选连接
  quickReconnect() {
    const ld = get().lastDevice;
    if (!ld || get().connected || get().scanning || get().quickConnecting) return;
    set({ quickConnecting: true });
    get().addLog(`一键重连：正在搜索「${ld.name || ld.id}」…`);
    clearQuickTimer();
    quickTimer = window.setTimeout(() => {
      quickTimer = null;
      if (!useEpaperStore.getState().quickConnecting) return;
      autoPushAfterConnect = false; // 超时未扫到设备，放弃本次补推
      window.AAS_EPD?.select('');
      useEpaperStore.setState({ quickConnecting: false });
      useEpaperStore.getState().addLog('一键重连超时（60 秒未发现设备）：墨水屏可能已休眠停止蓝牙广播，请在设备上按键或重新上电唤醒后再试，或用「连接设备」重新搜索');
    }, 60_000);
    void epdClient.preConnect();
  },

  cancelQuickReconnect() {
    if (!get().quickConnecting) return;
    clearQuickTimer();
    autoPushAfterConnect = false; // 用户主动取消，连带放弃本次补推
    window.AAS_EPD?.select('');
    set({ quickConnecting: false });
    get().addLog('已取消一键重连');
  },

  setInvertRender(v) {
    set({ invertRender: v });
    persist(INVERT_KEY, v);
    get().addLog(v ? '倒置渲染已开启：发送/推送时旋转 180°' : '倒置渲染已关闭');
  },

  async reconnect() {
    await epdClient.reConnect();
  },

  disconnect() {
    epdClient.disconnect();
  },
}));

// 模块级单例：事件直接写回 store
export const epdClient = new EpdBleClient({
  onLog(text, action) {
    useEpaperStore.getState().addLog(text, action);
  },
  onConnectionChange({ connected, canReconnect, deviceName, firmware }) {
    if (connected) {
      // 连接成功：关闭扫描 modal / 一键重连态，并把设备计入连接历史（含 deviceId，供一键重连）
      clearQuickTimer();
      const st = useEpaperStore.getState();
      let paired = st.pairedNames;
      let last = st.lastConnectedName;
      let lastDevice = st.lastDevice;
      if (deviceName) {
        last = deviceName;
        if (!paired.includes(deviceName)) paired = [...paired, deviceName];
      }
      if (pendingSelectId) {
        lastDevice = { id: pendingSelectId, name: deviceName || '' };
      }
      pendingSelectId = null;
      saveDevHistory(last, paired, lastDevice);
      useEpaperStore.setState({
        connected, canReconnect, deviceName, firmware,
        scanning: false, connectingId: null, scanDevices: [], quickConnecting: false,
        lastConnectedName: last, pairedNames: paired, lastDevice,
      });
      // 定时推送发起的重连：连上后等设备回传配置（INIT 后首条通知，含正确 driver）再补推 ——
      // 事件驱动（见 onConfigReceived → triggerAutoPushAfterConfig），而非固定盲等，
      // 避免慢设备/弱信号下 driver/MTU 尚未更新就用错误画布尺寸/颜色模式渲染发送。
      if (autoPushAfterConnect) {
        autoPushAfterConnect = false;
        pendingAutoPushAfterConfig = true;
        // 兜底：极个别固件可能迟迟不回配置；8s 后仍未触发则用当前 store 值（已校验的 driver/MTU）补推一次
        clearAutoPushFallback();
        autoPushFallbackTimer = window.setTimeout(() => {
          autoPushFallbackTimer = null;
          triggerAutoPushAfterConfig();
        }, 8000);
      }
    } else {
      // 断开 / 连接失败：复位连接态并关闭扫描 modal / 一键重连态（此时 requestDevice 已结束，
      // 列表不再更新，关闭后用户可重新点击「连接设备」发起新扫描）。
      clearQuickTimer();
      pendingSelectId = null;
      autoPushAfterConnect = false; // 重连失败则放弃本次补推，等下一轮定时
      pendingAutoPushAfterConfig = false; // 断开则取消「待配置补推」与兜底定时器
      clearAutoPushFallback();

      useEpaperStore.setState({
        connected, canReconnect, deviceName, firmware,
        scanning: false, connectingId: null, scanDevices: [], quickConnecting: false,
      });
    }
  },
  onConfigReceived(pins, driver) {
    useEpaperStore.setState({ pins, driver });
    // 配置（driver）已就绪：若有定时推送在等待，事件驱动触发补推（替代旧的固定 3500ms 盲等）
    triggerAutoPushAfterConfig();
  },
  onMtuUpdate(mtu) {
    useEpaperStore.setState({ mtu });
  },
  onLowFirmware(_version, oldUrl) {
    void (async () => {
      await appAlert('当前固件版本过低，可能无法正常使用部分功能，建议升级到最新版本。', { title: '固件版本过低' });
      if (await appConfirm('是否访问旧版本上位机？', { title: '固件版本过低' })) {
        // Electron 中经 setWindowOpenHandler 转交系统浏览器打开
        window.open(oldUrl);
      }
    })();
  },
});

// 订阅主进程推送的蓝牙设备流（仅 Electron 下可用）
if (typeof window !== 'undefined' && window.AAS_EPD) {
  window.AAS_EPD.onDevices(devices => {
    const st = useEpaperStore.getState();
    // 一键重连：发现目标设备（优先按 deviceId，名称回退）即自动回选，无需用户操作
    if (st.quickConnecting) {
      const ld = st.lastDevice;
      const hit = ld
        ? devices.find(d => d.deviceId === ld.id)
          ?? (ld.name ? devices.find(d => d.deviceName === ld.name) : undefined)
        : undefined;
      if (hit && pendingSelectId == null) {
        // 发现目标即「立即回选连接」：该设备无开关键、持续广播，扫到就连最稳；
        // 再等只会让连接窗口/适配器状态白白错过（原 20s「搜索宽限」已废弃）。
        clearQuickTimer();
        pendingSelectId = hit.deviceId;
        st.addLog(`已发现「${hit.deviceName || hit.deviceId}」，正在连接…`);
        window.AAS_EPD?.select(hit.deviceId);
      }
      return;
    }
    // 仅在扫描中接收，避免连接结束后的残留事件覆盖状态
    if (st.scanning) {
      useEpaperStore.setState({ scanDevices: devices });
    }
  });

  // 蓝牙配对确认：主进程不再弹系统框，这里用应用内对话框确认后回传
  window.AAS_EPD.onPairing?.(req => {
    void (async () => {
      const message = req.kind === 'confirmPin'
        ? `确认 ${req.deviceId} 的配对码：${req.pin}`
        : `允许连接 ${req.deviceId}？`;
      const ok = await appConfirm(message, { title: '蓝牙配对', confirmText: req.kind === 'confirmPin' ? '确认' : '允许' });
      window.AAS_EPD?.pairingResponse(ok);
    })();
  });

  // 窗口隐藏（缩托盘）时主动复位扫描 / 一键重连态（修复 E18 渲染层一致性）：
  // 注意：曾在此监听 visibilitychange，在窗口转入 hidden（最小化/收托盘/被其它窗口完全遮挡）时
  // closeScan()/cancelQuickReconnect()。但这会让「一键重连」一最小化/失焦就被打断，违背
  // 「只有用户点『取消重连』才停」的预期，故移除。配套地，主进程 close 缩托盘时也不再
  // resolvePendingBleRequests（仅真正退出/窗口销毁/重载才释放，见 main.cjs），因此隐藏期间
  // native 扫描与渲染层 scanning/quickConnecting 都保持运行、两端依然一致；又因
  // backgroundThrottling:false，隐藏后定时器不被节流，后台重连可全速进行。
}

// ===== 启动回灌：主进程 gui-settings.json → store =====
// localStorage 在打包应用下跨重启不可靠，文件值为权威：文件里有的键覆盖 store；
// 文件里没有的键（首次升级）保留 localStorage 初值并回写文件完成迁移。
async function hydrateFromFile() {
  if (typeof window === 'undefined' || !window.AAS_SETTINGS) return;
  let all: Record<string, unknown>;
  try {
    all = await window.AAS_SETTINGS.getAll();
  } catch {
    return;
  }
  const patch: Partial<EpaperState> = {};

  const dev = parseDevHistory(all[DEV_KEY] as Record<string, unknown> | undefined);
  if (dev) {
    patch.lastConnectedName = dev.last;
    patch.pairedNames = dev.paired;
    patch.lastDevice = dev.lastDevice;
  }

  const memosO = all[MEMO_KEY] as { items?: unknown; nextId?: unknown; archive?: unknown } | undefined;
  if (memosO && typeof memosO === 'object' && Array.isArray(memosO.items)) {
    // 与 loadMemos 同口径：逐条校验/规范化并重算 nextId，防止文件被外部改坏后渲染崩溃或 id 冲突
    const m = normalizeMemos(memosO.items, memosO.nextId);
    const a = normalizeArchive(memosO.archive, m.nextId);
    patch.memos = m.items;
    patch.memoArchive = a.archive;
    memoNextId = a.nextId;
  }

  const stationO = all[STATION_KEY] as { autoMin?: number; lastPush?: number; leave?: StationLeaveCfg } | undefined;
  if (stationO && typeof stationO === 'object') {
    patch.stationAutoMin = typeof stationO.autoMin === 'number' ? stationO.autoMin : 0;
    patch.stationLastPush = typeof stationO.lastPush === 'number' ? stationO.lastPush : null;
    patch.stationLeave = stationO.leave && typeof stationO.leave === 'object'
      ? { ...DEFAULT_LEAVE, ...stationO.leave }
      : { ...DEFAULT_LEAVE };
  }

  if (typeof all[INVERT_KEY] === 'boolean') patch.invertRender = all[INVERT_KEY] as boolean;

  if (Object.keys(patch).length) useEpaperStore.setState(patch);

  // 回写全部键：补齐文件缺失键（迁移 localStorage 旧数据），并同步 localStorage 与文件
  const st = useEpaperStore.getState();
  saveDevHistory(st.lastConnectedName, st.pairedNames, st.lastDevice);
  saveMemos(st.memos, memoNextId, st.memoArchive);
  saveStationCfg(st.stationAutoMin, st.stationLastPush, st.stationLeave);
  persist(INVERT_KEY, st.invertRender);

  archiveExpiredMemos(); // 回灌完成后立刻清一遍过期完成项
}
void hydrateFromFile();

// ===== 备忘录自动归档 =====
// 划掉超过 3 天的项移入归档区（不再上屏/占列表位）；旧数据里已划掉但没有
// doneAt 的项先补记当前时刻（从现在起算 3 天），避免升级后被立即归档。
function archiveExpiredMemos() {
  const st = useEpaperStore.getState();
  const now = Date.now();
  let changed = false;
  const keep: StationMemoItem[] = [];
  const archive = [...st.memoArchive];
  for (const m of st.memos) {
    if (m.done && !m.doneAt) {
      keep.push({ ...m, doneAt: now });
      changed = true;
    } else if (m.done && m.doneAt && now - m.doneAt > MEMO_ARCHIVE_MS) {
      archive.push({ ...m, archivedAt: now });
      changed = true;
    } else {
      keep.push(m);
    }
  }
  if (changed) {
    useEpaperStore.setState({ memos: keep, memoArchive: archive });
    saveMemos(keep, memoNextId, archive);
  }
}
archiveExpiredMemos();

// ===== 信息站数据组装（渲染预览与推送共用）=====

export async function buildStationData(): Promise<StationData> {
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  const todayIso = `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;

  // 请假设置：今天在区间内才生效（驱动「请假中」全屏状态）
  const lv = useEpaperStore.getState().stationLeave;
  const leaveActive = lv.enabled && !!lv.start && !!lv.end && lv.start <= todayIso && todayIso <= lv.end;

  // 额度与日历并行拉取；任一失败用 null（渲染器画占位，不阻塞）。
  // 请假生效时把结束日传给后端，拿「销假上班」的首个工作日。
  const [usageR, calR] = await Promise.allSettled([
    api.getClaudeUsage(),
    api.getCalendarInfo(leaveActive ? lv.end : undefined),
  ]);
  const clawd = await loadClawdImage();
  const calendar = calR.status === 'fulfilled' ? calR.value : null;
  return {
    now,
    lunar: lunarText(now),
    usage: usageR.status === 'fulfilled' ? usageR.value : null,
    calendar,
    memos: sortMemos(useEpaperStore.getState().memos), // 上屏同样未完成在上、已完成沉底

    clawd,
    leave: leaveActive ? { label: lv.label || '请假', start: lv.start, end: lv.end } : null,
    leaveWorkdayAfter: calendar?.workday_after ?? null,
  };
}

// ===== 信息站自动推送 ticker =====
// 模块级定时器：切页不中断。墨水屏全刷耗时长（约 15-25s）且影响寿命，
// 间隔下限 30 分钟（UI 选项控制）；仅设备已连接、无发送任务时执行。
// 推送失败时也按 lastAttempt 节流，避免每分钟反复重试打满日志。
//
// 方案2：无用户手势场景(定时推送 / 启动后主动重连)的"注入手势→手势内自动重连"。Web Bluetooth 的
// requestDevice 必须在 user activation 上下文中调用，而定时器/启动钩子都没有手势。主进程经 IPC 用
// sendInputEvent 注入一次可信 F24 键(isTrusted=true)，下面的 keydown 监听便在该手势上下文里发起一键
// 重连，无需用户手动点击。仅在 armed 的短窗口内响应、且任意键即可(不赌 Electron keyCode→key 映射，
// 误触仅多一次无害重连)；注入/手势在窗口缩托盘等情况下可能无效，由调用方 2s 兜底降级为"提示手动"。
let gestureReconnectArmed = false;
if (typeof window !== 'undefined') {
  window.addEventListener('keydown', () => {
    if (!gestureReconnectArmed) return;
    gestureReconnectArmed = false;
    const st = useEpaperStore.getState();
    if (!st.connected && !st.quickConnecting && !st.scanning && st.lastDevice) {
      st.addLog('已注入手势，发起自动重连…');
      st.quickReconnect();
    }
  });
}

// 尝试"注入手势→自动重连上次设备"。reason 仅作日志前缀。已连接/正在连接/无 lastDevice → 跳过；
// 无注入能力(非 Electron/旧包) → 直接提示手动；注入后 2s 未被 keydown 消费(手势无效/窗口隐藏) → 提示手动。
function attemptGestureReconnect(reason: string): void {
  if (typeof window === 'undefined') return;
  const st = useEpaperStore.getState();
  if (st.connected || st.quickConnecting || st.scanning || !st.lastDevice) return;
  const ld = st.lastDevice;
  const inject = window.AAS_EPD?.tryGestureReconnect;
  if (!inject) {
    st.addLog(`${reason}：设备未连接，请点「一键重连」连上「${ld.name || ld.id}」`);
    return;
  }
  gestureReconnectArmed = true;
  st.addLog(`${reason}：尝试自动重连「${ld.name || ld.id}」…`);
  void inject().then(ok => { if (!ok) gestureReconnectArmed = false; });
  window.setTimeout(() => {
    if (!gestureReconnectArmed) return; // 已被 keydown 消费(已发起重连)
    gestureReconnectArmed = false;
    const s = useEpaperStore.getState();
    if (!s.connected && !s.quickConnecting && !s.scanning) {
      s.addLog(`${reason}未生效（窗口可能在后台），请点「一键重连」连上「${ld.name || ld.id}」`);
    }
  }, 2000);
}

// 启动即主动重连一次：进入系统后(窗口通常在前台，最利于 sendInputEvent 注入手势生效)，若有上次设备
// 且未连接，主动触发一次"注入手势→一键重连"——实现"每次重启后主动连上次设备一次"，也便于验证方案2
// 的模拟手势在重启场景是否有效。延迟 5s 等窗口稳定 / 后端就绪 / preload IPC 可用。
if (typeof window !== 'undefined') {
  window.setTimeout(() => attemptGestureReconnect('启动自动重连'), 5000);
}
let stationLastAttempt = 0;
if (typeof window !== 'undefined') {
  window.setInterval(() => {
    archiveExpiredMemos(); // 长开应用也按时归档过期完成项（与自动推送开关无关）
    const st = useEpaperStore.getState();
    if (st.stationAutoMin <= 0) return;
    if (st.stationPushing || epdSendBusy()) return;
    const interval = st.stationAutoMin * 60_000;
    const base = Math.max(st.stationLastPush ?? 0, stationLastAttempt);
    if (Date.now() - base < interval) return;
    if (st.connected) {
      stationLastAttempt = Date.now();
      void st.pushStation('auto');
      return;
    }
    // 蓝牙会自动断开：到点未连接时先重连，连接成功后补推（见 onConnectionChange）。
    // 本次会话断联（设备对象还在内存）→ 直接 GATT 重连，最快；
    // 重启后（无内存设备）→ 走一键重连（按记忆的 lastDevice 后台扫描自动回选）。
    if (st.quickConnecting || st.scanning) return; // 已在连接流程中，等结果
    if (st.canReconnect) {
      stationLastAttempt = Date.now();
      autoPushAfterConnect = true;
      st.addLog('定时推送：设备已断开，正在重连…');
      void st.reconnect();
    } else if (st.lastDevice) {
      // 重启应用后内存已无设备对象，requestDevice 需用户手势而定时器没有 → 方案2：注入手势后在手势
      // 上下文里发起一键重连（详见 attemptGestureReconnect）；失败则降级提示手动。
      // 保留 autoPushAfterConnect：连上后(见 onConnectionChange)自动补推本次。
      stationLastAttempt = Date.now();
      autoPushAfterConnect = true;
      attemptGestureReconnect('定时推送');
    }
    // 无任何可重连目标：跳过本轮，等下一次到点
  }, 60_000);
}
