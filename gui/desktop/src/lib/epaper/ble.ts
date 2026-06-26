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

// TypeScript DOM lib 不含 Web Bluetooth，自带最小类型声明（Electron/Chromium 运行时可用）
interface BTCharacteristic {
  writeValueWithResponse(value: BufferSource): Promise<void>;
  writeValueWithoutResponse(value: BufferSource): Promise<void>;
  readValue(): Promise<DataView>;
  startNotifications(): Promise<BTCharacteristic>;
  addEventListener(type: 'characteristicvaluechanged', listener: (event: Event) => void): void;
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
  addEventListener(type: 'gattserverdisconnected', listener: () => void): void;
  removeEventListener(type: 'gattserverdisconnected', listener: () => void): void;
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
  private readonly onDisconnected = () => this.handleDisconnected();

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

  private handleDisconnected() {
    this.connectToken++;        // 令进行中的连接重试循环失效（设备已断开，不应再尝试）
    this.resetVariables();
    this.log('已断开连接.');
    this.emitConnectionChange();
  }

  async write(cmd: number, data?: string | Uint8Array | number[] | null, withResponse = true): Promise<boolean> {
    if (!this.epdCharacteristic) {
      this.log('服务不可用，请检查蓝牙连接');
      return false;
    }
    const payload: number[] = [cmd];
    if (data) {
      let bytes = data;
      if (typeof bytes === 'string') bytes = hex2bytes(bytes);
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

    for (let i = 0; i < data.length; i += chunkSize) {
      const currentTime = (new Date().getTime() - opts.startTime) / 1000.0;
      opts.onStatus(`${step === 'bw' ? '黑白' : '颜色'}块: ${chunkIdx + 1}/${count + 1}, 总用时: ${currentTime}s`);
      const payload = [
        (step === 'bw' ? 0x0f : 0x00) | (i === 0 ? 0x00 : 0xf0),
        ...data.slice(i, i + chunkSize),
      ];
      // 检查每块写入返回值：断连后 epdCharacteristic 被置空或 BLE 写入抛错时 write() 返回 false，
      // 此处必须抛错中断循环，否则会静默发送残缺图像并误报成功
      let ok: boolean;
      if (noReplyCount > 0) {
        ok = await this.write(EpdCmd.WRITE_IMG, payload, false);
        noReplyCount--;
      } else {
        ok = await this.write(EpdCmd.WRITE_IMG, payload, true);
        noReplyCount = interleavedCount;
      }
      if (!ok) throw new Error('图像分块写入失败，连接可能已断开');
      chunkIdx++;
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
      this.bleDevice = await bluetooth.requestDevice({
        optionalServices: [EPD_SERVICE_UUID],
        acceptAllDevices: true,
      });
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

  // GATT 连接（含 service/characteristic 获取）。失败不立刻放弃：在 CONNECT_RETRY_WINDOW_MS（≥20s）窗口内
  // 反复发起 gatt.connect()（每次失败后固定等 CONNECT_RETRY_DELAY_MS 再试），直到连上或窗口耗尽。
  // 成功返回 { service, characteristic }；返回 null 表示窗口内未连上，或本次尝试已被新的连接/断开流程
  // 取代（token 失效）——后者交由接管方处理状态，调用方不应再 emit。
  private async connectGatt(token: number): Promise<{ service: BTService; characteristic: BTCharacteristic } | null> {
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
        this.gattServer = await withTimeout(
          this.bleDevice.gatt.connect(),
          CONNECT_ATTEMPT_TIMEOUT_MS,
          `连接超时（${(CONNECT_ATTEMPT_TIMEOUT_MS / 1000).toFixed(0)}s 内未建立 GATT 连接）`,
        );
        this.log('  找到 GATT Server');
        const service = await this.gattServer.getPrimaryService(EPD_SERVICE_UUID);
        this.log('  找到 EPD Service');
        const characteristic = await service.getCharacteristic(EPD_CHARACTERISTIC_UUID);
        this.epdCharacteristic = characteristic;
        this.log('  找到 Characteristic');
        return { service, characteristic };
      } catch (e) {
        console.error(e);
        if ((e as Error).message) this.log('connect: ' + (e as Error).message);
        // 清理本次半连接状态（下一轮 gatt.connect 幂等重建）。这里不主动 disconnect：本次 gatt.connect()
        // 直接 reject 时 gatt.connected 仍为 false，按 Web Bluetooth 规范 disconnect() 会直接返回（no-op），
        // 既无法关闭底层那条失败连接，反而会在「半连上」时误触发 gattserverdisconnected 复位状态机。
        this.gattServer = null;
        this.epdCharacteristic = null;
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
    const { service: epdService, characteristic: epdCharacteristic } = gatt;

    try {
      const versionCharacteristic = await epdService.getCharacteristic(EPD_VERSION_CHARACTERISTIC_UUID);
      const versionData = await versionCharacteristic.readValue();
      this.appVersion = versionData.getUint8(0);
      this.log(`固件版本: 0x${this.appVersion.toString(16)}`);
    } catch (e) {
      console.error(e);
      this.appVersion = 0x15;
    }

    if (this.appVersion < 0x16) {
      this.events.onLowFirmware(this.appVersion, OLD_DASHBOARD_URL);
      setTimeout(() => {
        this.log(`如遇到问题，可访问旧版本上位机: ${OLD_DASHBOARD_URL}`);
      }, 500);
    }

    try {
      await epdCharacteristic.startNotifications();
      epdCharacteristic.addEventListener('characteristicvaluechanged', (event) => {
        const target = event.target as unknown as { value: DataView };
        this.handleNotify(target.value, this.msgIndex++);
      });
    } catch (e) {
      console.error(e);
      if ((e as Error).message) this.log('startNotifications: ' + (e as Error).message);
    }

    await this.write(EpdCmd.INIT);
    this.emitConnectionChange();
  }
}
