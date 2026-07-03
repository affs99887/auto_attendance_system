// EPD-nRF5 Web Bluetooth 客户端（连接/写入/通知）。
// 不依赖 DOM/React：所有 UI 反馈通过 EpdBleEvents 回调输出，由 store/组件接管。

import {
  EpdCmd,
  EPD_SERVICE_UUID,
  EPD_CHARACTERISTIC_UUID,
  EPD_VERSION_CHARACTERISTIC_UUID,
  hex2bytes,
  bytes2hex,
} from './protocol';
// sendImage 对 ble 只有 type-only 导入（编译后擦除），这里反向引用不构成运行时循环依赖
import { epdSendBusy } from './sendImage';

// TypeScript DOM lib 不含 Web Bluetooth，自带最小类型声明（Electron/Chromium 运行时可用）
interface BTCharacteristic {
  writeValueWithResponse(value: BufferSource): Promise<void>;
  writeValueWithoutResponse(value: BufferSource): Promise<void>;
  readValue(): Promise<DataView>;
  startNotifications(): Promise<BTCharacteristic>;
  addEventListener(type: 'characteristicvaluechanged', listener: (event: Event) => void): void;
  removeEventListener(type: 'characteristicvaluechanged', listener: (event: Event) => void): void;
}

interface BTService {
  getCharacteristic(uuid: string): Promise<BTCharacteristic>;
}

interface BTGattServer {
  connected: boolean;
  connect(): Promise<BTGattServer>;
  disconnect(): void;
  getPrimaryService(uuid: string): Promise<BTService>;
}

interface BTDevice {
  name?: string;
  gatt: BTGattServer;
  addEventListener(type: 'gattserverdisconnected', listener: (event: Event) => void): void;
  removeEventListener(type: 'gattserverdisconnected', listener: (event: Event) => void): void;
}

interface BTRequestOptions {
  optionalServices?: string[];
  acceptAllDevices?: boolean;
  filters?: Array<{ namePrefix: string }>;
}

interface BTNavigator {
  bluetooth?: {
    requestDevice(options: BTRequestOptions): Promise<BTDevice>;
  };
}

export interface EpdConnectionState {
  connected: boolean;
  canReconnect: boolean;
  deviceName: string | null;
  firmware: number | null;   // 已连接时为固件版本号（如 0x16），否则 null
}

export interface EpdBleEvents {
  onLog: (text: string, action?: string) => void;
  onConnectionChange: (state: EpdConnectionState) => void;
  // 首条通知是设备当前配置（引脚 + 驱动）
  onConfigReceived: (pins: string, driver: string) => void;
  onMtuUpdate: (mtu: number) => void;
  // 固件版本过低（< 0x16）时回调，由 UI 决定如何提示
  onLowFirmware: (version: number, oldUrl: string) => void;
}

export const OLD_DASHBOARD_URL = 'https://tsl0922.github.io/EPD-nRF5/v1.5';

// 连接失败重试：设备已选定后的 GATT 建立（含 service/characteristic 获取）阶段——此时 bleDevice 已在内存，
// 重连无需用户手势（requestDevice 选设备失败多为用户取消或需手势，不在此自动重试）。
// 不再「连几次就放弃」，而是按「时间窗口」持续重试：在 CONNECT_RETRY_WINDOW_MS 内反复发起 gatt.connect()，
// 每次失败后固定等 CONNECT_RETRY_DELAY_MS 再试，直到连上或窗口耗尽。原因：观测到的 "Connection attempt
// failed" 是浏览器毫秒级自拒，一次 connect 根本不耗时；唯有在这段时间里不停重试，才可能撞上适配器/设备
// 就绪的那一刻连上。窗口取 20s（用户要求：一次重连至少持续 20s），以后想更久直接调大本值即可。
const CONNECT_RETRY_WINDOW_MS = 20000;
const CONNECT_RETRY_DELAY_MS = 1000; // 每次连接失败后，等这么久再发起下一次（固定短退避）
// 设备选定（requestDevice 解析 / 重连复用旧句柄）后，到发起 gatt.connect() 之间的等待。
// 选中后应当「立即发起连接」，这里只留一个极短缓冲（让回选所在的事件循环跑完），不再人为拖延。
const CONNECT_SETTLE_DELAY_MS = 300;

// 单次 gatt.connect() 的「挂起兜底上限」：超过本时长仍未拿到 GATT Server 即判本次失败、转入重试，
// 避免连接卡死时界面永远停在「正在连接」。注意：观测到的「Connection attempt failed」是浏览器毫秒级自拒，
// 并非耗时超时——本上限只为兜底「连接挂起永不返回」这种卡死场景。
const CONNECT_ATTEMPT_TIMEOUT_MS = 20000;

// 给一个 Promise 套超时：到点仍未结算就以 message 抛错；原 Promise 正常结算时清掉定时器透传结果/错误。
// 注意 JS 无法真正「取消」底层操作，这里只是不再等待它——故仅用于「挂起/卡死」兜底，配合上层重试使用。
function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    promise.then(
      value => { clearTimeout(timer); resolve(value); },
      err => { clearTimeout(timer); reject(err); },
    );
  });
}

export class EpdBleClient {
  private events: EpdBleEvents;
  private bleDevice: BTDevice | null = null;
  private gattServer: BTGattServer | null = null;
  private epdCharacteristic: BTCharacteristic | null = null;
  private msgIndex = 0;
  private textDecoder: TextDecoder | null = null;
  // 连接尝试令牌：每次发起连接自增，并被进行中的重试循环持有；断开/被新连接流程取代时令牌变化，
  // 旧的重试循环在下一轮检查时主动退出，避免「已断开或已被取代却仍在后台重试连上」。
  private connectToken = 0;
  private readonly onDisconnected = (event: Event) => this.handleDisconnected(event);
  // 通知回调持具名引用（而非匿名函数），才能在重复初始化时先摘除再挂载，避免同一条通知被处理多次
  private readonly onNotify = (event: Event) => {
    const target = event.target as unknown as { value: DataView };
    this.handleNotify(target.value, this.msgIndex++);
  };

  appVersion = 0x15;

  constructor(events: EpdBleEvents) {
    this.events = events;
  }

  get connected(): boolean {
    return this.gattServer != null && this.gattServer.connected;
  }

  get deviceName(): string | null {
    return this.bleDevice?.name ?? null;
  }

  private emitConnectionChange() {
    this.events.onConnectionChange({
      connected: this.connected,
      canReconnect: this.bleDevice != null && !this.connected,
      deviceName: this.deviceName,
      firmware: this.connected ? this.appVersion : null,
    });
  }

  private log(text: string, action = '') {
    this.events.onLog(text, action);
  }

  private resetVariables() {
    this.gattServer = null;
    this.epdCharacteristic = null;
    this.msgIndex = 0;
  }

  private handleDisconnected(event?: Event) {
    // 只处理当前设备的断连：换设备后旧设备晚到的断连事件（事件源不是 this.bleDevice）直接忽略，
    // 否则会误清新连接的状态、并让正在进行的重连令牌失效
    if (event != null && (event.target as unknown as BTDevice) !== this.bleDevice) return;
    this.connectToken++;        // 令进行中的连接重试循环失效（设备已断开，不应再尝试）
    this.resetVariables();
    this.log('已断开连接.');
    this.emitConnectionChange();
  }

  // 写入互斥：BLE 链路同一时刻只允许一个「逻辑写入单元」占用——一次 write() 是一个单元，
  // writeImage 的整个分块循环也是一个单元（分块之间不许其他命令插队，否则设备端图像接收
  // 状态机被打断会花屏）。实现为 promise 链排队：acquire 等到轮到自己时解析出释放函数。
  // 与 sendImage.ts 的 sendingLock 分工：sendingLock 标记「整个发送管线（多层图像+刷新）进行中」，
  // 供下面 write() 直接拒绝外部命令；本互斥只保证单个写入单元不被并发穿插。
  private writeMutex: Promise<void> = Promise.resolve();

  private acquireWriteLock(): Promise<() => void> {
    let release!: () => void;
    const next = new Promise<void>(resolve => { release = resolve; });
    const prev = this.writeMutex;
    this.writeMutex = next;
    return prev.then(() => release);
  }

  async write(cmd: number, data?: string | Uint8Array | number[] | null, withResponse = true): Promise<boolean> {
    // 图像发送期间（全刷耗时 15-25s）只放行图像分块、刷新与 INIT：其他命令即便排队等到锁，
    // 也会落在黑白层/红白层等多层图像之间破坏图传，所以直接拒绝而不是排队。
    // INIT 放行给"发送中途断连后快速重连"的连接初始化用——那时发送管线的占用标记可能
    // 还没释放，但旧发送已经死了；用户面板发 INIT 的按钮在发送期间本就被禁用。
    if (epdSendBusy() && cmd !== EpdCmd.WRITE_IMG && cmd !== EpdCmd.REFRESH && cmd !== EpdCmd.INIT) {
      this.log('图像发送中，已拒绝本次命令，请等屏幕刷新完成后重试');
      return false;
    }
    const release = await this.acquireWriteLock();
    try {
      return await this.writeUnlocked(cmd, data, withResponse);
    } finally {
      release();
    }
  }

  // 实际写入（不排队）。仅供 write() 与 writeImage() 内部使用：
  // writeImage 已整体持有写入锁，分块若再经 write() 排队会等自己释放锁（死锁）
  private async writeUnlocked(cmd: number, data?: string | Uint8Array | number[] | null, withResponse = true): Promise<boolean> {
    if (!this.epdCharacteristic) {
      this.log('服务不可用，请检查蓝牙连接');
      return false;
    }
    const payload: number[] = [cmd];
    if (data) {
      let bytes = data;
      if (typeof bytes === 'string') {
        const parsed = hex2bytes(bytes);
        if (parsed == null) {
          this.log(`非法 16 进制数据（含非 hex 字符或长度为奇数），已取消发送: ${bytes}`);
          return false;
        }
        bytes = parsed;
      }
      if (bytes instanceof Uint8Array) bytes = Array.from(bytes);
      payload.push(...bytes);
    }
    this.log(bytes2hex(payload), '⇑');
    try {
      if (withResponse)
        await this.epdCharacteristic.writeValueWithResponse(Uint8Array.from(payload));
      else
        await this.epdCharacteristic.writeValueWithoutResponse(Uint8Array.from(payload));
    } catch (e) {
      console.error(e);
      if ((e as Error).message) this.log('write: ' + (e as Error).message);
      return false;
    }
    return true;
  }

  // 分块发送图像数据；onStatus 回传进度文案（与原版一致）
  async writeImage(
    data: Uint8Array,
    step: 'bw' | 'red' | 'color',
    opts: { mtuSize: number; interleavedCount: number; startTime: number; onStatus: (text: string) => void },
  ): Promise<void> {
    const chunkSize = opts.mtuSize - 2;
    // 防御畸形 MTU：chunkSize<1 时 for 循环步长为 0/负，会死循环卡死 BLE 发送（sendingLock 永久占用），
    // 直接抛错中断，由上层捕获并解锁，避免应用假死
    if (!Number.isFinite(chunkSize) || chunkSize < 1) {
      throw new Error(`MTU 过小或无效 (mtu=${opts.mtuSize})，无法发送图像`);
    }
    const interleavedCount = opts.interleavedCount;
    const count = Math.round(data.length / chunkSize);
    let chunkIdx = 0;
    let noReplyCount = interleavedCount;

    // 整个分块循环持有写入锁：期间外部 write() 只能排队或被拒绝，不会插进分块流中间；
    // 循环内走 writeUnlocked（不再排队），否则会等自己释放锁形成死锁
    const release = await this.acquireWriteLock();
    try {
      for (let i = 0; i < data.length; i += chunkSize) {
        const currentTime = (new Date().getTime() - opts.startTime) / 1000.0;
        opts.onStatus(`${step === 'bw' ? '黑白' : '颜色'}块: ${chunkIdx + 1}/${count + 1}, 总用时: ${currentTime}s`);
        const payload = [
          (step === 'bw' ? 0x0f : 0x00) | (i === 0 ? 0x00 : 0xf0),
          ...data.slice(i, i + chunkSize),
        ];
        // 检查每块写入返回值：断连后 epdCharacteristic 被置空或 BLE 写入抛错时返回 false，
        // 此处必须抛错中断循环，否则会静默发送残缺图像并误报成功
        let ok: boolean;
        if (noReplyCount > 0) {
          ok = await this.writeUnlocked(EpdCmd.WRITE_IMG, payload, false);
          noReplyCount--;
        } else {
          ok = await this.writeUnlocked(EpdCmd.WRITE_IMG, payload, true);
          noReplyCount = interleavedCount;
        }
        if (!ok) throw new Error('图像分块写入失败，连接可能已断开');
        chunkIdx++;
      }
    } finally {
      release();
    }
  }

  private handleNotify(value: DataView, idx: number) {
    const data = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    if (idx === 0) {
      this.log(`收到配置：${bytes2hex(data)}`);
      let pins = bytes2hex(data.slice(0, 7));
      if (data.length > 10) pins += bytes2hex(data.slice(10, 11));
      const driver = bytes2hex(data.slice(7, 8));
      this.events.onConfigReceived(pins, driver);
    } else {
      if (this.textDecoder == null) this.textDecoder = new TextDecoder();
      const msg = this.textDecoder.decode(data);
      this.log(msg, '⇓');
      if (msg.startsWith('mtu=') && msg.length > 4) {
        const mtuSize = parseInt(msg.substring(4));
        // 校验固件回传的 MTU：必须为有限数且 > 2（chunkSize=mtu-2 需 >= 1），
        // 否则畸形值会污染 store.mtu 并令 writeImage 卡死/发空块，此处仅记录日志并忽略
        if (Number.isFinite(mtuSize) && mtuSize > 2) {
          this.events.onMtuUpdate(mtuSize);
          this.log(`MTU 已更新为: ${mtuSize}`);
        } else {
          this.log(`忽略非法 MTU: ${msg}`);
        }
      } else if (msg.startsWith('t=') && msg.length > 2) {
        const t = parseInt(msg.substring(2)) + new Date().getTimezoneOffset() * 60;
        this.log(`远端时间: ${new Date(t * 1000).toLocaleString()}`);
        this.log(`本地时间: ${new Date().toLocaleString()}`);
      }
    }
  }

  // 打开蓝牙扫描并连接。扫到的设备由主进程 IPC 推送到页面自定义 modal，
  // 用户在 modal 内回选具体设备（按 ID 过滤在 modal 内客户端完成），这里接受所有设备。
  async preConnect(): Promise<void> {
    // 如果当前已连接，先断开
    if (this.gattServer != null && this.gattServer.connected) {
      if (this.bleDevice != null && this.bleDevice.gatt.connected) {
        this.bleDevice.gatt.disconnect();
      }
      // 等待断开完成
      await new Promise(resolve => setTimeout(resolve, 300));
    }

    this.resetVariables();
    try {
      const bluetooth = (navigator as unknown as BTNavigator).bluetooth;
      if (!bluetooth) throw new Error('Web Bluetooth API 不可用');
      const device = await bluetooth.requestDevice({
        optionalServices: [EPD_SERVICE_UUID],
        acceptAllDevices: true,
      });
      // 换设备时先摘掉旧设备上的断连监听：旧设备晚到的断连事件不该再影响新设备的连接状态。
      // 必须放在选择成功之后摘——用户取消选择时旧设备仍是当前设备，监听要保留
      if (this.bleDevice != null && this.bleDevice !== device) {
        this.bleDevice.removeEventListener('gattserverdisconnected', this.onDisconnected);
      }
      this.bleDevice = device;
    } catch (e) {
      console.error(e);
      const msg = (e as Error).message || '';
      if (msg) this.log('requestDevice: ' + msg);
      // 用户取消 / 自动重连超时取消（User cancelled）不属于环境问题，不刷浏览器建议
      if (!/cancel/i.test(msg)) {
        this.log('请检查蓝牙是否已开启，且使用的浏览器支持蓝牙！建议使用以下浏览器：');
        this.log('• 电脑: Chrome/Edge');
        this.log('• Android: Chrome/Edge');
        this.log('• iOS: Bluefy 浏览器');
        // 修复 E12：非取消类失败（权限被拒/无设备/API 不可用）时 requestDevice 直接 reject，
        // 既不触发 gattserverdisconnected 也无后续连接，store 的 scanning/quickConnecting 会永久卡住。
        // 此处主动发一次连接态变化（resetVariables 已置空 gattServer → connected=false），
        // 复用 store onConnectionChange 的断开分支无条件复位扫描 modal / 一键重连态。
        // 取消类失败由 store 侧 closeScan/cancelQuickReconnect 已同步复位，无需再 emit（避免覆盖新扫描）。
        this.emitConnectionChange();
      }
      return;
    }

    this.bleDevice.addEventListener('gattserverdisconnected', this.onDisconnected);
    setTimeout(() => { void this.connect(); }, CONNECT_SETTLE_DELAY_MS);
  }

  async reConnect(): Promise<void> {
    if (this.bleDevice != null && this.bleDevice.gatt.connected)
      this.bleDevice.gatt.disconnect();
    this.resetVariables();
    this.log('正在重连');
    setTimeout(() => { void this.connect(); }, CONNECT_SETTLE_DELAY_MS);
  }

  // 主动断开（不再触发设备选择器）
  disconnect(): void {
    // 终止进行中的连接重试：失败重试期间 GATT 尚未连上，下面的 gatt.disconnect() 不会触发
    // gattserverdisconnected 来兜底中断，故这里显式让重试循环失效。
    this.connectToken++;
    if (this.bleDevice != null && this.bleDevice.gatt.connected) {
      this.bleDevice.gatt.disconnect();
    }
  }

  // 令牌复核：本次连接流程已被新的连接/断开流程取代时返回 true，调用方应立即收场退出。
  // 收场动作要分设备：同一设备的 gatt.connect() 每次 resolve 的是同一个 server 对象，
  // 断开它或清共享状态会连带杀掉接管流程刚建好的连接——所以同设备时什么都不动，
  // 链路留给接管方复用（对已连接的 server 再调 connect() 会立即成功）；
  // 只有换了设备（server 不属于当前设备）才断开旧链路并回滚自己写入的共享状态。
  private abortIfStale(token: number, server: BTGattServer): boolean {
    if (token === this.connectToken) return false;
    if (this.bleDevice != null && this.bleDevice.gatt === server) return true;
    if (this.gattServer === server) {
      this.gattServer = null;
      this.epdCharacteristic = null;
    }
    if (server.connected) server.disconnect();
    return true;
  }

  // GATT 连接（含 service/characteristic 获取）。失败不立刻放弃：在 CONNECT_RETRY_WINDOW_MS（≥20s）窗口内
  // 反复发起 gatt.connect()（每次失败后固定等 CONNECT_RETRY_DELAY_MS 再试），直到连上或窗口耗尽。
  // 成功返回 { server, service, characteristic }；返回 null 表示窗口内未连上，或本次尝试已被新的连接/断开
  // 流程取代（token 失效）——后者交由接管方处理状态，调用方不应再 emit。
  private async connectGatt(token: number): Promise<{ server: BTGattServer; service: BTService; characteristic: BTCharacteristic } | null> {
    const deadline = Date.now() + CONNECT_RETRY_WINDOW_MS;
    let attempt = 0;
    for (;;) {
      // 设备丢失，或本次尝试已被新连接/断开取代 → 放弃，交由接管方处理
      if (this.bleDevice == null || token !== this.connectToken) return null;
      attempt++;
      try {
        this.log(attempt === 1
          ? '正在连接: ' + this.bleDevice.name
          : `正在连接: ${this.bleDevice.name}（第 ${attempt} 次）`);
        // 给 gatt.connect() 套时间上限：正常几毫秒~几秒内返回；若蓝牙栈把这次连接「挂起」永不返回，
        // 到点抛超时错误，落入下面的 catch 走重试，而不是让 UI 永远卡在「正在连接」。
        const server = await withTimeout(
          this.bleDevice.gatt.connect(),
          CONNECT_ATTEMPT_TIMEOUT_MS,
          `连接超时（${(CONNECT_ATTEMPT_TIMEOUT_MS / 1000).toFixed(0)}s 内未建立 GATT 连接）`,
        );
        // 每个 await 成功后都复核令牌：await 期间本流程可能已被新连接/断开取代，
        // 旧流程若继续走完初始化，会重复挂监听、把 characteristic 指向错误设备
        if (this.abortIfStale(token, server)) return null;
        this.gattServer = server;
        this.log('  找到 GATT Server');
        const service = await server.getPrimaryService(EPD_SERVICE_UUID);
        if (this.abortIfStale(token, server)) return null;
        this.log('  找到 EPD Service');
        const characteristic = await service.getCharacteristic(EPD_CHARACTERISTIC_UUID);
        if (this.abortIfStale(token, server)) return null;
        this.epdCharacteristic = characteristic;
        this.log('  找到 Characteristic');
        return { server, service, characteristic };
      } catch (e) {
        console.error(e);
        if ((e as Error).message) this.log('connect: ' + (e as Error).message);
        // 清理本次半连接状态（下一轮 gatt.connect 幂等重建）。仅令牌仍有效时才清：被新流程取代后
        // 这两个字段可能已属于新流程，不能误清。这里不主动 disconnect：本次 gatt.connect()
        // 直接 reject 时 gatt.connected 仍为 false，按 Web Bluetooth 规范 disconnect() 会直接返回（no-op），
        // 既无法关闭底层那条失败连接，反而会在「半连上」时误触发 gattserverdisconnected 复位状态机。
        if (token === this.connectToken) {
          this.gattServer = null;
          this.epdCharacteristic = null;
        }
        // 窗口已用尽 / 被新流程取代 → 跳出去判失败
        if (Date.now() >= deadline || token !== this.connectToken) break;
        const remainSec = Math.ceil((deadline - Date.now()) / 1000);
        this.log(`连接失败，${(CONNECT_RETRY_DELAY_MS / 1000).toFixed(1)}s 后重试…（本次重连还剩约 ${remainSec}s）`);
        await new Promise(resolve => setTimeout(resolve, CONNECT_RETRY_DELAY_MS));
      }
    }
    if (token === this.connectToken) {
      this.log(`连接失败：持续重连 ${(CONNECT_RETRY_WINDOW_MS / 1000).toFixed(0)}s 仍未成功`);
      // 反复瞬时失败（"Connection attempt failed"）多为环境态，纯软件无法连上，给出对症排障指引：
      this.log('若反复连不上请依次排查：① 墨水屏可能已休眠并停止蓝牙广播——在屏上按键或重新上电唤醒后重试；'
        + '② 若曾在 Windows「设置 → 蓝牙和其他设备」里配对过本设备——找到它「删除设备」清掉残留配对，'
        + '再用「连接设备」重新搜索；③ 关闭可能独占该设备的其他蓝牙工具（如 nRF Connect）后重试。');
    }
    return null;
  }

  private async connect(): Promise<void> {
    if (this.bleDevice == null || this.epdCharacteristic != null) return;
    const token = ++this.connectToken;

    const gatt = await this.connectGatt(token);
    if (gatt == null) {
      // token 仍是本次 → 确属失败（非被取代）：复位并通知断开；被新流程取代则交给接管方，不再 emit
      if (token === this.connectToken) this.handleDisconnected();
      return;
    }
    const { server, service: epdService, characteristic: epdCharacteristic } = gatt;

    try {
      const versionCharacteristic = await epdService.getCharacteristic(EPD_VERSION_CHARACTERISTIC_UUID);
      const versionData = await versionCharacteristic.readValue();
      this.appVersion = versionData.getUint8(0);
      this.log(`固件版本: 0x${this.appVersion.toString(16)}`);
    } catch (e) {
      console.error(e);
      this.appVersion = 0x15;
    }
    if (this.abortIfStale(token, server)) return;

    if (this.appVersion < 0x16) {
      this.events.onLowFirmware(this.appVersion, OLD_DASHBOARD_URL);
      setTimeout(() => {
        this.log(`如遇到问题，可访问旧版本上位机: ${OLD_DASHBOARD_URL}`);
      }, 500);
    }

    try {
      await epdCharacteristic.startNotifications();
    } catch (e) {
      console.error(e);
      if ((e as Error).message) this.log('startNotifications: ' + (e as Error).message);
    }
    if (this.abortIfStale(token, server)) return;
    // 先摘再挂（onNotify 是具名引用）：同一 characteristic 被重复初始化时不会叠挂监听器，
    // 否则每条通知会被处理多次、msgIndex 双倍自增导致配置帧被当普通文本解码
    epdCharacteristic.removeEventListener('characteristicvaluechanged', this.onNotify);
    epdCharacteristic.addEventListener('characteristicvaluechanged', this.onNotify);

    await this.write(EpdCmd.INIT);
    if (this.abortIfStale(token, server)) return;
    this.emitConnectionChange();
  }
}
