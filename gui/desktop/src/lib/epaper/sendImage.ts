// 画布 → 墨水屏 发送管线（从 Epaper.tsx 的 sendImg 抽出，供「手动发送」与「信息站自动推送」共用）。
// 模块级互斥锁：墨水屏全刷耗时 15-25s + 蓝牙分块传输，期间绝不允许并发写入，
// 手动与定时推送共用此锁互斥。

import { EpdCmd, convertUC8159 } from './protocol';
import { processImageData, type DitherMode } from './dithering';
import type { EpdBleClient } from './ble';

let sendingLock = false;

/** 是否有发送任务进行中（手动或自动） */
export function epdSendBusy(): boolean {
  return sendingLock;
}

export interface EpdSendOptions {
  driver: string;
  ditherMode: DitherMode;
  mtu: number;
  interleaved: number;
  onStatus: (text: string) => void;
  /** 发送前把图像旋转 180°（屏幕倒挂安装时勾选「倒置渲染」） */
  rotate180?: boolean;
}

// 180° 旋转 = 像素序整体反转（RGBA 按 4 字节一组），只影响发送数据，不改画布
function rotateImageData180(src: ImageData): ImageData {
  const out = new ImageData(src.width, src.height);
  const s = src.data, d = out.data, n = src.width * src.height;
  for (let i = 0; i < n; i++) {
    const si = i * 4, di = (n - 1 - i) * 4;
    d[di] = s[si];
    d[di + 1] = s[si + 1];
    d[di + 2] = s[si + 2];
    d[di + 3] = s[si + 3];
  }
  return out;
}

/**
 * 把画布当前内容发送到墨水屏并触发刷新。
 * 返回耗时（秒）。busy / 不支持的颜色模式抛 Error（调用方提示）。
 */
export async function sendCanvasToEpd(
  client: EpdBleClient,
  canvas: HTMLCanvasElement,
  ctx: CanvasRenderingContext2D,
  opts: EpdSendOptions,
): Promise<number> {
  if (sendingLock) throw new Error('已有发送任务进行中，请等待屏幕刷新完成');
  sendingLock = true;
  try {
    const { driver, ditherMode, mtu, interleaved, onStatus } = opts;
    const startTime = new Date().getTime();
    let imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    if (opts.rotate180) imageData = rotateImageData180(imageData);
    const processedData = processImageData(imageData, ditherMode);
    const writeOpts = { mtuSize: mtu, interleavedCount: interleaved, startTime, onStatus };

    if (ditherMode === 'fourColor') {
      await client.writeImage(processedData, 'color', writeOpts);
    } else if (ditherMode === 'threeColor') {
      const halfLength = Math.floor(processedData.length / 2);
      const blackWhiteData = processedData.slice(0, halfLength);
      const redWhiteData = processedData.slice(halfLength);
      if (driver === '08' || driver === '09') {
        await client.writeImage(convertUC8159(blackWhiteData, redWhiteData), 'bw', writeOpts);
      } else {
        await client.writeImage(blackWhiteData, 'bw', writeOpts);
        await client.writeImage(redWhiteData, 'red', writeOpts);
      }
    } else if (ditherMode === 'blackWhiteColor') {
      if (driver === '08' || driver === '09') {
        const emptyData = new Uint8Array(processedData.length).fill(0xFF);
        await client.writeImage(convertUC8159(processedData, emptyData), 'bw', writeOpts);
      } else {
        await client.writeImage(processedData, 'bw', writeOpts);
      }
    } else {
      throw new Error('当前固件不支持此颜色模式。');
    }

    await client.write(EpdCmd.REFRESH);
    return (new Date().getTime() - startTime) / 1000.0;
  } finally {
    sendingLock = false;
  }
}
