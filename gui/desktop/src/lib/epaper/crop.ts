// 图片裁剪管理器（缩放/平移背景图后截取画布区域）。
// 与 DOM 控件解耦：裁剪模式开关、标题提示、图片文件来源经 CropHost 回调与 React 同步。

export interface CropHost {
  setCanvasTitle: (title: string) => void;
  onCropModeChange: (active: boolean) => void;
  getImageFile: () => File | null;
}

export class CropManager {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private host: CropHost;

  private cropMode = false;
  private backgroundZoom = 1;
  private backgroundPanX = 0;
  private backgroundPanY = 0;
  private isPanning = false;
  private lastPanX = 0;
  private lastPanY = 0;
  private lastTouchDistance = 0;

  constructor(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D, host: CropHost) {
    this.canvas = canvas;
    this.ctx = ctx;
    this.host = host;

    this.handleBackgroundZoom = this.handleBackgroundZoom.bind(this);
    this.handleBackgroundPanStart = this.handleBackgroundPanStart.bind(this);
    this.handleBackgroundPan = this.handleBackgroundPan.bind(this);
    this.handleBackgroundPanEnd = this.handleBackgroundPanEnd.bind(this);
    this.handleTouchStart = this.handleTouchStart.bind(this);
    this.handleTouchMove = this.handleTouchMove.bind(this);
  }

  private resetStates() {
    this.backgroundZoom = 1;
    this.backgroundPanX = 0;
    this.backgroundPanY = 0;
    this.isPanning = false;
    this.lastPanX = 0;
    this.lastPanY = 0;
    this.lastTouchDistance = 0;
  }

  isCropMode(): boolean {
    return this.cropMode;
  }

  exitCropMode() {
    if (this.cropMode) {
      this.cropMode = false;
      this.host.onCropModeChange(false);
      this.host.setCanvasTitle('');
    }
    this.canvas.style.backgroundImage = '';
    this.canvas.style.cursor = 'default';

    this.canvas.removeEventListener('wheel', this.handleBackgroundZoom);
    this.canvas.removeEventListener('mousedown', this.handleBackgroundPanStart);
    this.canvas.removeEventListener('mousemove', this.handleBackgroundPan);
    this.canvas.removeEventListener('mouseup', this.handleBackgroundPanEnd);
    this.canvas.removeEventListener('mouseleave', this.handleBackgroundPanEnd);
    this.canvas.removeEventListener('touchstart', this.handleTouchStart);
    this.canvas.removeEventListener('touchmove', this.handleTouchMove);
    this.canvas.removeEventListener('touchend', this.handleBackgroundPanEnd);
    this.canvas.removeEventListener('touchcancel', this.handleBackgroundPanEnd);
  }

  private fillCanvas(style: string) {
    this.ctx.fillStyle = style;
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
  }

  initializeCrop() {
    const imageFile = this.host.getImageFile();
    if (!imageFile) {
      this.fillCanvas('white');
      return;
    }

    this.exitCropMode();
    this.resetStates();

    this.canvas.style.backgroundImage = `url(${URL.createObjectURL(imageFile)})`;
    this.canvas.style.backgroundSize = '100%';
    this.canvas.style.backgroundPosition = '';
    this.canvas.style.backgroundRepeat = 'no-repeat';

    this.canvas.addEventListener('wheel', this.handleBackgroundZoom);
    this.canvas.addEventListener('mousedown', this.handleBackgroundPanStart);
    this.canvas.addEventListener('mousemove', this.handleBackgroundPan);
    this.canvas.addEventListener('mouseup', this.handleBackgroundPanEnd);
    this.canvas.addEventListener('mouseleave', this.handleBackgroundPanEnd);

    // 移动端触摸
    this.canvas.addEventListener('touchstart', this.handleTouchStart);
    this.canvas.addEventListener('touchmove', this.handleTouchMove);
    this.canvas.addEventListener('touchend', this.handleBackgroundPanEnd);
    this.canvas.addEventListener('touchcancel', this.handleBackgroundPanEnd);

    // 让画布透明以显示背景图
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    this.host.setCanvasTitle('裁剪模式: 可用鼠标滚轮或双指触摸缩放图片');
    this.cropMode = true;
    this.host.onCropModeChange(true);
  }

  // 把当前缩放/平移下的可视区域绘制到画布并退出裁剪模式
  finishCrop(callback?: () => void) {
    const imageFile = this.host.getImageFile();
    if (!imageFile) return;

    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(image.src);

      const fieldsetRect = this.canvas.getBoundingClientRect();
      const scale = (image.width / fieldsetRect.width) / this.backgroundZoom;

      const sx = -this.backgroundPanX * scale;
      const sy = -this.backgroundPanY * scale;
      const sWidth = fieldsetRect.width * scale;
      const sHeight = fieldsetRect.height * scale;

      this.fillCanvas('white');
      this.ctx.drawImage(image, sx, sy, sWidth, sHeight, 0, 0, this.canvas.width, this.canvas.height);

      this.exitCropMode();
      if (callback) callback();
    };
    image.src = URL.createObjectURL(imageFile);
  }

  private handleTouchStart(e: TouchEvent) {
    e.preventDefault();
    if (e.touches.length === 1) {
      this.handleBackgroundPanStart(e.touches[0]);
    } else if (e.touches.length === 2) {
      this.isPanning = false; // 双指缩放时停止平移
      this.lastTouchDistance = this.getTouchDistance(e.touches);
    }
  }

  private handleTouchMove(e: TouchEvent) {
    e.preventDefault();
    if (this.isPanning && e.touches.length === 1) {
      this.handleBackgroundPan(e.touches[0]);
    } else if (e.touches.length === 2) {
      const newDist = this.getTouchDistance(e.touches);
      if (this.lastTouchDistance > 0) {
        const zoomFactor = newDist / this.lastTouchDistance;
        this.backgroundZoom *= zoomFactor;
        this.backgroundZoom = Math.max(0.1, Math.min(5, this.backgroundZoom));
        this.updateBackgroundTransform();
      }
      this.lastTouchDistance = newDist;
    }
  }

  private handleBackgroundZoom(e: { preventDefault: () => void; deltaY: number }) {
    e.preventDefault();
    const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
    this.backgroundZoom *= zoomFactor;
    this.backgroundZoom = Math.max(0.1, Math.min(5, this.backgroundZoom));
    this.updateBackgroundTransform();
  }

  private handleBackgroundPanStart(e: { clientX: number; clientY: number }) {
    this.isPanning = true;
    this.lastPanX = e.clientX;
    this.lastPanY = e.clientY;
    this.canvas.style.cursor = 'grabbing';
  }

  private handleBackgroundPan(e: { clientX: number; clientY: number }) {
    if (this.isPanning) {
      const deltaX = e.clientX - this.lastPanX;
      const deltaY = e.clientY - this.lastPanY;
      this.backgroundPanX += deltaX;
      this.backgroundPanY += deltaY;
      this.lastPanX = e.clientX;
      this.lastPanY = e.clientY;
      this.updateBackgroundTransform();
    }
  }

  private handleBackgroundPanEnd() {
    this.isPanning = false;
    this.lastTouchDistance = 0;
    this.canvas.style.cursor = 'grab';
  }

  private updateBackgroundTransform() {
    this.canvas.style.backgroundSize = `${100 * this.backgroundZoom}%`;
    this.canvas.style.backgroundPosition = `${this.backgroundPanX}px ${this.backgroundPanY}px`;
  }

  private getTouchDistance(touches: TouchList): number {
    const touch1 = touches[0];
    const touch2 = touches[1];
    return Math.sqrt(
      Math.pow(touch2.clientX - touch1.clientX, 2) +
      Math.pow(touch2.clientY - touch1.clientY, 2),
    );
  }

  // 工具栏按钮入口（替代原 initCropTools 的 DOM 绑定）
  zoomIn() {
    this.handleBackgroundZoom({ preventDefault: () => { }, deltaY: -1 });
  }

  zoomOut() {
    this.handleBackgroundZoom({ preventDefault: () => { }, deltaY: 1 });
  }

  move(dx: number, dy: number) {
    this.backgroundPanX += dx;
    this.backgroundPanY += dy;
    this.updateBackgroundTransform();
  }
}
