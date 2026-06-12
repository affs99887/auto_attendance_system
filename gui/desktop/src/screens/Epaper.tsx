// 墨水屏控制台 — EPD-nRF5 上位机的原生 React 实现（按设计稿 墨水屏控制.dc.html 重做）。
// 布局：顶部连接状态条 + 双栏工作台（左：传图工作台/画布；右：设备控制 / 运行日志 / 高级·开发模式）。
// 蓝牙连接/日志在 store/epaper.ts（切页不断连）；蓝牙选择走页面自定义 modal（主进程 IPC 推送设备流）。
// 画布、抖动与绘图工具为页面本地状态。
import * as React from 'react';
import { Icon } from '../lib/icons';
import { useEpaperStore, epdClient, buildStationData, sortMemos, type EpdScanDevice } from '../store/epaper';
import { EpdCmd, canvasSizes, canvasSizeLabels, epdDrivers, hex2bytes, parseHolidayData, buildHolidayPayload, DEFAULT_HOLIDAYS_2026, DEFAULT_HOLIDAYS_2027 } from '../lib/epaper/protocol';
import { adjustContrast, ditherImage, processImageData, decodeProcessedData, type DitherMode, type DitherAlgorithm } from '../lib/epaper/dithering';
import { renderStation, STATION_MEMO_MAX, type StationMemoItem } from '../lib/epaper/station';
import { sendCanvasToEpd, epdSendBusy } from '../lib/epaper/sendImage';
import { appAlert, appConfirm } from '../lib/dialog';
import { PaintManager, type PaintTool } from '../lib/epaper/paint';
import { CropManager } from '../lib/epaper/crop';

const DITHER_MODE_OPTIONS: Array<{ value: DitherMode; label: string }> = [
  { value: 'blackWhiteColor', label: '双色(黑白)' },
  { value: 'threeColor', label: '三色(黑白红)' },
  { value: 'fourColor', label: '四色(黑白红黄)' },
  { value: 'sixColor', label: '六色(黑白红黄蓝绿)' },
];

const DITHER_ALG_OPTIONS: Array<{ value: DitherAlgorithm; label: string }> = [
  { value: 'floydSteinberg', label: 'Floyd-Steinberg' },
  { value: 'atkinson', label: 'Atkinson' },
  { value: 'bayer', label: 'Bayer' },
  { value: 'stucki', label: 'Stucki' },
  { value: 'jarvis', label: 'Jarvis-Judice-Ninke' },
  { value: 'none', label: '无抖动' },
];

const BRUSH_COLORS = [
  { value: '#000000', label: '黑色' },
  { value: '#FF0000', label: '红色' },
  { value: '#FFFF00', label: '黄色' },
  { value: '#00FF00', label: '绿色' },
  { value: '#0000FF', label: '蓝色' },
  { value: '#FFFFFF', label: '白色' },
];

const FONT_OPTIONS = [
  { value: 'Arial', label: 'Arial' },
  { value: 'sans-serif', label: 'Sans-serif' },
  { value: 'monospace', label: 'Monospace' },
  { value: 'SimSun', label: '宋体' },
  { value: 'SimHei', label: '黑体' },
  { value: 'Microsoft Yahei', label: '微软雅黑' },
  { value: 'Microsoft JhengHei', label: '微软正黑体' },
  { value: 'KaiTi', label: '楷体' },
  { value: 'NSimSun', label: '新宋体' },
  { value: 'FangSong', label: '仿宋' },
  { value: 'YouYuan', label: '幼圆' },
  { value: 'LiSu', label: '隶书' },
  { value: 'STHeiti', label: '华文黑体' },
  { value: 'STXihei', label: '华文细黑' },
  { value: 'STKaiti', label: '华文楷体' },
  { value: 'STSong', label: '华文宋体' },
  { value: 'STFangsong', label: '华文仿宋' },
  { value: 'STZhongsong', label: '华文中宋' },
  { value: 'STHupo', label: '华文琥珀' },
  { value: 'STXinwei', label: '华文新魏' },
  { value: 'STLiti', label: '华文隶书' },
  { value: 'STXingkai', label: '华文行楷' },
  { value: 'FZShuTi', label: '方正舒体' },
  { value: 'FZYaoti', label: '方正姚体' },
  { value: 'PingFang SC', label: '苹方' },
  { value: 'Source Han Sans CN', label: '思源黑体' },
  { value: 'Source Han Serif SC', label: '思源宋体' },
  { value: 'WenQuanYi Micro Hei', label: '文泉驿微米黑' },
];

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

// Chromium/Electron 对无名或不支持的设备会回传本地化占位名
//（如「未知或不支持的设备 (AA:BB:CC:DD:EE:FF)」/「Unknown or Unsupported Device (…)」），
// 其稳定特征是名称内含完整 MAC 地址。这类按"无真实名称"处理：不展示，仅计入「已隐藏」。
const MAC_IN_NAME = /([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/;
const hasRealName = (name: string): boolean => {
  const n = name.trim();
  return n !== '' && !MAC_IN_NAME.test(n);
};

export function EpaperScreen() {
  // ===== store（蓝牙连接、扫描与设备配置，跨页面存活）=====
  const logs = useEpaperStore(s => s.logs);
  const connected = useEpaperStore(s => s.connected);
  const canReconnect = useEpaperStore(s => s.canReconnect);
  const deviceName = useEpaperStore(s => s.deviceName);
  const firmware = useEpaperStore(s => s.firmware);
  const pins = useEpaperStore(s => s.pins);
  const driver = useEpaperStore(s => s.driver);
  const mtu = useEpaperStore(s => s.mtu);
  const debug = useEpaperStore(s => s.debug);
  const addLog = useEpaperStore(s => s.addLog);
  const scanning = useEpaperStore(s => s.scanning);
  const scanDevices = useEpaperStore(s => s.scanDevices);
  const connectingId = useEpaperStore(s => s.connectingId);
  const lastConnectedName = useEpaperStore(s => s.lastConnectedName);
  const pairedNames = useEpaperStore(s => s.pairedNames);
  const lastDevice = useEpaperStore(s => s.lastDevice);
  const quickConnecting = useEpaperStore(s => s.quickConnecting);
  const invertRender = useEpaperStore(s => s.invertRender);
  const memos = useEpaperStore(s => s.memos);
  const memoArchive = useEpaperStore(s => s.memoArchive);
  const stationAutoMin = useEpaperStore(s => s.stationAutoMin);
  const stationPushing = useEpaperStore(s => s.stationPushing);
  const stationLastPush = useEpaperStore(s => s.stationLastPush);
  const stationLeave = useEpaperStore(s => s.stationLeave);

  const store = useEpaperStore.getState;

  // ===== 本地状态 =====
  const [filterId, setFilterId] = React.useState('');
  const [showHidden, setShowHidden] = React.useState(false); // 展开查看被隐藏的无名设备
  const [interleaved, setInterleaved] = React.useState(50);
  const [canvasSizeName, setCanvasSizeName] = React.useState('4.2_400_300');
  const [ditherMode, setDitherMode] = React.useState<DitherMode>('blackWhiteColor');
  const [ditherAlg, setDitherAlg] = React.useState<DitherAlgorithm>('floydSteinberg');
  const [ditherStrength, setDitherStrength] = React.useState(1.0);
  const [ditherContrast, setDitherContrast] = React.useState(1.2);
  const [sending, setSending] = React.useState(false);
  const [status, setStatus] = React.useState('');
  const [statusVisible, setStatusVisible] = React.useState(false);

  const [tool, setTool] = React.useState<PaintTool>(null);
  const [cropMode, setCropMode] = React.useState(false);
  const [canUndo, setCanUndo] = React.useState(false);
  const [canRedo, setCanRedo] = React.useState(false);
  const [canvasTitle, setCanvasTitle] = React.useState('');
  const [brushColor, setBrushColor] = React.useState('#000000');
  const [brushSize, setBrushSize] = React.useState(2);
  const [fontFamily, setFontFamily] = React.useState('Arial');
  const [fontSize, setFontSize] = React.useState(16);
  const [textInput, setTextInput] = React.useState('');
  const [textBold, setTextBold] = React.useState(false);
  const [textItalic, setTextItalic] = React.useState(false);

  const [cmdText, setCmdText] = React.useState('');
  const [testTs, setTestTs] = React.useState('');

  const [holidayOpen, setHolidayOpen] = React.useState(false);
  const [helpOpen, setHelpOpen] = React.useState(false);
  const [holidayYear, setHolidayYear] = React.useState(2026);
  const [holidayData, setHolidayData] = React.useState('');

  const [memoText, setMemoText] = React.useState('');
  const [memoEditId, setMemoEditId] = React.useState<number | null>(null); // 行内编辑中的备忘录 id
  const [memoEditText, setMemoEditText] = React.useState('');
  const [memoArchiveOpen, setMemoArchiveOpen] = React.useState(false); // 展开已归档备忘录
  const [stationRendering, setStationRendering] = React.useState(false);
  const [stationPreviewed, setStationPreviewed] = React.useState(false); // 已渲染过预览（显示预览画布）
  const [workbenchOpen, setWorkbenchOpen] = React.useState(false);       // 传图工作台展开（默认收起）

  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const stationCanvasRef = React.useRef<HTMLCanvasElement>(null); // 信息站卡片内的预览画布
  const ctxRef = React.useRef<CanvasRenderingContext2D | null>(null);
  const paintRef = React.useRef<PaintManager | null>(null);
  const cropRef = React.useRef<CropManager | null>(null);
  const fileRef = React.useRef<File | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const logBoxRef = React.useRef<HTMLDivElement>(null);
  const statusTimerRef = React.useRef<number | null>(null);

  // 管理器回调在 React 渲染周期外执行，经 ref 读取最新配置
  const optsRef = React.useRef({ ditherMode, ditherAlg, ditherStrength, ditherContrast, mtu, interleaved, textInput, fontFamily, fontSize });
  optsRef.current = { ditherMode, ditherAlg, ditherStrength, ditherContrast, mtu, interleaved, textInput, fontFamily, fontSize };

  const bluetoothSupported = typeof navigator !== 'undefined' && 'bluetooth' in navigator;

  // ===== 画布操作 =====

  const fillCanvas = (style: string) => {
    const canvas = canvasRef.current, ctx = ctxRef.current;
    if (!canvas || !ctx) return;
    ctx.fillStyle = style;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  };

  const convertDithering = React.useCallback(() => {
    const canvas = canvasRef.current, ctx = ctxRef.current, paint = paintRef.current;
    if (!canvas || !ctx || !paint) return;

    paint.redrawTextElements();
    paint.redrawLineSegments();

    const { ditherContrast, ditherAlg, ditherStrength, ditherMode } = optsRef.current;
    const currentImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const imageData = new ImageData(
      new Uint8ClampedArray(currentImageData.data),
      currentImageData.width,
      currentImageData.height,
    );

    adjustContrast(imageData, ditherContrast);

    const processedData = processImageData(ditherImage(imageData, ditherAlg, ditherStrength, ditherMode), ditherMode);
    const finalImageData = decodeProcessedData(processedData, canvas.width, canvas.height, ditherMode);
    ctx.putImageData(finalImageData, 0, 0);

    paint.saveToHistory();
  }, []);

  const applyDither = React.useCallback(() => {
    cropRef.current?.finishCrop(() => convertDithering());
  }, [convertDithering]);

  const updateImage = React.useCallback(() => {
    const canvas = canvasRef.current, ctx = ctxRef.current, paint = paintRef.current, crop = cropRef.current;
    if (!canvas || !ctx || !paint || !crop) return;

    const file = fileRef.current;
    if (!file) {
      fillCanvas('white');
      return;
    }

    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(image.src);
      if (image.width / image.height === canvas.width / canvas.height) {
        if (crop.isCropMode()) crop.exitCropMode();
        ctx.drawImage(image, 0, 0, image.width, image.height, 0, 0, canvas.width, canvas.height);
        convertDithering();
      } else {
        void appAlert('图片宽高比例与画布不匹配，将进入裁剪模式。\n请放大图片后移动图片使其充满画布, 再点击"完成"按钮。', { title: '进入裁剪模式' });
        paint.setActiveTool(null, '');
        crop.initializeCrop();
      }
    };
    image.src = URL.createObjectURL(file);
  }, [convertDithering]);

  const updateCanvasSize = React.useCallback((name: string) => {
    const size = canvasSizes.find(s => s.name === name);
    const canvas = canvasRef.current;
    if (!size || !canvas) return;
    canvas.width = size.width;
    canvas.height = size.height;
    updateImage();
  }, [updateImage]);

  // ===== 管理器装配 =====

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctxRef.current = ctx;

    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const paint = new PaintManager(canvas, ctx, {
      setCanvasTitle: t => setCanvasTitle(t),
      onToolChange: t => setTool(t),
      onHistoryChange: (u, r) => { setCanUndo(u); setCanRedo(r); },
      getTextConfig: () => ({
        text: optsRef.current.textInput,
        fontFamily: optsRef.current.fontFamily,
        fontSize: optsRef.current.fontSize,
      }),
      onTextPlaced: () => setTextInput(''),
    });
    const crop = new CropManager(canvas, ctx, {
      setCanvasTitle: t => setCanvasTitle(t),
      onCropModeChange: v => setCropMode(v),
      getImageFile: () => fileRef.current,
    });
    paintRef.current = paint;
    cropRef.current = crop;
    paint.attach();

    return () => {
      paint.detach();
      crop.exitCropMode();
      paintRef.current = null;
      cropRef.current = null;
      if (statusTimerRef.current) window.clearTimeout(statusTimerRef.current);
    };
  }, []);

  // 驱动变化（手动选择或设备回传配置）→ 同步颜色模式与画布尺寸（对应原 updateDitcherOptions）
  React.useEffect(() => {
    const d = epdDrivers.find(x => x.value === driver);
    if (!d) return;
    setDitherMode(d.color);
    optsRef.current.ditherMode = d.color;
    setCanvasSizeName(d.size);
    updateCanvasSize(d.size);
  }, [driver, updateCanvasSize]);

  // 日志自动滚动到底部
  React.useEffect(() => {
    const box = logBoxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [logs]);

  // 关闭/重开扫描 modal 时收起「已隐藏」展开区
  React.useEffect(() => {
    if (!scanning) setShowHidden(false);
  }, [scanning]);

  // ===== 设备控制 =====

  const ctrlDisabled = !connected || sending;

  const syncTime = async (mode: 1 | 2) => {
    if (mode === 2) {
      if (!(await appConfirm('提醒：时钟模式目前使用全刷实现，此功能目前多用于修复老化屏残影问题，不建议长期开启，是否继续？', { title: '时钟模式' }))) return;
    }
    const timestamp = new Date().getTime() / 1000;
    const data = new Uint8Array([
      (timestamp >> 24) & 0xFF,
      (timestamp >> 16) & 0xFF,
      (timestamp >> 8) & 0xFF,
      timestamp & 0xFF,
      -(new Date().getTimezoneOffset() / 60),
      mode,
    ]);
    if (await epdClient.write(EpdCmd.SET_TIME, data)) {
      addLog('时间已同步！');
      addLog('屏幕刷新完成前请不要操作。');
    }
  };

  const clearScreen = async () => {
    if (await appConfirm('确认清除屏幕内容?', { danger: true, confirmText: '清除' })) {
      await epdClient.write(EpdCmd.CLEAR);
      addLog('清屏指令已发送！');
      addLog('屏幕刷新完成前请不要操作。');
    }
  };

  const sendCmd = async () => {
    if (cmdText === '') return;
    const bytes = hex2bytes(cmdText);
    await epdClient.write(bytes[0], bytes.length > 1 ? bytes.slice(1) : null);
  };

  const setDriverCmd = async () => {
    await epdClient.write(EpdCmd.SET_PINS, pins);
    await epdClient.write(EpdCmd.INIT, driver);
  };

  // ===== 测试时间戳（开发模式）=====

  const tsInfo = React.useMemo(() => {
    const timestamp = parseInt(testTs);
    if (isNaN(timestamp) || timestamp <= 0) return '';
    const date = new Date(timestamp * 1000);
    const p = (n: number) => String(n).padStart(2, '0');
    return `对应时间: ${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} 星期${WEEKDAYS[date.getDay()]} ${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
  }, [testTs]);

  const setCurrentTimestamp = () => {
    setTestTs(String(Math.floor(new Date().getTime() / 1000)));
  };

  const addDays = (days: number) => {
    const current = parseInt(testTs) || Math.floor(new Date().getTime() / 1000);
    setTestTs(String(current + days * 86400)); // 86400秒 = 1天
  };

  const testCalendarJump = async (mode: 1 | 2) => {
    const timestamp = parseInt(testTs);
    if (isNaN(timestamp) || timestamp <= 0) {
      await appAlert('请输入有效的时间戳（Unix时间戳，秒为单位）');
      return;
    }

    const date = new Date(timestamp * 1000);
    const dateStr = date.toLocaleString('zh-CN');
    const modeName = mode === 1 ? '日历' : '时钟';
    if (!(await appConfirm(`确认要将设备时间设置为:\n${dateStr}\n并切换到${modeName}模式?`, { title: '时间测试' }))) return;

    const data = new Uint8Array([
      (timestamp >> 24) & 0xFF,
      (timestamp >> 16) & 0xFF,
      (timestamp >> 8) & 0xFF,
      timestamp & 0xFF,
      -(new Date().getTimezoneOffset() / 60),
      mode,
    ]);

    if (await epdClient.write(EpdCmd.SET_TIME, data)) {
      addLog(`测试时间已设置: ${dateStr}`);
      addLog(`模式: ${modeName}模式`);
      addLog('屏幕刷新完成前请不要操作。');
    }
  };

  // ===== 假期数据 =====

  const loadDefaultHolidays = (year: 2026 | 2027) => {
    setHolidayYear(year);
    setHolidayData(year === 2026 ? DEFAULT_HOLIDAYS_2026 : DEFAULT_HOLIDAYS_2027);
    addLog(year === 2026 ? '已加载2026年默认假期数据' : '已加载2027年默认假期数据（示例）');
  };

  const sendHolidayData = async () => {
    if (!holidayYear || holidayYear < 2020 || holidayYear > 2050) {
      await appAlert('请输入有效的年份 (2020-2050)');
      return;
    }

    const holidays = parseHolidayData(holidayData, line => addLog(`警告: 跳过无效数据 "${line}"`));

    if (holidays.length === 0) {
      await appAlert('没有有效的假期数据！');
      return;
    }
    if (holidays.length > 128) {
      await appAlert('假期数据过多，最多支持128个！');
      return;
    }

    addLog(`准备发送 ${holidayYear} 年假期数据，共 ${holidays.length} 个假期...`);

    if (await epdClient.write(EpdCmd.SET_HOLIDAYS, buildHolidayPayload(holidayYear, holidays))) {
      addLog('假期数据已发送成功！');
      setHolidayOpen(false);
    } else {
      addLog('假期数据发送失败！');
    }
  };

  // ===== 蓝牙传图 =====

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    fileRef.current = e.target.files && e.target.files.length > 0 ? e.target.files[0] : null;
    updateImage();
  };

  const sendImg = async () => {
    const canvas = canvasRef.current, ctx = ctxRef.current, crop = cropRef.current;
    if (!canvas || !ctx || !crop) return;

    if (crop.isCropMode()) {
      await appAlert('请先完成图片裁剪！发送已取消。');
      return;
    }

    const drv = epdDrivers.find(d => d.value === driver);
    if (drv && drv.size !== canvasSizeName) {
      if (!(await appConfirm('警告：画布尺寸和驱动不匹配，是否继续？', { title: '发送前检查' }))) return;
    }
    if (drv && drv.color !== ditherMode) {
      if (!(await appConfirm('警告：颜色模式和驱动不匹配，是否继续？', { title: '发送前检查' }))) return;
    }

    if (epdSendBusy()) {
      addLog('已有发送任务进行中，请等待屏幕刷新完成');
      return;
    }

    if (statusTimerRef.current) window.clearTimeout(statusTimerRef.current);
    setStatusVisible(true);
    setSending(true);
    try {
      const sendTime = await sendCanvasToEpd(epdClient, canvas, ctx, {
        driver, ditherMode, mtu, interleaved, rotate180: invertRender, onStatus: setStatus,
      });
      addLog(`发送完成！耗时: ${sendTime}s`);
      setStatus(`发送完成！耗时: ${sendTime}s`);
      addLog('屏幕刷新完成前请不要操作。');
      statusTimerRef.current = window.setTimeout(() => setStatusVisible(false), 5000);
    } catch (e) {
      const msg = (e as Error).message ?? String(e);
      addLog(`发送失败: ${msg}`);
      setStatus(`发送失败: ${msg}`);
    } finally {
      setSending(false);
    }
  };

  // ===== 信息站（按设计稿 墨水屏信息站.dc.html：Claude 额度 + 备忘录 + 日历）=====

  // 渲染信息站预览（绘制在信息站卡片内的专属画布上，效果与推屏一致）
  const renderStationPreview = async () => {
    const canvas = stationCanvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    setStationRendering(true);
    try {
      const data = await buildStationData();
      renderStation(ctx, canvas.width, canvas.height, data);
      setStationPreviewed(true);
      if (!data.usage?.available) addLog(`提示：Claude 额度数据不可用${data.usage?.error ? `（${data.usage.error}）` : ''}`);
      if (!data.calendar?.available) addLog('提示：日历数据不可用，仅按双休渲染');
    } catch (e) {
      addLog(`信息站渲染失败: ${(e as Error).message ?? e}`);
    } finally {
      setStationRendering(false);
    }
  };

  const addMemoFromInput = () => {
    if (!memoText.trim()) return;
    store().addMemo(memoText);
    setMemoText('');
  };

  // 展示序：未完成在上、已完成沉底（底层数组保持添加顺序，取消勾选回到原位置）
  const sortedMemos = React.useMemo(() => sortMemos(memos), [memos]);

  // FLIP 动画：排序/增删导致条目位移时，从旧位置平滑滑动到新位置（勾选沉底 / 取消勾选浮回）
  const memoListRef = React.useRef<HTMLDivElement | null>(null);
  const memoRowTops = React.useRef<Map<string, number>>(new Map());
  React.useLayoutEffect(() => {
    const list = memoListRef.current;
    if (!list) return;
    const rows = Array.from(list.querySelectorAll<HTMLElement>('[data-memo-id]'));
    const tops = new Map<string, number>();
    // 用容器内容坐标（抵消列表自身滚动），避免用户滚动后 toggle 触发整列假位移动画
    const base = list.getBoundingClientRect().top - list.scrollTop;
    for (const el of rows) tops.set(el.dataset.memoId!, el.getBoundingClientRect().top - base);
    for (const el of rows) {
      const id = el.dataset.memoId!;
      const prev = memoRowTops.current.get(id);
      const now = tops.get(id)!;
      if (prev != null && Math.abs(prev - now) > 1) {
        el.style.transition = 'none';
        el.style.transform = `translateY(${prev - now}px)`;
        void el.offsetHeight; // 强制 reflow，让起点 transform 先生效
        el.style.transition = 'transform 0.32s ease';
        el.style.transform = '';
        el.addEventListener('transitionend', function clear() {
          el.style.transition = '';
          el.removeEventListener('transitionend', clear);
        });
      }
    }
    memoRowTops.current = tops;
  }, [sortedMemos]);

  // 备忘录行内编辑（铅笔按钮或双击文本进入；Enter/失焦保存，Esc 取消，改空=放弃）
  const startMemoEdit = (m: StationMemoItem) => {
    setMemoEditId(m.id);
    setMemoEditText(m.text);
  };
  const commitMemoEdit = () => {
    if (memoEditId != null && memoEditText.trim()) store().updateMemo(memoEditId, memoEditText);
    setMemoEditId(null);
  };
  const cancelMemoEdit = () => setMemoEditId(null);

  const downloadDataArray = () => {
    const canvas = canvasRef.current, ctx = ctxRef.current, crop = cropRef.current;
    if (!canvas || !ctx || !crop) return;

    if (crop.isCropMode()) {
      void appAlert('请先完成图片裁剪！下载已取消。');
      return;
    }

    const mode = ditherMode;
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const processedData = processImageData(imageData, mode);

    if (mode === 'sixColor' && processedData.length !== canvas.width * canvas.height) {
      console.log(`错误：预期${canvas.width * canvas.height}字节，但得到${processedData.length}字节`);
      addLog('数组大小不匹配。请检查图像尺寸和模式。');
      return;
    }

    const dataLines: string[] = [];
    for (let i = 0; i < processedData.length; i++) {
      dataLines.push(`0x${(processedData[i] & 0xff).toString(16).padStart(2, '0')}`);
    }

    const formattedData: string[] = [];
    for (let i = 0; i < dataLines.length; i += 16) {
      formattedData.push(dataLines.slice(i, i + 16).join(', '));
    }

    const colorModeValue = mode === 'sixColor' ? 0 : mode === 'fourColor' ? 1 : mode === 'blackWhiteColor' ? 2 : 3;
    const arrayContent = [
      'const uint8_t imageData[] PROGMEM = {',
      formattedData.join(',\n'),
      '};',
      `const uint16_t imageWidth = ${canvas.width};`,
      `const uint16_t imageHeight = ${canvas.height};`,
      `const uint8_t colorMode = ${colorModeValue};`,
    ].join('\n');

    const blob = new Blob([arrayContent], { type: 'text/plain' });
    const link = document.createElement('a');
    link.download = 'imagedata.h';
    link.href = URL.createObjectURL(blob);
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const rotateCanvas = () => {
    const canvas = canvasRef.current, ctx = ctxRef.current, paint = paintRef.current;
    if (!canvas || !ctx || !paint) return;

    const currentWidth = canvas.width;
    const currentHeight = canvas.height;
    const imageData = ctx.getImageData(0, 0, currentWidth, currentHeight);

    canvas.width = currentHeight;
    canvas.height = currentWidth;

    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = currentWidth;
    tempCanvas.height = currentHeight;
    const tempCtx = tempCanvas.getContext('2d');
    if (!tempCtx) return;
    tempCtx.putImageData(imageData, 0, 0);

    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(90 * Math.PI / 180);
    ctx.drawImage(tempCanvas, -currentWidth / 2, -currentHeight / 2);
    ctx.setTransform(1, 0, 0, 1, 0, 0);

    paint.clearHistory();   // 画布尺寸已变，历史失效
    paint.clearElements();
    paint.saveToHistory();
  };

  const clearCanvas = async () => {
    const paint = paintRef.current, crop = cropRef.current;
    if (!paint || !crop) return;
    if (await appConfirm('清除画布内容?', { danger: true, confirmText: '清除' })) {
      fillCanvas('white');
      paint.clearElements();
      if (crop.isCropMode()) crop.exitCropMode();
      paint.saveToHistory();
    }
  };

  // ===== 绘图工具 =====

  const toggleTool = (t: Exclude<PaintTool, null>) => {
    const paint = paintRef.current;
    if (!paint) return;
    if (paint.currentTool === t) {
      paint.setActiveTool(null, '');
      return;
    }
    if (t === 'brush') {
      paint.setActiveTool('brush', '画笔模式');
      paint.brushColor = brushColor;
    } else if (t === 'eraser') {
      paint.setActiveTool('eraser', '橡皮擦');
      paint.brushColor = '#FFFFFF';
    } else {
      paint.setActiveTool('text', '插入文字');
      paint.brushColor = brushColor;
    }
  };

  const onBrushColorChange = (v: string) => {
    setBrushColor(v);
    if (paintRef.current) paintRef.current.brushColor = v;
  };

  const onBrushSizeChange = (v: number) => {
    if (isNaN(v)) return;
    setBrushSize(v);
    const paint = paintRef.current;
    if (paint) {
      paint.brushSize = v;
      paint.updateBrushCursorSize();
    }
  };

  const onToggleBold = () => {
    const next = !textBold;
    setTextBold(next);
    if (paintRef.current) paintRef.current.textBold = next;
  };

  const onToggleItalic = () => {
    const next = !textItalic;
    setTextItalic(next);
    if (paintRef.current) paintRef.current.textItalic = next;
  };

  // 抖动参数变化即时生效（原版 input/onchange 即触发 applyDither）
  const onDitherAlgChange = (v: DitherAlgorithm) => {
    setDitherAlg(v);
    optsRef.current.ditherAlg = v;
    applyDither();
  };
  const onDitherModeChange = (v: DitherMode) => {
    setDitherMode(v);
    optsRef.current.ditherMode = v;
    applyDither();
  };
  const onDitherStrengthChange = (v: number) => {
    setDitherStrength(v);
    optsRef.current.ditherStrength = v;
    applyDither();
  };
  const onDitherContrastChange = (v: number) => {
    setDitherContrast(v);
    optsRef.current.ditherContrast = v;
    applyDither();
  };

  // ===== 渲染派生 =====

  // 画布标题：管理器消息（裁剪/插入文字提示）优先，否则展示当前尺寸/颜色模式
  const sizeLabel = canvasSizeLabels[canvasSizeName] ?? canvasSizeName;
  const modeLabel = DITHER_MODE_OPTIONS.find(o => o.value === ditherMode)?.label ?? '';
  const shownCanvasTitle = canvasTitle || `${sizeLabel} · ${modeLabel}`;

  // 蓝牙扫描设备：有真实名称的正常列出（不额外过滤）；无真实名称（Chromium 占位）的折叠进「已隐藏」，
  // 点击展开后同样可查看/连接。filterId 在 modal 内对两组都做客户端子串过滤。
  // 有名设备：「上次连接」的那台一旦扫到就置顶，其余保持扫描到达顺序（稳定排序）
  // 匹配优先按持久化的 deviceId（跨重启稳定），设备名作回退
  const isLastDev = (d: EpdScanDevice) =>
    (lastDevice != null && d.deviceId === lastDevice.id) || (!!lastConnectedName && d.deviceName === lastConnectedName);
  const namedDevices = scanDevices
    .filter(d => hasRealName(d.deviceName))
    .sort((a, b) => (isLastDev(a) ? 0 : 1) - (isLastDev(b) ? 0 : 1));
  const hiddenDevices = scanDevices.filter(d => !hasRealName(d.deviceName));
  const hiddenCount = hiddenDevices.length;
  const fid = filterId.trim().toUpperCase();
  const matchFid = (d: EpdScanDevice) => d.deviceName.toUpperCase().includes(fid);
  const shownDevices = fid ? namedDevices.filter(matchFid) : namedDevices;
  const shownHidden = fid ? hiddenDevices.filter(matchFid) : hiddenDevices;

  // 设备行（有名/无名复用同一渲染，均可点击连接）
  const renderDeviceRow = (d: EpdScanDevice) => {
    const isConnecting = connectingId === d.deviceId;
    const isLast = isLastDev(d);
    const isPaired = !isLast && pairedNames.includes(d.deviceName);
    return (
      <div
        key={d.deviceId}
        className={`ep-dev-row ${isConnecting ? 'connecting' : ''}`}
        onClick={() => store().selectScanDevice(d.deviceId)}
      >
        <span className="ep-dev-ico"><Icon.Bluetooth size={19} /></span>
        <div className="ep-dev-meta">
          <span className="ep-dev-name">{d.deviceName}</span>
          {(isLast || isPaired) && (
            <div className="ep-dev-badges">
              {isLast && <span className="ep-badge ep-badge-last">上次连接</span>}
              {isPaired && <span className="ep-badge ep-badge-paired">已配对</span>}
            </div>
          )}
        </div>
        {isConnecting
          ? <span className="ep-dev-connecting"><span className="ep-spinner" />连接中…</span>
          : <span className="ep-dev-go">连接<Icon.ChevronRight size={12} /></span>}
      </div>
    );
  };

  // ===== 渲染 =====

  return (
    <div className="ep-page">

      {/* ===== 连接状态条 ===== */}
      <div className="ep-statusbar">
        <div className={`ep-status-icon ${connected ? 'on' : ''}`}>
          <Icon.Bluetooth size={22} />
        </div>
        <div className="ep-status-meta">
          <div className="ep-status-title">{connected ? `已连接 · ${deviceName ?? ''}` : '未连接'}</div>
          <div className="ep-status-sub">EPD-nRF5 · Web Bluetooth</div>
        </div>
        <div className="ep-pills">
          <span className={`pill ${bluetoothSupported ? 'pill-info' : 'pill-warning'}`}>
            <span className="dot" />{bluetoothSupported ? '蓝牙可用' : '蓝牙不可用'}
          </span>
          <span className={`pill ${connected ? 'pill-success' : 'pill-neutral'}`}>
            <span className="dot" />{connected ? '已连接' : '未连接'}
          </span>
          {connected && firmware != null && (
            <span className="pill pill-neutral mono">固件 0x{firmware.toString(16)}</span>
          )}
          {connected && <span className="pill pill-neutral mono">MTU {mtu}</span>}
        </div>
        <div className="ep-status-actions">
          {!connected && (
            <>
              <button className="btn btn-primary" disabled={quickConnecting} onClick={() => store().openScan()}>
                <Icon.Bluetooth size={15} /> 连接设备
              </button>
              {quickConnecting ? (
                <button className="btn" onClick={() => store().cancelQuickReconnect()}>
                  <span className="ep-spinner" /> 重连中 · 点击取消
                </button>
              ) : canReconnect ? (
                <button className="btn" onClick={() => void store().reconnect()}>
                  <Icon.Refresh size={14} /> 重连
                </button>
              ) : lastDevice ? (
                // 跨重启记忆的上次设备：免搜索一键重连（后台扫描，发现即自动连接）
                <button
                  className="btn"
                  title={`上次连接：${lastDevice.name || lastDevice.id}`}
                  onClick={() => store().quickReconnect()}
                >
                  <Icon.Refresh size={14} /> 一键重连 · {lastDevice.name || '上次设备'}
                </button>
              ) : null}
            </>
          )}
          {connected && (
            <>
              <button className="btn" onClick={() => void store().reconnect()}>
                <Icon.Refresh size={14} /> 重连
              </button>
              <button className="btn btn-danger" onClick={() => store().disconnect()}>断开</button>
            </>
          )}
        </div>
      </div>

      {/* ===== 双栏工作台 ===== */}
      <div className="ep-grid">

        {/* 左列：信息站 + 传图工作台 */}
        <div className="ep-col">

        {/* 信息站：Claude 额度 + 备忘录 + 放假倒计时，一屏推送 */}
        <div className="card">
          <div className="card-header">
            <div className="col" style={{ gap: 3 }}>
              <div className="card-title">信息站</div>
              <div className="card-sub">Claude 额度 · 备忘录 · 放假倒计时 — 渲染成一屏推送到墨水屏</div>
            </div>
            <span className="ep-hint-inline mono">
              {stationLastPush
                ? `上次推送 ${new Date(stationLastPush).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
                : '尚未推送'}
            </span>
          </div>
          <div className="card-body">
            <div className="ep-station-grid">

              {/* 左：屏幕预览 + 推送操作 */}
              <div className="ep-station-left">
                <div className="ep-station-preview">
                  <canvas
                    ref={stationCanvasRef}
                    width={400}
                    height={300}
                    style={{ display: stationPreviewed ? undefined : 'none' }}
                  />
                  {!stationPreviewed && (
                    <button
                      className="ep-station-placeholder"
                      disabled={stationRendering}
                      onClick={() => void renderStationPreview()}
                    >
                      <Icon.Epaper size={30} />
                      <span className="ep-station-ph-title">{stationRendering ? '渲染中…' : '点击渲染预览'}</span>
                      <span className="ep-station-ph-sub">400×300 · 三色量化 · 与推屏效果一致</span>
                    </button>
                  )}
                </div>
                <div className="ep-row">
                  <button className="btn" disabled={stationRendering} onClick={() => void renderStationPreview()}>
                    <Icon.Refresh size={14} /> {stationRendering ? '渲染中…' : stationPreviewed ? '刷新预览' : '渲染预览'}
                  </button>
                  <button
                    className="btn btn-primary"
                    style={{ flex: 1 }}
                    disabled={!connected || stationPushing || sending}
                    onClick={() => void store().pushStation()}
                  >
                    <Icon.Send size={14} /> {stationPushing ? '推送中…' : '推送到屏幕'}
                  </button>
                </div>
                <div className="ep-hint-inline">墨水屏全刷约 15–25 秒，推送期间请勿进行其他发送操作</div>
              </div>

              {/* 右：备忘录 + 推送/请假设置 */}
              <div className="ep-station-right">
                <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span className="field-label">备忘录（屏上展示前 {STATION_MEMO_MAX} 条）</span>
                  <span className="ep-hint-inline mono">{memos.filter(m => m.done).length} / {memos.length}</span>
                </div>
                <div className="ep-memo-list" ref={memoListRef}>
                  {memos.length === 0 && <div className="ep-memo-empty">暂无事项 — 在下方输入添加</div>}
                  {sortedMemos.map((m, i) => (
                    <div key={m.id} data-memo-id={m.id} className={`ep-memo-item ${m.done ? 'done' : ''}`}>
                      <button
                        className={`ep-memo-check ${m.done ? 'on' : ''}`}
                        title={m.done ? '标记未完成' : '标记完成'}
                        onClick={() => store().toggleMemo(m.id)}
                      >
                        {m.done && <Icon.Check size={11} />}
                      </button>
                      {memoEditId === m.id ? (
                        <input
                          className="input ep-memo-edit"
                          autoFocus
                          maxLength={40}
                          value={memoEditText}
                          onChange={e => setMemoEditText(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === 'Enter') commitMemoEdit();
                            else if (e.key === 'Escape') cancelMemoEdit();
                          }}
                          onBlur={commitMemoEdit}
                        />
                      ) : (
                        <span className="ep-memo-text" title="双击修改" onDoubleClick={() => startMemoEdit(m)}>{m.text}</span>
                      )}
                      {i >= STATION_MEMO_MAX && <span className="ep-badge" title="超出屏幕展示条数">屏外</span>}
                      {memoEditId !== m.id && (
                        <button className="ep-memo-edit-btn" title="修改" onClick={() => startMemoEdit(m)}>
                          <Icon.Pencil size={13} />
                        </button>
                      )}
                      <button className="ep-memo-del" title="删除" onClick={() => store().removeMemo(m.id)}>
                        <Icon.Trash size={13} />
                      </button>
                    </div>
                  ))}

                  {/* 已归档（划掉超 3 天自动移入）：可恢复 / 删除 / 清空 */}
                  {memoArchive.length > 0 && (
                    <>
                      <button className="ep-hidden-toggle" onClick={() => setMemoArchiveOpen(v => !v)}>
                        <Icon.ChevronDown size={13} className={`ep-hidden-chev ${memoArchiveOpen ? 'open' : ''}`} />
                        {memoArchiveOpen
                          ? `收起归档（${memoArchive.length}）`
                          : `已归档 ${memoArchive.length} 条 · 划掉超 3 天自动归档`}
                      </button>
                      {memoArchiveOpen && memoArchive.map(m => (
                        <div key={m.id} className="ep-memo-item done ep-memo-archived">
                          <span className="ep-memo-text">{m.text}</span>
                          <span className="ep-hint-inline mono">
                            {(d => `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} 归档`)(new Date(m.archivedAt))}
                          </span>
                          <button className="ep-memo-edit-btn" title="恢复为未完成" onClick={() => store().restoreMemo(m.id)}>
                            <Icon.Undo size={13} />
                          </button>
                          <button className="ep-memo-del" title="彻底删除" onClick={() => store().removeArchivedMemo(m.id)}>
                            <Icon.Trash size={13} />
                          </button>
                        </div>
                      ))}
                      {memoArchiveOpen && (
                        <button
                          className="ep-hidden-toggle"
                          onClick={() => void (async () => {
                            if (await appConfirm(`清空全部 ${memoArchive.length} 条归档？`, { title: '清空归档', danger: true, confirmText: '清空' })) {
                              store().clearMemoArchive();
                            }
                          })()}
                        >
                          <Icon.Trash size={12} /> 清空归档
                        </button>
                      )}
                    </>
                  )}
                </div>
                <div className="ep-row">
                  <input
                    className="input"
                    style={{ flex: 1, minWidth: 160 }}
                    placeholder="新事项，回车添加"
                    maxLength={40}
                    value={memoText}
                    onChange={e => setMemoText(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') addMemoFromInput(); }}
                  />
                  <button className="btn" onClick={addMemoFromInput}><Icon.Plus size={14} /> 添加</button>
                </div>

                <div className="ep-divider" />

                {/* 自动推送 */}
                <div className="ep-station-set-row">
                  <span className="ep-label">自动推送</span>
                  <select
                    className="input ep-select"
                    value={stationAutoMin}
                    onChange={e => store().setStationAutoMin(parseInt(e.target.value))}
                  >
                    <option value={0}>关闭</option>
                    <option value={30}>每 30 分钟</option>
                    <option value={60}>每 1 小时</option>
                    <option value={120}>每 2 小时</option>
                    <option value={240}>每 4 小时</option>
                  </select>
                  <span className="ep-hint-inline">到点未连接会先自动重连再推送；间隔过密影响屏幕寿命</span>
                </div>

                {/* 倒置渲染：屏幕倒挂安装时勾选，发送/推送统一旋转 180°（跨重启记忆） */}
                <div className="ep-station-set-row">
                  <label className="ep-leave-toggle">
                    <input
                      type="checkbox"
                      checked={invertRender}
                      onChange={e => store().setInvertRender(e.target.checked)}
                    />
                    倒置渲染
                  </label>
                  <span className="ep-hint-inline">发送 / 推送时旋转 180°，适合屏幕倒挂安装</span>
                </div>

                {/* 请假模式：区间内屏幕渲染「请假中」全屏状态（销假日由后端按工作日计算） */}
                <div className="ep-station-set-row">
                  <label className="ep-leave-toggle">
                    <input
                      type="checkbox"
                      checked={stationLeave.enabled}
                      onChange={e => store().setStationLeave({ enabled: e.target.checked })}
                    />
                    请假模式
                  </label>
                  {stationLeave.enabled && (
                    <>
                      <input
                        className="input"
                        style={{ width: 76 }}
                        placeholder="类型"
                        maxLength={6}
                        value={stationLeave.label}
                        onChange={e => store().setStationLeave({ label: e.target.value })}
                      />
                      <input
                        className="input mono"
                        type="date"
                        value={stationLeave.start}
                        onChange={e => store().setStationLeave({ start: e.target.value })}
                      />
                      <span className="ep-label">至</span>
                      <input
                        className="input mono"
                        type="date"
                        value={stationLeave.end}
                        onChange={e => store().setStationLeave({ end: e.target.value })}
                      />
                    </>
                  )}
                </div>
              </div>

            </div>
          </div>
        </div>

        {/* 传图工作台（默认收起画布，点击标题展开） */}
        <div className="card">
          <button className="ep-adv-toggle" onClick={() => setWorkbenchOpen(v => !v)}>
            <div className="ep-adv-head">
              <Icon.Epaper size={15} style={{ color: 'var(--text-muted)' }} />
              <div>
                <div className="ep-adv-title">传图工作台</div>
                <div className="ep-adv-sub">选择图片 → 抖动预览 → 发送到墨水屏；支持画笔、文字与裁剪</div>
              </div>
            </div>
            <Icon.ChevronDown size={14} className={`ep-adv-chev ${workbenchOpen ? 'open' : ''}`} style={{ color: 'var(--text-muted)' }} />
          </button>
          <div className="card-body col" style={{ gap: 14, display: workbenchOpen ? undefined : 'none' }}>
            {/* 文件 */}
            <div className="ep-file-row">
              <input
                ref={fileInputRef}
                type="file"
                className="ep-file"
                accept=".png,.jpg,.bmp,.webp,.jpeg"
                onChange={onFileChange}
              />
            </div>

            {/* 抖动参数 */}
            <div className="ep-row">
              <span className="ep-label">抖动算法</span>
              <select className="input ep-select" value={ditherAlg} onChange={e => onDitherAlgChange(e.target.value as DitherAlgorithm)}>
                {DITHER_ALG_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <span className="ep-label">强度</span>
              <input type="range" className="ep-range" min={0} max={5} step={0.1} value={ditherStrength} onChange={e => onDitherStrengthChange(parseFloat(e.target.value))} />
              <span className="ep-label mono" style={{ width: 24 }}>{ditherStrength.toFixed(1)}</span>
              <span className="ep-label">对比度</span>
              <input type="range" className="ep-range" min={0.5} max={2} step={0.1} value={ditherContrast} onChange={e => onDitherContrastChange(parseFloat(e.target.value))} />
              <span className="ep-label mono" style={{ width: 24 }}>{ditherContrast.toFixed(1)}</span>
            </div>

            {/* 画布 / 设备预览 */}
            <div className="ep-canvas-area">
              <div className="ep-canvas-title">{shownCanvasTitle}</div>
              <div className={`ep-canvas-frame ${cropMode ? 'crop' : ''}`}>
                <canvas ref={canvasRef} width={400} height={300} />
              </div>

              {/* 工具栏 */}
              {!cropMode && (
                <div className="ep-tools">
                  <button className={`ep-tool ${tool === 'brush' ? 'active' : ''}`} title="画笔" onClick={() => toggleTool('brush')}><Icon.Brush size={16} /></button>
                  <button className={`ep-tool ${tool === 'eraser' ? 'active' : ''}`} title="橡皮擦" onClick={() => toggleTool('eraser')}><Icon.Eraser size={16} /></button>
                  <button className={`ep-tool ${tool === 'text' ? 'active' : ''}`} title="添加文字" onClick={() => toggleTool('text')}><Icon.TextTool size={16} /></button>
                  {tool != null && (
                    <>
                      <span className="ep-tool-sep" />
                      <button className="ep-tool" title="撤销 (Ctrl+Z)" disabled={!canUndo} onClick={() => paintRef.current?.undo()}><Icon.Undo size={16} /></button>
                      <button className="ep-tool" title="重做 (Ctrl+Y)" disabled={!canRedo} onClick={() => paintRef.current?.redo()}><Icon.Redo size={16} /></button>
                    </>
                  )}
                </div>
              )}

              {/* 颜色 / 粗细 */}
              {!cropMode && tool != null && (
                <div className="ep-row center">
                  <span className="ep-label">颜色</span>
                  <select className="input ep-select" value={brushColor} disabled={tool === 'eraser'} onChange={e => onBrushColorChange(e.target.value)}>
                    {BRUSH_COLORS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                  <span className="ep-label">粗细</span>
                  <input className="input mono" style={{ width: 64 }} type="number" min={1} max={100} value={brushSize} disabled={tool === 'text'} onChange={e => onBrushSizeChange(parseInt(e.target.value))} />
                </div>
              )}

              {/* 文字 */}
              {!cropMode && tool === 'text' && (
                <div className="ep-row center">
                  <select className="input ep-select" value={fontFamily} onChange={e => setFontFamily(e.target.value)}>
                    {FONT_OPTIONS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                  <input className="input mono" style={{ width: 62 }} type="number" min={1} max={100} value={fontSize} onChange={e => { const v = parseInt(e.target.value); if (!isNaN(v)) setFontSize(v); }} />
                  <input className="input" style={{ width: 140 }} placeholder="输入文字" value={textInput} onChange={e => setTextInput(e.target.value)} />
                  <button className={`ep-tool ${textBold ? 'active' : ''}`} title="粗体" style={{ fontWeight: 700 }} onClick={onToggleBold}>B</button>
                  <button className={`ep-tool ${textItalic ? 'active' : ''}`} title="斜体" style={{ fontStyle: 'italic', fontFamily: 'Georgia, serif' }} onClick={onToggleItalic}>I</button>
                  <button className="btn btn-primary" onClick={() => paintRef.current?.startTextPlacement()}>添加文字</button>
                </div>
              )}

              {/* 裁剪工具 */}
              {cropMode && (
                <div className="ep-tools">
                  <button className="ep-tool" title="放大" onClick={() => cropRef.current?.zoomIn()}><Icon.Plus size={15} /></button>
                  <button className="ep-tool" title="缩小" onClick={() => cropRef.current?.zoomOut()}><Icon.Minus size={15} /></button>
                  <button className="ep-tool" title="左移" onClick={() => cropRef.current?.move(-10, 0)}><Icon.ChevronLeft size={15} /></button>
                  <button className="ep-tool" title="上移" onClick={() => cropRef.current?.move(0, -10)} style={{ transform: 'rotate(90deg)' }}><Icon.ChevronLeft size={15} /></button>
                  <button className="ep-tool" title="下移" onClick={() => cropRef.current?.move(0, 10)} style={{ transform: 'rotate(-90deg)' }}><Icon.ChevronLeft size={15} /></button>
                  <button className="ep-tool" title="右移" onClick={() => cropRef.current?.move(10, 0)}><Icon.ChevronRight size={15} /></button>
                  <button className="btn btn-primary" onClick={applyDither}>完成</button>
                </div>
              )}
            </div>

            {/* 发送状态 */}
            {statusVisible && (
              <div className="ep-status"><b>状态：</b>{status}</div>
            )}

            {/* 操作 */}
            <div className="ep-actions">
              <button className="btn" onClick={() => void clearCanvas()}>清除画布</button>
              {debug && <button className="btn" onClick={rotateCanvas}>旋转画布</button>}
              {debug && (
                <button className="btn" onClick={downloadDataArray}>
                  <Icon.Download size={13} /> 下载数组
                </button>
              )}
              <label className="ep-leave-toggle ep-send" title="发送 / 推送时旋转 180°，适合屏幕倒挂安装（与信息站共用此开关）">
                <input
                  type="checkbox"
                  checked={invertRender}
                  onChange={e => store().setInvertRender(e.target.checked)}
                />
                倒置渲染
              </label>
              <button className="btn btn-primary" disabled={ctrlDisabled} onClick={() => void sendImg()}>
                <Icon.Send size={14} /> 发送图片
              </button>
            </div>
          </div>
        </div>
        </div>

        {/* 右栏 */}
        <div className="ep-col">

          {/* 设备控制 */}
          <div className="card">
            <div className="card-header">
              <div className="col" style={{ gap: 3 }}>
                <div className="card-title">设备控制</div>
                <div className="card-sub">切换日历/时钟模式 · 假期数据写入 NVDS 断电不丢失</div>
              </div>
              {!connected && <span className="ep-hint-inline">连接后可用</span>}
            </div>
            <div className="card-body col" style={{ gap: 12 }}>
              <div className="ep-row">
                <button className="btn btn-primary" disabled={ctrlDisabled} onClick={() => void syncTime(1)}>
                  <Icon.Calendar size={14} /> 日历模式
                </button>
                <button className="btn btn-primary" disabled={ctrlDisabled} onClick={() => void syncTime(2)}>
                  <Icon.Clock size={14} /> 时钟模式
                </button>
                <button className="btn" disabled={ctrlDisabled} onClick={() => void clearScreen()}>清除屏幕</button>
              </div>
              <div className="ep-divider" />
              <div className="ep-row">
                <button className="btn" onClick={() => setHolidayOpen(true)}>设置假期数据</button>
                <button className="btn" onClick={() => setHelpOpen(true)}>假期格式说明</button>
              </div>
            </div>
          </div>

          {/* 运行日志 */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">运行日志</div>
              <button className="btn btn-sm" onClick={() => store().clearLog()}>清空</button>
            </div>
            <div className="ep-log" ref={logBoxRef}>
              {logs.length === 0 && <div className="ep-log-empty">暂无日志 — 点击「连接设备」开始</div>}
              {logs.map(l => (
                <div key={l.id} className="ep-log-line">
                  <span className="ep-log-time">{l.time}</span>
                  {l.action && <span className="ep-log-action">{l.action}</span>}
                  {l.text}
                </div>
              ))}
            </div>
          </div>

          {/* 高级 / 开发模式 */}
          <div className="card">
            <button className="ep-adv-toggle" onClick={() => store().toggleDebug()}>
              <div className="ep-adv-head">
                <Icon.AlertTriangle size={15} style={{ color: 'var(--warning)' }} />
                <div>
                  <div className="ep-adv-title">高级 / 开发模式</div>
                  <div className="ep-adv-sub">驱动、引脚、MTU、16进制命令与时间戳测试</div>
                </div>
              </div>
              <Icon.ChevronDown size={14} className={`ep-adv-chev ${debug ? 'open' : ''}`} style={{ color: 'var(--text-muted)' }} />
            </button>
            {debug && (
              <div className="ep-adv-body">
                <div className="ep-adv-warn">注意：以下为开发功能，不熟悉请勿随意修改，否则后果自负。</div>
                <div className="ep-row">
                  <span className="ep-label">驱动</span>
                  <select className="input ep-select" style={{ flex: 1, minWidth: 140 }} value={driver} onChange={e => store().setDriver(e.target.value)}>
                    {epdDrivers.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </div>
                <div className="ep-row">
                  <span className="ep-label">引脚</span>
                  <input className="input mono" style={{ flex: 1, minWidth: 130 }} placeholder="hex 引脚配置" value={pins} onChange={e => store().setPins(e.target.value)} />
                  <button className="btn btn-primary" disabled={ctrlDisabled} onClick={() => void setDriverCmd()}>确定</button>
                </div>
                <div className="ep-row">
                  <span className="ep-label">画布尺寸</span>
                  <select className="input ep-select" value={canvasSizeName} onChange={e => { setCanvasSizeName(e.target.value); updateCanvasSize(e.target.value); }}>
                    {canvasSizes.map(s => <option key={s.name} value={s.name}>{canvasSizeLabels[s.name] ?? s.name}</option>)}
                  </select>
                  <span className="ep-label">颜色模式</span>
                  <select className="input ep-select" value={ditherMode} onChange={e => onDitherModeChange(e.target.value as DitherMode)}>
                    {DITHER_MODE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
                <div className="ep-row">
                  <span className="ep-label">MTU</span>
                  <input className="input mono" style={{ width: 70 }} type="number" min={0} max={255} value={mtu} onChange={e => { const v = parseInt(e.target.value); if (!isNaN(v)) store().setMtu(v); }} />
                  <span className="ep-label">确认间隔</span>
                  <input className="input mono" style={{ width: 70 }} type="number" min={0} max={500} value={interleaved} onChange={e => { const v = parseInt(e.target.value); if (!isNaN(v)) setInterleaved(v); }} />
                </div>
                <div className="ep-row">
                  <input className="input mono" style={{ flex: 1, minWidth: 150 }} placeholder="16 进制命令" value={cmdText} onChange={e => setCmdText(e.target.value)} />
                  <button className="btn btn-primary" disabled={ctrlDisabled} onClick={() => void sendCmd()}>发送命令</button>
                </div>
                <div className="ep-row">
                  <input className="input mono" style={{ flex: 1, minWidth: 120 }} type="number" placeholder="Unix 时间戳" value={testTs} onChange={e => setTestTs(e.target.value)} />
                  <button className="btn" onClick={setCurrentTimestamp}>当前</button>
                  <button className="btn" onClick={() => addDays(-1)}>-1天</button>
                  <button className="btn" onClick={() => addDays(1)}>+1天</button>
                  <button className="btn btn-primary" disabled={ctrlDisabled} onClick={() => void testCalendarJump(1)}>日历测试</button>
                  <button className="btn btn-primary" disabled={ctrlDisabled} onClick={() => void testCalendarJump(2)}>时钟测试</button>
                </div>
                {tsInfo && <div className="ep-adv-tsinfo mono">{tsInfo}</div>}
              </div>
            )}
          </div>

        </div>
      </div>

      {/* ===== 页脚 ===== */}
      <div className="ep-footer">
        <span>
          基于开源固件 <a href="https://github.com/tsl0922/EPD-nRF5" target="_blank" rel="noreferrer">EPD-nRF5</a> · © 2025 tsl0922
        </span>
        <span>墨水屏日历 · 自动打卡系统</span>
      </div>

      {/* ===== 蓝牙选择 modal ===== */}
      {scanning && (
        <div className="ep-overlay" onClick={() => store().closeScan()}>
          <div className="ep-modal ep-modal-sm" onClick={e => e.stopPropagation()}>
            <div className="ep-modal-head">
              <div>
                <div className="ep-modal-title">选择蓝牙设备</div>
                <div className="ep-modal-sub">仅显示有名称的蓝牙设备</div>
              </div>
              <button className="ep-modal-close" onClick={() => store().closeScan()}><Icon.Close size={12} /></button>
            </div>

            <div className="ep-scan-bar">
              <span className="ep-scan-dot"><span className="ring" /><span className="core" /></span>
              <span className="ep-scan-text">持续扫描中…</span>
              <span className="ep-scan-count mono">{namedDevices.length} 个设备</span>
            </div>

            <div className="ep-modal-pad">
              <input
                className="input mono"
                style={{ width: '100%' }}
                maxLength={8}
                placeholder="按设备 ID 过滤（可选，如 A1B2）"
                value={filterId}
                onChange={e => setFilterId(e.target.value)}
              />
            </div>

            <div className="ep-dev-list">
              {shownDevices.length === 0 && (
                <div className="ep-scan-empty">
                  <div className="ep-scan-empty-icon">
                    <span className="ring" /><span className="ring ring2" />
                    <span className="badge"><Icon.Bluetooth size={20} /></span>
                  </div>
                  <div className="ep-scan-empty-title">正在搜索附近的墨水屏设备…</div>
                  <div className="ep-scan-empty-sub">请确保设备已开机并处于可连接状态</div>
                </div>
              )}

              {shownDevices.map(renderDeviceRow)}

              {hiddenCount > 0 && (
                <>
                  <button className="ep-hidden-toggle" onClick={() => setShowHidden(v => !v)}>
                    <Icon.ChevronDown size={13} className={`ep-hidden-chev ${showHidden ? 'open' : ''}`} />
                    {showHidden ? `收起无名称设备（${hiddenCount}）` : `已隐藏 ${hiddenCount} 个无名称设备 · 点击查看`}
                  </button>
                  {showHidden && shownHidden.map(renderDeviceRow)}
                </>
              )}
            </div>

            <div className="ep-modal-foot">
              <span className="ep-hint-inline">未找到设备？请检查蓝牙是否开启</span>
              <button className="btn" onClick={() => store().closeScan()}>取消</button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 假期数据设置 modal ===== */}
      {holidayOpen && (
        <div className="ep-overlay" onClick={() => setHolidayOpen(false)}>
          <div className="ep-modal" onClick={e => e.stopPropagation()}>
            <div className="ep-modal-head">
              <div className="ep-modal-title">设置假期数据</div>
              <button className="ep-modal-close" onClick={() => setHolidayOpen(false)}><Icon.Close size={12} /></button>
            </div>
            <div className="ep-modal-body">
              <div className="ep-row">
                <span className="ep-label">年份</span>
                <input className="input mono" style={{ width: 90 }} type="number" min={2020} max={2050} value={holidayYear} onChange={e => { const v = parseInt(e.target.value); if (!isNaN(v)) setHolidayYear(v); }} />
                <span className="ep-sep" />
                <button className="btn" onClick={() => loadDefaultHolidays(2026)}>加载 2026 默认</button>
                <button className="btn" onClick={() => loadDefaultHolidays(2027)}>加载 2027 默认</button>
              </div>
              <div className="col" style={{ gap: 5 }}>
                <span className="field-label">假期数据（每行一个，格式：月-日-类型）</span>
                <span className="field-hint">类型：0 = 休息日，1 = 调休上班 · 示例：1-1-0 表示 1月1日休息</span>
                <textarea
                  className="input mono"
                  rows={13}
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, resize: 'vertical', background: 'var(--bg-inset)' }}
                  placeholder={'1-1-0\n1-2-0\n1-3-0\n1-4-1'}
                  value={holidayData}
                  onChange={e => setHolidayData(e.target.value)}
                />
              </div>
              <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
                <button className="btn" onClick={() => setHolidayOpen(false)}>取消</button>
                <button className="btn btn-primary" onClick={() => void sendHolidayData()}>发送到设备</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== 假期格式说明 modal ===== */}
      {helpOpen && (
        <div className="ep-overlay" onClick={() => setHelpOpen(false)}>
          <div className="ep-modal ep-modal-lg" onClick={e => e.stopPropagation()}>
            <div className="ep-modal-head">
              <div className="ep-modal-title">假期数据格式说明</div>
              <button className="ep-modal-close" onClick={() => setHelpOpen(false)}><Icon.Close size={12} /></button>
            </div>
            <div className="ep-modal-body ep-help">
              <div>
                <div className="ep-help-title">数据格式</div>
                <div className="ep-help-block">每行一个假期，格式为 <b>月-日-类型</b></div>
                <ul className="ep-help-list">
                  <li>月：1–12</li>
                  <li>日：1–31</li>
                  <li>类型：0 = 休息日，1 = 调休上班</li>
                </ul>
              </div>
              <div>
                <div className="ep-help-title">示例</div>
                <div className="ep-help-block mono">
                  1-1-0 &nbsp; 元旦，1月1日休息<br />
                  1-4-1 &nbsp; 1月4日调休上班<br />
                  2-15-0 &nbsp; 春节，2月15日休息<br />
                  5-1-0 &nbsp; 劳动节，5月1日休息
                </div>
              </div>
              <div>
                <div className="ep-help-title">注意事项</div>
                <ul className="ep-help-list">
                  <li>最多支持 <b>128 个</b> 假期数据</li>
                  <li>以 # 或 // 开头的行会被忽略（可用作注释）</li>
                  <li>空行会被自动忽略</li>
                  <li>设备会保存到 NVDS，<b>断电不丢失</b></li>
                  <li>只有与当前年份匹配的数据才会在日历上显示</li>
                </ul>
              </div>
              <div>
                <div className="ep-help-title">蓝牙指令格式</div>
                <div className="ep-help-block">
                  <div>指令：<code className="mono">0xB6</code></div>
                  <div style={{ marginTop: 6 }}>数据：[年份高字节][年份低字节][数量][假期数据…]</div>
                  <div style={{ marginTop: 8, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
                    每个假期 2 字节编码：<br />
                    Bit 15–12 工作标志（0 休 / 1 班）· Bit 11–8 月份 · Bit 7–0 日期
                  </div>
                </div>
              </div>
              <div className="row" style={{ justifyContent: 'flex-end' }}>
                <button className="btn btn-primary" onClick={() => setHelpOpen(false)}>关闭</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
