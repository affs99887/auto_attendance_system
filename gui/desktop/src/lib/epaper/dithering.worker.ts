// 抖动流水线的 Web Worker：把 CPU 密集的整图处理（对比度→误差扩散抖动→打包→解包预览）
// 搬到独立线程执行，避免在渲染进程主线程上同步跑大画布（如 1360×480≈65 万像素）的
// Stucki/Jarvis 误差扩散，导致 Electron 窗口数百毫秒乃至数秒卡死无响应（审计 E2 核心冻结根因）。
// 复用 dithering.ts 中已有的纯函数，算法/调色板逻辑完全一致，仅改变执行线程。
import { adjustContrast, ditherImage, processImageData, decodeProcessedData } from './dithering';
import type { DitherMode, DitherAlgorithm } from './dithering';

interface DitherRequest {
  id: number;
  buffer: ArrayBuffer; // 画布像素的 RGBA 缓冲（Uint8ClampedArray 底层 buffer，转移所有权过来）
  width: number;
  height: number;
  contrast: number;
  alg: DitherAlgorithm;
  strength: number;
  mode: DitherMode;
}

self.onmessage = (e: MessageEvent<DitherRequest>) => {
  const { id, buffer, width, height, contrast, alg, strength, mode } = e.data;

  // 用转移过来的缓冲重建 ImageData，跑与主线程完全相同的流水线
  const imageData = new ImageData(new Uint8ClampedArray(buffer), width, height);
  adjustContrast(imageData, contrast);
  const processedData = processImageData(ditherImage(imageData, alg, strength, mode), mode);
  const finalImageData = decodeProcessedData(processedData, width, height, mode);

  // 把结果像素缓冲转移回主线程（零拷贝），主线程据此重建 ImageData 再 putImageData
  const outBuffer = finalImageData.data.buffer;
  (self as unknown as Worker).postMessage({ id, buffer: outBuffer, width, height }, [outBuffer]);
};
