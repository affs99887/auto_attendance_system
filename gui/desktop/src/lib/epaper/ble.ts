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

export class EpdBleClient {
  private events: EpdBleEvents;
  private bleDevice: BTDevice | null = null;
  private gattServer: BTGattServer | null = null;
  private epdCharacteristic: BTCharacteristic | null = null;
  private msgIndex = 0;
  private textDecoder: TextDecoder | null = null;
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
      if (noReplyCount > 0) {
        await this.write(EpdCmd.WRITE_IMG, payload, false);
        noReplyCount--;
      } else {
        await this.write(EpdCmd.WRITE_IMG, payload, true);
        noReplyCount = interleavedCount;
      }
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
        this.events.onMtuUpdate(mtuSize);
        this.log(`MTU 已更新为: ${mtuSize}`);
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
      if ((e as Error).message) this.log('requestDevice: ' + (e as Error).message);
      this.log('请检查蓝牙是否已开启，且使用的浏览器支持蓝牙！建议使用以下浏览器：');
      this.log('• 电脑: Chrome/Edge');
      this.log('• Android: Chrome/Edge');
      this.log('• iOS: Bluefy 浏览器');
      return;
    }

    this.bleDevice.addEventListener('gattserverdisconnected', this.onDisconnected);
    setTimeout(() => { void this.connect(); }, 300);
  }

  async reConnect(): Promise<void> {
    if (this.bleDevice != null && this.bleDevice.gatt.connected)
      this.bleDevice.gatt.disconnect();
    this.resetVariables();
    this.log('正在重连');
    setTimeout(() => { void this.connect(); }, 300);
  }

  // 主动断开（不再触发设备选择器）
  disconnect(): void {
    if (this.bleDevice != null && this.bleDevice.gatt.connected) {
      this.bleDevice.gatt.disconnect();
    }
  }

  private async connect(): Promise<void> {
    if (this.bleDevice == null || this.epdCharacteristic != null) return;

    let epdService: BTService;
    try {
      this.log('正在连接: ' + this.bleDevice.name);
      this.gattServer = await this.bleDevice.gatt.connect();
      this.log('  找到 GATT Server');
      epdService = await this.gattServer.getPrimaryService(EPD_SERVICE_UUID);
      this.log('  找到 EPD Service');
      this.epdCharacteristic = await epdService.getCharacteristic(EPD_CHARACTERISTIC_UUID);
      this.log('  找到 Characteristic');
    } catch (e) {
      console.error(e);
      if ((e as Error).message) this.log('connect: ' + (e as Error).message);
      this.handleDisconnected();
      return;
    }

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
      await this.epdCharacteristic.startNotifications();
      this.epdCharacteristic.addEventListener('characteristicvaluechanged', (event) => {
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
